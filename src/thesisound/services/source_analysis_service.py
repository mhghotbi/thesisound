from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

from thesisound import tracing
from thesisound.domain import (
    AuthorityClass,
    DocumentMap,
    Project,
    ProjectState,
    SourceAccess,
    SourceCandidate,
    SourceDecision,
    SourceRole,
)
from thesisound.ingestion import IngestionResult
from thesisound.modeling import ModelError, ModelRunRecord
from thesisound.pipeline import WorkspaceStore, mark_failed, transition
from thesisound.services.analysis_profile import (
    build_second_pass_profile,
    plan_evidence_extraction,
    required_section_block_ids,
)
from thesisound.services.block_builder import BlockBuilder
from thesisound.services.claim_reconciler import ClaimReconcilerService
from thesisound.services.document_identity import block_sequence_key
from thesisound.services.document_map_cache import DocumentMapCache, is_shareable_document_map
from thesisound.services.document_mapper import DocumentMapperService
from thesisound.services.evidence_extractor import EvidenceExtractorService
from thesisound.services.evidence_scope import extraction_profiles_compatible
from thesisound.services.evidence_validator import validate_evidence_collection
from thesisound.services.lineage_events import emit_cache_lookup
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    BlockEvidenceExtraction,
    ClaimLedger,
    EvidenceExtractionPlan,
    SourceAnalysisManifest,
    SourceDocumentBlock,
)

_MIN_PLANNED_TOKEN_RETENTION = 0.85
# R5 made extraction plans roughly three times smaller, so one block now carries 7-8% of
# planned token mass instead of 2-3%, and two ordinary rejections could fail an otherwise
# healthy source. The single largest loss is forgiven against the rule above, but overall
# retention may never fall below this floor -- a systemic failure still trips the gate.
_MIN_RETENTION_AFTER_LARGEST_LOSS = 0.75


def evidence_retention_holds(
    *,
    planned_tokens: int,
    kept_tokens: int,
    largest_lost_tokens: int,
) -> bool:
    """Whether enough planned token mass survived extraction.

    Shared with ``readiness`` so the live gate and the replayed one cannot drift.
    """

    if planned_tokens <= 0:
        return True
    retention = kept_tokens / planned_tokens
    if retention + 1e-9 >= _MIN_PLANNED_TOKEN_RETENTION:
        return True
    if retention + 1e-9 < _MIN_RETENTION_AFTER_LARGEST_LOSS:
        return False
    forgiven = (kept_tokens + largest_lost_tokens) / planned_tokens
    return forgiven + 1e-9 >= _MIN_PLANNED_TOKEN_RETENTION


