import re
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from thesisound.config import Settings
from thesisound.domain import ProjectState
from thesisound.pipeline import WorkspaceStore
from thesisound.web.app import create_app
from thesisound.web.source_manifest import UiSourceManifestStore, UiSourceStatus


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


def _create_project(client: TestClient) -> UUID:
    page = client.get("/projects/new")
    created = client.post(
        "/projects",
        data={
            "csrf_token": _csrf(page.text),
            "topic": "اخلاق کانت",
            "audience": "دانشجوی علوم انسانی",
            "prior_knowledge": "introductory",
            "duration": "20",
            "mode": "explanatory",
        },
        follow_redirects=False,
    )
    return UUID(created.headers["location"].split("/")[2])


def _confirm_brief(client: TestClient, project_id: UUID) -> None:
    page = client.get(f"/projects/{project_id}/brief")
    client.post(
        f"/projects/{project_id}/brief",
        data={
            "csrf_token": _csrf(page.text),
            "central_question": "اخلاق کانت چگونه کار می‌کند؟",
            "must_include": "",
            "exclusions": "",
            "action": "confirm",
        },
    )


def test_create_and_confirm_brief(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        _login(client)
        page = client.get("/projects/new")
        response = client.post(
            "/projects",
            data={
                "csrf_token": _csrf(page.text),
                "topic": "چرا مفهوم دولت نزد ابن‌خلدون مهم است؟",
                "audience": "دانشجوی علوم انسانی",
                "prior_knowledge": "introductory",
                "duration": "20",
                "mode": "explanatory",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        project_id = UUID(response.headers["location"].split("/")[2])

        project = WorkspaceStore(settings.workspace_root).load_project(project_id)
        assert project.state == ProjectState.BRIEF_READY

        page = client.get(response.headers["location"])
        response = client.post(
            f"/projects/{project_id}/brief",
            data={
                "csrf_token": _csrf(page.text),
                "central_question": project.brief.central_question,
                "must_include": "زمینه تاریخی",
                "exclusions": "",
                "action": "confirm",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    project = WorkspaceStore(settings.workspace_root).load_project(project_id)
    assert project.state == ProjectState.SOURCES_COLLECTING
    assert project.brief.scope_inclusions == ["زمینه تاریخی"]


def test_upload_select_and_confirm_real_corpus(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        _login(client)
        project_id = _create_project(client)
        _confirm_brief(client, project_id)

        page = client.get(f"/projects/{project_id}/sources")
        source_text = ("این یک منبع واقعی برای آزمون استخراج و کنترل کیفیت است. " * 12).encode()
        client.post(
            f"/projects/{project_id}/sources/upload",
            data={"csrf_token": _csrf(page.text)},
            files={"source_file": ("kant.txt", source_text, "text/plain")},
        )

        manifest_store = UiSourceManifestStore(
            WorkspaceStore(settings.workspace_root).project_dir(project_id)
        )
        source = manifest_store.load()[0]
        assert source.status == UiSourceStatus.READY
        assert source.parser_name == "native"
        assert source.quality_verdict == "pass"
        assert source.safe_for_claim_extraction
        assert source.block_count == 1
        assert source.text_characters > 200
        assert source.artifact_ref is not None
        assert (
            settings.ingestion_artifact_root
            / str(project_id)
            / str(source.source_id)
            / source.artifact_ref
        ).exists()

        page = client.get(f"/projects/{project_id}/sources")
        assert "native" in page.text
        match = re.search(r'data-source-id="([0-9a-f-]{36})"', page.text)
        assert match is not None
        source_id = UUID(match.group(1))
        client.post(
            f"/projects/{project_id}/sources/{source_id}/toggle",
            data={"csrf_token": _csrf(page.text)},
        )

        page = client.get(f"/projects/{project_id}/sources")
        response = client.post(
            f"/projects/{project_id}/corpus/confirm",
            data={"csrf_token": _csrf(page.text)},
            follow_redirects=False,
        )

    assert response.status_code == 303
    project = WorkspaceStore(settings.workspace_root).load_project(project_id)
    assert project.state == ProjectState.CORPUS_BUILDING
    assert len(project.sources) == 1
    assert project.sources[0].title == "kant.txt"
    assert "real parse-quality gate" in project.sources[0].relevance_reasons[0]
