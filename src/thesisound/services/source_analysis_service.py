from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

from thesisound.domain import (
    AuthorityClass,
    ProjectState,
    SourceAccess,
    SourceCandidate,
    SourceDecision,
    SourceRole,
)
from thesisound.ingestion import IngestionResult
from thesisound.modeling import ModelError
from thesisound.pipeline import WorkspaceStore, mark_failed, transition
from thesisound.services.block_builder import BlockBuilder
from thesisound.services.claim_reconciler import ClaimReconcilerService
from thesisound.services.document_mapper import DocumentMapperService
from thesisound.services.evidence_extractor import EvidenceExtractorService
from thesisound.services.evidence_validator import validate_evidence_collection
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import ClaimLedger, SourceAnalysisManifest, SourceDocumentBlock


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
    ) -> None:
        self.workspace_store = workspace_store
        self.artifact_store = artifact_store
        self.block_builder = block_builder
        self.document_mapper = document_mapper
        self.evidence_extractor = evidence_extractor
        self.claim_reconciler = claim_reconciler

    def build_blocks(
        self,
        project_id: UUID,
        ingestion: IngestionResult,
        *,
        source_id: UUID | None = None,
    ) -> tuple[UUID, list[SourceDocumentBlock], SourceAnalysisManifest]:
        project = self.workspace_store.load_project(project_id)
        _validate_ingestion(project.brief is not None, ingestion)
        resolved_source_id = source_id or uuid5(project.project_id, ingestion.inspection.sha256)
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
        blocks = self.artifact_store.load_blocks(project_id, source_id)
        document_map, run = self.document_mapper.map_document(
            project_id=project_id,
            source_id=source_id,
            blocks=blocks,
            model=model,
            prompt_version=prompt_version,
        )
        self.artifact_store.save_document_map(project_id, source_id, document_map)
        manifest = self.artifact_store.load_manifest(project_id, source_id)
        manifest.status = "document_mapped"
        manifest.model_run_ids.append(run.run_id)
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
    ) -> SourceAnalysisManifest:
        blocks = self.artifact_store.load_blocks(project_id, source_id)
        document_map = self.artifact_store.load_document_map(project_id, source_id)

        def save_one(extraction, block_id: str) -> None:
            self.artifact_store.save_block_extraction(
                project_id,
                source_id,
                extraction,
                block_id,
            )

        extractions, runs = self.evidence_extractor.extract_source(
            project_id=project_id,
            source_id=source_id,
            blocks=blocks,
            document_map=document_map,
            model=model,
            prompt_version=prompt_version,
            on_extraction=save_one,
        )
        validate_evidence_collection(extractions, blocks)
        self.artifact_store.save_evidence(project_id, source_id, extractions)
        manifest = self.artifact_store.load_manifest(project_id, source_id)
        manifest.status = "evidence_ready"
        manifest.evidence_count = sum(len(item.claims) for item in extractions)
        manifest.model_run_ids.extend(run.run_id for run in runs)
        manifest.updated_at = datetime.now(UTC)
        self.artifact_store.save_manifest(manifest)
        return manifest

    def build_claims(
        self,
        project_id: UUID,
        source_id: UUID,
        *,
        model: str,
        prompt_version: str | None = None,
    ) -> tuple[ClaimLedger, SourceAnalysisManifest]:
        extractions = self.artifact_store.load_extractions(project_id, source_id)
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

        project = self.workspace_store.load_project(project_id)
        if project.state == ProjectState.CORPUS_BUILDING:
            transition(project, ProjectState.CORPUS_READY)
            self.workspace_store.save_project(project)
        return ledger, manifest

    def analyze_source(
        self,
        project_id: UUID,
        ingestion_path: Path,
        *,
        fast_model: str,
        strong_model: str,
        source_id: UUID | None = None,
        prompt_version: str | None = None,
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

    @staticmethod
    def _enter_corpus_building(project) -> None:
        if project.state == ProjectState.BRIEF_READY:
            transition(project, ProjectState.SOURCES_COLLECTING)
        if project.state == ProjectState.CORPUS_READY:
            transition(project, ProjectState.SOURCES_COLLECTING)
        if project.state == ProjectState.SOURCES_COLLECTING:
            transition(project, ProjectState.SOURCE_SELECTION_REQUIRED)
        if project.state == ProjectState.SOURCE_SELECTION_REQUIRED:
            transition(project, ProjectState.CORPUS_BUILDING)
        elif project.state == ProjectState.FAILED_RETRYABLE:
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


def _validate_ingestion(has_brief: bool, ingestion: IngestionResult) -> None:
    if not has_brief:
        raise ValueError("Build a ResearchBrief before analyzing a source.")
    if not ingestion.safe_for_claim_extraction:
        raise ValueError("Ingestion result did not pass the claim-extraction quality gate.")
    if ingestion.parsed is None:
        raise ValueError("Ingestion result does not contain a parsed document.")


def _register_source(project, source_id: UUID, ingestion: IngestionResult) -> None:
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