class SourceAnalysisService:
    def __init__(
        self,
        *,
        workspace_store: WorkspaceStore,
        artifact_store: SourceArtifactStore,
        block_builder: BlockBuilder,
        document_mapper: DocumentMapperService,
        evidence_extractor: EvidenceExtractorService,
        claim_reconciler: ClaimReconcilerService,
        document_map_cache: DocumentMapCache | None = None,
    ) -> None:
        self.workspace_store = workspace_store
        self.artifact_store = artifact_store
        self.block_builder = block_builder
        self.document_mapper = document_mapper
        self.evidence_extractor = evidence_extractor
        self.claim_reconciler = claim_reconciler
        self.document_map_cache = document_map_cache or DocumentMapCache(workspace_store.root)

    def build_blocks(
        self,
        project_id: UUID,
        ingestion: IngestionResult,
        *,
        source_id: UUID | None = None,
    ) -> tuple[UUID, list[SourceDocumentBlock], SourceAnalysisManifest]:
        project = self.workspace_store.load_project(project_id)
        _validate_ingestion(project.brief is not None, ingestion)
        resolved_source_id = source_id or uuid5(
            project.project_id,
            ingestion.inspection.sha256,
        )
        self._enter_corpus_building(project)
        _register_source(project, resolved_source_id, ingestion)
        self.workspace_store.save_project(project)

        assert ingestion.parsed is not None
        blocks, report = self.block_builder.build(
            ingestion.parsed,
            source_id=resolved_source_id,
        )
        if not blocks:
            raise ValueError("Block builder produced no analyzable content.")
        self.artifact_store.save_ingestion(project_id, resolved_source_id, ingestion)
        self.artifact_store.save_blocks(project_id, resolved_source_id, blocks, report)
        manifest = SourceAnalysisManifest(
            project_id=project_id,
            source_id=resolved_source_id,
            source_sha256=ingestion.inspection.sha256,
            status="blocks_ready",
            block_count=len(blocks),
        )
        self.artifact_store.save_manifest(manifest)
        return resolved_source_id, blocks, manifest

    def map_document(
        self,
        project_id: UUID,
        source_id: UUID,
        *,
        model: str,
        prompt_version: str | None = None,
    ) -> SourceAnalysisManifest:
        with tracing.span(
            "corpus.map_document",
            component="corpus",
            project_id=project_id,
            subject_type="source",
            subject_id=str(source_id),
        ) as span:
            blocks = self.artifact_store.load_blocks(project_id, source_id)
            reusable = self._load_reusable_document_map(project_id, source_id, blocks)
            emit_cache_lookup(
                cache="project_document_map",
                result="hit" if reusable is not None else "miss",
                subject_type="source",
                subject_id=str(source_id),
                avoided_calls=1 if reusable is not None else None,
            )
            if reusable is not None:
                span.set(source="project_reuse")
                return self._mark_document_mapped(project_id, source_id)
            content_key = block_sequence_key(blocks)
            shared = self.document_map_cache.load(content_key, blocks, source_id=source_id)
            emit_cache_lookup(
                cache="shared_document_map",
                result="hit" if shared is not None else "miss",
                subject_type="source",
                subject_id=str(source_id),
                lookup_key=content_key[:16],
                artifact_hash=content_key[:16] if shared is not None else None,
                avoided_calls=1 if shared is not None else None,
            )
            if shared is not None:
                self.artifact_store.save_document_map(project_id, source_id, shared)
                span.set(source="shared_cache")
                return self._mark_document_mapped(project_id, source_id)
            document_map, run = self.document_mapper.map_document(
                project_id=project_id,
                source_id=source_id,
                blocks=blocks,
                model=model,
                prompt_version=prompt_version,
            )
            self.artifact_store.save_document_map(project_id, source_id, document_map)
            if is_shareable_document_map(document_map):
                self.document_map_cache.save(content_key, blocks, document_map)
            span.set(source="model")
            return self._mark_document_mapped(
                project_id, source_id, run_id=run.run_id if run is not None else None
            )

    def has_reusable_document_map(self, project_id: UUID, source_id: UUID) -> bool:
        blocks = self.artifact_store.load_blocks(project_id, source_id)
        if self._load_reusable_document_map(project_id, source_id, blocks) is not None:
            return True
        return (
            self.document_map_cache.load(
                block_sequence_key(blocks),
                blocks,
                source_id=source_id,
            )
            is not None
        )

    def _mark_document_mapped(
        self,
        project_id: UUID,
        source_id: UUID,
        *,
        run_id: UUID | None = None,
    ) -> SourceAnalysisManifest:
        manifest = self.artifact_store.load_manifest(project_id, source_id)
        manifest.status = "document_mapped"
        if run_id is not None:
            manifest.model_run_ids.append(run_id)
        manifest.updated_at = datetime.now(UTC)
        self.artifact_store.save_manifest(manifest)
        return manifest

    def extract_evidence(
        self,
        project_id: UUID,
        source_id: UUID,
        *,
        model: str,
        prompt_version: str | None = None,
    ) -> tuple[SourceAnalysisManifest, list[str]]:
        project = self.workspace_store.load_project(project_id)
        if project.brief is None:
            raise ValueError("ResearchBrief is required to plan evidence depth.")
        blocks = self.artifact_store.load_blocks(project_id, source_id)
        document_map = self.artifact_store.load_document_map(project_id, source_id)
        # A changed brief can shift selected_block_ids between retry attempts.
        try:
            prior_plan = self.artifact_store.load_extraction_plan(project_id, source_id)
        except (OSError, ValueError):
            prior_plan = None
        plan = plan_evidence_extraction(project.brief, document_map, blocks)
        self.artifact_store.save_extraction_plan(project_id, source_id, plan)

        known_ids = {block.block_id for block in blocks}
        self.artifact_store.prune_block_extractions(project_id, source_id, known_ids)
        prior = [
            record
            for record in self.artifact_store.load_block_extractions(project_id, source_id)
            if record.block_id in known_ids
        ]
        extracted_prior = [record for record in prior if record.status == "extracted"]
        selected_ids = set(plan.selected_block_ids)
        profile_ok = (
            prior_plan is not None
            and extraction_profiles_compatible(prior_plan.profile, plan.profile)
        )
        # Reuse only selected blocks whose extraction contract still matches. Deferred
        # priors stay on disk for resume but are excluded from skip and aggregates.
        skip_ids = {
            record.block_id
            for record in extracted_prior
            if record.block_id in selected_ids and profile_ok
        }

        def save_one(record: BlockEvidenceExtraction) -> None:
            self.artifact_store.save_block_extraction(
                project_id,
                source_id,
                record,
            )

        new_records, runs = self.evidence_extractor.extract_source(
            project_id=project_id,
            source_id=source_id,
            blocks=blocks,
            document_map=document_map,
            model=model,
            plan=plan,
            prompt_version=prompt_version,
            on_extraction=save_one,
            skip_block_ids=skip_ids,
        )
        by_id = {record.block_id: record for record in extracted_prior}
        by_id.update({record.block_id: record for record in new_records})
        records = [by_id[block.block_id] for block in blocks if block.block_id in by_id]
        # Aggregate files must reflect the current selection only so long→short
        # duration changes do not leave deferred-block claims eligible downstream.
        scoped_records = [
            record for record in records if record.block_id in selected_ids
        ]
        scoped_records, second_pass_runs = self._apply_second_pass(
            project_id=project_id,
            source_id=source_id,
            blocks=blocks,
            document_map=document_map,
            plan=plan,
            scoped_records=scoped_records,
            model=model,
            prompt_version=prompt_version,
        )
        runs = [*runs, *second_pass_runs]
        validate_evidence_collection(
            [record for record in scoped_records if record.status == "extracted"],
            blocks,
        )
        self.artifact_store.save_evidence(project_id, source_id, scoped_records)

        kept_ids = {
            record.block_id for record in scoped_records if record.status == "extracted"
        }
        kept_tokens = sum(
            block.estimated_token_count
            for block in blocks
            if block.block_id in kept_ids and block.block_id in selected_ids
        )
        largest_lost_tokens = max(
            (
                block.estimated_token_count
                for block in blocks
                if block.block_id in selected_ids and block.block_id not in kept_ids
            ),
            default=0,
        )
        planned_tokens = plan.selected_source_tokens
        total_tokens = plan.total_source_tokens
        kept_coverage = kept_tokens / total_tokens if total_tokens else 1.0
        retention = kept_tokens / planned_tokens if planned_tokens else 1.0
        claim_count = sum(
            len(record.extraction.claims)
            for record in scoped_records
            if record.status == "extracted"
        )
        rejected = [record for record in scoped_records if record.status == "rejected"]
        skipped = [record for record in scoped_records if record.status == "skipped"]
        warnings = [
            f"Rejected evidence for {record.block_id}: {record.rejection_reason}"
            for record in rejected
            if record.rejection_reason
        ]
        for record in skipped:
            reason = record.rejection_reason or "provider failure"
            warnings.append(f"Skipped evidence for {record.block_id}: {reason}")
            tracing.event(
                "corpus.block_skipped",
                component="corpus",
                level="warn",
                project_id=project_id,
                subject_type="block",
                subject_id=record.block_id,
                reason=reason,
            )
        warnings.append(
            f"Extracted {len(kept_ids)} of {len(plan.selected_block_ids)} planned blocks; "
            f"{len(skipped)} skipped after provider errors, {len(rejected)} rejected. "
            f"Kept {retention:.0%} of planned tokens."
        )
        # Claim yield per surviving block is how a shrinking plan shows up downstream:
        # the coverage audit judges the ledger, not the plan, so this has to be trackable
        # across runs rather than reconstructed from artifacts after a gate blocks.
        tracing.event(
            "corpus.evidence_yield",
            component="corpus",
            project_id=project_id,
            subject_type="source",
            subject_id=str(source_id),
            selected_block_count=len(plan.selected_block_ids),
            kept_block_count=len(kept_ids),
            claim_count=claim_count,
            claims_per_kept_block=round(claim_count / len(kept_ids), 3) if kept_ids else 0.0,
        )

        manifest = self.artifact_store.load_manifest(project_id, source_id)
        manifest.status = "evidence_ready"
        manifest.selected_block_count = len(plan.selected_block_ids)
        manifest.deferred_block_count = len(plan.deferred_block_ids)
        manifest.analysis_depth = plan.profile.depth
        manifest.evidence_token_coverage = min(1.0, kept_coverage)
        manifest.evidence_count = claim_count
        manifest.skipped_block_count = len(skipped)
        manifest.model_run_ids.extend(run.run_id for run in runs)
        manifest.updated_at = datetime.now(UTC)
        self.artifact_store.save_manifest(manifest)

        if claim_count == 0:
            raise ValueError(
                "Evidence extraction produced no claim-bearing evidence after retries."
            )
        if not evidence_retention_holds(
            planned_tokens=planned_tokens,
            kept_tokens=kept_tokens,
            largest_lost_tokens=largest_lost_tokens,
        ):
            raise ValueError(
                f"Evidence extraction lost {1 - retention:.0%} of the planned source tokens "
                f"across {len(rejected)} rejected and {len(skipped)} skipped block(s); at least "
                f"{_MIN_PLANNED_TOKEN_RETENTION:.0%} must survive, with the largest single loss "
                f"forgiven down to {_MIN_RETENTION_AFTER_LARGEST_LOSS:.0%}. "
                f"Kept coverage is {kept_coverage:.0%} of the source."
            )
        if kept_coverage + 1e-9 < plan.profile.block_coverage_target:
            warnings.append(
                f"Evidence coverage {kept_coverage:.0%} is below the "
                f"{plan.profile.block_coverage_target:.0%} target for the "
                f"{plan.profile.depth} profile "
                f"(the plan itself could only reach {plan.achieved_token_coverage:.0%}"
                f"{_coverage_cause(plan)})."
            )
        return manifest, warnings

    def _apply_second_pass(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        blocks: list[SourceDocumentBlock],
        document_map: DocumentMap,
        plan: EvidenceExtractionPlan,
        scoped_records: list[BlockEvidenceExtraction],
        model: str,
        prompt_version: str | None,
    ) -> tuple[list[BlockEvidenceExtraction], list[ModelRunRecord]]:
        """Re-extract required-section blocks at deepened depth, in place.

        Gated on ``second_pass_for_core_sections`` (today only >45-minute "extended"
        episodes). Idempotent: a block already at ``extraction_pass`` 2 is never
        targeted again, so a no-op re-run of ``extract_evidence`` does not re-pay for
        a second-pass call. A pass-2 rejection/skip keeps the pass-1 record rather
        than regressing a good extraction because a retry had a bad day.
        """

        if not plan.profile.second_pass_for_core_sections:
            return scoped_records, []

        required_ids = required_section_block_ids(document_map, plan.selected_block_ids)
        targets = {
            record.block_id
            for record in scoped_records
            if record.status == "extracted"
            and record.block_id in required_ids
            and record.extraction_pass < 2
        }
        if not targets:
            return scoped_records, []

        target_tokens = sum(
            block.estimated_token_count for block in blocks if block.block_id in targets
        )
        second_pass_plan = EvidenceExtractionPlan(
            source_id=source_id,
            profile=build_second_pass_profile(plan.profile),
            selected_block_ids=sorted(targets),
            deferred_block_ids=[],
            selected_source_tokens=target_tokens,
            total_source_tokens=target_tokens,
            achieved_token_coverage=1.0,
        )
        deepened, runs = self.evidence_extractor.extract_source(
            project_id=project_id,
            source_id=source_id,
            blocks=blocks,
            document_map=document_map,
            model=model,
            plan=second_pass_plan,
            prompt_version=prompt_version,
        )

        by_id = {record.block_id: record for record in scoped_records}
        upgraded = 0
        for record in deepened:
            if record.status == "extracted":
                promoted = record.model_copy(update={"extraction_pass": 2})
                by_id[record.block_id] = promoted
                self.artifact_store.save_block_extraction(project_id, source_id, promoted)
                upgraded += 1
        tracing.event(
            "corpus.evidence_second_pass",
            component="corpus",
            project_id=project_id,
            subject_type="source",
            subject_id=str(source_id),
            attempted_block_count=len(targets),
            upgraded_block_count=upgraded,
            failed_block_count=len(targets) - upgraded,
        )
        updated_records = [by_id[record.block_id] for record in scoped_records]
        return updated_records, runs

    def build_claims(
        self,
        project_id: UUID,
        source_id: UUID,
        *,
        model: str,
        prompt_version: str | None = None,
        finalize_project: bool = True,
    ) -> tuple[ClaimLedger, SourceAnalysisManifest]:
        project = self.workspace_store.load_project(project_id)
        selected_ids: set[str] | None = None
        try:
            plan = self.artifact_store.load_extraction_plan(project_id, source_id)
            selected_ids = set(plan.selected_block_ids)
        except (OSError, ValueError):
            if project.brief is not None:
                blocks = self.artifact_store.load_blocks(project_id, source_id)
                document_map = self.artifact_store.load_document_map(project_id, source_id)
                planned = plan_evidence_extraction(project.brief, document_map, blocks)
                selected_ids = set(planned.selected_block_ids)
        extractions = [
            record
            for record in self.artifact_store.load_extractions(project_id, source_id)
            if record.status == "extracted"
            and (selected_ids is None or record.block_id in selected_ids)
        ]
        ledger, run = self.claim_reconciler.reconcile(
            project_id=project_id,
            source_id=source_id,
            extractions=extractions,
            model=model,
            prompt_version=prompt_version,
        )
        self.artifact_store.save_claim_ledger(project_id, source_id, ledger)
        manifest = self.artifact_store.load_manifest(project_id, source_id)
        manifest.status = "claims_ready"
        manifest.claim_count = len(ledger.claims)
        if run.provider != "none":
            manifest.model_run_ids.append(run.run_id)
        manifest.updated_at = datetime.now(UTC)
        self.artifact_store.save_manifest(manifest)

        if finalize_project and project.state == ProjectState.CORPUS_BUILDING:
            transition(project, ProjectState.CORPUS_READY)
            self.workspace_store.save_project(project)
        return ledger, manifest

    def sync_to_current_profile(
        self,
        project_id: UUID,
        source_id: UUID,
        *,
        fast_model: str,
        strong_model: str,
    ) -> bool:
        """Re-extract delta blocks and rebuild claims when the brief profile diverges.

        Returns True when extraction/claims were refreshed. Compatible plans with the
        same selected_block_ids are a no-op so duration requeues that already match
        the stored corpus do not pay for model work.
        """

        project = self.workspace_store.load_project(project_id)
        if project.brief is None:
            raise ValueError("ResearchBrief is required to sync evidence depth.")
        blocks = self.artifact_store.load_blocks(project_id, source_id)
        document_map = self.artifact_store.load_document_map(project_id, source_id)
        planned = plan_evidence_extraction(project.brief, document_map, blocks)
        try:
            stored_plan = self.artifact_store.load_extraction_plan(project_id, source_id)
        except (OSError, ValueError):
            stored_plan = None
        if (
            stored_plan is not None
            and extraction_profiles_compatible(stored_plan.profile, planned.profile)
            and stored_plan.selected_block_ids == planned.selected_block_ids
        ):
            return False

        previous_selected = (
            len(stored_plan.selected_block_ids) if stored_plan is not None else 0
        )
        tracing.event(
            "corpus.profile_delta",
            component="corpus",
            project_id=project_id,
            subject_type="source",
            subject_id=str(source_id),
            previous_selected_block_count=previous_selected,
            selected_block_count=len(planned.selected_block_ids),
            previous_depth=stored_plan.profile.depth if stored_plan is not None else None,
            depth=planned.profile.depth,
        )
        self.extract_evidence(project_id, source_id, model=fast_model)
        self.build_claims(
            project_id,
            source_id,
            model=strong_model,
            finalize_project=False,
        )
        return True

    def analyze_source(
        self,
        project_id: UUID,
        ingestion_path: Path,
        *,
        fast_model: str,
        strong_model: str,
        source_id: UUID | None = None,
        prompt_version: str | None = None,
        finalize_project: bool = True,
    ) -> tuple[ClaimLedger, SourceAnalysisManifest]:
        ingestion = self.artifact_store.load_ingestion(ingestion_path)
        resolved_source_id: UUID | None = None
        try:
            resolved_source_id, _, _ = self.build_blocks(
                project_id,
                ingestion,
                source_id=source_id,
            )
            self.map_document(
                project_id,
                resolved_source_id,
                model=fast_model,
                prompt_version=prompt_version,
            )
            self.extract_evidence(
                project_id,
                resolved_source_id,
                model=fast_model,
                prompt_version=prompt_version,
            )
            return self.build_claims(
                project_id,
                resolved_source_id,
                model=strong_model,
                prompt_version=prompt_version,
                finalize_project=finalize_project,
            )
        except (ModelError, ValueError, FileNotFoundError) as exc:
            project = self.workspace_store.load_project(project_id)
            if project.state != ProjectState.FAILED_RETRYABLE:
                mark_failed(project, str(exc))
            else:
                project.last_error = str(exc)
                project.updated_at = datetime.now(UTC)
            self.workspace_store.save_project(project)
            if resolved_source_id is not None:
                self._mark_manifest_failed(project_id, resolved_source_id, str(exc))
            raise

    def _load_reusable_document_map(
        self,
        project_id: UUID,
        source_id: UUID,
        blocks: list[SourceDocumentBlock],
    ) -> DocumentMap | None:
        try:
            document_map = self.artifact_store.load_document_map(project_id, source_id)
        except (FileNotFoundError, OSError):
            return None
        if document_map.source_id != source_id:
            return None
        if not is_shareable_document_map(document_map):
            return None
        known_ids = {block.block_id for block in blocks}
        content_ids = {block.block_id for block in blocks if block.block_type != "front_matter"}
        mapped: list[str] = []
        for section in document_map.sections:
            if set(section.source_block_ids) - known_ids:
                return None
            mapped.extend(section.source_block_ids)
        mapped_content = set(mapped) & content_ids
        coverage = len(mapped_content) / len(content_ids) if content_ids else 1.0
        if coverage < 0.9:
            return None
        return document_map

    @staticmethod
    def _enter_corpus_building(project: Project) -> None:
        if project.state in {ProjectState.BRIEF_READY, ProjectState.CORPUS_READY}:
            transition(project, ProjectState.SOURCES_COLLECTING)
        if project.state == ProjectState.SOURCES_COLLECTING:
            transition(project, ProjectState.SOURCE_SELECTION_REQUIRED)
        if project.state in {
            ProjectState.SOURCE_SELECTION_REQUIRED,
            ProjectState.FAILED_RETRYABLE,
        }:
            transition(project, ProjectState.CORPUS_BUILDING)
        elif project.state != ProjectState.CORPUS_BUILDING:
            raise ValueError(f"Cannot analyze a source from project state {project.state}.")

    def _mark_manifest_failed(
        self,
        project_id: UUID,
        source_id: UUID,
        message: str,
    ) -> None:
        try:
            manifest = self.artifact_store.load_manifest(project_id, source_id)
        except FileNotFoundError:
            return
        manifest.status = "failed"
        manifest.last_error = message
        manifest.updated_at = datetime.now(UTC)
        self.artifact_store.save_manifest(manifest)


