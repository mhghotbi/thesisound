"""The memo in front of the gates must never outlive the artifacts it read.

Caching a readiness verdict is caching the one thing this phase exists to keep honest,
so the key is checked here from both directions: it holds across a repeat read of an
untouched project, and it lets go the moment anything the gates can see moves.
"""

from __future__ import annotations

from pathlib import Path

from thesisound.domain import Project, ProjectState, ResearchBrief, TopicType
from thesisound.pipeline import WorkspaceStore
from thesisound.services import readiness_cache
from thesisound.services.readiness_cache import cached_project_readiness, clear_cache


def _project(state: ProjectState = ProjectState.BRIEF_READY) -> Project:
    return Project(
        raw_input="topic",
        state=state,
        brief=ResearchBrief(
            normalized_topic="topic",
            topic_type=TopicType.CONCEPT,
            central_question="What is the argument?",
            target_duration_minutes=10,
        ),
    )


def _statuses(results) -> dict[str, str]:
    return {result.code: result.status for result in results}


def test_a_repeat_read_of_an_untouched_project_is_served_from_the_memo(
    tmp_path: Path,
    monkeypatch,
) -> None:
    clear_cache()
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    project = _project()
    workspace.save_project(project)

    calls = {"count": 0}
    real = readiness_cache.project_readiness

    def counted(**kwargs):
        calls["count"] += 1
        return real(**kwargs)

    monkeypatch.setattr(readiness_cache, "project_readiness", counted)

    first = cached_project_readiness(
        project_id=project.project_id,
        workspace_root=root,
        updated_at=project.updated_at,
    )
    second = cached_project_readiness(
        project_id=project.project_id,
        workspace_root=root,
        updated_at=project.updated_at,
    )

    assert calls["count"] == 1
    assert first is second


def test_a_state_change_is_never_served_from_the_memo(tmp_path: Path) -> None:
    """`updated_at` is content, not a file timestamp, so it survives a coarse clock."""
    clear_cache()
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    project = _project()
    workspace.save_project(project)

    before = cached_project_readiness(
        project_id=project.project_id,
        workspace_root=root,
        updated_at=project.updated_at,
    )
    assert _statuses(before)["brief-confirmed"] == "blocked"

    project.state = ProjectState.SOURCES_COLLECTING
    workspace.save_project(project)

    after = cached_project_readiness(
        project_id=project.project_id,
        workspace_root=root,
        updated_at=workspace.load_project(project.project_id).updated_at,
    )
    assert _statuses(after)["brief-confirmed"] == "pass"


def test_an_artifact_written_beside_the_project_invalidates_the_memo(tmp_path: Path) -> None:
    """Not every gate input goes through `save_project`; the directory half catches those."""
    clear_cache()
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    project = _project(ProjectState.SOURCES_COLLECTING)
    workspace.save_project(project)

    before = cached_project_readiness(
        project_id=project.project_id,
        workspace_root=root,
        updated_at=project.updated_at,
    )

    source_dir = workspace.project_dir(project.project_id) / "sources" / "one"
    source_dir.mkdir(parents=True)
    (source_dir / "ingestion-result.json").write_text("{ broken", encoding="utf-8")

    after = cached_project_readiness(
        project_id=project.project_id,
        workspace_root=root,
        updated_at=project.updated_at,
    )
    assert after is not before
    assert _statuses(after) != _statuses(before)


def test_the_append_only_trees_do_not_churn_the_memo(tmp_path: Path) -> None:
    """`model-runs` grows on every call and the gates never read it."""
    clear_cache()
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    project = _project()
    workspace.save_project(project)
    project_dir = workspace.project_dir(project.project_id)

    before = readiness_cache._directory_fingerprint(project_dir)
    runs = project_dir / "model-runs"
    runs.mkdir(parents=True)
    (runs / "call-1.json").write_text("{}" * 500, encoding="utf-8")

    assert readiness_cache._directory_fingerprint(project_dir) == before
