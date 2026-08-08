from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from thesisound.adapters.models.gemini import GeminiStructuredModel
from thesisound.config import Settings
from thesisound.domain import ProjectState
from thesisound.pipeline import WorkspaceStore
from thesisound.prompt_loader import PromptLoader
from thesisound.services.claim_prioritizer import ClaimPrioritizer
from thesisound.services.coverage_auditor import CoverageAuditorService
from thesisound.services.disagreement_graph import DisagreementGraphBuilder
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.episode_budget import EpisodeBudgetEstimator
from thesisound.services.episode_planner import EpisodePlannerService
from thesisound.services.episode_planning_run import (
    EpisodePlanningRunService,
    EpisodePlanningRunStore,
)
from thesisound.services.episode_preparation_service import EpisodePreparationService
from thesisound.services.evidence_pack_builder import EvidencePackBuilder
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.services.sqlite_block_retriever import SQLiteBlockRetriever


def create_episode_planner(
    settings: Settings,
    workspace: WorkspaceStore,
) -> EpisodePlanningRunService:
    source_store = SourceArtifactStore(workspace.root)
    episode_store = EpisodeArtifactStore(workspace.root)

    def preparation_service_factory(project_id: UUID) -> EpisodePreparationService:
        model_port = GeminiStructuredModel(api_key=settings.gemini_api_key)
        runner = ModelRunner(
            model_port,
            PromptLoader(),
            WorkspaceModelRunStore(
                workspace.root,
                keep_prompts=settings.keep_rendered_prompts,
            ),
            base_retry_delay_seconds=settings.model_retry_base_seconds,
        )
        retriever = SQLiteBlockRetriever(
            episode_store.retrieval_database_path(project_id)
        )
        return EpisodePreparationService(
            workspace_store=workspace,
            source_store=source_store,
            episode_store=episode_store,
            coverage_auditor=CoverageAuditorService(runner),
            claim_prioritizer=ClaimPrioritizer(),
            budget_estimator=EpisodeBudgetEstimator(),
            disagreement_builder=DisagreementGraphBuilder(),
            episode_planner=EpisodePlannerService(runner),
            evidence_pack_builder=EvidencePackBuilder(retriever),
        )

    planner = EpisodePlanningRunService(
        workspace_store=workspace,
        run_store=EpisodePlanningRunStore(workspace.root),
        episode_store=episode_store,
        preparation_service_factory=preparation_service_factory,
        coverage_model=settings.model_strong,
        planning_model=settings.model_strong,
    )
    _reconcile_completed_runs(planner, workspace)
    planner.recover_interrupted_runs()
    return planner


def _reconcile_completed_runs(
    planner: EpisodePlanningRunService,
    workspace: WorkspaceStore,
) -> None:
    """Repair the final-write window where project completion beat run completion."""

    for run in planner.run_store.list_current_runs():
        if run.status not in {"queued", "running"}:
            continue
        try:
            project = workspace.load_project(run.project_id)
        except FileNotFoundError:
            continue
        if project.state == ProjectState.EPISODE_PLANNED and project.episode_plan is not None:
            run.status = "succeeded"
            run.stage = "complete"
            run.finished_at = datetime.now(UTC)
            run.last_error = None
            planner.run_store.save(run)
