from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Literal, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from thesisound.audio import script_hash
from thesisound.domain import ProjectState
from thesisound.pipeline import WorkspaceStore, mark_failed
from thesisound.services.audio_artifact_store import AudioArtifactStore
from thesisound.services.audio_pipeline_service import AudioPipelineService
from thesisound.services.script_artifact_store import ScriptArtifactStore

AudioBuildStatus = Literal["queued", "running", "succeeded", "failed"]
AudioBuildStage = Literal[
    "queued",
    "segmenting",
    "synthesizing",
    "transcribing",
    "regenerating",
    "assembling",
    "complete",
    "failed",
]


class AudioBuildRun(BaseModel):
    run_id: UUID = Field(default_factory=uuid4)
    previous_run_id: UUID | None = None
    project_id: UUID
    verified_script_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: AudioBuildStatus = "queued"
    stage: AudioBuildStage = "queued"
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    last_error: str | None = None


class AudioBuildRunStore:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()

    def current_path(self, project_id: UUID) -> Path:
        return self.workspace_root / str(project_id) / "audio-build-run.json"

    def history_dir(self, project_id: UUID) -> Path:
        return self.workspace_root / str(project_id) / "runs" / "audio"

    def attempt_path(self, project_id: UUID, run_id: UUID) -> Path:
        return self.history_dir(project_id) / f"{run_id}.json"

    def load(self, project_id: UUID) -> AudioBuildRun:
        path = self.current_path(project_id)
        if not path.exists():
            raise FileNotFoundError(f"Audio build run not found: {project_id}")
        return AudioBuildRun.model_validate_json(path.read_text(encoding="utf-8"))

    def load_optional(self, project_id: UUID) -> AudioBuildRun | None:
        try:
            return self.load(project_id)
        except FileNotFoundError:
            return None

    def load_history(self, project_id: UUID) -> list[AudioBuildRun]:
        directory = self.history_dir(project_id)
        if not directory.exists():
            return []
        runs: list[AudioBuildRun] = []
        for path in directory.glob("*.json"):
            try:
                runs.append(AudioBuildRun.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(runs, key=lambda run: run.updated_at)

    def list_current_runs(self) -> list[AudioBuildRun]:
        runs: list[AudioBuildRun] = []
        for path in self.workspace_root.glob("*/audio-build-run.json"):
            try:
                runs.append(AudioBuildRun.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return runs

    def save(self, run: AudioBuildRun) -> Path:
        run.updated_at = datetime.now(UTC)
        payload = json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        _atomic_write(self.attempt_path(run.project_id, run.run_id), payload)
        _atomic_write(self.current_path(run.project_id), payload)
        return self.current_path(run.project_id)


class AudioBuildRunService:
    def __init__(
        self,
        *,
        workspace_store: WorkspaceStore,
        run_store: AudioBuildRunStore,
        script_store: ScriptArtifactStore,
        audio_store: AudioArtifactStore,
        pipeline_factory: Callable[[UUID], AudioPipelineService],
    ) -> None:
        self.workspace_store = workspace_store
        self.run_store = run_store
        self.script_store = script_store
        self.audio_store = audio_store
        self.pipeline_factory = pipeline_factory
        self._mutation_lock = Lock()

    def queue(self, project_id: UUID) -> AudioBuildRun:
        with self._mutation_lock:
            project = self.workspace_store.load_project(project_id)
            if project.state != ProjectState.SCRIPT_VERIFIED:
                raise ValueError("Audio generation can only start from SCRIPT_VERIFIED.")
            if not self.script_store.has_verified_artifacts(project_id):
                raise ValueError("Verified script artifacts are missing or stale.")
            script = self.script_store.load_latest_script(project_id)
            digest = script_hash(script)
            existing = self.run_store.load_optional(project_id)
            if existing is not None and existing.status in {"queued", "running"}:
                raise ValueError("An audio-building run is already active.")
            run = AudioBuildRun(
                project_id=project_id,
                previous_run_id=existing.run_id if existing else None,
                verified_script_hash=digest,
            )
            self.run_store.save(run)
            return run

    def retry(self, project_id: UUID) -> AudioBuildRun:
        with self._mutation_lock:
            project = self.workspace_store.load_project(project_id)
            if project.state != ProjectState.FAILED_RETRYABLE:
                raise ValueError("Only a retryable audio failure can be retried.")
            previous = self.run_store.load(project_id)
            if previous.status != "failed":
                raise ValueError("The latest audio run is not failed.")
            if not self.script_store.has_verified_artifacts(project_id):
                raise ValueError("Verified script artifacts are missing or stale.")
            script = self.script_store.load_latest_script(project_id)
            digest = script_hash(script)
            if digest != previous.verified_script_hash:
                raise ValueError("Verified script changed; return to SCRIPT_VERIFIED first.")
            run = AudioBuildRun(
                project_id=project_id,
                previous_run_id=previous.run_id,
                verified_script_hash=digest,
            )
            self.run_store.save(run)
            return run

    def run(self, project_id: UUID) -> AudioBuildRun:
        run = self.run_store.load(project_id)
        if run.status == "succeeded":
            return run
        if run.status != "queued":
            raise ValueError(f"Cannot start audio run with status {run.status}.")
        try:
            script = self.script_store.load_latest_script(project_id)
            if not self.script_store.has_verified_artifacts(project_id):
                raise ValueError("Verified script artifacts are missing or stale.")
            if script_hash(script) != run.verified_script_hash:
                raise ValueError("Queued audio run is bound to another script version.")
            run.status = "running"
            run.started_at = datetime.now(UTC)
            run.finished_at = None
            run.last_error = None
            self.run_store.save(run)
            pipeline = self.pipeline_factory(project_id)
            pipeline.run(project_id, on_stage=lambda value: self._set_stage(run, value))
            project = self.workspace_store.load_project(project_id)
            if project.state != ProjectState.COMPLETE:
                raise ValueError("Audio pipeline ended without reaching COMPLETE.")
            if not self.audio_store.has_verified_artifacts(
                project_id,
                script_hash=run.verified_script_hash,
            ):
                raise ValueError("Audio pipeline ended without verified artifacts.")
            self._mark_succeeded(run)
            return run
        except Exception as exc:
            message = str(exc)[:1_000] or type(exc).__name__
            project = self.workspace_store.load_project(project_id)
            if project.state == ProjectState.COMPLETE and self.audio_store.has_verified_artifacts(
                project_id,
                script_hash=run.verified_script_hash,
            ):
                self._mark_succeeded(run)
                return run
            if project.state in {
                ProjectState.SCRIPT_VERIFIED,
                ProjectState.AUDIO_GENERATING,
                ProjectState.AUDIO_READY,
                ProjectState.AUDIO_VERIFYING,
                ProjectState.COMPLETE,
            }:
                mark_failed(project, message)
                self.workspace_store.save_project(project)
            elif project.state == ProjectState.FAILED_RETRYABLE:
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
        interrupted = "Audio generation was interrupted by a service restart. Retry to continue."
        invalid_complete = (
            "The project is COMPLETE, but verified audio artifacts are missing or stale. "
            "Retry to rebuild audio."
        )
        for run in self.run_store.list_current_runs():
            try:
                project = self.workspace_store.load_project(run.project_id)
            except FileNotFoundError:
                project = None
            if project is not None and project.state == ProjectState.COMPLETE:
                if self.audio_store.has_verified_artifacts(
                    run.project_id,
                    script_hash=run.verified_script_hash,
                ):
                    self._mark_succeeded(run)
                else:
                    run.status = "failed"
                    run.stage = "failed"
                    run.last_error = invalid_complete
                    run.finished_at = datetime.now(UTC)
                    self.run_store.save(run)
                    mark_failed(project, invalid_complete)
                    self.workspace_store.save_project(project)
                recovered.append(run.project_id)
                continue
            if run.status == "succeeded":
                continue
            if run.status not in {"queued", "running"}:
                continue
            run.status = "failed"
            run.stage = "failed"
            run.last_error = interrupted
            run.finished_at = datetime.now(UTC)
            self.run_store.save(run)
            if project is not None and project.state in {
                ProjectState.SCRIPT_VERIFIED,
                ProjectState.AUDIO_GENERATING,
                ProjectState.AUDIO_READY,
                ProjectState.AUDIO_VERIFYING,
            }:
                mark_failed(project, interrupted)
                self.workspace_store.save_project(project)
            recovered.append(run.project_id)
        return recovered

    def _mark_succeeded(self, run: AudioBuildRun) -> None:
        run.status = "succeeded"
        run.stage = "complete"
        run.last_error = None
        run.finished_at = datetime.now(UTC)
        self.run_store.save(run)

    def _set_stage(self, run: AudioBuildRun, value: str) -> None:
        allowed = {
            "segmenting",
            "synthesizing",
            "transcribing",
            "regenerating",
            "assembling",
        }
        if value not in allowed:
            raise ValueError(f"Unknown audio stage: {value}")
        run.stage = cast(AudioBuildStage, value)
        self.run_store.save(run)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
