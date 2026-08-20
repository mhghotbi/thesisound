from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from thesisound import tracing
from thesisound.domain import Project, ProjectState
from thesisound.pipeline import WorkspaceStore, mark_failed, transition
from thesisound.services.corpus_reuse import reusable_claim_ledger
from thesisound.services.source_analysis_service import SourceAnalysisService
from thesisound.services.source_artifact_store import SourceArtifactStore

CorpusRunStatus = Literal["queued", "running", "succeeded", "failed"]
CorpusSourceStatus = Literal["queued", "running", "succeeded", "skipped", "failed"]
CorpusStage = Literal[
    "queued",
    "building_blocks",
    "mapping_document",
    "extracting_evidence",
    "building_claims",
    "complete",
    "skipped",
    "failed",
]
# A settled source needs no further work in any later attempt of the same corpus.
SETTLED_SOURCE_STATUSES: frozenset[str] = frozenset({"succeeded", "skipped"})


class CorpusSourceInput(BaseModel):
    source_id: UUID
    filename: str = Field(min_length=1)
    ingestion_path: Path


class CorpusSourceRun(CorpusSourceInput):
    status: CorpusSourceStatus = "queued"
    stage: CorpusStage = "queued"
    claim_count: int = Field(default=0, ge=0)
    last_error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    carried_forward: bool = False
    """Finished before this attempt and reused instead of rebuilt."""


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

    @property
    def skipped_source_count(self) -> int:
        return sum(source.status == "skipped" for source in self.sources)

    @property
    def selected_source_count(self) -> int:
        """Sources still part of the corpus, excluding the ones the user dropped."""

        return len(self.sources) - self.skipped_source_count


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
            sources=[self._confirmed_source(project, source) for source in sources],
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

        run = CorpusBuildRun(
            project_id=project_id,
            previous_run_id=previous.run_id,
            sources=_next_attempt_sources(previous),
        )
        self.run_store.save(run)
        return run

    def skip_source(self, project_id: UUID, source_id: UUID) -> CorpusBuildRun:
        """Drop one stopped source and continue the corpus with what is left.

        The dropped source also leaves the confirmed selection on the project, because
        every later stage reads `Project.sources` and requires a claim ledger for each
        of them.
        """

        with self._mutation_lock:
            previous = self.run_store.load(project_id)
            if previous.status != "failed":
                raise ValueError("Only a stopped corpus run can drop a source.")
            target = next(
                (source for source in previous.sources if source.source_id == source_id),
                None,
            )
            if target is None:
                raise ValueError("The source is not part of the latest corpus run.")
            if target.status not in {"queued", "failed"}:
                raise ValueError(f"A {target.status} source cannot be dropped.")

            original_project = self.workspace_store.load_project(project_id)
            if original_project.state not in {
                ProjectState.CORPUS_BUILDING,
                ProjectState.FAILED_RETRYABLE,
            }:
                raise ValueError(
                    f"Cannot drop a source from project state {original_project.state}."
                )

            sources = _next_attempt_sources(previous, skip_source_id=source_id)
            if all(source.status == "skipped" for source in sources):
                raise ValueError("At least one source must stay in the corpus.")
            skipped_ids = {
                source.source_id for source in sources if source.status == "skipped"
            }

            project = original_project.model_copy(deep=True)
            project.sources = [
                source
                for source in project.sources
                if source.source_id not in skipped_ids
            ]
            project.updated_at = datetime.now(UTC)
            self.workspace_store.save_project(project)
            try:
                run = CorpusBuildRun(
                    project_id=project_id,
                    previous_run_id=previous.run_id,
                    sources=sources,
                )
                self.run_store.save(run)
            except Exception:
                self.workspace_store.save_project(original_project)
                raise
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

        # new_root=True: this runs from a FastAPI BackgroundTasks callback, so the
        # HTTP request that queued it has already returned and its span (if any)
        # has already closed. Attaching to it would nest a long-running child under
        # a parent whose lifetime already ended.
        with tracing.span(
            "corpus.run",
            component="corpus",
            kind="stage",
            new_root=True,
            project_id=project_id,
            workflow_run_id=run.run_id,
            source_count=len(run.sources),
        ) as root:
            try:
                service: SourceAnalysisService | None = None
                for source in run.sources:
                    if source.status in SETTLED_SOURCE_STATUSES:
                        continue
                    if service is None:
                        service = self.analysis_service_factory()
                    with tracing.span(
                        "corpus.source",
                        component="corpus",
                        kind="stage",
                        subject_type="source",
                        subject_id=str(source.source_id),
                    ) as source_span:
                        self._run_source(service, run, source)
                        source_span.set(
                            status=source.status, carried_forward=source.carried_forward
                        )
                        source_span.measure(claim_count=source.claim_count)

                if not any(source.status == "succeeded" for source in run.sources):
                    raise ValueError("Every selected source was dropped; the corpus is empty.")

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
                root.measure(
                    succeeded=run.completed_source_count,
                    skipped=run.skipped_source_count,
                )
                return run
            except Exception as exc:
                # The exception is deliberately swallowed below (run() always
                # returns a CorpusBuildRun, never raises), so the span's own
                # automatic exception handling never fires -- mark it explicitly.
                root.mark("error", reason=type(exc).__name__)
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

    def _confirmed_source(
        self,
        project: Project,
        source: CorpusSourceInput,
    ) -> CorpusSourceRun:
        """Carry a finished source into the new run instead of rebuilding it."""

        queued = CorpusSourceRun(**source.model_dump())
        ledger = reusable_claim_ledger(
            artifact_store=self.source_store,
            project=project,
            source_id=source.source_id,
            ingestion_path=source.ingestion_path,
            model=self.strong_model,
        )
        # Hit/miss lineage is emitted inside reusable_claim_ledger.
        if ledger is None:
            return queued
        queued.status = "succeeded"
        queued.stage = "complete"
        queued.claim_count = len(ledger.claims)
        queued.carried_forward = True
        return queued

    def _run_source(
        self,
        service: SourceAnalysisService,
        run: CorpusBuildRun,
        source: CorpusSourceRun,
    ) -> None:
        source.status = "running"
        source.last_error = None
        source.warnings = []
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

            if service.has_reusable_document_map(run.project_id, source.source_id):
                self._set_stage(run, source, "extracting_evidence")
            else:
                self._set_stage(run, source, "mapping_document")
            service.map_document(
                run.project_id,
                source.source_id,
                model=self.fast_model,
            )

            self._set_stage(run, source, "extracting_evidence")
            _, extraction_warnings = service.extract_evidence(
                run.project_id,
                source.source_id,
                model=self.fast_model,
            )
            source.warnings.extend(extraction_warnings)

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
        previous = source.stage
        source.stage = stage
        self.run_store.save(run)
        tracing.event(
            "run.stage_changed",
            component="corpus",
            project_id=run.project_id,
            workflow_run_id=run.run_id,
            subject_type="source",
            subject_id=str(source.source_id),
            previous=previous,
            current=stage,
        )


def _next_attempt_sources(
    previous: CorpusBuildRun,
    *,
    skip_source_id: UUID | None = None,
) -> list[CorpusSourceRun]:
    """Keep settled sources, drop the skipped one, and re-queue everything else."""

    sources: list[CorpusSourceRun] = []
    for source in previous.sources:
        if source.source_id == skip_source_id:
            dropped = source.model_copy(deep=True)
            dropped.status = "skipped"
            dropped.stage = "skipped"
            sources.append(dropped)
        elif source.status in SETTLED_SOURCE_STATUSES:
            sources.append(source.model_copy(deep=True))
        else:
            sources.append(
                CorpusSourceRun(
                    source_id=source.source_id,
                    filename=source.filename,
                    ingestion_path=source.ingestion_path,
                )
            )
    return sources


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
