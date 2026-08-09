from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from thesisound import tracing
from thesisound.domain import ProjectState
from thesisound.pipeline import WorkspaceStore, mark_failed, transition
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.episode_preparation_service import EpisodePreparationService

EpisodePlanningStatus = Literal["queued", "running", "blocked", "succeeded", "failed"]
EpisodePlanningStage = Literal[
    "queued",
    "auditing_coverage",
    "prioritizing_claims",
    "estimating_budget",
    "building_disagreements",
    "planning_episode",
    "building_evidence_packs",
    "blocked",
    "complete",
    "failed",
]


class EpisodePlanningRun(BaseModel):
    run_id: UUID = Field(default_factory=uuid4)
    previous_run_id: UUID | None = None
    project_id: UUID
    status: EpisodePlanningStatus = "queued"
    stage: EpisodePlanningStage = "queued"
    target_duration_minutes: int = Field(ge=5, le=120)
    max_supported_minutes: int | None = Field(default=None, ge=0, le=120)
    effective_supported_minutes: float | None = Field(default=None, ge=0, le=120)
    coverage_recommendation: str | None = None
    material_gaps: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    last_error: str | None = None

    @property
    def supported_duration_minutes(self) -> float | None:
        candidates = [
            value
            for value in (self.max_supported_minutes, self.effective_supported_minutes)
            if value is not None
        ]
        return min(candidates) if candidates else None


class EpisodePlanningRunStore:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()

    def current_path(self, project_id: UUID) -> Path:
        return self.workspace_root / str(project_id) / "episode" / "planning-run.json"

    def history_dir(self, project_id: UUID) -> Path:
        return self.workspace_root / str(project_id) / "runs" / "episode-planning"

    def attempt_path(self, project_id: UUID, run_id: UUID) -> Path:
        return self.history_dir(project_id) / f"{run_id}.json"

    def load(self, project_id: UUID) -> EpisodePlanningRun:
        path = self.current_path(project_id)
        if not path.exists():
            raise FileNotFoundError(f"Episode planning run not found: {project_id}")
        return EpisodePlanningRun.model_validate_json(path.read_text(encoding="utf-8"))

    def load_optional(self, project_id: UUID) -> EpisodePlanningRun | None:
        try:
            return self.load(project_id)
        except FileNotFoundError:
            return None

    def load_history(self, project_id: UUID) -> list[EpisodePlanningRun]:
        directory = self.history_dir(project_id)
        if not directory.exists():
            return []
        runs: list[EpisodePlanningRun] = []
        for path in directory.glob("*.json"):
            try:
                runs.append(
                    EpisodePlanningRun.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError):
                continue
        return sorted(runs, key=lambda run: run.updated_at)

    def list_current_runs(self) -> list[EpisodePlanningRun]:
        runs: list[EpisodePlanningRun] = []
        for path in self.workspace_root.glob("*/episode/planning-run.json"):
            try:
                runs.append(
                    EpisodePlanningRun.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError):
                continue
        return runs

    def save(self, run: EpisodePlanningRun) -> Path:
        run.updated_at = datetime.now(UTC)
        payload = json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        attempt = self.attempt_path(run.project_id, run.run_id)
        current = self.current_path(run.project_id)
        _atomic_write(attempt, payload)
        _atomic_write(current, payload)
        return current

    def mark_outputs_stale(self, project_id: UUID, reason: str) -> Path:
        payload = {
            "project_id": str(project_id),
            "reason": reason,
            "marked_at": datetime.now(UTC).isoformat(),
        }
        path = self.workspace_root / str(project_id) / "episode" / "stale.json"
        _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return path


