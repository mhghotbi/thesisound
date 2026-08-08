from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from thesisound.config import Settings
from thesisound.domain import Project, ProjectState, ResearchBrief, TopicType
from thesisound.pipeline import WorkspaceStore
from thesisound.services.episode_planning_run import (
    EpisodePlanningRun,
    EpisodePlanningRunStore,
)
from thesisound.web.app import create_app


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        ingestion_artifact_root=tmp_path / "artifacts",
        web_session_secret="test-secret-that-is-long-enough",
        allow_test_otp=True,
        test_otp_phone="0912000000",
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
            "phone": "0912000000",
            "csrf_token": _csrf(page.text),
            "next_path": "/projects",
        },
    )
    page = client.get("/login/verify")
    client.post(
        "/login/verify",
        data={"code": "999999", "csrf_token": _csrf(page.text)},
    )


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


def test_web_queues_episode_planning_from_corpus_ready(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project(ProjectState.CORPUS_READY)
    workspace.save_project(project)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )

    with TestClient(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/episode")
        assert "سنجش کفایت منابع و ساخت طرح" in page.text
        response = client.post(
            f"/projects/{project.project_id}/episode/prepare",
            data={"csrf_token": _csrf(page.text)},
            follow_redirects=False,
        )

    assert response.status_code == 303
    run = EpisodePlanningRunStore(settings.workspace_root).load(project.project_id)
    assert run.status == "queued"
    assert run.target_duration_minutes == 20


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

    with TestClient(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/episode")
        assert "ادامه‌دادن با corpus ناکافی مجاز نیست" in page.text
        assert "ادامه به هر حال" not in page.text
        response = client.post(
            f"/projects/{project.project_id}/episode/reduce-duration",
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

    with TestClient(app) as client:
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
