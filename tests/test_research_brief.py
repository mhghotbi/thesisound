from __future__ import annotations

from pathlib import Path

from thesisound.domain import Project, ProjectState, ResearchBrief, TopicType
from thesisound.modeling import ModelUsage, StructuredModelResponse
from thesisound.pipeline import WorkspaceStore
from thesisound.ports import RunMetadata
from thesisound.prompt_loader import PromptLoader
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner
from thesisound.services.research_brief import ResearchBriefService


class BriefModel:
    provider = "fake"

    def __init__(self, outputs: list[ResearchBrief]) -> None:
        self.outputs = outputs
        self.prompts: list[str] = []

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_type: type[ResearchBrief],
        model: str,
        metadata: RunMetadata,
    ) -> StructuredModelResponse[ResearchBrief]:
        _ = system_prompt, output_type, model, metadata
        self.prompts.append(user_prompt)
        output = self.outputs.pop(0)
        return StructuredModelResponse[ResearchBrief](
            output=output,
            provider=self.provider,
            model="fake",
            usage=ModelUsage(input_tokens=20, output_tokens=10, total_tokens=30),
            latency_ms=10,
            finish_reason="STOP",
        )


def _brief(*, objectives: list[str] | None = None) -> ResearchBrief:
    return ResearchBrief(
        normalized_topic="Hannah Arendt and action",
        topic_type=TopicType.PERSON,
        central_question="What does action mean in Arendt's political thought?",
        audience="social-science graduate student",
        prior_knowledge="intermediate",
        target_duration_minutes=25,
        output_language="fa",
        modes=["explanatory", "critical"],
        learning_objectives=objectives
        or [
            "Distinguish action from labor and work.",
            "Evaluate a major criticism of Arendt's account of action.",
        ],
        subquestions=["How is action related to plurality?"],
        scope_inclusions=["The Human Condition"],
        scope_exclusions=["A complete intellectual biography"],
        ambiguities=[],
    )


def _service(tmp_path: Path, model: BriefModel) -> tuple[WorkspaceStore, ResearchBriefService]:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    runner = ModelRunner(
        model,
        PromptLoader(),
        WorkspaceModelRunStore(tmp_path / "workspaces"),
        base_retry_delay_seconds=0,
        sleeper=lambda _: None,
    )
    return workspace, ResearchBriefService(workspace, runner)


def test_research_brief_stage_persists_brief_before_transition(tmp_path: Path) -> None:
    workspace, service = _service(tmp_path, BriefModel([_brief()]))
    project = Project(raw_input="آرنت و مفهوم کنش")
    workspace.save_project(project)

    execution = service.build(
        project.project_id,
        model="fake-model",
        audience="social-science graduate student",
        prior_knowledge="intermediate",
        target_duration_minutes=25,
        modes=["explanatory", "critical"],
        output_language="fa",
    )

    saved = workspace.load_project(project.project_id)
    assert execution.output.normalized_topic == "Hannah Arendt and action"
    assert saved.state == ProjectState.BRIEF_READY
    assert saved.brief == execution.output
    run_dir = (
        tmp_path
        / "workspaces"
        / str(project.project_id)
        / "model-runs"
        / str(execution.record.run_id)
    )
    assert (run_dir / "validated-output.json").exists()


def test_research_brief_repairs_invalid_learning_objectives(tmp_path: Path) -> None:
    invalid = _brief(objectives=["Learn about Arendt"])
    valid = _brief()
    model = BriefModel([invalid, valid])
    workspace, service = _service(tmp_path, model)
    project = Project(raw_input="آرنت")
    workspace.save_project(project)

    execution = service.build(
        project.project_id,
        model="fake-model",
        audience="social-science graduate student",
        prior_knowledge="intermediate",
        target_duration_minutes=25,
        modes=["explanatory", "critical"],
    )

    assert len(execution.record.attempts) == 2
    assert "REPAIR_INSTRUCTION" in model.prompts[1]
    assert workspace.load_project(project.project_id).state == ProjectState.BRIEF_READY