class EpisodePlanningRunService:
    """Orchestrate coverage and plan creation without bypassing the review gate."""

    def __init__(
        self,
        *,
        workspace_store: WorkspaceStore,
        run_store: EpisodePlanningRunStore,
        episode_store: EpisodeArtifactStore,
        preparation_service_factory: Callable[[UUID], EpisodePreparationService],
        coverage_model: str,
        planning_model: str,
    ) -> None:
        self.workspace_store = workspace_store
        self.run_store = run_store
        self.episode_store = episode_store
        self.preparation_service_factory = preparation_service_factory
        self.coverage_model = coverage_model
        self.planning_model = planning_model

    def recover_interrupted_runs(self) -> list[UUID]:
        message = "Episode planning was interrupted by a service restart. Retry to continue."
        recovered: list[UUID] = []
        for run in self.run_store.list_current_runs():
            if run.status not in {"queued", "running"}:
                continue
            run.status = "failed"
            run.stage = "failed"
            run.last_error = message
            run.finished_at = datetime.now(UTC)
            self.run_store.save(run)
            try:
                project = self.workspace_store.load_project(run.project_id)
            except FileNotFoundError:
                recovered.append(run.project_id)
                continue
            if project.state == ProjectState.EPISODE_PLANNING:
                mark_failed(project, message)
                self.workspace_store.save_project(project)
            recovered.append(run.project_id)
        return recovered

    def queue(self, project_id: UUID) -> EpisodePlanningRun:
        project = self.workspace_store.load_project(project_id)
        if project.state != ProjectState.CORPUS_READY:
            raise ValueError("Episode planning can only start from CORPUS_READY.")
        if project.brief is None:
            raise ValueError("ResearchBrief is required before episode planning.")
        existing = self.run_store.load_optional(project_id)
        if existing is not None and existing.status in {"queued", "running"}:
            raise ValueError("An episode-planning run is already active.")
        run = EpisodePlanningRun(
            project_id=project_id,
            previous_run_id=existing.run_id if existing else None,
            target_duration_minutes=project.brief.target_duration_minutes,
        )
        self.run_store.save(run)
        return run

    def retry(self, project_id: UUID) -> EpisodePlanningRun:
        project = self.workspace_store.load_project(project_id)
        if project.state != ProjectState.FAILED_RETRYABLE:
            raise ValueError("Only a retryable planning failure can be retried.")
        previous = self.run_store.load(project_id)
        if previous.status != "failed":
            raise ValueError("The latest episode-planning run is not failed.")
        if project.brief is None:
            raise ValueError("ResearchBrief is required before episode planning.")
        run = EpisodePlanningRun(
            project_id=project_id,
            previous_run_id=previous.run_id,
            target_duration_minutes=project.brief.target_duration_minutes,
        )
        self.run_store.save(run)
        return run

    def requeue_with_duration(
        self,
        project_id: UUID,
        duration_minutes: int,
    ) -> EpisodePlanningRun:
        project = self.workspace_store.load_project(project_id)
        previous = self.run_store.load(project_id)
        # Both ceilings are recorded before the run can block, so a finished plan knows
        # its supported duration just as well as a blocked one does. The episode plan is
        # the only artifact duration has reached by either point, and it is rebuilt here.
        if (project.state, previous.status) not in {
            (ProjectState.EPISODE_PLANNING, "blocked"),
            (ProjectState.EPISODE_PLANNED, "succeeded"),
        }:
            raise ValueError(
                "Duration can only change from a blocked coverage review or a finished "
                f"episode plan; this project is in an invalid state ({project.state.value})."
            )
        if project.brief is None:
            raise ValueError("ResearchBrief is required before episode planning.")
        if not 5 <= duration_minutes <= 120:
            raise ValueError("Duration must be between 5 and 120 minutes.")
        supported = previous.supported_duration_minutes
        if supported is not None and duration_minutes > supported:
            raise ValueError("The selected duration is still longer than the supported corpus.")
        project.brief.target_duration_minutes = duration_minutes
        project.episode_plan = None
        if project.state == ProjectState.EPISODE_PLANNED:
            transition(project, ProjectState.EPISODE_PLANNING)
        self.workspace_store.save_project(project)
        run = EpisodePlanningRun(
            project_id=project_id,
            previous_run_id=previous.run_id,
            target_duration_minutes=duration_minutes,
        )
        self.run_store.save(run)
        if previous.status == "blocked":
            tracing.event(
                "gate.resolved",
                component="episode",
                project_id=project_id,
                workflow_run_id=previous.run_id,
                resolution="reduced_duration",
            )
        return run

    def reopen_inputs(self, project_id: UUID, *, reason: str) -> None:
        project = self.workspace_store.load_project(project_id)
        run = self.run_store.load(project_id)
        if project.state != ProjectState.EPISODE_PLANNING or run.status != "blocked":
            raise ValueError("Inputs can only reopen after a blocked coverage review.")
        project.episode_plan = None
        transition(project, ProjectState.SOURCES_COLLECTING)
        self.workspace_store.save_project(project)
        self.run_store.mark_outputs_stale(project_id, reason)
        tracing.event(
            "gate.resolved",
            component="episode",
            project_id=project_id,
            workflow_run_id=run.run_id,
            resolution="reopened_inputs",
        )

    def run(self, project_id: UUID) -> EpisodePlanningRun:
        run = self.run_store.load(project_id)
        if run.status in {"blocked", "succeeded"}:
            return run
        if run.status != "queued":
            raise ValueError(f"Cannot start episode planning with status {run.status}.")

        project = self.workspace_store.load_project(project_id)
        if project.state in {ProjectState.CORPUS_READY, ProjectState.FAILED_RETRYABLE}:
            transition(project, ProjectState.EPISODE_PLANNING)
            self.workspace_store.save_project(project)
        if project.state != ProjectState.EPISODE_PLANNING:
            raise ValueError(f"Cannot plan episode from project state {project.state}.")

        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.finished_at = None
        run.last_error = None
        self.run_store.save(run)

        # new_root=True: runs from a BackgroundTasks callback after the request that
        # queued it has already returned, so there is no live parent span to attach to.
        with tracing.span(
            "episode.run",
            component="episode",
            kind="stage",
            new_root=True,
            project_id=project_id,
            workflow_run_id=run.run_id,
        ) as root:
            try:
                service = self.preparation_service_factory(project_id)

                self._set_stage(run, "auditing_coverage")
                with tracing.span("episode.audit_coverage", component="episode") as span:
                    coverage = service.audit_coverage(project_id, model=self.coverage_model)
                    span.set(can_plan_episode=coverage.can_plan_episode)
                run.max_supported_minutes = coverage.max_supported_minutes
                run.coverage_recommendation = coverage.recommendation
                run.material_gaps = list(coverage.material_gaps)
                self.run_store.save(run)
                if not coverage.can_plan_episode:
                    root.mark("blocked", reason="coverage_insufficient")
                    return self._block(run, coverage.recommendation_reason)

                self._set_stage(run, "prioritizing_claims")
                with tracing.span("episode.prioritize_claims", component="episode"):
                    service.prioritize_claims(project_id)

                self._set_stage(run, "estimating_budget")
                with tracing.span("episode.estimate_budget", component="episode") as span:
                    budget = service.estimate_budget(project_id)
                    span.set(
                        effective_supported_minutes=budget.effective_supported_minutes,
                        target_duration_minutes=budget.target_duration_minutes,
                    )
                run.effective_supported_minutes = budget.effective_supported_minutes
                self.run_store.save(run)
                if budget.effective_supported_minutes < budget.target_duration_minutes * 0.8:
                    root.mark("blocked", reason="budget_insufficient")
                    return self._block(
                        run,
                        "مجموعه منابع برای مدت درخواستی محتوای مستند کافی ندارد.",
                    )

                self._set_stage(run, "building_disagreements")
                with tracing.span("episode.build_disagreement_graph", component="episode"):
                    service.build_disagreement_graph(project_id)

                self._set_stage(run, "planning_episode")
                with tracing.span("episode.plan_episode", component="episode"):
                    service.plan_episode(project_id, model=self.planning_model)

                self._set_stage(run, "building_evidence_packs")
                with tracing.span("episode.build_evidence_packs", component="episode"):
                    service.build_evidence_packs(project_id)

                run.status = "succeeded"
                run.stage = "complete"
                run.finished_at = datetime.now(UTC)
                self.run_store.save(run)
                return run
            except Exception as exc:
                # run() always returns an EpisodePlanningRun, never raises, so the
                # span's own automatic exception handling never fires here.
                root.mark("error", reason=type(exc).__name__)
                message = str(exc)[:1_000] or type(exc).__name__
                project = self.workspace_store.load_project(project_id)
                if project.state != ProjectState.FAILED_RETRYABLE:
                    mark_failed(project, message)
                else:
                    project.last_error = message
                    project.updated_at = datetime.now(UTC)
                self.workspace_store.save_project(project)
                self._mark_manifest_failed(project_id, message)
                run.status = "failed"
                run.stage = "failed"
                run.last_error = message
                run.finished_at = datetime.now(UTC)
                self.run_store.save(run)
                return run

    def _block(self, run: EpisodePlanningRun, reason: str) -> EpisodePlanningRun:
        run.status = "blocked"
        run.stage = "blocked"
        run.last_error = reason
        run.finished_at = datetime.now(UTC)
        self.run_store.save(run)
        # Paired with "gate.resolved" in requeue_with_duration()/reopen_inputs() --
        # the time between the two is real, unmeasured-until-now human wait time,
        # usually the largest slice of this project's end-to-end latency.
        tracing.event(
            "gate.blocked",
            component="episode",
            project_id=run.project_id,
            workflow_run_id=run.run_id,
            reason=reason,
        )
        return run

    def _set_stage(self, run: EpisodePlanningRun, stage: EpisodePlanningStage) -> None:
        previous = run.stage
        run.stage = stage
        self.run_store.save(run)
        tracing.event(
            "run.stage_changed",
            component="episode",
            project_id=run.project_id,
            workflow_run_id=run.run_id,
            previous=previous,
            current=stage,
        )

    def _mark_manifest_failed(self, project_id: UUID, message: str) -> None:
        try:
            manifest = self.episode_store.load_manifest(project_id)
        except FileNotFoundError:
            return
        manifest.status = "failed"
        manifest.last_error = message
        manifest.updated_at = datetime.now(UTC)
        self.episode_store.save_manifest(manifest)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
