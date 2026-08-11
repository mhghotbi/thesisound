from pathlib import Path
from uuid import UUID, uuid4

from thesisound import tracing
from thesisound.domain import (
    EpisodePlan,
    EpisodeSegment,
    Project,
    ProjectState,
    ResearchBrief,
    TopicType,
)
from thesisound.episode import CoverageReport, EpisodeBudgetReport
from thesisound.pipeline import WorkspaceStore, transition
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.episode_planning_run import (
    EpisodePlanningRunService,
    EpisodePlanningRunStore,
)


class FakePreparationService:
    def __init__(
        self,
        workspace: WorkspaceStore,
        *,
        can_plan: bool = True,
        supported_minutes: float = 20,
        fail_stage: str | None = None,
    ) -> None:
        self.workspace = workspace
        self.can_plan = can_plan
        self.supported_minutes = supported_minutes
        self.fail_stage = fail_stage
        self.calls: list[str] = []

    def audit_coverage(self, project_id: UUID, *, model: str):
        del model
        self.calls.append("coverage")
        project = self.workspace.load_project(project_id)
        if project.state == ProjectState.CORPUS_READY:
            transition(project, ProjectState.EPISODE_PLANNING)
            self.workspace.save_project(project)
        if self.fail_stage == "coverage":
            raise ValueError("coverage failed")
        return CoverageReport(
            project_id=project_id,
            central_question_status="well_covered" if self.can_plan else "partially_covered",
            max_supported_minutes=int(self.supported_minutes),
            recommendation="continue" if self.can_plan else "more_evidence",
            recommendation_reason=(
                "The corpus is sufficient."
                if self.can_plan
                else "Additional evidence is required."
            ),
            material_gaps=[] if self.can_plan else ["Missing historical context"],
            can_plan_episode=self.can_plan,
            model_run_id=uuid4(),
        )

    def prioritize_claims(self, project_id: UUID):
        del project_id
        self.calls.append("priorities")
        if self.fail_stage == "priorities":
            raise ValueError("priorities failed")
        return object()

    def estimate_budget(self, project_id: UUID):
        self.calls.append("budget")
        project = self.workspace.load_project(project_id)
        assert project.brief is not None
        return EpisodeBudgetReport(
            project_id=project_id,
            target_duration_minutes=project.brief.target_duration_minutes,
            words_per_minute=130,
            available_claim_seconds=1_200,
            original_evidence_tokens=2_000,
            estimated_supported_minutes=self.supported_minutes,
            model_reported_supported_minutes=int(self.supported_minutes),
            effective_supported_minutes=self.supported_minutes,
            calibration_status="fixture_calibrated",
        )

    def build_disagreement_graph(self, project_id: UUID):
        del project_id
        self.calls.append("disagreements")
        return object()

    def plan_episode(self, project_id: UUID, *, model: str):
        del model
        self.calls.append("plan")
        project = self.workspace.load_project(project_id)
        assert project.brief is not None
        project.episode_plan = EpisodePlan(
            title="طرح آزمون",
            listener_outcome="فهم موضوع",
            estimated_duration_minutes=project.brief.target_duration_minutes,
            segments=[
                EpisodeSegment(
                    segment_id="seg-001",
                    title="بخش اول",
                    purpose="شرح موضوع",
                    estimated_minutes=project.brief.target_duration_minutes,
                    claim_ids=["claim-1"],
                    key_question="سؤال؟",
                    speaker_dynamic="explanation",
                )
            ],
        )
        self.workspace.save_project(project)
        return project.episode_plan

    def build_evidence_packs(self, project_id: UUID):
        self.calls.append("packs")
        project = self.workspace.load_project(project_id)
        transition(project, ProjectState.EPISODE_PLANNED)
        self.workspace.save_project(project)
        return [object()]


def _brief(duration: int = 20) -> ResearchBrief:
    return ResearchBrief(
        normalized_topic="موضوع",
        topic_type=TopicType.CONCEPT,
        central_question="سؤال مرکزی چیست؟",
        target_duration_minutes=duration,
        learning_objectives=["فهم موضوع"],
    )


