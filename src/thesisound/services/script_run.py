from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Literal, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from thesisound import tracing
from thesisound.domain import ProjectState
from thesisound.pipeline import WorkspaceStore, mark_failed, transition
from thesisound.services.plan_approval import (
    EpisodePlanApproval,
    EpisodePlanApprovalStore,
)
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_pipeline_service import ScriptPipelineService

ScriptBuildStatus = Literal["queued", "running", "succeeded", "failed"]
ScriptBuildStage = Literal[
    "queued",
    "building_glossary",
    "writing_segments",
    "checking_draft",
    "verifying_draft",
    "revising",
    "checking_revision",
    "verifying_revision",
    "complete",
    "failed",
]


class ScriptBuildRun(BaseModel):
    run_id: UUID = Field(default_factory=uuid4)
    previous_run_id: UUID | None = None
    project_id: UUID
    approved_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1, max_length=200)
    status: ScriptBuildStatus = "queued"
    stage: ScriptBuildStage = "queued"
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    last_error: str | None = None


class ScriptBuildRunStore:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()

    def current_path(self, project_id: UUID) -> Path:
        return self.workspace_root / str(project_id) / "script-build-run.json"

    def history_dir(self, project_id: UUID) -> Path:
        return self.workspace_root / str(project_id) / "runs" / "script"

    def attempt_path(self, project_id: UUID, run_id: UUID) -> Path:
        return self.history_dir(project_id) / f"{run_id}.json"

    def load(self, project_id: UUID) -> ScriptBuildRun:
        path = self.current_path(project_id)
        if not path.exists():
            raise FileNotFoundError(f"Script build run not found: {project_id}")
        return ScriptBuildRun.model_validate_json(path.read_text(encoding="utf-8"))

    def load_optional(self, project_id: UUID) -> ScriptBuildRun | None:
        try:
            return self.load(project_id)
        except FileNotFoundError:
            return None

    def load_history(self, project_id: UUID) -> list[ScriptBuildRun]:
        directory = self.history_dir(project_id)
        if not directory.exists():
            return []
        runs: list[ScriptBuildRun] = []
        for path in directory.glob("*.json"):
            try:
                runs.append(ScriptBuildRun.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(runs, key=lambda run: run.updated_at)

    def list_current_runs(self) -> list[ScriptBuildRun]:
        runs: list[ScriptBuildRun] = []
        for path in self.workspace_root.glob("*/script-build-run.json"):
            try:
                runs.append(ScriptBuildRun.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return runs

    def save(self, run: ScriptBuildRun) -> Path:
        run.updated_at = datetime.now(UTC)
        payload = json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        attempt = self.attempt_path(run.project_id, run.run_id)
        current = self.current_path(run.project_id)
        _atomic_write(attempt, payload)
        _atomic_write(current, payload)
        return current


class ScriptBuildRunService:
    """Require explicit plan approval and persist a resumable script run."""

    def __init__(
        self,
        *,
        workspace_store: WorkspaceStore,
        run_store: ScriptBuildRunStore,
        approval_store: EpisodePlanApprovalStore,
        script_store: ScriptArtifactStore,
        pipeline_factory: Callable[[UUID], ScriptPipelineService],
        glossary_model: str,
        writer_model: str,
        verifier_model: str,
        reviser_model: str,
    ) -> None:
        self.workspace_store = workspace_store
        self.run_store = run_store
        self.approval_store = approval_store
        self.script_store = script_store
        self.pipeline_factory = pipeline_factory
        self.glossary_model = glossary_model
        self.writer_model = writer_model
        self.verifier_model = verifier_model
        self.reviser_model = reviser_model
        self._mutation_lock = Lock()

    def approve_and_queue(
        self,
        project_id: UUID,
        *,
        approved_by: str,
    ) -> ScriptBuildRun:
        with self._mutation_lock:
            project = self.workspace_store.load_project(project_id)
            if project.state != ProjectState.EPISODE_PLANNED:
                raise ValueError("The Episode Plan can only be approved from EPISODE_PLANNED.")
            existing = self.run_store.load_optional(project_id)
            if existing is not None and existing.status in {"queued", "running"}:
                raise ValueError("A script-building run is already active.")
            previous_approval = self.approval_store.load_optional(project_id)
            self.script_store.clear_pipeline_artifacts(project_id)
            approval = self.approval_store.approve(project, approved_by=approved_by)
            run = self._new_run(project_id, approval, existing)
            try:
                self.run_store.save(run)
            except Exception:
                if previous_approval is None:
                    self.approval_store.clear(project_id)
                else:
                    self.approval_store.save(previous_approval)
                raise
            return run

    def retry(self, project_id: UUID) -> ScriptBuildRun:
        with self._mutation_lock:
            project = self.workspace_store.load_project(project_id)
            if project.state not in {
                ProjectState.EPISODE_PLANNED,
                ProjectState.FAILED_RETRYABLE,
                ProjectState.SCRIPT_READY,
            }:
                raise ValueError("This script failure is not retryable from the current state.")
            previous = self.run_store.load(project_id)
            if previous.status != "failed":
                raise ValueError("The latest script run is not failed.")
            approval = self.approval_store.require_current(project)
            run = self._new_run(project_id, approval, previous)
            self.run_store.save(run)
            return run

    def send_back(self, project_id: UUID) -> ScriptBuildRun:
        """Queue a fresh attempt after a named reviewer sends a script back."""

        with self._mutation_lock:
            project = self.workspace_store.load_project(project_id)
            if project.state != ProjectState.SCRIPT_DRAFTING:
                raise ValueError("A reviewed script must return to SCRIPT_DRAFTING first.")
            previous = self.run_store.load(project_id)
            approval = self.approval_store.require_current(project)
            run = self._new_run(project_id, approval, previous)
            self.run_store.save(run)
            return run

    def run(self, project_id: UUID) -> ScriptBuildRun:
        run = self.run_store.load(project_id)
        if run.status == "succeeded":
            return run
        if run.status != "queued":
            raise ValueError(f"Cannot start script run with status {run.status}.")

        # new_root=True: runs from a BackgroundTasks callback after the request that
        # queued it has already returned, so there is no live parent span to attach to.
        with tracing.span(
            "script.run",
            component="script",
            kind="stage",
            new_root=True,
            project_id=project_id,
            workflow_run_id=run.run_id,
        ) as root:
            try:
                project = self.workspace_store.load_project(project_id)
                approval = self.approval_store.require_current(project)
                if approval.plan_hash != run.approved_plan_hash:
                    raise ValueError("Queued script run does not match the approved Episode Plan.")
                if project.state in {
                    ProjectState.EPISODE_PLANNED,
                    ProjectState.FAILED_RETRYABLE,
                }:
                    transition(project, ProjectState.SCRIPT_DRAFTING)
                    self.workspace_store.save_project(project)
                elif project.state not in {
                    ProjectState.SCRIPT_DRAFTING,
                    ProjectState.SCRIPT_READY,
                    ProjectState.SCRIPT_VERIFYING,
                    ProjectState.SCRIPT_REVIEW_REQUIRED,
                }:
                    raise ValueError(
                        f"Cannot build script from project state {project.state.value}."
                    )

                run.status = "running"
                run.started_at = datetime.now(UTC)
                run.finished_at = None
                run.last_error = None
                self.run_store.save(run)

                pipeline = self.pipeline_factory(project_id)
                pipeline.run(
                    project_id,
                    glossary_model=self.glossary_model,
                    writer_model=self.writer_model,
                    verifier_model=self.verifier_model,
                    reviser_model=self.reviser_model,
                    on_stage=lambda value: self._set_stage(run, value),
                )
                project = self.workspace_store.load_project(project_id)
                if project.state not in {
                    ProjectState.SCRIPT_VERIFIED,
                    ProjectState.SCRIPT_REVIEW_REQUIRED,
                }:
                    raise ValueError(
                        "Script pipeline ended without a verified or review-required outcome."
                    )
                self._mark_succeeded(run)
                return run
            except Exception as exc:
                # run() always returns a ScriptBuildRun, never raises, so the span's
                # own automatic exception handling never fires here.
                root.mark("error", reason=type(exc).__name__)
                message = str(exc)[:1_000] or type(exc).__name__
                project = self.workspace_store.load_project(project_id)
                if (
                    project.state == ProjectState.SCRIPT_VERIFIED
                    and self.script_store.has_verified_artifacts(
                        project_id,
                        plan_hash=run.approved_plan_hash,
                    )
                ) or (
                    project.state == ProjectState.SCRIPT_REVIEW_REQUIRED
                    and self.script_store.has_reviewable_artifacts(
                        project_id,
                        plan_hash=run.approved_plan_hash,
                    )
                ):
                    root.mark("ok")
                    self._mark_succeeded(run)
                    return run
                if project.state in {
                    ProjectState.SCRIPT_DRAFTING,
                    ProjectState.SCRIPT_VERIFYING,
                    ProjectState.SCRIPT_REVIEW_REQUIRED,
                    ProjectState.SCRIPT_VERIFIED,
                }:
                    mark_failed(project, message)
                    self.workspace_store.save_project(project)
                elif project.state in {
                    ProjectState.FAILED_RETRYABLE,
                    ProjectState.SCRIPT_READY,
                }:
                    # SCRIPT_READY cannot transition directly to FAILED_RETRYABLE.
                    # Preserve the failure on the current state; retry() explicitly
                    # accepts SCRIPT_READY and the resumed pipeline restores drafting.
                    project.last_error = message
                    project.updated_at = datetime.now(UTC)
                    self.workspace_store.save_project(project)
                run.status = "failed"
                run.stage = "failed"
                run.last_error = message
                run.finished_at = datetime.now(UTC)
                self.run_store.save(run)
                return run

    def recover_interrupted_runs(self) -> list[UUID]:
        recovered: list[UUID] = []
        interrupted = "Script generation was interrupted by a service restart. Retry to continue."
        invalid_verified = (
            "The project was marked SCRIPT_VERIFIED, but its verified script artifacts "
            "are missing, incomplete, or bound to another Episode Plan. Retry to rebuild."
        )
        for run in self.run_store.list_current_runs():
            if run.status == "succeeded":
                continue
            try:
                project = self.workspace_store.load_project(run.project_id)
            except FileNotFoundError:
                project = None
            if project is not None and project.state in {
                ProjectState.SCRIPT_VERIFIED,
                ProjectState.SCRIPT_REVIEW_REQUIRED,
            }:
                artifacts_valid = (
                    project.state == ProjectState.SCRIPT_VERIFIED
                    and self.script_store.has_verified_artifacts(
                        run.project_id,
                        plan_hash=run.approved_plan_hash,
                    )
                ) or (
                    project.state == ProjectState.SCRIPT_REVIEW_REQUIRED
                    and self.script_store.has_reviewable_artifacts(
                        run.project_id,
                        plan_hash=run.approved_plan_hash,
                    )
                )
                if artifacts_valid:
                    self._mark_succeeded(run)
                    recovered.append(run.project_id)
                    continue
                run.status = "failed"
                run.stage = "failed"
                run.finished_at = datetime.now(UTC)
                run.last_error = invalid_verified
                self.run_store.save(run)
                mark_failed(project, invalid_verified)
                self.workspace_store.save_project(project)
                recovered.append(run.project_id)
                continue
            if run.status not in {"queued", "running"}:
                continue

            run.status = "failed"
            run.stage = "failed"
            run.finished_at = datetime.now(UTC)
            run.last_error = interrupted
            self.run_store.save(run)
            if project is not None and project.state in {
                ProjectState.SCRIPT_DRAFTING,
                ProjectState.SCRIPT_VERIFYING,
            }:
                mark_failed(project, interrupted)
                self.workspace_store.save_project(project)
            elif project is not None and project.state == ProjectState.SCRIPT_READY:
                project.last_error = interrupted
                project.updated_at = datetime.now(UTC)
                self.workspace_store.save_project(project)
            recovered.append(run.project_id)
        return recovered

    def _new_run(
        self,
        project_id: UUID,
        approval: EpisodePlanApproval,
        previous: ScriptBuildRun | None,
    ) -> ScriptBuildRun:
        return ScriptBuildRun(
            project_id=project_id,
            previous_run_id=previous.run_id if previous else None,
            approved_plan_hash=approval.plan_hash,
            approved_by=approval.approved_by,
        )

    def _mark_succeeded(self, run: ScriptBuildRun) -> None:
        run.status = "succeeded"
        run.stage = "complete"
        run.finished_at = datetime.now(UTC)
        run.last_error = None
        self.run_store.save(run)

    def _set_stage(self, run: ScriptBuildRun, value: str) -> None:
        allowed = {
            "building_glossary",
            "writing_segments",
            "checking_draft",
            "verifying_draft",
            "revising",
            "checking_revision",
            "verifying_revision",
        }
        if value not in allowed:
            raise ValueError(f"Unknown script stage: {value}")
        previous = run.stage
        run.stage = cast(ScriptBuildStage, value)
        self.run_store.save(run)
        tracing.event(
            "run.stage_changed",
            component="script",
            project_id=run.project_id,
            workflow_run_id=run.run_id,
            previous=previous,
            current=value,
        )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
