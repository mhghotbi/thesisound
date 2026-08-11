from __future__ import annotations

from pathlib import Path
from uuid import UUID

from thesisound import tracing
from thesisound.domain import (
    EpisodePlan,
    EpisodeSegment,
    Project,
    ProjectState,
    ResearchBrief,
    Script,
    ScriptTurn,
    TopicType,
)
from thesisound.pipeline import WorkspaceStore, transition
from thesisound.script import ScriptCheckReport, ScriptPipelineManifest, VerificationDraft
from thesisound.services.plan_approval import EpisodePlanApprovalStore
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_run import ScriptBuildRunService, ScriptBuildRunStore


class FakePipeline:
    def __init__(self, workspace: WorkspaceStore, *, fail: bool = False) -> None:
        self.workspace = workspace
        self.fail = fail
        self.calls = 0

    def run(self, project_id: UUID, *, on_stage, **_):
        self.calls += 1
        on_stage("building_glossary")
        on_stage("writing_segments")
        if self.fail:
            raise ValueError("writer failed")
        project = self.workspace.load_project(project_id)
        assert project.state == ProjectState.SCRIPT_DRAFTING
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
    pipeline: FakePipeline,
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
    )


def test_approval_queues_exact_plan_and_successful_run(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = FakePipeline(workspace)
    service = _service(tmp_path, project, pipeline)

    queued = service.approve_and_queue(project.project_id, approved_by="09120000000")

    assert workspace.load_project(project.project_id).state == ProjectState.EPISODE_PLANNED
    assert queued.status == "queued"
    assert queued.approved_by == "09120000000"
    approval = service.approval_store.load(project.project_id)
    assert queued.approved_plan_hash == approval.plan_hash

    completed = service.run(project.project_id)

    assert completed.status == "succeeded"
    assert completed.stage == "complete"
    assert workspace.load_project(project.project_id).state == ProjectState.SCRIPT_VERIFIED
    assert pipeline.calls == 1


def test_successful_run_emits_a_root_span_and_stage_changed_events(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = FakePipeline(workspace)
    service = _service(tmp_path, project, pipeline)
    service.approve_and_queue(project.project_id, approved_by="09120000000")

    run = service.run(project.project_id)

    assert run.status == "succeeded"
    root = recording_tracer.sink.one("script.run")
    assert root.status == "ok"
    assert root.parent_span_id is None  # new_root: no ambient HTTP span was open

    # FakePipeline.run() calls on_stage("building_glossary") then
    # on_stage("writing_segments") directly -- this is the on_stage callback
    # wiring itself under test, not ScriptPipelineService's own instrumentation.
    stage_events = [
        event.attributes["current"]
        for event in recording_tracer.sink.events
        if event.name == "run.stage_changed"
    ]
    assert stage_events == ["building_glossary", "writing_segments"]


def test_failed_run_marks_its_span_as_error(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    failing = FakePipeline(workspace, fail=True)
    service = _service(tmp_path, project, failing)
    service.approve_and_queue(project.project_id, approved_by="operator")

    run = service.run(project.project_id)

    assert run.status == "failed"
    root = recording_tracer.sink.one("script.run")
    assert root.status == "error"
    assert root.attributes["status_reason"] == "ValueError"


def test_changed_plan_invalidates_queued_approval(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = FakePipeline(workspace)
    service = _service(tmp_path, project, pipeline)
    service.approve_and_queue(project.project_id, approved_by="operator")
    changed = workspace.load_project(project.project_id)
    assert changed.episode_plan is not None
    changed.episode_plan.title = "طرح تغییرکرده"
    workspace.save_project(changed)

    failed = service.run(project.project_id)

    assert failed.status == "failed"
    assert "changed after approval" in failed.last_error
    assert workspace.load_project(project.project_id).state == ProjectState.EPISODE_PLANNED
    assert pipeline.calls == 0


def test_failed_run_retries_with_new_attempt_and_keeps_history(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    failing = FakePipeline(workspace, fail=True)
    service = _service(tmp_path, project, failing)
    queued = service.approve_and_queue(project.project_id, approved_by="operator")
    failed = service.run(project.project_id)

    assert failed.run_id == queued.run_id
    assert failed.status == "failed"
    assert workspace.load_project(project.project_id).state == ProjectState.FAILED_RETRYABLE

    retry = service.retry(project.project_id)

    assert retry.run_id != failed.run_id
    assert retry.previous_run_id == failed.run_id
    assert [run.run_id for run in service.run_store.load_history(project.project_id)] == [
        failed.run_id,
        retry.run_id,
    ]


def test_restart_reconciles_verified_project_with_stale_running_pointer(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = FakePipeline(workspace)
    service = _service(tmp_path, project, pipeline)
    run = service.approve_and_queue(project.project_id, approved_by="operator")
    run.status = "running"
    run.stage = "verifying_revision"
    service.run_store.save(run)

    verified = workspace.load_project(project.project_id)
    transition(verified, ProjectState.SCRIPT_DRAFTING)
    transition(verified, ProjectState.SCRIPT_READY)
    transition(verified, ProjectState.SCRIPT_VERIFYING)
    transition(verified, ProjectState.SCRIPT_VERIFIED)
    workspace.save_project(verified)
    store = ScriptArtifactStore(workspace.root)
    store.save_script(
        project.project_id,
        Script(
            title="سناریو",
            turns=[
                ScriptTurn(
                    turn_id="seg-1-turn-001",
                    segment_id="seg-1",
                    speaker="A",
                    spoken_text_fa="متن",
                    claim_ids=["claim-1"],
                    evidence_ids=["evidence-1"],
                )
            ],
        ),
    )
    store.save_checks(
        ScriptCheckReport(
            project_id=project.project_id,
            verdict="pass",
            word_count=1,
            estimated_minutes=0.01,
            substantive_turn_count=1,
        )
    )
    store.save_verification(
        project.project_id,
        VerificationDraft(verdict="pass", unsupported_claim_ratio=0),
    )
    store.save_manifest(ScriptPipelineManifest(project_id=project.project_id, status="verified"))

    recovered = service.recover_interrupted_runs()

    assert recovered == [project.project_id]
    current = service.run_store.load(project.project_id)
    assert current.status == "succeeded"
    assert current.stage == "complete"


def test_restart_marks_active_script_state_retryable(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = FakePipeline(workspace)
    service = _service(tmp_path, project, pipeline)
    run = service.approve_and_queue(project.project_id, approved_by="operator")
    run.status = "running"
    run.stage = "writing_segments"
    service.run_store.save(run)
    active = workspace.load_project(project.project_id)
    transition(active, ProjectState.SCRIPT_DRAFTING)
    workspace.save_project(active)

    service.recover_interrupted_runs()

    assert service.run_store.load(project.project_id).status == "failed"
    assert workspace.load_project(project.project_id).state == ProjectState.FAILED_RETRYABLE


def test_review_required_artifacts_survive_interrupted_run_recovery(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = FakePipeline(workspace)
    service = _service(tmp_path, project, pipeline)
    run = service.approve_and_queue(project.project_id, approved_by="operator")
    run.status = "running"
    run.stage = "verifying_revision"
    service.run_store.save(run)

    review = workspace.load_project(project.project_id)
    transition(review, ProjectState.SCRIPT_DRAFTING)
    transition(review, ProjectState.SCRIPT_READY)
    transition(review, ProjectState.SCRIPT_VERIFYING)
    transition(review, ProjectState.SCRIPT_REVIEW_REQUIRED)
    workspace.save_project(review)
    store = ScriptArtifactStore(workspace.root)
    store.save_script(
        project.project_id,
        Script(
            title="متن",
            turns=[
                ScriptTurn(
                    turn_id="seg-1-turn-001",
                    segment_id="seg-1",
                    speaker="A",
                    spoken_text_fa="متن",
                    claim_ids=["claim-1"],
                    evidence_ids=["evidence-1"],
                )
            ],
        ),
    )
    store.save_checks(
        ScriptCheckReport(
            project_id=project.project_id,
            verdict="pass",
            word_count=1,
            estimated_minutes=0.01,
            substantive_turn_count=1,
        )
    )
    store.save_verification(
        project.project_id,
        VerificationDraft(verdict="revise", unsupported_claim_ratio=0.1),
    )
    store.save_manifest(
        ScriptPipelineManifest(
            project_id=project.project_id,
            status="review_required",
            last_error="Human review required.",
        )
    )

    recovered = service.recover_interrupted_runs()

    assert recovered == [project.project_id]
    assert service.run_store.load(project.project_id).status == "succeeded"
    assert workspace.load_project(project.project_id).state == ProjectState.SCRIPT_REVIEW_REQUIRED


def test_failure_from_script_ready_is_recorded_and_retryable(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()

    class ReadyFailurePipeline(FakePipeline):
        def run(self, project_id: UUID, *, on_stage, **_):
            self.calls += 1
            current = self.workspace.load_project(project_id)
            assert current.state == ProjectState.SCRIPT_DRAFTING
            transition(current, ProjectState.SCRIPT_READY)
            self.workspace.save_project(current)
            raise ValueError(
                "Revised script failed deterministic checks; the original script was kept."
            )

    failing = ReadyFailurePipeline(workspace)
    service = _service(tmp_path, project, failing)
    queued = service.approve_and_queue(project.project_id, approved_by="operator")

    failed = service.run(project.project_id)

    assert failed.status == "failed"
    assert failed.last_error == (
        "Revised script failed deterministic checks; the original script was kept."
    )
    persisted = workspace.load_project(project.project_id)
    assert persisted.state == ProjectState.SCRIPT_READY
    assert persisted.last_error == failed.last_error

    retry = service.retry(project.project_id)
    assert retry.status == "queued"
    assert retry.previous_run_id == queued.run_id


def test_recovery_from_script_ready_preserves_retryable_state(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = FakePipeline(workspace)
    service = _service(tmp_path, project, pipeline)
    run = service.approve_and_queue(project.project_id, approved_by="operator")
    run.status = "running"
    run.stage = "checking_revision"
    service.run_store.save(run)

    active = workspace.load_project(project.project_id)
    transition(active, ProjectState.SCRIPT_DRAFTING)
    transition(active, ProjectState.SCRIPT_READY)
    workspace.save_project(active)

    recovered = service.recover_interrupted_runs()

    assert recovered == [project.project_id]
    assert service.run_store.load(project.project_id).status == "failed"
    persisted = workspace.load_project(project.project_id)
    assert persisted.state == ProjectState.SCRIPT_READY
    assert "interrupted" in (persisted.last_error or "").lower()
    assert service.retry(project.project_id).status == "queued"
def test_review_required_is_a_successful_run(tmp_path: Path) -> None:
    class ReviewRequiredPipeline(FakePipeline):
        def run(self, project_id: UUID, *, on_stage, **_):
            self.calls += 1
            on_stage("verifying_draft")
            project = self.workspace.load_project(project_id)
            assert project.state == ProjectState.SCRIPT_DRAFTING
            transition(project, ProjectState.SCRIPT_READY)
            transition(project, ProjectState.SCRIPT_VERIFYING)
            transition(project, ProjectState.SCRIPT_REVIEW_REQUIRED)
            self.workspace.save_project(project)
            return object()

    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = ReviewRequiredPipeline(workspace)
    service = _service(tmp_path, project, pipeline)
    service.approve_and_queue(project.project_id, approved_by="operator")

    run = service.run(project.project_id)

    assert run.status == "succeeded"
    assert run.stage == "complete"
    assert workspace.load_project(project.project_id).state == ProjectState.SCRIPT_REVIEW_REQUIRED
    assert pipeline.calls == 1


def test_accepted_artifacts_survive_recover_interrupted_runs(tmp_path: Path) -> None:
    from thesisound.script import ScriptReviewDecision

    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    pipeline = FakePipeline(workspace)
    service = _service(tmp_path, project, pipeline)
    run = service.approve_and_queue(project.project_id, approved_by="operator")
    run.status = "running"
    run.stage = "verifying_revision"
    service.run_store.save(run)

    accepted = workspace.load_project(project.project_id)
    transition(accepted, ProjectState.SCRIPT_DRAFTING)
    transition(accepted, ProjectState.SCRIPT_READY)
    transition(accepted, ProjectState.SCRIPT_VERIFYING)
    transition(accepted, ProjectState.SCRIPT_REVIEW_REQUIRED)
    transition(accepted, ProjectState.SCRIPT_VERIFIED)
    workspace.save_project(accepted)

    store = ScriptArtifactStore(workspace.root)
    store.prepare_for_plan(project.project_id, run.approved_plan_hash)
    store.save_script(
        project.project_id,
        Script(
            title="متن",
            turns=[
                ScriptTurn(
                    turn_id="seg-1-turn-001",
                    segment_id="seg-1",
                    speaker="A",
                    spoken_text_fa="متن",
                    claim_ids=["claim-1"],
                    evidence_ids=["evidence-1"],
                )
            ],
        ),
    )
    store.save_checks(
        ScriptCheckReport(
            project_id=project.project_id,
            verdict="pass",
            word_count=1,
            estimated_minutes=0.01,
            substantive_turn_count=1,
        )
    )
    store.save_verification(
        project.project_id,
        VerificationDraft(verdict="revise", unsupported_claim_ratio=0.1),
    )
    store.save_manifest(ScriptPipelineManifest(project_id=project.project_id, status="verified"))
    store.save_review_decision(
        ScriptReviewDecision(
            project_id=project.project_id,
            decision="accepted",
            reviewer="operator",
            reason="Accept the residual qualification risk.",
            plan_hash=run.approved_plan_hash,
            checks_verdict="pass",
            verification_verdict="revise",
            unsupported_claim_ratio=0.1,
            quality_overall=None,
        )
    )

    recovered = service.recover_interrupted_runs()

    assert recovered == [project.project_id]
    current = service.run_store.load(project.project_id)
    assert current.status == "succeeded"
    assert current.stage == "complete"
    assert workspace.load_project(project.project_id).state == ProjectState.SCRIPT_VERIFIED
