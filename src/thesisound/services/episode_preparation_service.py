from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from thesisound.concepts import ConceptCell, LessonPart, SegmentSkeleton
from thesisound.domain import (
    ClaimRecord,
    DeliberatelyOmittedClaim,
    EpisodePlan,
    EpisodeSegment,
    EvidenceItem,
    ExtractedAuxiliaryPoint,
    ExtractedDefinition,
    ExtractedDistinction,
    LessonIntent,
    MustNotBeLostPoint,
    Project,
    ProjectState,
    ResearchBrief,
)
from thesisound.episode import (
    ClaimPriorityReport,
    CoverageReport,
    DisagreementGraph,
    EpisodeBudgetReport,
    EpisodePlanDraft,
    EpisodePreparationManifest,
    EpisodeSegmentDraft,
    EpisodeStageInputs,
    MustNotBeLostReview,
    MustNotBeLostReviewItem,
    SegmentEvidencePack,
)
from thesisound.modeling import ModelError
from thesisound.pipeline import WorkspaceStore, mark_failed, transition
from thesisound.script import QualityNote, QualityNotesLedger
from thesisound.services.analysis_profile import plan_evidence_extraction, resolve_extraction_seeds
from thesisound.services.cell_selection import select_cells
from thesisound.services.claim_cell_linkage import link_claims_to_cells
from thesisound.services.claim_prioritizer import ClaimPrioritizer
from thesisound.services.concept_map_overlay import effective_concept_map
from thesisound.services.coverage_auditor import CoverageAuditorService, can_plan_episode
from thesisound.services.disagreement_graph import DisagreementGraphBuilder
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.episode_budget import EpisodeBudgetEstimator
from thesisound.services.episode_planner import EpisodePlannerService
from thesisound.services.episode_reuse import planning_input_key
from thesisound.services.evidence_pack_builder import EvidencePackBuilder
from thesisound.services.evidence_scope import scope_by_block, scope_claims_and_evidence
from thesisound.services.lineage_events import emit_cache_lookup
from thesisound.services.part_packer import pack_parts
from thesisound.services.segment_skeleton import build as build_segment_skeleton
from thesisound.services.semantic_identity import (
    COVERAGE_AUDITOR_VERSION,
    EPISODE_PLANNER_VERSION,
    first_mismatch,
    planning_semantic,
)
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    ClaimLedger,
    EvidenceExtractionPlan,
    SourceDocumentBlock,
)


@dataclass(frozen=True)
class CorpusArtifacts:
    source_ids: list[UUID]
    claims: list[ClaimRecord]
    evidence_items: list[EvidenceItem]
    blocks: list[SourceDocumentBlock]
    extraction_plans: list[EvidenceExtractionPlan]
    definitions: list[ExtractedDefinition] = field(default_factory=list)
    distinctions: list[ExtractedDistinction] = field(default_factory=list)
    examples: list[ExtractedAuxiliaryPoint] = field(default_factory=list)
    objections: list[ExtractedAuxiliaryPoint] = field(default_factory=list)
    responses: list[ExtractedAuxiliaryPoint] = field(default_factory=list)
    must_not_be_lost: list[MustNotBeLostPoint] = field(default_factory=list)


