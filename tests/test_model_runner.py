from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel

from thesisound.modeling import (
    DeterministicValidationError,
    ModelSafetyError,
    ModelTimeoutError,
    ModelUsage,
    StructuredModelResponse,
)
from thesisound.ports import RunMetadata
from thesisound.prompt_loader import PromptLoader
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner


class ExampleOutput(BaseModel):
    value: str


class FakeModel:
    provider = "fake"

    def __init__(self, results: list[object]) -> None:
        self.results = results
        self.prompts: list[str] = []

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_type: type[ExampleOutput],
        model: str,
        metadata: RunMetadata,
    ) -> StructuredModelResponse[ExampleOutput]:
        _ = system_prompt, output_type, model, metadata
        self.prompts.append(user_prompt)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        assert isinstance(result, ExampleOutput)
        return StructuredModelResponse[ExampleOutput](
            output=result,
            provider=self.provider,
            model="fake-model",
            usage=ModelUsage(input_tokens=10, output_tokens=4, total_tokens=14),
            latency_ms=25,
            finish_reason="STOP",
        )


def _prompt_root(tmp_path: Path) -> Path:
    root = tmp_path / "prompts"
    version = root / "example" / "1.0.0"
    version.mkdir(parents=True)
    (version / "contract.json").write_text(
        json.dumps(
            {
                "id": "example",
                "version": "1.0.0",
                "model_tier": "fast",
                "output_model": "ExampleOutput",
                "max_attempts": 2,
                "retry_schema_errors": True,
                "system_file": "system.md",
                "user_file": "user.md",
            }
        ),
        encoding="utf-8",
    )
    (version / "system.md").write_text("System {{ context }}", encoding="utf-8")
    (version / "user.md").write_text("User {{ topic }}", encoding="utf-8")
    return root


def _runner(
    tmp_path: Path,
    model: FakeModel,
    *,
    sleeper=lambda _: None,
    keep_prompts: bool = False,
) -> ModelRunner:
    return ModelRunner(
        model,
        PromptLoader(_prompt_root(tmp_path)),
        WorkspaceModelRunStore(tmp_path / "workspaces", keep_prompts=keep_prompts),
        base_retry_delay_seconds=0.1,
        sleeper=sleeper,
    )


def test_model_runner_persists_validated_output_without_raw_prompts(tmp_path: Path) -> None:
    project_id = uuid4()
    execution = _runner(tmp_path, FakeModel([ExampleOutput(value="ok")])).run(
        project_id=project_id,
        stage="example",
        prompt_name="example",
        variables={"context": "safe", "topic": "Arendt"},
        output_type=ExampleOutput,
        model="fake-model",
    )

    run_dir = tmp_path / "workspaces" / str(project_id) / "model-runs" / str(
        execution.record.run_id
    )
    assert execution.output.value == "ok"
    assert execution.record.prompt_version == "1.0.0"
    assert execution.record.status == "succeeded"
    assert (run_dir / "validated-output.json").exists()
    assert not (run_dir / "rendered-prompts.json").exists()
    request = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    assert request["variable_names"] == ["context", "topic"]
    assert "Arendt" not in json.dumps(request)


def test_model_runner_retries_transient_error_with_backoff(tmp_path: Path) -> None:
    delays: list[float] = []
    model = FakeModel([ModelTimeoutError("timeout"), ExampleOutput(value="ok")])

    execution = _runner(tmp_path, model, sleeper=delays.append).run(
        project_id=uuid4(),
        stage="example",
        prompt_name="example",
        variables={"context": "safe", "topic": "Nietzsche"},
        output_type=ExampleOutput,
        model="fake-model",
    )

    assert len(execution.record.attempts) == 2
    assert delays == [0.1]
    assert model.prompts[0] == model.prompts[1]


def test_model_runner_adds_targeted_repair_instruction(tmp_path: Path) -> None:
    model = FakeModel([ExampleOutput(value="bad"), ExampleOutput(value="good")])

    def validator(output: ExampleOutput) -> None:
        if output.value != "good":
            raise DeterministicValidationError("value must equal good")

    execution = _runner(tmp_path, model).run(
        project_id=uuid4(),
        stage="example",
        prompt_name="example",
        variables={"context": "safe", "topic": "Zizek"},
        output_type=ExampleOutput,
        model="fake-model",
        validator=validator,
    )

    assert execution.output.value == "good"
    assert "REPAIR_INSTRUCTION" in model.prompts[1]
    assert "value must equal good" in model.prompts[1]


def test_model_runner_does_not_retry_safety_error(tmp_path: Path) -> None:
    model = FakeModel([ModelSafetyError("blocked"), ExampleOutput(value="unused")])

    with pytest.raises(ModelSafetyError):
        _runner(tmp_path, model).run(
            project_id=uuid4(),
            stage="example",
            prompt_name="example",
            variables={"context": "safe", "topic": "topic"},
            output_type=ExampleOutput,
            model="fake-model",
        )

    assert len(model.prompts) == 1


def test_prompt_store_can_explicitly_keep_rendered_prompts(tmp_path: Path) -> None:
    project_id = uuid4()
    execution = _runner(
        tmp_path,
        FakeModel([ExampleOutput(value="ok")]),
        keep_prompts=True,
    ).run(
        project_id=project_id,
        stage="example",
        prompt_name="example",
        variables={"context": "safe", "topic": "Arendt"},
        output_type=ExampleOutput,
        model="fake-model",
    )

    run_dir = tmp_path / "workspaces" / str(project_id) / "model-runs" / str(
        execution.record.run_id
    )
    assert (run_dir / "rendered-prompts.json").exists()
