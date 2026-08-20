from __future__ import annotations

from datetime import UTC, datetime
from json import dumps
from pathlib import Path
from uuid import UUID

from thesisound import tracing
from thesisound.domain import Project, ProjectState
from thesisound.product_metrics import ProductEvent, emit
from thesisound.product_metrics.catalogue import stage_for_state
from thesisound.product_metrics.emit import classify_error
from thesisound.product_metrics.events import (
    ProjectRecovered,
    ProjectStageEntered,
    ProjectStageFailed,
    ProjectTransitionRejected,
)

ALLOWED_TRANSITIONS: dict[ProjectState, set[ProjectState]] = {
    ProjectState.DRAFT: {ProjectState.BRIEF_READY, ProjectState.FAILED_RETRYABLE},
    ProjectState.BRIEF_READY: {
        ProjectState.SOURCES_COLLECTING,
        ProjectState.FAILED_RETRYABLE,
    },
    ProjectState.SOURCES_COLLECTING: {
        ProjectState.SOURCE_SELECTION_REQUIRED,
        ProjectState.FAILED_RETRYABLE,
    },
    ProjectState.SOURCE_SELECTION_REQUIRED: {
        ProjectState.CORPUS_BUILDING,
        ProjectState.SOURCES_COLLECTING,
    },
    ProjectState.CORPUS_BUILDING: {
        ProjectState.CORPUS_READY,
        ProjectState.FAILED_RETRYABLE,
        ProjectState.FAILED_PERMANENT,
    },
    ProjectState.CORPUS_READY: {
        ProjectState.EPISODE_PLANNING,
        ProjectState.SOURCES_COLLECTING,
    },
    ProjectState.EPISODE_PLANNING: {
        ProjectState.EPISODE_PLANNED,
        ProjectState.SOURCES_COLLECTING,
        ProjectState.FAILED_RETRYABLE,
    },
    ProjectState.EPISODE_PLANNED: {
        ProjectState.SCRIPT_DRAFTING,
        ProjectState.EPISODE_PLANNING,
    },
    ProjectState.SCRIPT_DRAFTING: {
        ProjectState.SCRIPT_READY,
        ProjectState.FAILED_RETRYABLE,
    },
    ProjectState.SCRIPT_READY: {
        ProjectState.SCRIPT_VERIFYING,
        ProjectState.SCRIPT_DRAFTING,
    },
    ProjectState.SCRIPT_VERIFYING: {
        ProjectState.SCRIPT_VERIFIED,
        ProjectState.SCRIPT_REVIEW_REQUIRED,
        ProjectState.SCRIPT_DRAFTING,
        ProjectState.FAILED_RETRYABLE,
    },
    ProjectState.SCRIPT_REVIEW_REQUIRED: {
        ProjectState.SCRIPT_VERIFIED,
        ProjectState.SCRIPT_DRAFTING,
        ProjectState.FAILED_RETRYABLE,
    },
    ProjectState.SCRIPT_VERIFIED: {
        ProjectState.AUDIO_GENERATING,
        # `delivery == text` projects skip audio entirely; ScriptPipelineService.run()
        # makes this transition directly once the script is verified.
        ProjectState.COMPLETE,
        ProjectState.FAILED_RETRYABLE,
    },
    ProjectState.AUDIO_GENERATING: {
        ProjectState.AUDIO_READY,
        ProjectState.FAILED_RETRYABLE,
    },
    ProjectState.AUDIO_READY: {
        ProjectState.AUDIO_VERIFYING,
        ProjectState.AUDIO_GENERATING,
    },
    ProjectState.AUDIO_VERIFYING: {
        ProjectState.COMPLETE,
        ProjectState.AUDIO_GENERATING,
        ProjectState.FAILED_RETRYABLE,
    },
    ProjectState.COMPLETE: {ProjectState.FAILED_RETRYABLE},
    ProjectState.FAILED_RETRYABLE: {
        ProjectState.BRIEF_READY,
        ProjectState.SOURCES_COLLECTING,
        ProjectState.CORPUS_BUILDING,
        ProjectState.EPISODE_PLANNING,
        ProjectState.SCRIPT_DRAFTING,
        ProjectState.SCRIPT_VERIFYING,
        ProjectState.AUDIO_GENERATING,
        ProjectState.AUDIO_VERIFYING,
        ProjectState.FAILED_PERMANENT,
    },
    ProjectState.FAILED_PERMANENT: set(),
}


