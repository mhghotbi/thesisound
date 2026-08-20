"""`/projects/{id}/lesson/{part}` (`10c` P4)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from thesisound.domain import (
    DeliveryMode,
    Project,
    ProjectState,
    ResearchBrief,
    Script,
    ScriptTurn,
    TopicType,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.web.app import create_app

from test_web_report import _login, _settings


def _project(*, delivery: DeliveryMode) -> Project:
    return Project(
        raw_input="موضوع",
        state=ProjectState.COMPLETE,
        delivery=delivery,
        brief=ResearchBrief(
            normalized_topic="موضوع",
            topic_type=TopicType.CONCEPT,
            central_question="سؤال؟",
            target_duration_minutes=10,
        ),
    )


def test_text_delivery_lesson_page_renders_paragraphs(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project(delivery=DeliveryMode.TEXT)
    workspace.save_project(project)
    ScriptArtifactStore(settings.workspace_root).save_script(
        project.project_id,
        Script(
            title="عنوان درس",
            turns=[
                ScriptTurn(
                    turn_id="seg-001-turn-001",
                    segment_id="seg-001",
                    speaker="A",
                    spoken_text_fa="این نخستین پاراگراف درس نوشتاری است.",
                    editorial_only=True,
                ),
            ],
        ),
    )

    app = create_app(
        settings, corpus_executor=lambda _: None,
        episode_executor=lambda _: None, script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/lesson/1")
        export = client.get(f"/projects/{project.project_id}/lesson/1/export.md")

    assert page.status_code == 200
    assert "این نخستین پاراگراف درس نوشتاری است." in page.text
    assert export.status_code == 200
    assert "این نخستین پاراگراف درس نوشتاری است." in export.text
    assert export.headers["content-type"].startswith("text/markdown")


def test_audio_delivery_project_has_no_written_lesson(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project(delivery=DeliveryMode.AUDIO)
    workspace.save_project(project)

    app = create_app(
        settings, corpus_executor=lambda _: None,
        episode_executor=lambda _: None, script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/lesson/1")

    assert page.status_code == 200
    assert "نسخهٔ نوشتاری ندارد" in page.text