class EpisodePreparationService:
    def __init__(
        self,
        *,
        workspace_store: WorkspaceStore,
        source_store: SourceArtifactStore,
        episode_store: EpisodeArtifactStore,
        coverage_auditor: CoverageAuditorService,
        claim_prioritizer: ClaimPrioritizer,
        budget_estimator: EpisodeBudgetEstimator,
        disagreement_builder: DisagreementGraphBuilder,
        episode_planner: EpisodePlannerService,
        evidence_pack_builder: EvidencePackBuilder,
    ) -> None:
        self.workspace_store = workspace_store
        self.source_store = source_store
        self.episode_store = episode_store
        self.coverage_auditor = coverage_auditor
        self.claim_prioritizer = claim_prioritizer
        self.budget_estimator = budget_estimator
        self.disagreement_builder = disagreement_builder
        self.episode_planner = episode_planner
        self.evidence_pack_builder = evidence_pack_builder

    def audit_coverage(
        self,
        project_id: UUID,
        *,
        model: str,
        prompt_version: str | None = None,
    ) -> CoverageReport:
        project = self.workspace_store.load_project(project_id)
        self._enter_episode_planning(project)
        self.workspace_store.save_project(project)
        corpus = self._load_corpus(project_id)
        assert project.brief is not None
        semantic = planning_semantic(
            model=model,
            prompt_version=prompt_version,
            stage_version=COVERAGE_AUDITOR_VERSION,
        )
        key = self._planning_key(
            corpus,
            project.brief,
            include_duration=False,
            semantic=semantic,
        )
        reused, miss_reason = self._reusable_coverage(
            project_id,
            key,
            project.brief,
            semantic=semantic,
            lesson_intent=project.lesson_intent,
        )
        emit_cache_lookup(
            cache="coverage_audit",
            result="hit" if reused is not None else "miss",
            project_id=project_id,
            lookup_key=key[:16],
            avoided_calls=1 if reused is not None else None,
            invalidation_reason=miss_reason,
        )
        if reused is not None:
            self._save_coverage_manifest(project_id, reused, corpus.source_ids)
            return reused

        report, run = self.coverage_auditor.audit(
            project_id=project_id,
            brief=project.brief,
            claims=corpus.claims,
            extraction_plans=corpus.extraction_plans,
            model=model,
            prompt_version=prompt_version,
            lesson_intent=project.lesson_intent,
        )
        self.episode_store.save_coverage(report)
        # A fresh audit invalidates the stored plan: it was built on the previous answer.
        self.episode_store.save_stage_inputs(
            project_id,
            EpisodeStageInputs(coverage=key, coverage_semantic=dict(semantic)),
        )
        self._save_coverage_manifest(project_id, report, corpus.source_ids)
        return report

    def prioritize_claims(self, project_id: UUID) -> ClaimPriorityReport:
        project = self.workspace_store.load_project(project_id)
        self._require_planning_state(project)
        if project.brief is None:
            raise ValueError("ResearchBrief is required for claim prioritization.")
        corpus = self._load_corpus(project_id)
        coverage = self.episode_store.load_coverage(project_id)
        report = self.claim_prioritizer.prioritize(
            project_id=project_id,
            brief=project.brief,
            claims=corpus.claims,
            coverage=coverage,
        )
        self.episode_store.save_priorities(report)
        manifest = self.episode_store.load_manifest(project_id)
        manifest.status = "priorities_ready"
        manifest.updated_at = datetime.now(UTC)
        self.episode_store.save_manifest(manifest)
        return report

    def estimate_budget(self, project_id: UUID) -> EpisodeBudgetReport:
        project = self.workspace_store.load_project(project_id)
        self._require_planning_state(project)
        if project.brief is None:
            raise ValueError("ResearchBrief is required for budget estimation.")
        corpus = self._load_corpus(project_id)
        coverage = self.episode_store.load_coverage(project_id)
        priorities = self.episode_store.load_priorities(project_id)
        report = self.budget_estimator.estimate(
            project_id=project_id,
            target_duration_minutes=project.brief.target_duration_minutes,
            coverage=coverage,
            priorities=priorities,
            original_blocks=corpus.blocks,
        )
        self.episode_store.save_budget(report)
        manifest = self.episode_store.load_manifest(project_id)
        manifest.status = "budget_ready"
        manifest.updated_at = datetime.now(UTC)
        self.episode_store.save_manifest(manifest)
        return report

    def build_disagreement_graph(self, project_id: UUID) -> DisagreementGraph:
        project = self.workspace_store.load_project(project_id)
        self._require_planning_state(project)
        corpus = self._load_corpus(project_id)
        graph = self.disagreement_builder.build(
            project_id=project_id,
            claims=corpus.claims,
            evidence_items=corpus.evidence_items,
        )
        self.episode_store.save_disagreement_graph(graph)
        manifest = self.episode_store.load_manifest(project_id)
        manifest.status = "disagreement_ready"
        manifest.disagreement_count = len(graph.nodes)
        manifest.updated_at = datetime.now(UTC)
        self.episode_store.save_manifest(manifest)
        return graph

    def plan_episode(
        self,
        project_id: UUID,
        *,
        model: str,
        prompt_version: str | None = None,
    ) -> EpisodePlan:
        project = self.workspace_store.load_project(project_id)
        self._require_planning_state(project)
        if project.brief is None:
            raise ValueError("ResearchBrief is required for episode planning.")
        corpus = self._load_corpus(project_id)
        semantic = planning_semantic(
            model=model,
            prompt_version=prompt_version,
            stage_version=EPISODE_PLANNER_VERSION,
        )
        key = self._planning_key(
            corpus,
            project.brief,
            include_duration=True,
            semantic=semantic,
        )
        stored_inputs = self.episode_store.load_stage_inputs(project_id)
        plan, miss_reason = self._reusable_plan(project_id, stored_inputs, key, semantic)
        emit_cache_lookup(
            cache="episode_plan",
            result="hit" if plan is not None else "miss",
            project_id=project_id,
            lookup_key=key[:16],
            avoided_calls=1 if plan is not None else None,
            invalidation_reason=miss_reason,
        )
        model_run_ids: list[UUID] = []
        if plan is None:
            coverage = self.episode_store.load_coverage(project_id)
            budget = self.episode_store.load_budget(project_id)
            priorities = self.episode_store.load_priorities(project_id)
            disagreement_graph = self.episode_store.load_disagreement_graph(project_id)
            if project.lesson_intent == LessonIntent.SOURCE_COVERAGE:
                plan, draft, quality_notes, part_run_ids = self._plan_episode_parts(
                    project_id=project_id,
                    project=project,
                    brief=project.brief,
                    corpus=corpus,
                    coverage=coverage,
                    budget=budget,
                    disagreement_graph=disagreement_graph,
                    model=model,
                    prompt_version=prompt_version,
                )
                model_run_ids.extend(part_run_ids)
            else:
                plan, draft, run, quality_notes = self.episode_planner.plan(
                    project_id=project_id,
                    brief=project.brief,
                    claims=corpus.claims,
                    coverage=coverage,
                    budget=budget,
                    priorities=priorities,
                    disagreement_graph=disagreement_graph,
                    extraction_plans=corpus.extraction_plans,
                    definitions=corpus.definitions,
                    distinctions=corpus.distinctions,
                    examples=corpus.examples,
                    objections=corpus.objections,
                    responses=corpus.responses,
                    model=model,
                    prompt_version=prompt_version,
                )
                model_run_ids.append(run.run_id)
            self.episode_store.save_plan(project_id, plan, draft)
            self.episode_store.save_quality_notes(
                QualityNotesLedger(project_id=project_id, notes=quality_notes)
            )
            self.episode_store.save_stage_inputs(
                project_id,
                stored_inputs.model_copy(
                    update={"plan": key, "plan_semantic": dict(semantic)}
                ),
            )

        project.episode_plan = plan
        self.workspace_store.save_project(project)
        # Runs whether the plan was freshly generated or reused from cache, so the
        # review always reflects the current corpus/plan pairing, not a stale one.
        self.episode_store.save_must_not_be_lost_review(
            self._build_must_not_be_lost_review(project_id, corpus, plan)
        )
        manifest = self.episode_store.load_manifest(project_id)
        manifest.status = "plan_ready"
        manifest.segment_count = len(plan.segments)
        manifest.model_run_ids.extend(model_run_ids)
        manifest.updated_at = datetime.now(UTC)
        self.episode_store.save_manifest(manifest)
        return plan

    def _plan_episode_parts(
        self,
        *,
        project_id: UUID,
        project: Project,
        brief: ResearchBrief,
        corpus: CorpusArtifacts,
        coverage: CoverageReport,
        budget: EpisodeBudgetReport,
        disagreement_graph: DisagreementGraph,
        model: str,
        prompt_version: str | None,
    ) -> tuple[EpisodePlan, EpisodePlanDraft, list[QualityNote], list[UUID]]:
        """Plan one part per packed group of in-scope cells (`10c` P3 Step 8).

        Each part gets its own deterministic segment skeleton
        (`segment_skeleton.build`) and its own `episode_planner.plan` call,
        scoped to only the claims linked to that part's cells -- the model
        never sees, and so cannot ground on, another part's material. A part
        whose skeleton exceeds `target_minutes * 1.25` is re-packed once into
        two half-budget parts before planning (10c P3 Step 8: "re-pack on
        window overflow"); a part with no linked claim at all cannot form a
        segment and is dropped (surfaces as "not covered" in the report,
        `10c` P3 Step 11).
        """

        source_id = (
            project.scope.source_id if project.scope is not None else corpus.source_ids[0]
        )
        concept_map = effective_concept_map(self.source_store, project_id, source_id)
        if concept_map is None:
            raise ValueError("source_coverage planning requires a built concept map.")
        in_scope, _omitted = select_cells(concept_map, project.scope, project.compression)
        in_scope_cells = [item.cell for item in in_scope]
        if not in_scope_cells:
            raise ValueError(
                "No in-scope concept cells to plan a source_coverage episode from."
            )
        cells_by_key = {cell.cell_key: cell for cell in in_scope_cells}
        minutes_by_cell = {cell.cell_key: cell.estimated_minutes for cell in in_scope_cells}
        target_minutes = float(project.episode_target_minutes)

        # Re-pack on window overflow (`10c` P3 Step 8): a packed part whose
        # skeleton exceeds `target * 1.25` is re-packed into two half-budget
        # parts. Bounded recursion -- `pack_parts`' own fill rule can force a
        # cell in past FILL_MAX to reach FILL_MIN, so one split does not
        # always land under the new ceiling either; a genuinely oversized
        # single cell (`len(cell_keys) == 1`) can never be split further and
        # is accepted as-is (already flagged `oversize_cell` by the packer).
        _MAX_REPACK_DEPTH = 3
        pending: deque[tuple[list[ConceptCell], float, int]] = deque(
            [(in_scope_cells, target_minutes, 0)]
        )
        units: list[tuple[LessonPart, list[SegmentSkeleton], float]] = []
        while pending:
            group_cells, group_target, depth = pending.popleft()
            for part in pack_parts(group_cells, concept_map.edges, group_target, minutes_by_cell):
                part_cells = [cells_by_key[key] for key in part.cell_keys]
                skeleton = build_segment_skeleton(
                    part, part_cells, corpus.claims, corpus.evidence_items, concept_map.edges
                )
                total_minutes = sum(item.estimated_minutes for item in skeleton)
                ceiling = group_target * 1.25
                splittable = len(part.cell_keys) > 1 and depth < _MAX_REPACK_DEPTH
                if total_minutes > ceiling and splittable:
                    pending.append((part_cells, group_target / 2, depth + 1))
                else:
                    # A part accepted despite still exceeding `group_target *
                    # 1.25` (an atomic cell, or the repack depth cap) genuinely
                    # needs that much time; report its own size as the target
                    # instead of failing the deterministic skeleton-ceiling
                    # check against a budget it was never going to meet.
                    units.append((part, skeleton, max(group_target, total_minutes)))

        # Recursive re-packing does not process groups in book order; the
        # final numbering must, so sort by each unit's earliest cell_key.
        units.sort(key=lambda unit: min(unit[0].cell_keys))
        units = [unit for unit in units if unit[1]]
        if not units:
            raise ValueError(
                "No part has a claim to plan from; check the extraction plan and claim ledger."
            )

        all_segments: list[EpisodeSegment] = []
        all_draft_segments: list[EpisodeSegmentDraft] = []
        omitted_claims: list[DeliberatelyOmittedClaim] = []
        follow_up_topics: list[str] = []
        final_parts: list[LessonPart] = []
        run_ids: list[UUID] = []
        quality_notes: list[QualityNote] = []
        listener_outcomes: list[str] = []
        known_so_far = list(project.known_concepts)

        for part_index, (part, skeleton, part_target) in enumerate(units, start=1):
            part_cells = [cells_by_key[key] for key in part.cell_keys]
            claim_to_cells = link_claims_to_cells(corpus.claims, corpus.evidence_items, part_cells)
            must_include_ids = {claim_id for claim_id, keys in claim_to_cells.items() if keys}
            part_claims = [claim for claim in corpus.claims if claim.claim_id in must_include_ids]
            part_priorities = self.claim_prioritizer.prioritize(
                project_id=project_id,
                brief=brief,
                claims=part_claims,
                coverage=coverage,
                project=project,
                must_include_claim_ids=must_include_ids,
            )
            part_plan, part_draft, run, part_notes = self.episode_planner.plan(
                project_id=project_id,
                brief=brief,
                claims=part_claims,
                coverage=coverage,
                budget=budget,
                priorities=part_priorities,
                disagreement_graph=disagreement_graph,
                extraction_plans=corpus.extraction_plans,
                definitions=corpus.definitions,
                distinctions=corpus.distinctions,
                examples=corpus.examples,
                objections=corpus.objections,
                responses=corpus.responses,
                model=model,
                prompt_version=prompt_version,
                part={
                    "part_index": part_index,
                    "part_count": len(units),
                    "part_target_minutes": part_target,
                    "cell_labels": [cell.label_fa for cell in part_cells],
                },
                segment_skeleton=[item.model_dump(mode="json") for item in skeleton],
                known_concepts=known_so_far,
            )
            # `episode_planner.plan` numbers segment_id from 1 within each part
            # call, so merging parts as-is collides ids across parts (part 2's
            # "seg-001" overwrites part 1's evidence pack / turn attribution).
            # Renumber globally, in the same book/part order the parts list is
            # already in, before merging into the project-wide segment list.
            renumbered_segments = [
                segment.model_copy(
                    update={"segment_id": f"seg-{len(all_segments) + offset + 1:03d}"}
                )
                for offset, segment in enumerate(part_plan.segments)
            ]
            all_segments.extend(renumbered_segments)
            all_draft_segments.extend(part_draft.segments)
            omitted_claims.extend(part_plan.deliberately_omitted_claims)
            follow_up_topics.extend(part_plan.follow_up_topics)
            quality_notes.extend(part_notes)
            run_ids.append(run.run_id)
            listener_outcomes.append(part_plan.listener_outcome)
            final_parts.append(
                LessonPart(
                    part_index=part_index,
                    title_fa=part.title_fa,
                    cell_keys=part.cell_keys,
                    claim_ids=[
                        claim_id
                        for segment in part_plan.segments
                        for claim_id in segment.claim_ids
                    ],
                    estimated_minutes=sum(
                        segment.estimated_minutes for segment in part_plan.segments
                    ),
                    graph_backed=part.graph_backed,
                    flags=part.flags,
                )
            )
            known_so_far = [*known_so_far, *(cell.label_fa for cell in part_cells)]

        plan = EpisodePlan(
            title=brief.normalized_topic,
            listener_outcome=" | ".join(dict.fromkeys(listener_outcomes)),
            estimated_duration_minutes=sum(part.estimated_minutes for part in final_parts),
            segments=all_segments,
            deliberately_omitted_claims=omitted_claims,
            follow_up_topics=list(dict.fromkeys(follow_up_topics)),
            parts=final_parts,
        )
        draft = EpisodePlanDraft(
            title=plan.title,
            listener_outcome=plan.listener_outcome,
            segments=all_draft_segments,
            deliberately_omitted_claims=[
                {"claim_id": item.claim_id, "reason": item.reason} for item in omitted_claims
            ],
            follow_up_topics=plan.follow_up_topics,
        )
        return plan, draft, quality_notes, run_ids

    @staticmethod
    def _build_must_not_be_lost_review(
        project_id: UUID,
        corpus: CorpusArtifacts,
        plan: EpisodePlan,
    ) -> MustNotBeLostReview:
        """Deterministic, non-blocking cross-reference -- never raises, only informs.

        Extraction 2.0 (10c P2 Step 1) flags ``must_not_be_lost`` on the claim
        itself, so this walks flagged claims directly rather than through
        block-level evidence indirection.
        """

        used_claim_ids = {
            claim_id for segment in plan.segments for claim_id in segment.claim_ids
        }

        items: list[MustNotBeLostReviewItem] = []
        unused_count = 0
        for claim in corpus.claims:
            if not claim.must_not_be_lost:
                continue
            used_in_plan = claim.claim_id in used_claim_ids
            if not used_in_plan:
                unused_count += 1
            items.append(
                MustNotBeLostReviewItem(
                    claim_id=claim.claim_id,
                    claim=claim.claim,
                    used_in_plan=used_in_plan,
                )
            )
        return MustNotBeLostReview(
            project_id=project_id,
            items=items,
            unused_count=unused_count,
        )

    def build_evidence_packs(self, project_id: UUID) -> list[SegmentEvidencePack]:
        project = self.workspace_store.load_project(project_id)
        self._require_planning_state(project)
        corpus = self._load_corpus(project_id)
        plan = self.episode_store.load_plan(project_id)
        packs = self.evidence_pack_builder.build(
            episode_plan=plan,
            claims=corpus.claims,
            evidence_items=corpus.evidence_items,
            blocks=corpus.blocks,
            extraction_plans=corpus.extraction_plans,
        )
        self.episode_store.save_evidence_packs(project_id, packs)
        manifest = self.episode_store.load_manifest(project_id)
        manifest.status = "evidence_packs_ready"
        manifest.evidence_pack_count = len(packs)
        manifest.updated_at = datetime.now(UTC)
        self.episode_store.save_manifest(manifest)
        if project.state == ProjectState.EPISODE_PLANNING:
            transition(project, ProjectState.EPISODE_PLANNED)
            self.workspace_store.save_project(project)
        return packs

    def prepare_episode(
        self,
        project_id: UUID,
        *,
        coverage_model: str,
        planning_model: str,
        prompt_version: str | None = None,
    ) -> tuple[
        CoverageReport,
        ClaimPriorityReport,
        EpisodeBudgetReport,
        DisagreementGraph,
        EpisodePlan,
        list[SegmentEvidencePack],
    ]:
        try:
            coverage = self.audit_coverage(
                project_id,
                model=coverage_model,
                prompt_version=prompt_version,
            )
            if not coverage.can_plan_episode:
                raise ValueError(
                    "Coverage audit blocked episode planning: "
                    f"{coverage.recommendation_reason}"
                )
            priorities = self.prioritize_claims(project_id)
            budget = self.estimate_budget(project_id)
            if budget.effective_supported_minutes < budget.target_duration_minutes * 0.8:
                raise ValueError(
                    "Deterministic budget blocked episode planning: corpus supports "
                    f"{budget.effective_supported_minutes:.1f} minutes for a "
                    f"{budget.target_duration_minutes}-minute request."
                )
            graph = self.build_disagreement_graph(project_id)
            plan = self.plan_episode(
                project_id,
                model=planning_model,
                prompt_version=prompt_version,
            )
            packs = self.build_evidence_packs(project_id)
            return coverage, priorities, budget, graph, plan, packs
        except (FileNotFoundError, ModelError, ValueError) as exc:
            self._mark_failed(project_id, str(exc))
            raise

    @staticmethod
    def _planning_key(
        corpus: CorpusArtifacts,
        brief: ResearchBrief,
        *,
        include_duration: bool,
        semantic: dict[str, object],
    ) -> str:
        return planning_input_key(
            source_ids=corpus.source_ids,
            claim_ids=[claim.claim_id for claim in corpus.claims],
            extraction_plans=corpus.extraction_plans,
            brief=brief,
            include_duration=include_duration,
            semantic=semantic,
        )

    def _reusable_coverage(
        self,
        project_id: UUID,
        key: str,
        brief: ResearchBrief,
        *,
        semantic: dict[str, object],
        lesson_intent: LessonIntent | None = None,
    ) -> tuple[CoverageReport | None, str | None]:
        """Return the stored audit when the corpus and the research question are the same.

        The verdict is re-derived for the duration currently requested, so a reduced
        duration is answered from the audit already paid for.
        """

        stored_inputs = self.episode_store.load_stage_inputs(project_id)
        if stored_inputs.coverage != key:
            reason = first_mismatch(
                stored_inputs.coverage_semantic,
                semantic,
                ("model", "prompt_version", "stage_version"),
            )
            return None, reason or "input_key_mismatch"
        try:
            report = self.episode_store.load_coverage(project_id)
        except (OSError, ValueError):
            return None, "artifact_missing"
        verdict = can_plan_episode(
            recommendation=report.recommendation,
            max_supported_minutes=report.max_supported_minutes,
            target_duration_minutes=brief.target_duration_minutes,
            lesson_intent=lesson_intent,
        )
        if report.can_plan_episode != verdict:
            report.can_plan_episode = verdict
            self.episode_store.save_coverage(report)
        return report, None

    def _reusable_plan(
        self,
        project_id: UUID,
        stored_inputs: EpisodeStageInputs,
        key: str,
        semantic: dict[str, object],
    ) -> tuple[EpisodePlan | None, str | None]:
        if stored_inputs.plan != key:
            reason = first_mismatch(
                stored_inputs.plan_semantic,
                semantic,
                ("model", "prompt_version", "stage_version"),
            )
            return None, reason or "input_key_mismatch"
        try:
            return self.episode_store.load_plan(project_id), None
        except (OSError, ValueError):
            return None, "artifact_missing"

    def _save_coverage_manifest(
        self,
        project_id: UUID,
        report: CoverageReport,
        source_ids: list[UUID],
    ) -> None:
        self.episode_store.save_manifest(
            EpisodePreparationManifest(
                project_id=project_id,
                status="coverage_ready",
                source_ids=source_ids,
                coverage_recommendation=report.recommendation,
                model_run_ids=[report.model_run_id],
            )
        )

    def _load_corpus(self, project_id: UUID) -> CorpusArtifacts:
        project = self.workspace_store.load_project(project_id)
        claim_ready_ids = self.source_store.list_claim_ready_source_ids(project_id)
        source_ids = [
            source.source_id for source in project.sources if source.usable_as_evidence
        ]
        if not project.sources:
            source_ids = claim_ready_ids
        if not source_ids:
            raise ValueError("The project has no confirmed evidence sources.")

        claim_ready = set(claim_ready_ids)
        missing = [source_id for source_id in source_ids if source_id not in claim_ready]
        if missing:
            missing_text = ", ".join(str(source_id) for source_id in missing)
            raise ValueError(
                "Confirmed corpus contains sources that are not claim-ready: "
                f"{missing_text}"
            )

        ledgers: list[ClaimLedger] = []
        evidence_items: list[EvidenceItem] = []
        blocks: list[SourceDocumentBlock] = []
        extraction_plans: list[EvidenceExtractionPlan] = []
        project_brief = project.brief
        for source_id in source_ids:
            source_blocks = self.source_store.load_blocks(project_id, source_id)
            blocks.extend(source_blocks)
            try:
                plan = self.source_store.load_extraction_plan(project_id, source_id)
            except (OSError, ValueError):
                if project_brief is None:
                    raise
                document_map = self.source_store.load_document_map(project_id, source_id)
                seed_cells, force_depth = resolve_extraction_seeds(
                    project, effective_concept_map(self.source_store, project_id, source_id)
                )
                plan = plan_evidence_extraction(
                    project_brief,
                    document_map,
                    source_blocks,
                    seed_cells=seed_cells,
                    force_depth=force_depth,
                    project=project,
                )
            extraction_plans.append(plan)
            ledger = self.source_store.load_claim_ledger(project_id, source_id)
            source_evidence = self.source_store.load_evidence_items(project_id, source_id)
            scoped_claims, scoped_evidence = scope_claims_and_evidence(
                ledger.claims,
                source_evidence,
                plan.selected_block_ids,
            )
            ledgers.append(
                ClaimLedger(
                    source_id=ledger.source_id,
                    claims=scoped_claims,
                    unresolved_evidence_ids=[
                        evidence_id
                        for evidence_id in ledger.unresolved_evidence_ids
                        if evidence_id in {item.evidence_id for item in scoped_evidence}
                    ],
                    warnings=list(ledger.warnings),
                    definitions=scope_by_block(ledger.definitions, plan.selected_block_ids),
                    distinctions=scope_by_block(ledger.distinctions, plan.selected_block_ids),
                    examples=scope_by_block(ledger.examples, plan.selected_block_ids),
                    objections=scope_by_block(ledger.objections, plan.selected_block_ids),
                    responses=scope_by_block(ledger.responses, plan.selected_block_ids),
                    must_not_be_lost=scope_by_block(
                        ledger.must_not_be_lost, plan.selected_block_ids
                    ),
                )
            )
            evidence_items.extend(scoped_evidence)
        claims = [claim for ledger in ledgers for claim in ledger.claims]
        claim_ids = [claim.claim_id for claim in claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("Corpus contains duplicate claim IDs across sources.")
        evidence_ids = [item.evidence_id for item in evidence_items]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Corpus contains duplicate evidence IDs across sources.")
        return CorpusArtifacts(
            source_ids=source_ids,
            claims=claims,
            evidence_items=evidence_items,
            blocks=blocks,
            extraction_plans=extraction_plans,
            definitions=[item for ledger in ledgers for item in ledger.definitions],
            distinctions=[item for ledger in ledgers for item in ledger.distinctions],
            examples=[item for ledger in ledgers for item in ledger.examples],
            objections=[item for ledger in ledgers for item in ledger.objections],
            responses=[item for ledger in ledgers for item in ledger.responses],
            must_not_be_lost=[
                item for ledger in ledgers for item in ledger.must_not_be_lost
            ],
        )

    @staticmethod
    def _enter_episode_planning(project: Project) -> None:
        if project.brief is None:
            raise ValueError("ResearchBrief is required before episode planning.")
        if project.state in {
            ProjectState.CORPUS_READY,
            ProjectState.EPISODE_PLANNED,
            ProjectState.FAILED_RETRYABLE,
        }:
            transition(project, ProjectState.EPISODE_PLANNING)
        elif project.state != ProjectState.EPISODE_PLANNING:
            raise ValueError(f"Cannot prepare an episode from project state {project.state}.")

    @staticmethod
    def _require_planning_state(project: Project) -> None:
        if project.state != ProjectState.EPISODE_PLANNING:
            raise ValueError(
                f"Expected episode_planning state, found {project.state.value}."
            )

    def _mark_failed(self, project_id: UUID, message: str) -> None:
        project = self.workspace_store.load_project(project_id)
        if project.state != ProjectState.FAILED_RETRYABLE:
            mark_failed(project, message)
        else:
            project.last_error = message
            project.updated_at = datetime.now(UTC)
        self.workspace_store.save_project(project)
        try:
            manifest = self.episode_store.load_manifest(project_id)
        except FileNotFoundError:
            return
        manifest.status = "failed"
        manifest.last_error = message
        manifest.updated_at = datetime.now(UTC)
        self.episode_store.save_manifest(manifest)