class InvalidTransitionError(ValueError):
    pass


def transition(
    project: Project,
    target: ProjectState,
    *,
    actor_user_id: int | None = None,
) -> Project:
    """Move a project to a valid next state and update its timestamp."""

    allowed = ALLOWED_TRANSITIONS[project.state]
    previous = project.state
    if target not in allowed:
        tracing.event(
            "project.transition_rejected",
            component="pipeline",
            level="warn",
            project_id=project.project_id,
            previous=previous.value,
            attempted=target.value,
        )
        emit(
            ProductEvent.PROJECT_TRANSITION_REJECTED,
            ProjectTransitionRejected(
                from_state=previous.value,
                attempted_state=target.value,
            ),
            user_id=actor_user_id,
            project_id=project.project_id,
        )
        raise InvalidTransitionError(f"Cannot transition from {project.state} to {target}")

    now = datetime.now(UTC)
    failed_for_seconds = 0
    if previous == ProjectState.FAILED_RETRYABLE:
        failed_for_seconds = max(0, int((now - project.updated_at).total_seconds()))

    from_stage = stage_for_state(previous)
    to_stage = stage_for_state(target)

    project.state = target
    project.updated_at = now
    if target not in {ProjectState.FAILED_RETRYABLE, ProjectState.FAILED_PERMANENT}:
        project.last_error = None
    tracing.event(
        "project.state_changed",
        component="pipeline",
        project_id=project.project_id,
        previous=previous.value,
        current=target.value,
    )

    if target in {ProjectState.FAILED_RETRYABLE, ProjectState.FAILED_PERMANENT}:
        fail_stage = from_stage if from_stage is not None else (to_stage or 1)
        emit(
            ProductEvent.PROJECT_STAGE_FAILED,
            ProjectStageFailed(
                stage=fail_stage,
                state=target.value,
                permanent=target == ProjectState.FAILED_PERMANENT,
                error_class=classify_error(project.last_error),
            ),
            user_id=actor_user_id,
            project_id=project.project_id,
        )
    if previous == ProjectState.FAILED_RETRYABLE and target not in {
        ProjectState.FAILED_RETRYABLE,
        ProjectState.FAILED_PERMANENT,
    }:
        recovered_stage = to_stage if to_stage is not None else (from_stage or 1)
        emit(
            ProductEvent.PROJECT_RECOVERED,
            ProjectRecovered(stage=recovered_stage, failed_for_seconds=failed_for_seconds),
            user_id=actor_user_id,
            project_id=project.project_id,
        )
    if to_stage is not None and to_stage != from_stage:
        emit(
            ProductEvent.PROJECT_STAGE_ENTERED,
            ProjectStageEntered(
                stage=to_stage,
                from_stage=from_stage,
                state=target.value,
                from_state=previous.value,
            ),
            user_id=actor_user_id,
            project_id=project.project_id,
        )
    return project


def mark_failed(
    project: Project,
    message: str,
    *,
    permanent: bool = False,
    actor_user_id: int | None = None,
) -> Project:
    target = ProjectState.FAILED_PERMANENT if permanent else ProjectState.FAILED_RETRYABLE
    project.last_error = message
    return transition(project, target, actor_user_id=actor_user_id)

class WorkspaceStore:
    """Simple JSON store for the CLI-first prototype.

    This is intentionally not a production repository implementation. It gives the
    core pipeline an inspectable artifact trail before a database is introduced.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: UUID | str) -> Path:
        return self.root / str(project_id)

    def save_project(self, project: Project) -> Path:
        directory = self.project_dir(project.project_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "project.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            dumps(project.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
        return path

    def load_project(self, project_id: UUID | str) -> Project:
        path = self.project_dir(project_id) / "project.json"
        if not path.exists():
            raise FileNotFoundError(f"Project not found: {project_id}")
        return Project.model_validate_json(path.read_text(encoding="utf-8"))

    def list_projects(self) -> list[Project]:
        projects: list[Project] = []
        for path in self.root.glob("*/project.json"):
            try:
                projects.append(Project.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(projects, key=lambda project: project.updated_at, reverse=True)
