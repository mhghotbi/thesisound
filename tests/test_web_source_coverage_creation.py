"""Creation-form fields for `source_coverage` (`10c` P3 Step 12; `10b` B1.1)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from thesisound.config import Settings
from thesisound.domain import Compression, DeliveryMode, LessonIntent
from thesisound.pipeline import WorkspaceStore
from thesisound.web.app import create_app


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
        data={"phone": "09120000000", "csrf_token": _csrf(page.text), "next_path": "/projects"},
    )
    page = client.get("/login/verify")
    client.post("/login/verify", data={"code": "999999", "csrf_token": _csrf(page.text)})


def test_default_submission_keeps_focused_question_defaults(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(
        settings, corpus_executor=lambda _: None,
        episode_executor=lambda _: None, script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        new_page = client.get("/projects/new")
        created = client.post(
            "/projects",
            data={
                "csrf_token": _csrf(new_page.text),
                "topic": "دولت نزد ابن‌خلدون",
                "duration": "20",
            },
            follow_redirects=False,
        )
    project_id = created.headers["location"].split("/")[2]
    project = WorkspaceStore(settings.workspace_root).load_project(project_id)
    assert project.lesson_intent == LessonIntent.FOCUSED_QUESTION
    assert project.delivery == DeliveryMode.AUDIO
    assert project.compression == Compression.STANDARD
    assert project.episode_target_minutes == 20
    assert project.known_concepts == []


def test_source_coverage_submission_sets_the_new_fields(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(
        settings, corpus_executor=lambda _: None,
        episode_executor=lambda _: None, script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        new_page = client.get("/projects/new")
        assert "یادگیری کامل یک منبع" in new_page.text
        created = client.post(
            "/projects",
            data={
                "csrf_token": _csrf(new_page.text),
                "topic": "وضع بشر اثر آرنت",
                "duration": "20",
                "lesson_intent": "source_coverage",
                "delivery": "both",
                "compression": "concise",
                "episode_target_minutes": "15",
                "known_concepts": "کنش\nساختن",
            },
            follow_redirects=False,
        )
    project_id = created.headers["location"].split("/")[2]
    project = WorkspaceStore(settings.workspace_root).load_project(project_id)
    assert project.lesson_intent == LessonIntent.SOURCE_COVERAGE
    assert project.delivery == DeliveryMode.BOTH
    assert project.compression == Compression.CONCISE
    assert project.episode_target_minutes == 15
    assert project.known_concepts == ["کنش", "ساختن"]


def test_invalid_lesson_intent_is_a_validation_error_not_a_crash(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(
        settings, corpus_executor=lambda _: None,
        episode_executor=lambda _: None, script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        new_page = client.get("/projects/new")
        response = client.post(
            "/projects",
            data={
                "csrf_token": _csrf(new_page.text),
                "topic": "موضوع",
                "duration": "20",
                "lesson_intent": "not_a_real_intent",
            },
        )
    assert response.status_code == 422
