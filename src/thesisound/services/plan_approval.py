from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field

from thesisound.domain import EpisodePlan, Project, ProjectState
from thesisound.services.lineage_events import emit_review_decision
from thesisound.services.script_artifact_store import ScriptArtifactStore


class EpisodePlanApproval(BaseModel):
    project_id: UUID
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EpisodePlanApprovalStore:
    """Persist explicit approval of the exact Episode Plan being scripted."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()

    def path(self, project_id: UUID) -> Path:
        return self.workspace_root / str(project_id) / "episode" / "plan-approval.json"

    def load(self, project_id: UUID) -> EpisodePlanApproval:
        path = self.path(project_id)
        if not path.exists():
            raise FileNotFoundError(f"Episode Plan approval not found: {project_id}")
        return EpisodePlanApproval.model_validate_json(path.read_text(encoding="utf-8"))

    def load_optional(self, project_id: UUID) -> EpisodePlanApproval | None:
        try:
            return self.load(project_id)
        except FileNotFoundError:
            return None

    def save(self, approval: EpisodePlanApproval) -> Path:
        payload = json.dumps(
            approval.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        path = self.path(approval.project_id)
        _atomic_write(path, payload)
        ScriptArtifactStore(self.workspace_root).prepare_for_plan(
            approval.project_id,
            approval.plan_hash,
        )
        return path

    def approve(self, project: Project, *, approved_by: str) -> EpisodePlanApproval:
        if project.state != ProjectState.EPISODE_PLANNED:
            raise ValueError("Only an EPISODE_PLANNED project can be approved.")
        if project.episode_plan is None:
            raise ValueError("EpisodePlan is required before approval.")
        actor = approved_by.strip()
        if not actor:
            raise ValueError("Approval actor is required.")
        approval = EpisodePlanApproval(
            project_id=project.project_id,
            plan_hash=episode_plan_hash(project.episode_plan),
            approved_by=actor,
        )
        self.save(approval)
        emit_review_decision(
            disposition="approved",
            subject_type="plan",
            subject_id=str(project.project_id),
            reviewer=actor,
            reason_code="plan_approval",
        )
        return approval

    def require_current(self, project: Project) -> EpisodePlanApproval:
        if project.episode_plan is None:
            raise ValueError("EpisodePlan is required before script generation.")
        try:
            approval = self.load(project.project_id)
        except FileNotFoundError as exc:
            raise ValueError(
                "The current Episode Plan has not been explicitly approved."
            ) from exc
        current_hash = episode_plan_hash(project.episode_plan)
        if approval.plan_hash != current_hash:
            raise ValueError(
                "Episode Plan changed after approval. Review and approve the current plan."
            )
        ScriptArtifactStore(self.workspace_root).prepare_for_plan(
            project.project_id,
            current_hash,
        )
        return approval

    def clear(self, project_id: UUID) -> None:
        self.path(project_id).unlink(missing_ok=True)


def episode_plan_hash(plan: EpisodePlan) -> str:
    payload = json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
