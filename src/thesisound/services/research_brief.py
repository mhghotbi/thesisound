from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from thesisound.domain import ProjectState, ResearchBrief
from thesisound.modeling import DeterministicValidationError, ModelError, ModelExecution
from thesisound.pipeline import WorkspaceStore, mark_failed, transition
from thesisound.services.model_runner import ModelRunner

PriorKnowledge = Literal["none", "introductory", "intermediate", "advanced"]
BriefMode = Literal["explanatory", "critical", "comparative", "debate"]


class ResearchBriefService:
    def __init__(self, workspace_store: WorkspaceStore, model_runner: ModelRunner) -> None:
        self.workspace_store = workspace_store
        self.model_runner = model_runner

    def build(
        self,
        project_id: UUID,
        *,
        model: str,
        audience: str = "educated general listener",
        prior_knowledge: PriorKnowledge = "introductory",
        target_duration_minutes: int = 30,
        modes: list[BriefMode] | None = None,
        output_language: str = "fa",
        file_metadata: list[dict[str, object]] | None = None,
        prompt_version: str | None = None,
    ) -> ModelExecution[ResearchBrief]:
        project = self.workspace_store.load_project(project_id)
        if project.state not in {
            ProjectState.DRAFT,
            ProjectState.BRIEF_READY,
            ProjectState.FAILED_RETRYABLE,
        }:
            raise ValueError(f"Cannot build a research brief from state {project.state}.")
        if project.state == ProjectState.FAILED_RETRYABLE and project.brief is not None:
            raise ValueError("The failed project has already progressed beyond brief creation.")

        requested_modes = modes or ["explanatory"]
        variables = {
            "raw_user_input": project.raw_input,
            "audience": audience,
            "prior_knowledge": prior_knowledge,
            "target_duration_minutes": target_duration_minutes,
            "modes": requested_modes,
            "output_language": output_language,
            "file_metadata": file_metadata or [],
        }

        def validate(brief: ResearchBrief) -> None:
            _validate_brief(
                brief,
                requested_duration=target_duration_minutes,
                requested_modes=requested_modes,
                output_language=output_language,
            )

        try:
            execution = self.model_runner.run(
                project_id=project.project_id,
                stage="research_brief",
                prompt_name="research_brief",
                variables=variables,
                output_type=ResearchBrief,
                model=model,
                prompt_version=prompt_version,
                validator=validate,
            )
        except ModelError as exc:
            if project.state != ProjectState.FAILED_RETRYABLE:
                mark_failed(project, str(exc))
            else:
                project.last_error = str(exc)
                project.updated_at = datetime.now(UTC)
            self.workspace_store.save_project(project)
            raise

        project.brief = execution.output
        if project.state in {ProjectState.DRAFT, ProjectState.FAILED_RETRYABLE}:
            transition(project, ProjectState.BRIEF_READY)
        else:
            project.updated_at = datetime.now(UTC)
            project.last_error = None
        self.workspace_store.save_project(project)
        return execution


def _validate_brief(
    brief: ResearchBrief,
    *,
    requested_duration: int,
    requested_modes: list[BriefMode],
    output_language: str,
) -> None:
    if not brief.normalized_topic.strip():
        raise DeterministicValidationError("normalized_topic must not be empty.")
    if not brief.central_question.strip():
        raise DeterministicValidationError("central_question must not be empty.")
    if not 2 <= len(brief.learning_objectives) <= 5:
        raise DeterministicValidationError("learning_objectives must contain 2 to 5 items.")
    normalized_objectives = {
        " ".join(objective.casefold().split()) for objective in brief.learning_objectives
    }
    if len(normalized_objectives) != len(brief.learning_objectives):
        raise DeterministicValidationError("learning_objectives must not contain duplicates.")
    if brief.target_duration_minutes != requested_duration:
        raise DeterministicValidationError(
            "target_duration_minutes must preserve the user's requested duration."
        )
    if brief.output_language != output_language:
        raise DeterministicValidationError("output_language must preserve the requested language.")
    missing_modes = set(requested_modes) - set(brief.modes)
    if missing_modes:
        raise DeterministicValidationError(
            f"The brief omitted requested modes: {', '.join(sorted(missing_modes))}."
        )
