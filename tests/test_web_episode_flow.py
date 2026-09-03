from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from thesisound.config import Settings
from thesisound.domain import (
    EpisodePlan,
    EpisodeSegment,
    Project,
    ProjectState,
    ResearchBrief,
    TopicType,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.services.episode_planning_run import (
    EpisodePlanningRun,
    EpisodePlanningRunStore,
)
from thesisound.web.app import create_app


def _client(app) -> TestClient:
    return TestClient(app, base_url="https://testserver.local")


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        ingestion_artifact_root=tmp_path / "artifacts",
        web_session_secret="test-secret-that-is-long-enough",
        allow_test_otp=True,
        test_otp_phone="09120000000",
        test_otp_code="999999",
        otp_resend_cooldown_seconds=5,
        ui_demo_mode=False,
    )


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _login(client: TestClient) -> None:
    page = client.get("/login")
    client.post(
        "/login/request-code",
        data={
            "phone": "09120000000",
            "csrf_token": _csrf(page.text),
            "next_path": "/projects",
        },
    )
    page = client.get("/login/verify")
    client.post(
        "/login/verify",
        data={"code": "999999", "csrf_token": _csrf(page.text)},
    )
    account = client.app.state.accounts.get_or_create_phone_user("09120000000")
    for project in client.app.state.workspace.list_projects():
        client.app.state.accounts.add_project_member(project.project_id, account.user_id)


def _project(state: ProjectState, *, duration: int = 20) -> Project:
    return Project(
        raw_input="موضوع",
        state=state,
        brief=ResearchBrief(
            normalized_topic="موضوع",
            topic_type=TopicType.CONCEPT,
            central_question="سؤال مرکزی چیست؟",
            target_duration_minutes=duration,
            learning_objectives=["فهم موضوع"],
        ),
    )


