from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from thesisound.domain import Project, ProjectState
from thesisound.pipeline import WorkspaceStore, mark_failed, transition
from thesisound.services.source_analysis_service import SourceAnalysisService
from thesisound.services.source_artifact_store import SourceArtifactStore

CorpusRunStatus = Literal["queued", "running", "succeeded", "failed"]
CorpusSourceStatus = Literal["queued", "running", "succeeded", "failed"]
CorpusStage = Literal[
    "queued",
    "building_blocks",
    "mapping_document",
    "extracting_evidence",
    "building_claims",
    "complete",
    "failed",
]


class CorpusSourceInput(BaseModel):
    source_id: UUID
    filename: str = Field(min_length=1)
    ingestion_path: Path


class CorpusSourceRun(CorpusSourceInput):
    status: CorpusSourceStatus = "queued"
    stage: CorpusStage = "queued"
    claim_count: int = Field(default=0, ge=0)
    last_error: str | None = None


class CorpusBuildRun(BaseModel):
    run_id: UUID = Field(default_factory=uuid4)
    previous_run_id: UUID | None = None
    project_id: UUID
    status: CorpusRunStatus = "queued"
    sources: list[CorpusSourceRun] = Field(min_length=1)
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    last_error: str | None = None

    @property
    def completed_source_count(self) -> int:
        return sum(source.status == "succeeded" for source in self.sources)


