from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from thesisound.adapters.fetch.trafilatura import UrlFetchError, UrlFetchResult
from thesisound.config import Settings
from thesisound.domain import Project, ProjectState, ResearchBrief, TopicType
from thesisound.pipeline import WorkspaceStore
from thesisound.services.url_probe import UrlProbeResult
from thesisound.web import source_url_import
from thesisound.web.app import create_app
from thesisound.web.source_manifest import UiSourceManifestStore, UiSourceStatus
from thesisound.web.source_url_import import UrlSourceImportService


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "workspace_root": tmp_path / "workspaces",
        "ingestion_artifact_root": tmp_path / "artifacts",
        "observability_database_path": tmp_path / "observability.sqlite3",
        "web_session_secret": "test-secret-that-is-long-enough",
        "allow_test_otp": True,
        "test_otp_phone": "09120000000",
        "test_otp_code": "999999",
        "otp_resend_cooldown_seconds": 5,
        "ui_demo_mode": False,
        "web_secure_cookies": False,
        "url_probe_enabled": False,
        "url_source_fetch_enabled": True,
        "web_source_discovery_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _project() -> Project:
    return Project(
        raw_input="اخلاق کانت",
        brief=ResearchBrief(
            normalized_topic="اخلاق کانت",
            topic_type=TopicType.CONCEPT,
            central_question="اخلاق کانت چگونه کار می‌کند؟",
        ),
    )


def _long_markdown(*, title: str = "مقاله آزمون") -> str:
    body = (
        "این متن کامل یک منبع وب برای آزمون بازیابی، استخراج، کنترل کیفیت و ردیابی شواهد است. "
    ) * 12
    return f"# {title}\n\n{body}\n"


def _fetch_result(*, title: str = "مقاله آزمون", markdown: str | None = None) -> UrlFetchResult:
    text = markdown or _long_markdown(title=title)
    return UrlFetchResult(
        title=title,
        markdown=text,
        canonical_url="https://example.com/article",
        text_characters=len(text),
    )


