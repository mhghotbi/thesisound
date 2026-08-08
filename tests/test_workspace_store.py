from datetime import UTC, datetime, timedelta
from pathlib import Path

from thesisound.domain import Project
from thesisound.pipeline import WorkspaceStore


def test_list_projects_orders_by_recent_update(tmp_path: Path) -> None:
    store = WorkspaceStore(tmp_path)
    older = Project(raw_input="older")
    newer = Project(raw_input="newer")
    older.updated_at = datetime.now(UTC) - timedelta(days=1)
    newer.updated_at = datetime.now(UTC)

    store.save_project(older)
    store.save_project(newer)

    assert [project.raw_input for project in store.list_projects()] == ["newer", "older"]
