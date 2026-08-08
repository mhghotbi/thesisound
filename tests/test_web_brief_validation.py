from pathlib import Path

from fastapi.testclient import TestClient

from thesisound.config import Settings
from thesisound.pipeline import WorkspaceStore
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


def test_brief_validation_preserves_all_submitted_values(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
        audio_executor=lambda _: None,
    )

    with TestClient(app) as client:
        _login(client)
        new_page = client.get("/projects/new")
        created = client.post(
            "/projects",
            data={
                "csrf_token": _csrf(new_page.text),
                "topic": "دولت نزد ابن‌خلدون",
                "audience": "دانشجوی علوم انسانی",
                "prior_knowledge": "introductory",
                "duration": "20",
                "mode": "explanatory",
            },
            follow_redirects=False,
        )
        project_id = created.headers["location"].split("/")[2]
        brief_page = client.get(created.headers["location"])
        response = client.post(
            f"/projects/{project_id}/brief",
            data={
                "csrf_token": _csrf(brief_page.text),
                "central_question": "",
                "must_include": "زمینه تاریخی مغرب\nچرخه عصبیت",
                "exclusions": "زندگی‌نامه تفصیلی",
                "action": "save",
            },
        )

    assert response.status_code == 422
    assert "پرسش مرکزی نمی‌تواند خالی باشد" in response.text
    assert "زمینه تاریخی مغرب\nچرخه عصبیت" in response.text
    assert "زندگی‌نامه تفصیلی" in response.text

    saved = WorkspaceStore(settings.workspace_root).load_project(project_id)
    assert saved.brief is not None
    assert saved.brief.scope_inclusions == []
    assert saved.brief.scope_exclusions == []