def test_full_url_fetch_is_parsed_and_selected(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()
    workspace.save_project(project)
    monkeypatch.setattr(
        source_url_import,
        "fetch_and_extract_url",
        lambda *_args, **_kwargs: _fetch_result(),
    )

    manifest = UrlSourceImportService(settings, workspace).import_url(
        project.project_id,
        "https://example.com/article",
    )

    assert manifest.status == UiSourceStatus.READY
    assert manifest.selected
    assert manifest.safe_for_claim_extraction
    assert manifest.origin == "url_fetch"
    assert manifest.canonical_url == "https://example.com/article"
    assert manifest.retrieval_scope == "full_text"
    assert manifest.artifact_ref is not None
    assert (
        settings.ingestion_artifact_root
        / str(project.project_id)
        / str(manifest.source_id)
        / manifest.artifact_ref
    ).exists()


def test_dead_url_is_blocked_before_fetch(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, url_probe_enabled=True)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()
    workspace.save_project(project)
    calls: list[str] = []

    monkeypatch.setattr(
        source_url_import,
        "probe_url",
        lambda *_args, **_kwargs: UrlProbeResult(
            "https://example.com/dead", "dead", 404, "HTTP 404"
        ),
    )

    def _unexpected(*_args: object, **_kwargs: object) -> UrlFetchResult:
        calls.append("fetch")
        raise AssertionError("fetch should not run after a dead probe")

    monkeypatch.setattr(source_url_import, "fetch_and_extract_url", _unexpected)

    manifest = UrlSourceImportService(settings, workspace).import_url(
        project.project_id,
        "https://example.com/dead",
    )

    assert manifest.status == UiSourceStatus.BLOCKED
    assert manifest.origin == "url_fetch"
    assert calls == []


def test_empty_extract_is_blocked(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()
    workspace.save_project(project)

    def _fail(*_args: object, **_kwargs: object) -> UrlFetchResult:
        raise UrlFetchError("extracted text was empty")

    monkeypatch.setattr(source_url_import, "fetch_and_extract_url", _fail)

    manifest = UrlSourceImportService(settings, workspace).import_url(
        project.project_id,
        "https://example.com/empty",
    )

    assert manifest.status == UiSourceStatus.BLOCKED
    assert manifest.retrieval_scope == "unavailable"
    assert "بازیابی نشد" in (manifest.issue_summary or "")


def test_short_extract_is_blocked(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, url_fetch_min_characters=400)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()
    workspace.save_project(project)
    short = "# کوتاه\n\nمتن کوتاه.\n"
    monkeypatch.setattr(
        source_url_import,
        "fetch_and_extract_url",
        lambda *_args, **_kwargs: UrlFetchResult(
            title="کوتاه",
            markdown=short,
            canonical_url="https://example.com/short",
            text_characters=len(short),
        ),
    )

    manifest = UrlSourceImportService(settings, workspace).import_url(
        project.project_id,
        "https://example.com/short",
    )

    assert manifest.status == UiSourceStatus.BLOCKED
    assert manifest.retrieval_scope == "partial_text"


def test_url_fetch_flag_off_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path, url_source_fetch_enabled=False)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()
    workspace.save_project(project)

    try:
        UrlSourceImportService(settings, workspace).import_url(
            project.project_id,
            "https://example.com/article",
        )
    except ValueError as error:
        assert "در دسترس نیست" in str(error)
    else:
        raise AssertionError("expected ValueError when url fetch is disabled")


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


def test_from_url_route_imports_source(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(
        "thesisound.web.source_url_import.fetch_and_extract_url",
        lambda *_args, **_kwargs: _fetch_result(),
    )
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        project_id = _create_and_confirm(client)
        sources = client.get(f"/projects/{project_id}/sources")
        assert "sources/from-url" in sources.text
        response = client.post(
            f"/projects/{project_id}/sources/from-url",
            data={
                "csrf_token": _csrf(sources.text),
                "url": "https://example.com/article",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        page = client.get(f"/projects/{project_id}/sources")
        assert "منبع از نشانی وب" in page.text
        assert "https://example.com/article" in page.text


def test_from_url_route_disabled(tmp_path: Path) -> None:
    settings = _settings(tmp_path, url_source_fetch_enabled=False)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        project_id = _create_and_confirm(client)
        sources = client.get(f"/projects/{project_id}/sources")
        assert "sources/from-url" not in sources.text
        response = client.post(
            f"/projects/{project_id}/sources/from-url",
            data={
                "csrf_token": _csrf(sources.text),
                "url": "https://example.com/article",
            },
            follow_redirects=False,
        )
        assert response.status_code == 422
        assert "در دسترس نیست" in response.text


def test_from_url_blocked_import_keeps_selection_when_ready_source_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, url_fetch_min_characters=400)
    short = "# کوتاه\n\nمتن کوتاه.\n"
    monkeypatch.setattr(
        "thesisound.web.source_url_import.fetch_and_extract_url",
        lambda *_args, **_kwargs: UrlFetchResult(
            title="کوتاه",
            markdown=short,
            canonical_url="https://example.com/short",
            text_characters=len(short),
        ),
    )
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        project_id = _create_and_confirm(client)
        sources = client.get(f"/projects/{project_id}/sources")
        source_text = ("این یک منبع واقعی برای آزمون استخراج و کنترل کیفیت است. " * 12).encode()
        client.post(
            f"/projects/{project_id}/sources/upload",
            data={"csrf_token": _csrf(sources.text)},
            files={"source_file": ("kant.txt", source_text, "text/plain")},
        )
        workspace = WorkspaceStore(settings.workspace_root)
        assert workspace.load_project(project_id).state == ProjectState.SOURCE_SELECTION_REQUIRED

        sources = client.get(f"/projects/{project_id}/sources")
        response = client.post(
            f"/projects/{project_id}/sources/from-url",
            data={
                "csrf_token": _csrf(sources.text),
                "url": "https://example.com/short",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    project = workspace.load_project(project_id)
    assert project.state == ProjectState.SOURCE_SELECTION_REQUIRED
    manifests = UiSourceManifestStore(workspace.project_dir(project_id)).load()
    assert any(item.status == UiSourceStatus.READY for item in manifests)
    assert any(item.status == UiSourceStatus.BLOCKED for item in manifests)
