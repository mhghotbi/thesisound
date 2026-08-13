from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from thesisound.adapters.models.gemini import GeminiStructuredModel
from thesisound.config import Settings
from thesisound.domain import ProjectState
from thesisound.pipeline import WorkspaceStore
from thesisound.prompt_loader import PromptLoader
from thesisound.services.block_builder import BlockBuilder
from thesisound.services.claim_reconciler import ClaimReconcilerService
from thesisound.services.corpus_building import (
    SETTLED_SOURCE_STATUSES,
    CorpusBuildingService,
    CorpusBuildRunStore,
    CorpusSourceInput,
)
from thesisound.services.episode_planning_run import EpisodePlanningRunService
from thesisound.services.document_map_part_cache import DocumentMapPartCache
from thesisound.services.document_mapper import DocumentMapperService
from thesisound.services.evidence_extractor import EvidenceExtractorService
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner
from thesisound.services.source_analysis_service import SourceAnalysisService
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.web.source_manifest import UiSourceManifest


def create_corpus_builder(
    settings: Settings,
    workspace: WorkspaceStore,
) -> CorpusBuildingService:
    source_store = SourceArtifactStore(workspace.root)

    def analysis_service_factory() -> SourceAnalysisService:
        model_port = GeminiStructuredModel(api_keys=settings.gemini_api_keys)
        runner = ModelRunner(
            model_port,
            PromptLoader(),
            WorkspaceModelRunStore(
                workspace.root,
                keep_prompts=settings.keep_rendered_prompts,
            ),
            base_retry_delay_seconds=settings.model_retry_base_seconds,
        )
        return SourceAnalysisService(
            workspace_store=workspace,
            artifact_store=source_store,
            block_builder=BlockBuilder(),
            document_mapper=DocumentMapperService(
                runner,
                part_cache=DocumentMapPartCache(workspace.root),
                max_workers=settings.document_map_workers,
            ),
            evidence_extractor=EvidenceExtractorService(
                runner,
                max_workers=settings.evidence_extraction_workers,
                batch_size=settings.evidence_extraction_batch_size,
            ),
            claim_reconciler=ClaimReconcilerService(
                runner,
                max_workers=settings.claim_reconciliation_workers,
            ),
        )

    builder = CorpusBuildingService(
        workspace_store=workspace,
        run_store=CorpusBuildRunStore(workspace.root),
        source_store=source_store,
        analysis_service_factory=analysis_service_factory,
        fast_model=settings.model_fast,
        strong_model=settings.model_strong,
    )
    _reconcile_completed_runs(builder, workspace)
    builder.recover_interrupted_runs()
    return builder


def _reconcile_completed_runs(
    builder: CorpusBuildingService,
    workspace: WorkspaceStore,
) -> None:
    """Repair the final-write window where project completion beat run completion."""

    for run in builder.run_store.list_runs():
        if run.status not in {"queued", "running"}:
            continue
        try:
            project = workspace.load_project(run.project_id)
        except FileNotFoundError:
            continue
        if (
            project.state == ProjectState.CORPUS_READY
            and any(source.status == "succeeded" for source in run.sources)
            and all(source.status in SETTLED_SOURCE_STATUSES for source in run.sources)
        ):
            run.status = "succeeded"
            run.finished_at = datetime.now(UTC)
            run.last_error = None
            builder.run_store.save(run)


def corpus_source_inputs(
    settings: Settings,
    project_id: UUID,
    sources: list[UiSourceManifest],
) -> list[CorpusSourceInput]:
    inputs: list[CorpusSourceInput] = []
    for source in sources:
        if not source.artifact_ref:
            raise ValueError(f"Ingestion artifact is missing for source {source.source_id}.")
        root = settings.ensure_ingestion_artifact_root() / str(project_id) / str(source.source_id)
        path = (root / source.artifact_ref).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Ingestion artifact path escaped its source namespace.")
        if not path.exists():
            raise ValueError(f"Ingestion artifact was not found for source {source.source_id}.")
        inputs.append(
            CorpusSourceInput(
                source_id=source.source_id,
                filename=source.filename,
                ingestion_path=path,
            )
        )
    return inputs


def run_corpus_then_queue_planning(
    *,
    run_corpus: Callable[[UUID], object],
    workspace: WorkspaceStore,
    planner: EpisodePlanningRunService,
    run_episode: Callable[[UUID], None],
) -> Callable[[UUID], None]:
    """After a successful corpus build, queue coverage/planning automatically (spec 12 D2)."""

    def execute(project_id: UUID) -> None:
        result = run_corpus(project_id)
        status = getattr(result, "status", None)
        if status is not None and status != "succeeded":
            return
        project = workspace.load_project(project_id)
        if project.state != ProjectState.CORPUS_READY:
            return
        try:
            planner.queue(project_id)
        except ValueError:
            return
        run_episode(project_id)

    return execute