class CorpusBuildRunStore:
    """Persist the latest corpus run and every retry attempt."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()

    def path(self, project_id: UUID) -> Path:
        """Compatibility pointer to the latest attempt."""

        return self.workspace_root / str(project_id) / "corpus-build-run.json"

    def history_dir(self, project_id: UUID) -> Path:
        return self.workspace_root / str(project_id) / "runs" / "corpus"

    def attempt_path(self, project_id: UUID, run_id: UUID) -> Path:
        return self.history_dir(project_id) / f"{run_id}.json"

    def load(self, project_id: UUID) -> CorpusBuildRun:
        path = self.path(project_id)
        if not path.exists():
            raise FileNotFoundError(f"Corpus build run not found: {project_id}")
        return CorpusBuildRun.model_validate_json(path.read_text(encoding="utf-8"))

    def load_optional(self, project_id: UUID) -> CorpusBuildRun | None:
        try:
            return self.load(project_id)
        except FileNotFoundError:
            return None

    def load_history(self, project_id: UUID) -> list[CorpusBuildRun]:
        directory = self.history_dir(project_id)
        if not directory.exists():
            return []
        runs: list[CorpusBuildRun] = []
        for path in directory.glob("*.json"):
            try:
                runs.append(CorpusBuildRun.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(runs, key=lambda run: run.updated_at)

    def list_runs(self) -> list[CorpusBuildRun]:
        """Return one latest run per project for startup recovery."""

        runs: list[CorpusBuildRun] = []
        for path in self.workspace_root.glob("*/corpus-build-run.json"):
            try:
                runs.append(CorpusBuildRun.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return runs

    def save(self, run: CorpusBuildRun) -> Path:
        run.updated_at = datetime.now(UTC)
        payload = json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        attempt = self.attempt_path(run.project_id, run.run_id)
        latest = self.path(run.project_id)
        _atomic_write(attempt, payload)
        _atomic_write(latest, payload)
        return latest


class CorpusBuildingService:
    """Build every selected source before promoting a project to CORPUS_READY."""

    def __init__(
        self,
        *,
        workspace_store: WorkspaceStore,
        run_store: CorpusBuildRunStore,
        source_store: SourceArtifactStore,
        analysis_service_factory: Callable[[], SourceAnalysisService],
        fast_model: str,
        strong_model: str,
    ) -> None:
        self.workspace_store = workspace_store
        self.run_store = run_store
        self.source_store = source_store
        self.analysis_service_factory = analysis_service_factory
        self.fast_model = fast_model
        self.strong_model = strong_model
        self._mutation_lock = Lock()

    def recover_interrupted_runs(self) -> list[UUID]:
        """Turn orphaned queued/running work into an explicit retryable failure."""

        recovered: list[UUID] = []
        message = "Corpus building was interrupted by a service restart. Retry to continue."
        for run in self.run_store.list_runs():
            if run.status not in {"queued", "running"}:
                continue
            for source in run.sources:
                if source.status == "running":
                    source.status = "failed"
                    source.stage = "failed"
                    source.last_error = message
            run.status = "failed"
            run.last_error = message
            run.finished_at = datetime.now(UTC)
            self.run_store.save(run)

            try:
                project = self.workspace_store.load_project(run.project_id)
            except FileNotFoundError:
                recovered.append(run.project_id)
                continue
            if project.state == ProjectState.CORPUS_BUILDING:
                mark_failed(project, message)
                self.workspace_store.save_project(project)
            recovered.append(run.project_id)
        return recovered

    def confirm_project(
        self,
        original_project: Project,
        confirmed_project: Project,
        sources: list[CorpusSourceInput],
    ) -> CorpusBuildRun:
        """Persist the confirmed project and queued run as one compensated mutation."""

        if original_project.project_id != confirmed_project.project_id:
            raise ValueError("Original and confirmed projects do not match.")
        if confirmed_project.state != ProjectState.CORPUS_BUILDING:
            raise ValueError("Confirmed project must be in CORPUS_BUILDING.")

        with self._mutation_lock:
            current = self.workspace_store.load_project(original_project.project_id)
            if current != original_project:
                raise ValueError("Project changed while corpus confirmation was in progress.")
            self.workspace_store.save_project(confirmed_project)
            try:
                return self.queue(confirmed_project.project_id, sources)
            except Exception:
                self.workspace_store.save_project(original_project)
                raise

    def queue(
        self,
        project_id: UUID,
        sources: list[CorpusSourceInput],
    ) -> CorpusBuildRun:
        project = self.workspace_store.load_project(project_id)
        if project.state != ProjectState.CORPUS_BUILDING:
            raise ValueError("Corpus building can only be queued from CORPUS_BUILDING.")
        existing = self.run_store.load_optional(project_id)
        if existing is not None and existing.status in {"queued", "running"}:
            raise ValueError("A corpus-building run is already active for this project.")
        if not sources:
            raise ValueError("At least one selected source is required.")
        source_ids = [source.source_id for source in sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Corpus source IDs must be unique.")
        run = CorpusBuildRun(
            project_id=project_id,
            previous_run_id=existing.run_id if existing else None,
            sources=[CorpusSourceRun(**source.model_dump()) for source in sources],
        )
        self.run_store.save(run)
        return run

    def retry(self, project_id: UUID) -> CorpusBuildRun:
        project = self.workspace_store.load_project(project_id)
        if project.state != ProjectState.FAILED_RETRYABLE:
            raise ValueError("Only a retryable failed project can restart corpus building.")
        previous = self.run_store.load(project_id)
        if previous.status != "failed":
            raise ValueError("The latest corpus run is not failed.")

        sources: list[CorpusSourceRun] = []
        for source in previous.sources:
            if source.status == "succeeded":
                sources.append(source.model_copy(deep=True))
            else:
                sources.append(
                    CorpusSourceRun(
                        source_id=source.source_id,
                        filename=source.filename,
                        ingestion_path=source.ingestion_path,
                    )
                )
        run = CorpusBuildRun(
            project_id=project_id,
            previous_run_id=previous.run_id,
            sources=sources,
        )
        self.run_store.save(run)
        return run

    def run(self, project_id: UUID) -> CorpusBuildRun:
        run = self.run_store.load(project_id)
        if run.status == "succeeded":
            return run
        if run.status != "queued":
            raise ValueError(f"Cannot start corpus run with status {run.status}.")

        project = self.workspace_store.load_project(project_id)
        if project.state == ProjectState.FAILED_RETRYABLE:
            transition(project, ProjectState.CORPUS_BUILDING)
            self.workspace_store.save_project(project)
        if project.state != ProjectState.CORPUS_BUILDING:
            raise ValueError(f"Cannot build corpus from project state {project.state}.")

        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.finished_at = None
        run.last_error = None
        self.run_store.save(run)

        try:
            service = self.analysis_service_factory()
            for source in run.sources:
                if source.status == "succeeded":
                    continue
                self._run_source(service, run, source)

            project = self.workspace_store.load_project(project_id)
            if project.state != ProjectState.CORPUS_BUILDING:
                raise ValueError(
                    "Project left CORPUS_BUILDING before every selected source completed."
                )
            transition(project, ProjectState.CORPUS_READY)
            self.workspace_store.save_project(project)
            run.status = "succeeded"
            run.finished_at = datetime.now(UTC)
            self.run_store.save(run)
            return run
        except Exception as exc:
            message = str(exc)[:1_000] or type(exc).__name__
            project = self.workspace_store.load_project(project_id)
            if project.state != ProjectState.FAILED_RETRYABLE:
                mark_failed(project, message)
            else:
                project.last_error = message
                project.updated_at = datetime.now(UTC)
            self.workspace_store.save_project(project)
            run.status = "failed"
            run.last_error = message
            run.finished_at = datetime.now(UTC)
            self.run_store.save(run)
            return run

    def _run_source(
        self,
        service: SourceAnalysisService,
        run: CorpusBuildRun,
        source: CorpusSourceRun,
    ) -> None:
        source.status = "running"
        source.last_error = None
        self._set_stage(run, source, "building_blocks")
        try:
            ingestion = self.source_store.load_ingestion(source.ingestion_path)
            resolved_source_id, _, _ = service.build_blocks(
                run.project_id,
                ingestion,
                source_id=source.source_id,
            )
            if resolved_source_id != source.source_id:
                raise ValueError("Source-analysis service changed the selected source ID.")

            self._set_stage(run, source, "mapping_document")
            service.map_document(
                run.project_id,
                source.source_id,
                model=self.fast_model,
            )

            self._set_stage(run, source, "extracting_evidence")
            service.extract_evidence(
                run.project_id,
                source.source_id,
                model=self.fast_model,
            )

            self._set_stage(run, source, "building_claims")
            ledger, _ = service.build_claims(
                run.project_id,
                source.source_id,
                model=self.strong_model,
                finalize_project=False,
            )
            source.claim_count = len(ledger.claims)
            source.status = "succeeded"
            source.stage = "complete"
            self.run_store.save(run)
        except Exception as exc:
            source.status = "failed"
            source.stage = "failed"
            source.last_error = str(exc)[:1_000] or type(exc).__name__
            self.run_store.save(run)
            raise

    def _set_stage(
        self,
        run: CorpusBuildRun,
        source: CorpusSourceRun,
        stage: CorpusStage,
    ) -> None:
        source.stage = stage
        self.run_store.save(run)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
