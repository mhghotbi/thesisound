from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from thesisound.config import Settings
from thesisound.domain import ProjectState
from thesisound.pipeline import WorkspaceStore
from thesisound.services.runtime_preflight import RuntimePreflight
from thesisound.web.app import create_app
from thesisound.web.source_discovery import WebSourceCandidate
from thesisound.web.source_manifest import (
    UiSourceManifest,
    UiSourceManifestStore,
    UiSourceStatus,
)
from thesisound.web.source_routes import WebSourceDiscoveryService


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


def _create_and_confirm(client: TestClient) -> UUID:
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
    project_id = UUID(created.headers["location"].split("/")[2])
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
    return project_id


def test_project_can_start_with_only_a_title_and_auto_add_web_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path)

    def fake_search(self, project, query):
        return [
            WebSourceCandidate(
                query=query or project.brief.central_question,
                title="منبع وب آزمون",
                url="https://example.com/kant",
                snippet="candidate only",
            )
        ]

    def fake_import(self, project_id, candidate):
        return UiSourceManifest(
            filename="kant.web.md",
            display_title=candidate.title,
            content_type="text/markdown",
            size_bytes=1200,
            status=UiSourceStatus.READY,
            selected=True,
            safe_for_claim_extraction=True,
            block_count=4,
            text_characters=1100,
            parser_name="native",
            quality_verdict="pass",
            origin="gemini_web_search",
            canonical_url=str(candidate.url),
            retrieval_scope="full_text",
            artifact_ref="ingestion-result.json",
        )

    monkeypatch.setattr(WebSourceDiscoveryService, "search", fake_search)
    monkeypatch.setattr(WebSourceDiscoveryService, "import_candidate", fake_import)
    monkeypatch.setattr(RuntimePreflight, "require", lambda *_: None)

    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        project_id = _create_and_confirm(client)
        page = client.get(f"/projects/{project_id}/sources")
        assert "پیدا کردن منبع با Gemini" in page.text
        assert "داشتن فایل از قبل الزامی نیست" in page.text

        response = client.post(
            f"/projects/{project_id}/sources/search",
            data={
                "csrf_token": _csrf(page.text),
                "query": "",
                "mode": "auto",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        result_page = client.get(response.headers["location"])
        assert "منبع وب آزمون" in result_page.text
        assert "منبع وب بازیابی‌شده" in result_page.text

    project = WorkspaceStore(settings.workspace_root).load_project(project_id)
    sources = UiSourceManifestStore(
        WorkspaceStore(settings.workspace_root).project_dir(project_id)
    ).load()
    assert project.state == ProjectState.SOURCE_SELECTION_REQUIRED
    assert len(sources) == 1
    assert sources[0].selected


def test_failed_project_can_rewind_to_sources_and_edit_again(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(RuntimePreflight, "require", lambda *_: None)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )
    workspace = WorkspaceStore(settings.workspace_root)

    with TestClient(app) as client:
        _login(client)
        project_id = _create_and_confirm(client)
        project = workspace.load_project(project_id)
        project.state = ProjectState.FAILED_RETRYABLE
        project.last_error = "Document map failed"
        workspace.save_project(project)
        project_dir = workspace.project_dir(project_id)
        (project_dir / "sources").mkdir()
        (project_dir / "sources" / "stale.json").write_text("{}", encoding="utf-8")
        (project_dir / "corpus-build-run.json").write_text(
            json.dumps({"status": "failed"}),
            encoding="utf-8",
        )

        page = client.get(f"/projects/{project_id}/sources")
        assert "بازگشت و اصلاح مراحل قبلی" in page.text
        response = client.post(
            f"/projects/{project_id}/workflow/rewind",
            data={
                "csrf_token": _csrf(page.text),
                "target": "sources",
                "reason": "اصلاح پس از خطا",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].endswith("/sources?rewound=1")

    current = workspace.load_project(project_id)
    assert current.state == ProjectState.SOURCES_COLLECTING
    assert current.last_error is None
    assert not (workspace.project_dir(project_id) / "sources").exists()
    archive_root = workspace.project_dir(project_id) / "archive" / "revisions"
    assert any((item / "sources" / "stale.json").exists() for item in archive_root.iterdir())
