from pathlib import Path

from thesisound.audio import AudioPipelineManifest
from thesisound.domain import Project, ProjectState, Script, ScriptTurn
from thesisound.pipeline import WorkspaceStore, mark_failed, transition
from thesisound.services.audio_direction import AudioDirectionSettings
from thesisound.services.audio_run import AudioBuildRunService, AudioBuildRunStore


class FakeScriptStore:
    def __init__(self, script: Script) -> None:
        self.script = script
        self.valid = True

    def has_verified_artifacts(self, project_id) -> bool:
        del project_id
        return self.valid

    def load_latest_script(self, project_id) -> Script:
        del project_id
        return self.script


class FakeAudioStore:
    def __init__(self) -> None:
        self.valid = False

    def has_verified_artifacts(
        self,
        project_id,
        *,
        script_hash: str,
        accept_manual_review: bool = False,
        **_kwargs,
    ) -> bool:
        del project_id, script_hash, accept_manual_review
        return self.valid


class FakePipeline:
    def __init__(self, workspace: WorkspaceStore, audio_store: FakeAudioStore) -> None:
        self.workspace = workspace
        self.audio_store = audio_store

    def run(self, project_id, *, on_stage=None):
        if on_stage:
            on_stage("synthesizing")
        project = self.workspace.load_project(project_id)
        transition(project, ProjectState.AUDIO_GENERATING)
        transition(project, ProjectState.AUDIO_READY)
        transition(project, ProjectState.AUDIO_VERIFYING)
        transition(project, ProjectState.COMPLETE)
        self.workspace.save_project(project)
        self.audio_store.valid = True
        return AudioPipelineManifest(
            project_id=project_id,
            script_hash="a" * 64,
            status="verified",
            chunk_count=1,
            passed_chunk_count=1,
        )


def _script() -> Script:
    return Script(
        title="script",
        turns=[
            ScriptTurn(
                turn_id="turn-1",
                segment_id="seg-1",
                speaker="A",
                spoken_text_fa="متن آزمون",
                claim_ids=["claim-1"],
                evidence_ids=["evidence-1"],
            )
        ],
    )


def _service(tmp_path: Path):
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(raw_input="topic", state=ProjectState.SCRIPT_VERIFIED, script=_script())
    workspace.save_project(project)
    scripts = FakeScriptStore(_script())
    audio = FakeAudioStore()
    service = AudioBuildRunService(
        workspace_store=workspace,
        run_store=AudioBuildRunStore(workspace.root),
        script_store=scripts,  # type: ignore[arg-type]
        audio_store=audio,  # type: ignore[arg-type]
        pipeline_factory=lambda _project_id, _direction, _workflow_run_id: FakePipeline(  # type: ignore[return-value]
            workspace,
            audio,
        ),
        default_direction=AudioDirectionSettings(voice_a="Kore", voice_b="Puck"),
    )
    return workspace, project, service, scripts, audio


def test_audio_run_succeeds_and_preserves_attempt_history(tmp_path: Path) -> None:
    workspace, project, service, _, _ = _service(tmp_path)

    queued = service.queue(project.project_id)
    completed = service.run(project.project_id)

    assert completed.run_id == queued.run_id
    assert completed.status == "succeeded"
    assert workspace.load_project(project.project_id).state == ProjectState.COMPLETE
    assert [item.run_id for item in service.run_store.load_history(project.project_id)] == [
        queued.run_id
    ]


def test_queued_run_interrupted_before_audio_transition_becomes_retryable(
    tmp_path: Path,
) -> None:
    workspace, project, service, _, _ = _service(tmp_path)
    queued = service.queue(project.project_id)

    recovered = service.recover_interrupted_runs()

    assert recovered == [project.project_id]
    failed = service.run_store.load(project.project_id)
    assert failed.run_id == queued.run_id
    assert failed.status == "failed"
    assert workspace.load_project(project.project_id).state == ProjectState.FAILED_RETRYABLE
    retried = service.retry(project.project_id)
    assert retried.run_id != queued.run_id
    assert retried.previous_run_id == queued.run_id


def test_complete_project_with_missing_audio_is_reopened_for_recovery(
    tmp_path: Path,
) -> None:
    workspace, project, service, _, audio = _service(tmp_path)
    run = service.queue(project.project_id)
    run.status = "failed"
    run.stage = "failed"
    service.run_store.save(run)
    completed = workspace.load_project(project.project_id)
    transition(completed, ProjectState.AUDIO_GENERATING)
    transition(completed, ProjectState.AUDIO_READY)
    transition(completed, ProjectState.AUDIO_VERIFYING)
    transition(completed, ProjectState.COMPLETE)
    workspace.save_project(completed)
    audio.valid = False

    service.recover_interrupted_runs()

    assert workspace.load_project(project.project_id).state == ProjectState.FAILED_RETRYABLE
    assert service.run_store.load(project.project_id).status == "failed"


def test_succeeded_pointer_does_not_hide_deleted_or_corrupt_final_audio(
    tmp_path: Path,
) -> None:
    workspace, project, service, _, audio = _service(tmp_path)
    run = service.queue(project.project_id)
    run.status = "succeeded"
    run.stage = "complete"
    service.run_store.save(run)
    completed = workspace.load_project(project.project_id)
    transition(completed, ProjectState.AUDIO_GENERATING)
    transition(completed, ProjectState.AUDIO_READY)
    transition(completed, ProjectState.AUDIO_VERIFYING)
    transition(completed, ProjectState.COMPLETE)
    workspace.save_project(completed)
    audio.valid = False

    recovered = service.recover_interrupted_runs()

    assert recovered == [project.project_id]
    assert workspace.load_project(project.project_id).state == ProjectState.FAILED_RETRYABLE
    repaired = service.run_store.load(project.project_id)
    assert repaired.status == "failed"
    assert "missing or stale" in repaired.last_error


def test_retry_preserves_direction_from_previous_run(tmp_path: Path) -> None:
    workspace, project, service, _, _ = _service(tmp_path)
    direction = AudioDirectionSettings(voice_a="Puck", voice_b="Kore", tone="شوخ‌طبع")
    queued = service.queue(project.project_id, direction=direction)
    assert queued.direction == direction

    run = service.run_store.load(project.project_id)
    run.status = "failed"
    service.run_store.save(run)
    completed = workspace.load_project(project.project_id)
    mark_failed(completed, "forced failure for retry direction test")
    workspace.save_project(completed)

    retried = service.retry(project.project_id)
    assert retried.direction == direction
