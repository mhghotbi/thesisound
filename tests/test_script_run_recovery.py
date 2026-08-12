from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from thesisound.domain import (
    EpisodePlan,
    EpisodeSegment,
    Project,
    ProjectState,
    ResearchBrief,
    TopicType,
)
from thesisound.modeling import (
    DeterministicValidationError,
    ModelProviderError,
    ModelTimeoutError,
    SchemaValidationError,
)
from thesisound.pipeline import WorkspaceStore, transition
from thesisound.script import (
    Glossary,
    RevisionDecision,
    ScriptPipelineManifest,
    SegmentScriptDraft,
    ScriptTurnDraft,
)
from thesisound.services.plan_approval import EpisodePlanApprovalStore
from thesisound.services.run_recovery import (
    classify_run_failure,
    recovery_backoff_seconds,
    should_auto_retry,
)
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_run import ScriptBuildRunService, ScriptBuildRunStore


class CountingPipeline:
    def __init__(
        self,
        workspace: WorkspaceStore,
        *,
        errors: list[BaseException] | None = None,
    ) -> None:
        self.workspace = workspace
        self.errors = list(errors or [])
        self.calls = 0

    def run(self, project_id: UUID, *, on_stage, **_):
        self.calls += 1
        on_stage("building_glossary")
        on_stage("writing_segments")
        if self.errors:
            raise self.errors.pop(0)
        project = self.workspace.load_project(project_id)
        transition(project, ProjectState.SCRIPT_READY)
        transition(project, ProjectState.SCRIPT_VERIFYING)
        transition(project, ProjectState.SCRIPT_VERIFIED)
        self.workspace.save_project(project)
        return object()


class FailThenSucceedPipeline:
    """Fail with a transport error for ``fail_times`` calls, then succeed."""

    def __init__(
        self,
        workspace: WorkspaceStore,
        *,
        fail_times: int = 1,
        error: BaseException | None = None,
        fail_stage: str = "writing_segments",
    ) -> None:
        self.workspace = workspace
        self.fail_times = fail_times
        self.error = error or ModelTimeoutError("Okian request timed out.")
        self.fail_stage = fail_stage
        self.calls = 0

    def run(self, project_id: UUID, *, on_stage, **_):
        self.calls += 1
        on_stage("building_glossary")
        on_stage(self.fail_stage)
        if self.calls <= self.fail_times:
            raise self.error
        project = self.workspace.load_project(project_id)
        if project.state == ProjectState.SCRIPT_DRAFTING:
            transition(project, ProjectState.SCRIPT_READY)
            transition(project, ProjectState.SCRIPT_VERIFYING)
            transition(project, ProjectState.SCRIPT_VERIFIED)
            self.workspace.save_project(project)
        return object()


def _project() -> Project:
    return Project(
        raw_input="موضوع",
        state=ProjectState.EPISODE_PLANNED,
        brief=ResearchBrief(
            normalized_topic="موضوع",
            topic_type=TopicType.CONCEPT,
            central_question="سؤال؟",
            target_duration_minutes=5,
        ),
        episode_plan=EpisodePlan(
            title="طرح",
            listener_outcome="فهم موضوع",
            estimated_duration_minutes=5,
            segments=[
                EpisodeSegment(
                    segment_id="seg-1",
                    title="بخش",
                    purpose="توضیح",
                    estimated_minutes=5,
                    claim_ids=["claim-1"],
                    key_question="سؤال؟",
                    speaker_dynamic="explanation",
                )
            ],
        ),
    )


def _service(
    tmp_path: Path,
    project: Project,
    pipeline,
    *,
    max_automatic_retries: int = 2,
    recovery_wall_clock_seconds: float = 900,
    provider_retry_base_seconds: float = 0,
) -> ScriptBuildRunService:
    workspace = pipeline.workspace
    workspace.save_project(project)
    return ScriptBuildRunService(
        workspace_store=workspace,
        run_store=ScriptBuildRunStore(workspace.root),
        approval_store=EpisodePlanApprovalStore(workspace.root),
        script_store=ScriptArtifactStore(workspace.root),
        pipeline_factory=lambda _: pipeline,  # type: ignore[return-value]
        glossary_model="fake",
        writer_model="fake",
        verifier_model="fake",
        reviser_model="fake",
        max_automatic_retries=max_automatic_retries,
        recovery_wall_clock_seconds=recovery_wall_clock_seconds,
        provider_retry_base_seconds=provider_retry_base_seconds,
    )