def test_web_prepare_still_queues_when_planning_stalled(tmp_path: Path) -> None:
    """POST /episode/prepare still works when corpus is ready but planning never started."""
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project(ProjectState.CORPUS_READY)
    workspace.save_project(project)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )

    with _client(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/episode")
        assert "سنجش کفایت منابع و ساخت طرح" not in page.text
        assert "به‌صورت خودکار" in page.text
        response = client.post(
            f"/projects/{project.project_id}/episode/prepare",
            data={"csrf_token": _csrf(page.text)},
            follow_redirects=False,
        )

    assert response.status_code == 303
    run = EpisodePlanningRunStore(settings.workspace_root).load(project.project_id)
    assert run.status == "queued"
    assert run.target_duration_minutes == 20


def test_corpus_confirmation_queues_planning(tmp_path: Path) -> None:
    from thesisound.web.corpus_runtime import run_corpus_then_queue_planning
    from thesisound.web.episode_runtime import create_episode_planner

    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project(ProjectState.CORPUS_BUILDING)
    workspace.save_project(project)
    planned: list = []

    def _to_ready(project_id) -> None:
        loaded = workspace.load_project(project_id)
        loaded.state = ProjectState.CORPUS_READY
        workspace.save_project(loaded)

    execute = run_corpus_then_queue_planning(
        run_corpus=_to_ready,
        workspace=workspace,
        planner=create_episode_planner(settings, workspace),
        run_episode=planned.append,
    )
    execute(project.project_id)

    run = EpisodePlanningRunStore(settings.workspace_root).load(project.project_id)
    assert run.status == "queued"
    assert run.target_duration_minutes == 20
    assert planned == [project.project_id]


def test_insufficient_coverage_still_stops_with_its_message(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project(ProjectState.EPISODE_PLANNING, duration=20)
    workspace.save_project(project)
    run_store = EpisodePlanningRunStore(settings.workspace_root)
    blocked = EpisodePlanningRun(
        run_id=uuid4(),
        project_id=project.project_id,
        status="blocked",
        stage="blocked",
        target_duration_minutes=20,
        max_supported_minutes=10,
        material_gaps=["زمینه تاریخی کافی نیست"],
        last_error="منابع برای مدت درخواستی کافی نیستند.",
    )
    run_store.save(blocked)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )

    with _client(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/episode")
        assert "ادامه‌دادن با corpus ناکافی مجاز نیست." in page.text
        assert f"/projects/{project.project_id}/episode/duration" in page.text
        assert f"/projects/{project.project_id}/episode/reopen-inputs" in page.text


def test_blocked_web_flow_has_no_continue_anyway_and_can_reduce_duration(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project(ProjectState.EPISODE_PLANNING, duration=20)
    workspace.save_project(project)
    run_store = EpisodePlanningRunStore(settings.workspace_root)
    blocked = EpisodePlanningRun(
        run_id=uuid4(),
        project_id=project.project_id,
        status="blocked",
        stage="blocked",
        target_duration_minutes=20,
        max_supported_minutes=10,
        material_gaps=["زمینه تاریخی کافی نیست"],
        last_error="منابع برای مدت درخواستی کافی نیستند.",
    )
    run_store.save(blocked)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )

    with _client(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/episode")
        assert "ادامه‌دادن با corpus ناکافی مجاز نیست" in page.text
        assert "ادامه به هر حال" not in page.text
        assert "مدت کوتاه‌تر" not in page.text
        assert "مدت گفتار" in page.text
        response = client.post(
            f"/projects/{project.project_id}/episode/duration",
            data={
                "csrf_token": _csrf(page.text),
                "duration_minutes": "10",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    next_run = run_store.load(project.project_id)
    assert next_run.run_id != blocked.run_id
    assert next_run.previous_run_id == blocked.run_id
    assert next_run.status == "queued"
    saved = workspace.load_project(project.project_id)
    assert saved.brief.target_duration_minutes == 10


def test_blocked_web_flow_can_reopen_sources_and_marks_episode_stale(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project(ProjectState.EPISODE_PLANNING)
    workspace.save_project(project)
    EpisodePlanningRunStore(settings.workspace_root).save(
        EpisodePlanningRun(
            project_id=project.project_id,
            status="blocked",
            stage="blocked",
            target_duration_minutes=20,
            max_supported_minutes=8,
            last_error="منبع بیشتری لازم است.",
        )
    )
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )

    with _client(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/episode")
        response = client.post(
            f"/projects/{project.project_id}/episode/reopen-inputs",
            data={"csrf_token": _csrf(page.text), "action": "add-source"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].endswith(f"/{project.project_id}/sources")
    assert workspace.load_project(project.project_id).state == ProjectState.SOURCES_COLLECTING
    assert (workspace.project_dir(project.project_id) / "episode" / "stale.json").exists()


def _succeeded_run(project: Project, *, supported: int) -> EpisodePlanningRun:
    return EpisodePlanningRun(
        run_id=uuid4(),
        project_id=project.project_id,
        status="succeeded",
        stage="complete",
        target_duration_minutes=project.brief.target_duration_minutes,
        max_supported_minutes=supported,
        effective_supported_minutes=float(supported),
    )


def test_duration_can_change_on_a_finished_plan(tmp_path: Path) -> None:
    """The corpus ceiling is only knowable here, so the choice belongs here too."""

    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project(ProjectState.EPISODE_PLANNED, duration=20)
    workspace.save_project(project)
    run_store = EpisodePlanningRunStore(settings.workspace_root)
    succeeded = _succeeded_run(project, supported=35)
    run_store.save(succeeded)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )

    with _client(app) as client:
        _login(client)
        projects = client.get("/projects")
        response = client.post(
            f"/projects/{project.project_id}/episode/duration",
            data={"csrf_token": _csrf(projects.text), "duration_minutes": "30"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    saved = workspace.load_project(project.project_id)
    assert saved.brief.target_duration_minutes == 30
    assert saved.state == ProjectState.EPISODE_PLANNING
    assert saved.episode_plan is None
    next_run = run_store.load(project.project_id)
    assert next_run.status == "queued"
    assert next_run.previous_run_id == succeeded.run_id
    assert next_run.target_duration_minutes == 30


def test_duration_cannot_exceed_the_supported_ceiling(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project(ProjectState.EPISODE_PLANNED, duration=20)
    workspace.save_project(project)
    run_store = EpisodePlanningRunStore(settings.workspace_root)
    run_store.save(_succeeded_run(project, supported=25))
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )

    with _client(app) as client:
        _login(client)
        projects = client.get("/projects")
        response = client.post(
            f"/projects/{project.project_id}/episode/duration",
            data={"csrf_token": _csrf(projects.text), "duration_minutes": "45"},
            follow_redirects=False,
        )

    assert response.status_code != 303
    saved = workspace.load_project(project.project_id)
    assert saved.brief.target_duration_minutes == 20
    assert saved.state == ProjectState.EPISODE_PLANNED


def test_duration_is_locked_once_the_script_has_started(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project(ProjectState.SCRIPT_DRAFTING, duration=20)
    workspace.save_project(project)
    run_store = EpisodePlanningRunStore(settings.workspace_root)
    run_store.save(_succeeded_run(project, supported=35))
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )

    with _client(app) as client:
        _login(client)
        projects = client.get("/projects")
        response = client.post(
            f"/projects/{project.project_id}/episode/duration",
            data={"csrf_token": _csrf(projects.text), "duration_minutes": "30"},
            follow_redirects=False,
        )

    assert response.status_code != 303
    saved = workspace.load_project(project.project_id)
    assert saved.brief.target_duration_minutes == 20


def _blocked_run(project_id, *, supported: int = 10, target: int = 20) -> EpisodePlanningRun:
    return EpisodePlanningRun(
        run_id=uuid4(),
        project_id=project_id,
        status="blocked",
        stage="blocked",
        target_duration_minutes=target,
        max_supported_minutes=supported,
        material_gaps=["زمینه تاریخی کافی نیست"],
        last_error="منابع برای مدت درخواستی کافی نیستند.",
    )


def test_a_refusal_leads_the_processing_page_instead_of_trailing_it(tmp_path: Path) -> None:
    """The ruling used to be 13px --danger text at the foot of the page, with no heading.

    DESIGN.md gives a blocking state the same typographic care as a passing one, and
    `episode.html` already did. `/processing` says it in the same words now, at the
    same size, with the action beside it.
    """
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project(ProjectState.EPISODE_PLANNING, duration=20)
    workspace.save_project(project)
    EpisodePlanningRunStore(settings.workspace_root).save(_blocked_run(project.project_id))
    app = create_app(settings, corpus_executor=lambda _: None, episode_executor=lambda _: None)

    with _client(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/processing")

    assert page.status_code == 200
    assert 'id="processing-blocked-title"' in page.text
    assert "حکم کفایت منابع" in page.text
    assert "دیدن راه‌های اصلاح" in page.text
    # The ruling is a verdict heading now, not a caption under a source row.
    assert 'class="source-row__summary">منابع برای مدت درخواستی' not in page.text
    # And the generic second offer of the same destination is gone.
    assert page.text.count("مشاهدهٔ کفایت منابع و طرح گفتار") == 0


def test_a_blocked_stage_does_not_pulse_as_if_it_were_running(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project(ProjectState.EPISODE_PLANNING, duration=20)
    workspace.save_project(project)
    EpisodePlanningRunStore(settings.workspace_root).save(_blocked_run(project.project_id))
    app = create_app(settings, corpus_executor=lambda _: None, episode_executor=lambda _: None)

    with _client(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/processing")

    assert "stage-row is-blocked is-current" in page.text
    assert "is-running" not in page.text
    assert "منتظر تصمیم شما" in page.text


def test_the_readiness_verdict_is_the_largest_thing_on_its_page(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project(ProjectState.BRIEF_READY)
    workspace.save_project(project)
    app = create_app(settings, corpus_executor=lambda _: None, episode_executor=lambda _: None)

    with _client(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/readiness")

    assert page.status_code == 200
    # `.coverage-verdict h2` is clamp(20px, 2.4vw, 26px); the old box put this at 16px.
    assert 'class="coverage-verdict" aria-labelledby="readiness-verdict-title"' in page.text
    assert "readiness-verdict " not in page.text
    assert "حکم آمادگی" in page.text


def test_both_explicit_gates_use_the_same_confirmation(tmp_path: Path) -> None:
    """Approving the plan is the heavier of the two gates and had the lighter design.

    Confirming sources has always used `.sticky-confirmation`: it follows the reader
    down the page and names what it commits. Approving the plan — which starts the
    writing and binds to this exact version — was a notice and a bare primary button
    at the foot of a long page.
    """
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project(ProjectState.EPISODE_PLANNED)
    project.episode_plan = EpisodePlan(
        title="سه پرسش دربارهٔ کنش",
        listener_outcome="تمایز کار و کنش روشن می‌شود",
        estimated_duration_minutes=20,
        segments=[
            EpisodeSegment(
                segment_id=f"seg-{index}",
                title=f"بخش {index}",
                purpose="توضیح",
                estimated_minutes=10,
                claim_ids=[f"claim-{index}"],
                key_question="چرا؟",
                speaker_dynamic="explanation",
            )
            for index in (1, 2)
        ],
    )
    workspace.save_project(project)
    app = create_app(settings, corpus_executor=lambda _: None, episode_executor=lambda _: None)

    with _client(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/episode")

    assert page.status_code == 200
    assert 'class="sticky-confirmation" aria-labelledby="plan-confirm-title"' in page.text
    # It names what it commits — the plan and how many parts — not just "confirm".
    assert "سه پرسش دربارهٔ کنش" in page.text
    assert "۲ بخش" in page.text
    assert 'aria-describedby="plan-confirm-hint"' in page.text
    assert f"/projects/{project.project_id}/script/approve" in page.text
