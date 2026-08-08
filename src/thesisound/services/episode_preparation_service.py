from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from thesisound.domain import ClaimRecord, EpisodePlan, EvidenceItem, Project, ProjectState
from thesisound.episode import (
    ClaimPriorityReport,
    CoverageReport,
    DisagreementGraph,
    EpisodeBudgetReport,
    EpisodePreparationManifest,
    SegmentEvidencePack,
)
from thesisound.modeling import ModelError
from thesisound.pipeline import WorkspaceStore, mark_failed, transition
from thesisound.services.claim_prioritizer import ClaimPrioritizer
from thesisound.services.coverage_auditor import CoverageAuditorService
from thesisound.services.disagreement_graph import DisagreementGraphBuilder
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.episode_budget import EpisodeBudgetEstimator
from thesisound.services.episode_planner import EpisodePlannerService
from thesisound.services.evidence_pack_builder import EvidencePackBuilder
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
        report, run = self.coverage_auditor.audit(
            project_id=project_id,
            brief=project.brief,
            claims=corpus.claims,
            extraction_plans=corpus.extraction_plans,
            model=model,
            prompt_version=prompt_version,
        )
        self.episode_store.save_coverage(report)
        manifest = EpisodePreparationManifest(
            project_id=project_id,
            status="coverage_ready",
            source_ids=corpus.source_ids,
            coverage_recommendation=report.recommendation,
            model_run_ids=[run.run_id],
        )
        self.episode_store.save_manifest(manifest)
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
        coverage = self.episode_store.load_coverage(project_id)
        budget = self.episode_store.load_budget(project_id)
        priorities = self.episode_store.load_priorities(project_id)
        disagreement_graph = self.episode_store.load_disagreement_graph(project_id)
        plan, draft, run = self.episode_planner.plan(
            project_id=project_id,
            brief=project.brief,
            claims=corpus.claims,
            coverage=coverage,
            budget=budget,
            priorities=priorities,
            disagreement_graph=disagreement_graph,
            extraction_plans=corpus.extraction_plans,
            model=model,
            prompt_version=prompt_version,
        )
        self.episode_store.save_plan(project_id, plan, draft)
        project.episode_plan = plan
        self.workspace_store.save_project(project)
        manifest = self.episode_store.load_manifest(project_id)
        manifest.status = "plan_ready"
        manifest.segment_count = len(plan.segments)
        manifest.model_run_ids.append(run.run_id)
        manifest.updated_at = datetime.now(UTC)
        self.episode_store.save_manifest(manifest)
        return plan

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
        for source_id in source_ids:
            ledgers.append(self.source_store.load_claim_ledger(project_id, source_id))
            evidence_items.extend(
                self.source_store.load_evidence_items(project_id, source_id)
            )
            blocks.extend(self.source_store.load_blocks(project_id, source_id))
            extraction_plans.append(
                self.source_store.load_extraction_plan(project_id, source_id)
            )
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