def test_classify_run_failure_categories() -> None:
    assert classify_run_failure(ModelTimeoutError("timed out")) == "transport"
    assert classify_run_failure(ModelProviderError("Not Acceptable", retryable=True)) == "transport"
    assert classify_run_failure(SchemaValidationError("bad json")) == "model_contract"
    assert (
        classify_run_failure(DeterministicValidationError("check tripped")) == "model_quality"
    )
    assert classify_run_failure(ValueError("Cannot build script from project state x.")) == (
        "structural"
    )
    assert classify_run_failure(RuntimeError("unexpected")) == "structural"


def test_should_auto_retry_budget_for_quality() -> None:
    assert should_auto_retry("transport", quality_retries_used=0)
    assert should_auto_retry("model_contract", quality_retries_used=0)
    assert should_auto_retry("model_quality", quality_retries_used=0)
    assert not should_auto_retry("model_quality", quality_retries_used=1)
    assert not should_auto_retry("structural", quality_retries_used=0)
    assert recovery_backoff_seconds(1, 1.0) == 1.0
    assert recovery_backoff_seconds(2, 1.0) == 2.0
    assert recovery_backoff_seconds(1, 0.0) == 0.0


def test_transient_transport_failure_recovers_without_user_action(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = FailThenSucceedPipeline(workspace, fail_times=1)
    service = _service(tmp_path, project, pipeline)
    service.approve_and_queue(project.project_id, approved_by="operator")

    run = service.run(project.project_id)

    assert run.status == "succeeded"
    assert pipeline.calls == 2
    assert workspace.load_project(project.project_id).state == ProjectState.SCRIPT_VERIFIED
    assert workspace.load_project(project.project_id).state != ProjectState.FAILED_RETRYABLE
    assert len(run.attempts) == 1
    assert run.attempts[0].classification == "transport"


def test_structural_failure_is_not_retried(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = CountingPipeline(
        workspace,
        errors=[ValueError("Cannot build script from project state complete.")],
    )
    service = _service(tmp_path, project, pipeline)
    service.approve_and_queue(project.project_id, approved_by="operator")

    run = service.run(project.project_id)

    assert run.status == "failed"
    assert pipeline.calls == 1
    assert run.attempts[0].classification == "structural"
    assert workspace.load_project(project.project_id).state == ProjectState.FAILED_RETRYABLE


def test_invalidation_is_scoped_to_the_failed_stage(tmp_path: Path) -> None:
    store = ScriptArtifactStore(tmp_path / "ws")
    project_id = uuid4()
    script_dir = store.script_dir(project_id)
    store.prepare_for_plan(project_id, "a" * 64)
    store.save_glossary(Glossary(project_id=project_id, model_run_id=uuid4()))
    store.save_manifest(ScriptPipelineManifest(project_id=project_id, status="draft_ready"))
    store.save_segment_draft(
        project_id,
        "seg-1",
        SegmentScriptDraft(
            turns=[
                ScriptTurnDraft(
                    speaker="A",
                    spoken_text_fa="متن",
                    claim_ids=["c1"],
                    evidence_ids=["e1"],
                )
            ]
        ),
    )
    (script_dir / "script-draft.json").write_text("{}", encoding="utf-8")
    (script_dir / "checks.json").write_text("{}", encoding="utf-8")
    (script_dir / "verification.json").write_text("{}", encoding="utf-8")
    (script_dir / "script-revised.json").write_text("{}", encoding="utf-8")
    (script_dir / "checks-revised.json").write_text('{"severity":"high"}', encoding="utf-8")
    (script_dir / "verification-revised.json").write_text("{}", encoding="utf-8")
    store.save_revision_decision(
        RevisionDecision(
            project_id=project_id,
            accepted=True,
            reason="ok",
            original_verdict="revise",
            revised_verdict="pass",
            original_overall=None,
            revised_overall=None,
            delta=None,
            original_issue_count=1,
            revised_issue_count=0,
            changed_turn_count=1,
        )
    )

    removed = store.invalidate_from_stage(project_id, "checking_revision")

    assert "checks-revised.json" in removed
    assert "verification-revised.json" in removed
    assert "revision-decision.json" in removed
    assert (script_dir / "glossary.json").exists()
    assert (script_dir / "segments" / "seg-1.json").exists()
    assert (script_dir / "script-draft.json").exists()
    assert (script_dir / "checks.json").exists()
    assert (script_dir / "script-revised.json").exists()
    assert not (script_dir / "checks-revised.json").exists()
    assert (script_dir / "approved-plan-hash.txt").exists()


def test_stale_revision_checks_are_recomputed_on_retry(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = FailThenSucceedPipeline(
        workspace,
        fail_times=99,
        error=SchemaValidationError("invalid JSON"),
        fail_stage="checking_revision",
    )
    service = _service(tmp_path, project, pipeline, max_automatic_retries=0)
    queued = service.approve_and_queue(project.project_id, approved_by="operator")
    store = ScriptArtifactStore(workspace.root)
    store.prepare_for_plan(project.project_id, queued.approved_plan_hash)
    store.save_glossary(Glossary(project_id=project.project_id, model_run_id=uuid4()))
    store.save_manifest(
        ScriptPipelineManifest(project_id=project.project_id, status="draft_ready")
    )
    script_dir = store.script_dir(project.project_id)
    (script_dir / "segments").mkdir(exist_ok=True)
    (script_dir / "segments" / "seg-1.json").write_text("{}", encoding="utf-8")
    (script_dir / "checks-revised.json").write_text(
        '{"severity":"high"}',
        encoding="utf-8",
    )

    failed = service.run(project.project_id)
    assert failed.status == "failed"
    assert failed.failed_stage == "checking_revision"
    assert (script_dir / "checks-revised.json").exists()

    retry = service.retry(project.project_id)

    assert retry.status == "queued"
    assert (script_dir / "glossary.json").exists()
    assert (script_dir / "segments" / "seg-1.json").exists()
    assert not (script_dir / "checks-revised.json").exists()


def test_exhausted_budget_surfaces_the_last_real_error(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = CountingPipeline(
        workspace,
        errors=[
            ModelTimeoutError("timeout attempt 1"),
            ModelTimeoutError("timeout attempt 2"),
            ModelTimeoutError("timeout attempt 3 final"),
        ],
    )
    service = _service(tmp_path, project, pipeline, max_automatic_retries=2)
    service.approve_and_queue(project.project_id, approved_by="operator")

    run = service.run(project.project_id)

    assert run.status == "failed"
    assert pipeline.calls == 3
    assert run.last_error == "timeout attempt 3 final"
    assert "retries exhausted" not in (run.last_error or "").lower()
    assert workspace.load_project(project.project_id).state == ProjectState.FAILED_RETRYABLE


def test_successful_first_attempt_makes_no_extra_calls(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = FailThenSucceedPipeline(workspace, fail_times=0)
    service = _service(tmp_path, project, pipeline)
    service.approve_and_queue(project.project_id, approved_by="operator")

    run = service.run(project.project_id)

    assert run.status == "succeeded"
    assert pipeline.calls == 1
    assert run.attempts == []


def test_wall_clock_ceiling_stops_recovery(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = FailThenSucceedPipeline(workspace, fail_times=5)
    service = _service(
        tmp_path,
        project,
        pipeline,
        max_automatic_retries=2,
        recovery_wall_clock_seconds=0,
    )
    service.approve_and_queue(project.project_id, approved_by="operator")

    run = service.run(project.project_id)

    assert run.status == "failed"
    assert pipeline.calls == 1
    assert run.attempts[0].classification == "transport"


def test_attempt_history_records_classification(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = CountingPipeline(
        workspace,
        errors=[
            ModelTimeoutError("transport"),
            SchemaValidationError("contract"),
            DeterministicValidationError("quality"),
        ],
    )
    service = _service(tmp_path, project, pipeline, max_automatic_retries=2)
    service.approve_and_queue(project.project_id, approved_by="operator")
    script_dir = ScriptArtifactStore(workspace.root).script_dir(project.project_id)
    (script_dir / "script-draft.json").write_text("{}", encoding="utf-8")

    run = service.run(project.project_id)

    assert run.status == "failed"
    assert [item.classification for item in run.attempts] == [
        "transport",
        "model_contract",
        "model_quality",
    ]
    assert all(item.stage == "writing_segments" for item in run.attempts)
    assert "script-draft.json" in run.attempts[0].invalidated
    assert run.attempts[-1].invalidated == []  # terminal attempt does not clear
