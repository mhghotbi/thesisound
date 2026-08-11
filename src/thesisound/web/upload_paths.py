"""Resolve uploaded source files under a project uploads tree."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from thesisound.pipeline import WorkspaceStore
from thesisound.web.source_manifest import UiSourceManifest


def resolve_uploaded_source_path(
    workspace: WorkspaceStore,
    project_id: UUID,
    source: UiSourceManifest,
) -> Path | None:
    """Return the upload path if it exists and stays under project uploads/.

    Prefers ``uploads/<source_id>/`` then ``uploads/web/<source_id>/``.
    Path traversal or a missing file yields ``None`` (caller maps to 404).
    """
    project_dir = workspace.project_dir(project_id).resolve()
    uploads_root = (project_dir / "uploads").resolve()
    filename = Path(source.filename).name
    if not filename or filename in {".", ".."}:
        return None

    candidates = [
        project_dir / "uploads" / str(source.source_id) / filename,
        project_dir / "uploads" / "web" / str(source.source_id) / filename,
    ]
    # Prefer local over web when both exist — match historical probe order,
    # but only return a path that actually is a file.
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        try:
            resolved.relative_to(uploads_root)
        except ValueError:
            return None
        return resolved
    return None