def _service(
    tmp_path: Path,
    project: Project,
    fake: FakePreparationService,
) -> EpisodePlanningRunService:
    workspace = fake.workspace
    workspace.save_project(project)

    class _NoopAnalysis:
        def sync_to_current_profile(self, project_id, source_id, *, fast_model, strong_model):
            del project_id, source_id, fast_model, strong_model
            return False

    return EpisodePlanningRunService(
        workspace_store=workspace,
        run_store=EpisodePlanningRunStore(workspace.root),
        episode_store=EpisodeArtifactStore(workspace.root),
        preparation_service_factory=lambda _: fake,  # type: ignore[return-value]
        source_analysis_service_factory=lambda: _NoopAnalysis(),  # type: ignore[return-value]
        coverage_model="fake",
        planning_model="fake",
        fast_model="fake-fast",
        strong_model="fake-strong",
    )


def test_successful_run_stops_at_episode_review_gate(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(
        raw_input="موضوع",
        state=ProjectState.CORPUS_READY,
        brief=_brief(),
    )
    fake = FakePreparationService(workspace)
    service = _service(tmp_path, project, fake)

    queued = service.queue(project.project_id)
    run = service.run(project.project_id)

    assert run.run_id == queued.run_id
    assert run.status == "succeeded"
    assert run.stage == "complete"
    assert fake.calls == [
        "coverage",
        "priorities",
        "budget",
        "disagreements",
        "plan",
        "packs",
    ]
    saved = workspace.load_project(project.project_id)
    assert saved.state == ProjectState.EPISODE_PLANNED
    assert saved.episode_plan is not None
    assert [item.run_id for item in service.run_store.load_history(project.project_id)] == [
        run.run_id
    ]


def test_successful_run_produces_a_stage_span_per_step(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(raw_input="موضوع", state=ProjectState.CORPUS_READY, brief=_brief())
    fake = FakePreparationService(workspace)
    service = _service(tmp_path, project, fake)

    service.queue(project.project_id)
    run = service.run(project.project_id)

    assert run.status == "succeeded"
    root = recording_tracer.sink.one("episode.run")
    assert root.status == "ok"
    assert root.parent_span_id is None  # new_root: no ambient HTTP span was open

    step_names = [
        "episode.refresh_evidence_scope",
        "episode.audit_coverage",
        "episode.prioritize_claims",
        "episode.estimate_budget",
        "episode.build_disagreement_graph",
        "episode.plan_episode",
        "episode.build_evidence_packs",
    ]
    for name in step_names:
        step = recording_tracer.sink.one(name)
        assert step.parent_span_id == root.context.span_id
        assert step.context.trace_id == root.context.trace_id
        assert step.status == "ok"

    stage_events = [
        event.attributes["current"]
        for event in recording_tracer.sink.events
        if event.name == "run.stage_changed"
    ]
    assert stage_events == [
        "refreshing_evidence_scope",
        "auditing_coverage",
        "prioritizing_claims",
        "estimating_budget",
        "building_disagreements",
        "planning_episode",
        "building_evidence_packs",
    ]


def test_blocked_run_marks_its_span_blocked_not_error(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(raw_input="موضوع", state=ProjectState.CORPUS_READY, brief=_brief(20))
    fake = FakePreparationService(workspace, can_plan=False, supported_minutes=10)
    service = _service(tmp_path, project, fake)

    service.queue(project.project_id)
    run = service.run(project.project_id)

    assert run.status == "blocked"
    root = recording_tracer.sink.one("episode.run")
    assert root.status == "blocked"
    assert root.attributes["status_reason"] == "coverage_insufficient"


def test_failed_step_marks_the_run_span_as_error(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(raw_input="موضوع", state=ProjectState.CORPUS_READY, brief=_brief())
    failing = FakePreparationService(workspace, fail_stage="priorities")
    service = _service(tmp_path, project, failing)

    service.queue(project.project_id)
    run = service.run(project.project_id)

    assert run.status == "failed"
    root = recording_tracer.sink.one("episode.run")
    assert root.status == "error"
    assert root.attributes["status_reason"] == "ValueError"
    # The failure surfaces first as the step span's own automatic error status.
    step = recording_tracer.sink.one("episode.prioritize_claims")
    assert step.status == "error"
    assert step.error_type == "ValueError"


def test_insufficient_coverage_blocks_without_marking_project_failed(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(
        raw_input="موضوع",
        state=ProjectState.CORPUS_READY,
        brief=_brief(20),
    )
    fake = FakePreparationService(workspace, can_plan=False, supported_minutes=10)
    service = _service(tmp_path, project, fake)

    service.queue(project.project_id)
    run = service.run(project.project_id)

    assert run.status == "blocked"
    assert run.max_supported_minutes == 10
    assert run.material_gaps == ["Missing historical context"]
    assert workspace.load_project(project.project_id).state == ProjectState.EPISODE_PLANNING
    assert fake.calls == ["coverage"]


def test_block_and_resolve_by_reducing_duration_emit_a_gate_pair(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    """gate.blocked and gate.resolved bracket real, currently-unmeasured human
    wait time -- usually the largest slice of a project's end-to-end latency."""

    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(raw_input="موضوع", state=ProjectState.CORPUS_READY, brief=_brief(20))
    fake = FakePreparationService(workspace, can_plan=False, supported_minutes=10)
    service = _service(tmp_path, project, fake)
    service.queue(project.project_id)
    service.run(project.project_id)

    service.requeue_with_duration(project.project_id, 10)

    blocked = [e for e in recording_tracer.sink.events if e.name == "gate.blocked"]
    resolved = [e for e in recording_tracer.sink.events if e.name == "gate.resolved"]
    assert len(blocked) == 1
    assert len(resolved) == 1
    assert resolved[0].attributes["resolution"] == "reduced_duration"
    assert blocked[0].workflow_run_id == resolved[0].workflow_run_id


def test_blocked_run_can_reduce_duration_in_a_new_attempt(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(
        raw_input="موضوع",
        state=ProjectState.CORPUS_READY,
        brief=_brief(20),
    )
    fake = FakePreparationService(workspace, can_plan=False, supported_minutes=10)
    service = _service(tmp_path, project, fake)
    service.queue(project.project_id)
    blocked = service.run(project.project_id)

    next_run = service.requeue_with_duration(project.project_id, 10)

    assert next_run.run_id != blocked.run_id
    assert next_run.previous_run_id == blocked.run_id
    assert next_run.target_duration_minutes == 10
    assert workspace.load_project(project.project_id).brief.target_duration_minutes == 10
    assert len(service.run_store.load_history(project.project_id)) == 2


def test_blocked_run_can_reopen_inputs_and_mark_outputs_stale(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(
        raw_input="موضوع",
        state=ProjectState.CORPUS_READY,
        brief=_brief(),
    )
    fake = FakePreparationService(workspace, can_plan=False, supported_minutes=8)
    service = _service(tmp_path, project, fake)
    service.queue(project.project_id)
    service.run(project.project_id)

    service.reopen_inputs(project.project_id, reason="add evidence")

    assert workspace.load_project(project.project_id).state == ProjectState.SOURCES_COLLECTING
    stale = workspace.project_dir(project.project_id) / "episode" / "stale.json"
    assert stale.exists()
    assert "add evidence" in stale.read_text(encoding="utf-8")


def test_failure_and_restart_recovery_create_retryable_new_attempts(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(
        raw_input="موضوع",
        state=ProjectState.CORPUS_READY,
        brief=_brief(),
    )
    failing = FakePreparationService(workspace, fail_stage="priorities")
    service = _service(tmp_path, project, failing)
    service.queue(project.project_id)
    failed = service.run(project.project_id)

    assert failed.status == "failed"
    assert workspace.load_project(project.project_id).state == ProjectState.FAILED_RETRYABLE
    retried = service.retry(project.project_id)
    assert retried.run_id != failed.run_id
    assert retried.previous_run_id == failed.run_id

    retried.status = "running"
    retried.stage = "planning_episode"
    service.run_store.save(retried)
    project_after_retry = workspace.load_project(project.project_id)
    transition(project_after_retry, ProjectState.EPISODE_PLANNING)
    workspace.save_project(project_after_retry)

    recovered = service.recover_interrupted_runs()

    assert recovered == [project.project_id]
    interrupted = service.run_store.load(project.project_id)
    assert interrupted.status == "failed"
    assert interrupted.stage == "failed"
    assert workspace.load_project(project.project_id).state == ProjectState.FAILED_RETRYABLE
