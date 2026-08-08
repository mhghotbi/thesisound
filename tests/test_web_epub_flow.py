from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from fastapi.testclient import TestClient

from thesisound.config import Settings
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
            "topic": "کنش نزد آرنت",
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
            "central_question": "کنش نزد آرنت چه معنایی دارد؟",
            "must_include": "",
            "exclusions": "",
            "action": "confirm",
        },
    )
    return project_id


def _epub_bytes() -> bytes:
    output = BytesIO()
    container = """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
      <rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles>
    </container>"""
    package = """<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
      <manifest>
        <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
      </manifest>
      <spine><itemref idref="chapter"/></spine>
    </package>"""
    text = " ".join(["این فصل ساختار کنش و آزادی سیاسی را توضیح می‌دهد."] * 12)
    chapter = f"""<html xmlns="http://www.w3.org/1999/xhtml"><body>
      <h1>فصل اول</h1><p>{text}</p>
    </body></html>"""
    with ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr("META-INF/container.xml", container, compress_type=ZIP_DEFLATED)
        archive.writestr("OPS/package.opf", package, compress_type=ZIP_DEFLATED)
        archive.writestr("OPS/chapter.xhtml", chapter, compress_type=ZIP_DEFLATED)
    return output.getvalue()


def test_web_upload_accepts_and_parses_epub(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        project_id = _create_project(client)
        page = client.get(f"/projects/{project_id}/sources")
        assert ".epub" in page.text
        response = client.post(
            f"/projects/{project_id}/sources/upload",
            data={"csrf_token": _csrf(page.text)},
            files={
                "source_file": (
                    "arendt.epub",
                    _epub_bytes(),
                    "application/epub+zip",
                )
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    workspace = WorkspaceStore(settings.workspace_root)
    source = UiSourceManifestStore(workspace.project_dir(project_id)).load()[0]
    assert source.status == UiSourceStatus.READY
    assert source.parser_name == "epub"
    assert source.safe_for_claim_extraction is True
    assert source.block_count == 2
    assert source.text_characters > 200
