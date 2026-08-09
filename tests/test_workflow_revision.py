from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from thesisound.domain import (
    Project,
    ProjectState,
    ResearchBrief,
    SourceAccess,
    SourceCandidate,
    SourceDecision,
    SourceRole,
    TopicType,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.workflow_revision import WorkflowRevisionService


def _project() -> Project:
    return Project(
        raw_input="اخلاق کانت",
        state=ProjectState.FAILED_RETRYABLE,
        brief=ResearchBrief(
            normalized_topic="اخلاق کانت",
            topic_type=TopicType.CONCEPT,
            central_question="اخلاق کانت چگونه کار می‌کند؟",
        ),
        sources=[
            SourceCandidate(
                source_id=uuid4(),
                title="Kant source",
                role=SourceRole.REFERENCE,
                source_type="web",
                origin="gemini_web_search",
                access=SourceAccess.FULL_TEXT,
                user_decision=SourceDecision.INCLUDE,
            )
        ],
        last_error="mapping failed",
    )


def _seed_workspace(tmp_path: Path) -> tuple[WorkspaceStore, Project]:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    workspace.save_project(project)
    project_dir = workspace.project_dir(project.project_id)
    (project_dir / "uploads" / "raw").mkdir(parents=True)
    (project_dir / "uploads" / "raw" / "source.txt").write_text(
        "raw source",
        encoding="utf-8",
    )
    for relative in ("sources", "episode", "script", "audio", "runs"):
        directory = project_dir / relative
        directory.mkdir(parents=True)
        (directory / "artifact.json").write_text("{}", encoding="utf-8")
    (project_dir / "corpus-build-run.json").write_text(
        json.dumps({"status": "failed"}),
        encoding="utf-8",
    )
    (project_dir / "ui-source-manifest.json").write_text(
        json.dumps(
            [
                {
                    "source_id": str(uuid4()),
                    "filename": "source.txt",
                    "size_bytes": 10,
                    "status": "ready",
                    "selected": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    return workspace, project


def test_rewind_to_sources_archives_downstream_and_preserves_raw_inputs(
    tmp_path: Path,
) -> None:
    workspace, project = _seed_workspace(tmp_path)
    service = WorkflowRevisionService(workspace)

    receipt = service.rewind(
        project.project_id,
        target="sources",
        actor="09120000000",
        reason="اصلاح منبع پس از خطا",
    )

    current = workspace.load_project(project.project_id)
    project_dir = workspace.project_dir(project.project_id)
    assert current.state == ProjectState.SOURCE_SELECTION_REQUIRED
    assert current.sources == []
    assert current.last_error is None
    assert (project_dir / "uploads" / "raw" / "source.txt").exists()
    # Per-source analysis stays put; a rebuild re-validates each source before reusing it.
    assert (project_dir / "sources" / "artifact.json").exists()
    assert "sources" not in receipt.archived_paths
    assert not (project_dir / "episode").exists()
    assert not (project_dir / "corpus-build-run.json").exists()
    archive = next((project_dir / "archive" / "revisions").iterdir())
    assert (archive / "episode" / "artifact.json").exists()
    assert (archive / "revision.json").exists()
    manifest = json.loads((project_dir / "ui-source-manifest.json").read_text())
    assert manifest[0]["selected"] is True


def test_rewind_to_brief_resets_selection_and_invalidates_search_results(
    tmp_path: Path,
) -> None:
    workspace, project = _seed_workspace(tmp_path)
    project_dir = workspace.project_dir(project.project_id)
    (project_dir / "web-search-candidates.json").write_text("[]", encoding="utf-8")

    WorkflowRevisionService(workspace).rewind(
        project.project_id,
        target="brief",
        actor="09120000000",
    )

    current = workspace.load_project(project.project_id)
    assert current.state == ProjectState.BRIEF_READY
    manifest = json.loads((project_dir / "ui-source-manifest.json").read_text())
    assert manifest[0]["selected"] is False
    assert not (project_dir / "web-search-candidates.json").exists()


def test_rewind_to_brief_keeps_analysis_for_the_reuse_check_to_judge(
    tmp_path: Path,
) -> None:
    """Whether an edited brief invalidates the analysis is not knowable yet.

    Deciding here would have to assume the worst; `reusable_claim_ledger` decides later
    with the edited brief actually in hand.
    """

    workspace, project = _seed_workspace(tmp_path)
    project_dir = workspace.project_dir(project.project_id)

    receipt = WorkflowRevisionService(workspace).rewind(
        project.project_id,
        target="brief",
        actor="09120000000",
    )

    assert (project_dir / "sources" / "artifact.json").exists()
    assert "sources" not in receipt.archived_paths
    # Everything downstream of the analysis still goes, on both rewind targets.
    assert not (project_dir / "episode").exists()
    assert not (project_dir / "script").exists()
    assert not (project_dir / "audio").exists()
    archive = next((project_dir / "archive" / "revisions").iterdir())
    assert (archive / "episode" / "artifact.json").exists()


def test_rewind_keeps_the_model_run_trail_that_manifests_point_at(
    tmp_path: Path,
) -> None:
    """A surviving claim must stay traceable back to the prompt that produced it."""

    workspace, project = _seed_workspace(tmp_path)
    store = WorkspaceModelRunStore(workspace.root)
    run_id = uuid4()
    run_dir = store.run_dir(project.project_id, run_id)
    run_dir.mkdir(parents=True)
    (run_dir / "record.json").write_text(
        json.dumps({"stage": "evidence_extraction"}),
        encoding="utf-8",
    )

    receipt = WorkflowRevisionService(workspace).rewind(
        project.project_id,
        target="brief",
        actor="09120000000",
    )

    assert "model-runs" not in receipt.archived_paths
    assert (store.run_dir(project.project_id, run_id) / "record.json").exists()


def test_rewind_rejects_an_active_run(tmp_path: Path) -> None:
    workspace, project = _seed_workspace(tmp_path)
    project_dir = workspace.project_dir(project.project_id)
    (project_dir / "script-build-run.json").write_text(
        json.dumps({"status": "running"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="اجرای فعال"):
        WorkflowRevisionService(workspace).rewind(
            project.project_id,
            target="sources",
            actor="09120000000",
        )

    assert workspace.load_project(project.project_id).state == ProjectState.FAILED_RETRYABLE
    assert (project_dir / "sources" / "artifact.json").exists()
