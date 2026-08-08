import re
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from thesisound.config import Settings
from thesisound.domain import ProjectState
from thesisound.pipeline import WorkspaceStore
from thesisound.services.corpus_building import CorpusBuildRunStore
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


def _app(settings: Settings) -> FastAPI:
    return create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
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


def _upload_and_select_source(
    client: TestClient,
    settings: Settings,
    project_id: UUID,
) -> tuple[UUID, UiSourceManifestStore]:
    page = client.get(f"/projects/{project_id}/sources")
    source_text = ("این یک منبع واقعی برای آزمون استخراج و کنترل کیفیت است. " * 12).encode()
    client.post(
        f"/projects/{project_id}/sources/upload",
        data={"csrf_token": _csrf(page.text)},
        files={"source_file": ("kant.txt", source_text, "text/plain")},
    )

    workspace = WorkspaceStore(settings.workspace_root)
    manifest_store = UiSourceManifestStore(workspace.project_dir(project_id))
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
    match = re.search(r'data-source-id="([0-9a-f-]{36})"', page.text)
    assert match is not None
    source_id = UUID(match.group(1))
    client.post(
        f"/projects/{project_id}/sources/{source_id}/toggle",
        data={"csrf_token": _csrf(page.text)},
    )
    return source_id, manifest_store


def test_create_and_confirm_brief(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(_app(settings)) as client:
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


def test_upload_select_queue_and_lock_confirmed_inputs(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(_app(settings)) as client:
        _login(client)
        project_id = _create_project(client)
        _confirm_brief(client, project_id)
        source_id, manifest_store = _upload_and_select_source(client, settings, project_id)

        page = client.get(f"/projects/{project_id}/sources")
        response = client.post(
            f"/projects/{project_id}/corpus/confirm",
            data={"csrf_token": _csrf(page.text)},
            follow_redirects=False,
        )
        assert response.status_code == 303

        run = CorpusBuildRunStore(settings.workspace_root).load(project_id)
        assert run.status == "queued"
        assert [item.source_id for item in run.sources] == [source_id]
        assert run.sources[0].ingestion_path.exists()

        locked_page = client.get(f"/projects/{project_id}/sources")
        locked = client.post(
            f"/projects/{project_id}/sources/{source_id}/toggle",
            data={"csrf_token": _csrf(locked_page.text)},
            follow_redirects=False,
        )
        assert locked.status_code == 303
        assert locked.headers["location"].endswith("error=selection-locked")

        brief_page = client.get(f"/projects/{project_id}/brief")
        assert "فقط خواندنی" in brief_page.text
        rejected = client.post(
            f"/projects/{project_id}/brief",
            data={
                "csrf_token": _csrf(brief_page.text),
                "central_question": "سؤال تغییرکرده",
                "must_include": "",
                "exclusions": "",
                "action": "save",
            },
        )
        assert rejected.status_code == 422

    project = WorkspaceStore(settings.workspace_root).load_project(project_id)
    assert project.state == ProjectState.CORPUS_BUILDING
    assert len(project.sources) == 1
    assert project.sources[0].title == "kant.txt"
    assert project.brief.central_question == "اخلاق کانت چگونه کار می‌کند؟"
    assert "real parse-quality gate" in project.sources[0].relevance_reasons[0]
    assert manifest_store.load()[0].selected


def test_web_confirmation_rolls_back_when_queue_persistence_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path)
    app = _app(settings)
    with TestClient(app) as client:
        _login(client)
        project_id = _create_project(client)
        _confirm_brief(client, project_id)
        _upload_and_select_source(client, settings, project_id)

        def fail_save(_):
            raise RuntimeError("simulated persistence failure")

        monkeypatch.setattr(app.state.corpus_builder.run_store, "save", fail_save)
        page = client.get(f"/projects/{project_id}/sources")
        response = client.post(
            f"/projects/{project_id}/corpus/confirm",
            data={"csrf_token": _csrf(page.text)},
        )

    assert response.status_code == 422
    project = WorkspaceStore(settings.workspace_root).load_project(project_id)
    assert project.state == ProjectState.SOURCE_SELECTION_REQUIRED
    assert project.sources == []
    assert CorpusBuildRunStore(settings.workspace_root).load_optional(project_id) is None