def _coverage_cause(plan: EvidenceExtractionPlan) -> str:
    """Why the plan could not reach its coverage target.

    A budget-capped plan is a deliberate cost decision; a plan that fell short for any
    other reason is a corpus problem. Both read identically in the coverage number and
    they have opposite remedies, so the warning has to say which one happened.
    """

    budget = plan.profile.evidence_input_token_budget
    if plan.target_source_tokens == budget and budget < plan.total_source_tokens:
        return f", capped by the {budget:,}-token analysis budget"
    return ""


def _validate_ingestion(has_brief: bool, ingestion: IngestionResult) -> None:
    if not has_brief:
        raise ValueError("Build a ResearchBrief before analyzing a source.")
    if not ingestion.safe_for_claim_extraction:
        raise ValueError("Ingestion result did not pass the claim-extraction quality gate.")
    if ingestion.parsed is None:
        raise ValueError("Ingestion result does not contain a parsed document.")


def _register_source(
    project: Project,
    source_id: UUID,
    ingestion: IngestionResult,
) -> None:
    if any(source.source_id == source_id for source in project.sources):
        return
    project.sources.append(
        SourceCandidate(
            source_id=source_id,
            title=ingestion.inspection.path.stem,
            role=SourceRole.USER_CONTEXT,
            source_type=ingestion.inspection.extension.lstrip(".") or "document",
            origin="user_upload",
            access=SourceAccess.FULL_TEXT,
            user_decision=SourceDecision.INCLUDE,
            authority_class=AuthorityClass.UNKNOWN,
            relevance_reasons=["Explicitly supplied and selected by the user."],
        )
    )
