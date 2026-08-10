from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel

from thesisound import tracing
from thesisound.config import Settings
from thesisound.model_routing import load_model_router
from thesisound.modeling import (
    DeterministicValidationError,
    ModelConfigurationError,
    ModelSafetyError,
    ModelTimeoutError,
    ModelUsage,
    SchemaValidationError,
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

    def __init__(self, results: list[object], *, dwell_seconds: float = 0) -> None:
        self.results = results
        self.prompts: list[str] = []
        self.metadata_seen: list[RunMetadata] = []
        self.entered_at: list[datetime] = []
        self.dwell_seconds = dwell_seconds

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_type: type[ExampleOutput],
        model: str,
        metadata: RunMetadata,
    ) -> StructuredModelResponse[ExampleOutput]:
        _ = system_prompt, output_type, model
        self.prompts.append(user_prompt)
        self.metadata_seen.append(metadata)
        self.entered_at.append(datetime.now(UTC))
        if self.dwell_seconds:
            time.sleep(self.dwell_seconds)
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


def _script_verifier_prompt_root(tmp_path: Path) -> Path:
    root = tmp_path / "script-verifier-prompts"
    version = root / "script_verifier" / "1.0.0"
    version.mkdir(parents=True)
    (version / "contract.json").write_text(
        json.dumps(
            {
                "id": "script_verifier",
                "version": "1.0.0",
                "model_tier": "strong",
                "output_model": "ExampleOutput",
                "max_attempts": 1,
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

    run_dir = (
        tmp_path / "workspaces" / str(project_id) / "model-runs" / str(execution.record.run_id)
    )
    assert execution.output.value == "ok"
    assert execution.record.prompt_version == "1.0.0"
    assert execution.record.status == "succeeded"
    assert (run_dir / "validated-output.json").exists()
    assert not (run_dir / "rendered-prompts.json").exists()
    request = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    assert request["variable_names"] == ["context", "topic"]
    assert "Arendt" not in json.dumps(request)


def test_model_runner_carries_the_ambient_span_into_run_metadata(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    """The step spans added around corpus/episode/script/audio work (e.g.
    corpus.extract_evidence) are only useful if the model call they wrap
    actually attaches to them -- this is that join, one level up from the
    ModelCallSpec-level tests in test_observability.py."""

    model = FakeModel([ExampleOutput(value="ok")])

    with tracing.span("corpus.extract_evidence", subject_id="block-1") as span:
        _runner(tmp_path, model).run(
            project_id=uuid4(),
            stage="example",
            prompt_name="example",
            variables={"context": "safe", "topic": "Arendt"},
            output_type=ExampleOutput,
            model="fake-model",
        )

    assert len(model.metadata_seen) == 1
    metadata = model.metadata_seen[0]
    assert metadata.pipeline_trace_id == span.context.trace_id
    assert metadata.parent_span_id == span.context.span_id


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


def test_rejected_response_records_the_tokens_already_billed(tmp_path: Path) -> None:
    model = FakeModel([ExampleOutput(value="a"), ExampleOutput(value="b")])
    validations = 0

    def validator(_: ExampleOutput) -> None:
        nonlocal validations
        validations += 1
        if validations == 1:
            raise DeterministicValidationError("reject first response")

    execution = _runner(tmp_path, model).run(
        project_id=uuid4(),
        stage="example",
        prompt_name="example",
        variables={"context": "safe", "topic": "Arendt"},
        output_type=ExampleOutput,
        model="fake-model",
        validator=validator,
    )

    first, second = execution.record.attempts
    assert first.success is False
    assert first.error_type == "DeterministicValidationError"
    assert first.usage is not None
    assert first.usage.input_tokens == 10
    assert first.usage.output_tokens == 4
    assert second.usage.input_tokens == 10


def test_schema_error_records_the_tokens_the_adapter_carried(tmp_path: Path) -> None:
    model = FakeModel(
        [
            SchemaValidationError(
                "bad json",
                usage=ModelUsage(input_tokens=99, output_tokens=3, total_tokens=102),
            ),
            ExampleOutput(value="ok"),
        ]
    )

    execution = _runner(tmp_path, model).run(
        project_id=uuid4(),
        stage="example",
        prompt_name="example",
        variables={"context": "safe", "topic": "Arendt"},
        output_type=ExampleOutput,
        model="fake-model",
    )

    first = execution.record.attempts[0]
    assert first.usage is not None
    assert first.usage.input_tokens == 99
    assert first.usage.total_tokens == 102
    assert len(model.prompts) == 2
    assert "<REPAIR_INSTRUCTION>" in model.prompts[1]


def test_transport_failure_leaves_usage_unknown_rather_than_zero(tmp_path: Path) -> None:
    project_id = uuid4()
    execution = _runner(
        tmp_path,
        FakeModel([ModelTimeoutError("upstream timeout"), ExampleOutput(value="ok")]),
    ).run(
        project_id=project_id,
        stage="example",
        prompt_name="example",
        variables={"context": "safe", "topic": "Arendt"},
        output_type=ExampleOutput,
        model="fake-model",
    )

    assert execution.record.attempts[0].usage is None
    run_dir = (
        tmp_path / "workspaces" / str(project_id) / "model-runs" / str(execution.record.run_id)
    )
    payload = json.loads((run_dir / "record.json").read_text(encoding="utf-8"))
    assert payload["attempts"][0]["usage"] is None


def test_terminal_failure_persists_billed_tokens_in_the_error_artifact(tmp_path: Path) -> None:
    project_id = uuid4()
    model = FakeModel([ModelSafetyError("blocked", usage=ModelUsage(input_tokens=77))])

    with pytest.raises(ModelSafetyError):
        _runner(tmp_path, model).run(
            project_id=project_id,
            stage="example",
            prompt_name="example",
            variables={"context": "safe", "topic": "Arendt"},
            output_type=ExampleOutput,
            model="fake-model",
        )

    run_dir = next((tmp_path / "workspaces" / str(project_id) / "model-runs").glob("*"))
    payload = json.loads((run_dir / "error.json").read_text(encoding="utf-8"))
    assert payload["attempts"][0]["usage"]["input_tokens"] == 77


def test_attempt_started_at_precedes_the_provider_call(tmp_path: Path) -> None:
    model = FakeModel(
        [ExampleOutput(value="bad"), ExampleOutput(value="good")],
        dwell_seconds=0.02,
    )

    def validator(output: ExampleOutput) -> None:
        if output.value == "bad":
            raise DeterministicValidationError("retry")

    execution = _runner(tmp_path, model).run(
        project_id=uuid4(),
        stage="example",
        prompt_name="example",
        variables={"context": "safe", "topic": "Arendt"},
        output_type=ExampleOutput,
        model="fake-model",
        validator=validator,
    )

    assert all(
        attempt.started_at <= model.entered_at[index]
        for index, attempt in enumerate(execution.record.attempts)
    )
    assert execution.record.attempts[0].started_at <= execution.record.attempts[1].started_at


def test_record_json_reports_usage_for_every_attempt(tmp_path: Path) -> None:
    project_id = uuid4()
    execution = _runner(
        tmp_path,
        FakeModel(
            [
                SchemaValidationError("bad json", usage=ModelUsage(input_tokens=99)),
                ExampleOutput(value="ok"),
            ]
        ),
    ).run(
        project_id=project_id,
        stage="example",
        prompt_name="example",
        variables={"context": "safe", "topic": "Arendt"},
        output_type=ExampleOutput,
        model="fake-model",
    )

    run_dir = (
        tmp_path / "workspaces" / str(project_id) / "model-runs" / str(execution.record.run_id)
    )
    payload = json.loads((run_dir / "record.json").read_text(encoding="utf-8"))
    assert all(attempt["usage"]["input_tokens"] is not None for attempt in payload["attempts"])


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

    run_dir = (
        tmp_path / "workspaces" / str(project_id) / "model-runs" / str(execution.record.run_id)
    )
    assert (run_dir / "rendered-prompts.json").exists()


def test_model_runner_routes_by_prompt_contract_id_not_observability_stage(
    tmp_path: Path,
) -> None:
    from thesisound.model_routing import ResolvedModelRoute

    class RoutingFakeModel(FakeModel):
        def __init__(self) -> None:
            super().__init__([ExampleOutput(value="ok")])
            self.route_stages: list[str] = []

        def resolve_route(
            self,
            *,
            stage: str,
            requested_model: str,
            model_tier: str,
        ) -> ResolvedModelRoute:
            _ = requested_model, model_tier
            self.route_stages.append(stage)
            return ResolvedModelRoute(provider="okian", model="gemma-routed", profile="okian_gemma")

    model = RoutingFakeModel()
    execution = _runner(tmp_path, model).run(
        project_id=uuid4(),
        stage="script_segment:seg-001",
        prompt_name="example",
        variables={"context": "safe", "topic": "Arendt"},
        output_type=ExampleOutput,
        model="fake-model",
    )

    assert model.route_stages == ["example"]
    assert execution.record.provider == "okian"
    assert execution.record.model == "gemma-routed"
    assert execution.record.stage == "script_segment:seg-001"


def test_verifier_run_raises_before_any_provider_call_when_the_reviewer_is_not_independent(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        model_routing_file=Path("config/model-routing.toml"),
    )
    router = load_model_router(settings)

    class RoutingFakeModel(FakeModel):
        def __init__(self) -> None:
            super().__init__([])
            self.provider_calls = 0

        def resolve_route(
            self,
            *,
            stage: str,
            requested_model: str,
            model_tier: str,
        ):
            return router.resolve(
                stage=stage,
                requested_model=requested_model,
                model_tier=model_tier,  # type: ignore[arg-type]
            )

        def generate_structured(self, **kwargs: object) -> StructuredModelResponse[ExampleOutput]:
            _ = kwargs
            self.provider_calls += 1
            raise AssertionError("The provider must not be called for a blocked verifier.")

    model = RoutingFakeModel()
    runner = ModelRunner(
        model,
        PromptLoader(_script_verifier_prompt_root(tmp_path)),
        WorkspaceModelRunStore(tmp_path / "workspaces"),
    )

    with pytest.raises(ModelConfigurationError):
        runner.run(
            project_id=uuid4(),
            stage="script_verifier",
            prompt_name="script_verifier",
            variables={"context": "safe", "topic": "Arendt"},
            output_type=ExampleOutput,
            model=settings.model_strong,
        )

    assert model.provider_calls == 0
    # Route resolution precedes run_store.initialize(), so a blocked route must
    # not leave even a model-run record behind.
    assert list((tmp_path / "workspaces").rglob("record.json")) == []
