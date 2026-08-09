from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from thesisound.domain import ProjectState
from thesisound.pipeline import WorkspaceStore

RevisionTarget = Literal["brief", "sources"]
_ACTIVE_RUN_STATUSES = {"queued", "running"}
_RUN_POINTERS = (
    "corpus-build-run.json",
    "episode-planning-run.json",
    "script-build-run.json",
    "audio-build-run.json",
)
_DOWNSTREAM_PATHS = (
    "sources",
    "episode",
    "script",
    "audio",
    "runs",
    "model-runs",
    *_RUN_POINTERS,
)
# Per-source analysis survives a sources-scope rewind so a corpus rebuild can reuse the
# sources the user keeps. Every reuse is re-validated against the file and the current
# brief in `corpus_reuse.reusable_claim_ledger`, so nothing stale can slip through.
_SOURCE_SCOPE_KEPT_PATHS = ("sources",)


class WorkflowRevisionReceipt(BaseModel):
    project_id: UUID
    target: RevisionTarget
    actor: str
    reason: str | None = None
    previous_state: ProjectState
    new_state: ProjectState
    archived_paths: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkflowRevisionService:
    """Rewind editable inputs without allowing stale downstream reuse."""

    def __init__(self, workspace: WorkspaceStore) -> None:
        self.workspace = workspace

    def rewind(
        self,
        project_id: UUID,
        *,
        target: RevisionTarget,
        actor: str,
        reason: str | None = None,
    ) -> WorkflowRevisionReceipt:
        project = self.workspace.load_project(project_id)
        project_dir = self.workspace.project_dir(project_id)
        active = _active_run_labels(project_dir)
        if active:
            raise ValueError(
                "تا وقتی اجرای فعال متوقف یا تمام نشده نمی‌توان مرحله را عقب برد. "
                "اجرای فعال: " + "، ".join(active)
            )

        if target == "sources" and project.state == ProjectState.BRIEF_READY:
            raise ValueError("ابتدا برداشت پژوهش را تأیید کنید، سپس وارد منابع شوید.")

        previous_state = project.state
        archive_dir = _archive_directory(project_dir)
        archived_paths = _archive_downstream(
            project_dir,
            archive_dir,
            keep=() if target == "brief" else _SOURCE_SCOPE_KEPT_PATHS,
        )
        if target == "brief":
            candidate_path = project_dir / "web-search-candidates.json"
            if candidate_path.exists():
                archive_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(candidate_path), str(archive_dir / candidate_path.name))
                archived_paths.append(candidate_path.name)
            _reset_selected_sources(project_dir)
            project.state = ProjectState.BRIEF_READY
        else:
            project.state = (
                ProjectState.SOURCE_SELECTION_REQUIRED
                if _has_ready_source(project_dir)
                else ProjectState.SOURCES_COLLECTING
            )

        project.sources = []
        project.episode_plan = None
        project.script = None
        project.last_error = None
        project.updated_at = datetime.now(UTC)
        self.workspace.save_project(project)

        receipt = WorkflowRevisionReceipt(
            project_id=project_id,
            target=target,
            actor=actor,
            reason=reason.strip() if reason and reason.strip() else None,
            previous_state=previous_state,
            new_state=project.state,
            archived_paths=archived_paths,
        )
        if archived_paths:
            archive_dir.mkdir(parents=True, exist_ok=True)
            (archive_dir / "revision.json").write_text(
                receipt.model_dump_json(indent=2),
                encoding="utf-8",
            )
        return receipt


def _active_run_labels(project_dir: Path) -> list[str]:
    active: list[str] = []
    for filename in _RUN_POINTERS:
        path = project_dir / filename
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("status") in _ACTIVE_RUN_STATUSES:
            active.append(filename.removesuffix(".json"))
    return active


def _archive_directory(project_dir: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return project_dir / "archive" / "revisions" / stamp


def _archive_downstream(
    project_dir: Path,
    archive_dir: Path,
    *,
    keep: tuple[str, ...] = (),
) -> list[str]:
    archived: list[str] = []
    for relative in _DOWNSTREAM_PATHS:
        if relative in keep:
            continue
        source = project_dir / relative
        if not source.exists():
            continue
        archive_dir.mkdir(parents=True, exist_ok=True)
        destination = archive_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        archived.append(relative)
    return archived


def _manifest_payload(project_dir: Path) -> list[dict[str, object]]:
    path = project_dir / "ui-source-manifest.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def _has_ready_source(project_dir: Path) -> bool:
    return any(item.get("status") == "ready" for item in _manifest_payload(project_dir))


def _reset_selected_sources(project_dir: Path) -> None:
    path = project_dir / "ui-source-manifest.json"
    payload = _manifest_payload(project_dir)
    if not payload or not path.exists():
        return
    for item in payload:
        item["selected"] = False
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
