from __future__ import annotations

from threading import Barrier, Lock, Thread
from time import sleep
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from thesisound.adapters.models.gemini import GeminiStructuredModel
from thesisound.config import Settings
from thesisound.modeling import ModelRateLimitError, ModelSafetyError, SchemaValidationError
from thesisound.ports import RunMetadata


class ExampleOutput(BaseModel):
    value: str


class FakeModels:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, models: FakeModels) -> None:
        self.models = models


class RateLimitException(RuntimeError):
    status_code = 429


def _metadata() -> RunMetadata:
    return RunMetadata(stage="test", model_or_provider="fake")


def test_gemini_adapter_uses_pydantic_schema_without_sampling_parameters() -> None:
    response = SimpleNamespace(
        parsed=ExampleOutput(value="ok"),
        text='{"value":"ok"}',
        candidates=[SimpleNamespace(finish_reason="STOP")],
        prompt_feedback=None,
        usage_metadata=SimpleNamespace(
            prompt_token_count=12,
            candidates_token_count=3,
            total_token_count=15,
            thoughts_token_count=0,
        ),
    )
    models = FakeModels(response=response)
    adapter = GeminiStructuredModel(client=FakeClient(models))

    result = adapter.generate_structured(
        system_prompt="system",
        user_prompt="user",
        output_type=ExampleOutput,
        model="gemini-test",
        metadata=_metadata(),
    )

    assert result.output.value == "ok"
    config = models.calls[0]["config"]
    assert isinstance(config, dict)
    assert "response_schema" not in config
    assert config["response_json_schema"] == {
        "properties": {"value": {"title": "Value", "type": "string"}},
        "required": ["value"],
        "title": "ExampleOutput",
        "type": "object",
    }
    assert config["response_mime_type"] == "application/json"
    assert "temperature" not in config
    assert "top_p" not in config
    assert result.usage.total_tokens == 15


def test_gemini_adapter_validates_text_when_parsed_is_missing() -> None:
    response = SimpleNamespace(
        parsed=None,
        text='{"value":"from-text"}',
        candidates=[SimpleNamespace(finish_reason="STOP")],
        prompt_feedback=None,
        usage_metadata=None,
    )
    adapter = GeminiStructuredModel(client=FakeClient(FakeModels(response=response)))

    result = adapter.generate_structured(
        system_prompt="system",
        user_prompt="user",
        output_type=ExampleOutput,
        model="gemini-test",
        metadata=_metadata(),
    )

    assert result.output.value == "from-text"


def test_gemini_adapter_rejects_invalid_structured_output() -> None:
    response = SimpleNamespace(
        parsed={"wrong": "field"},
        text='{"wrong":"field"}',
        candidates=[SimpleNamespace(finish_reason="STOP")],
        prompt_feedback=None,
        usage_metadata=None,
    )
    adapter = GeminiStructuredModel(client=FakeClient(FakeModels(response=response)))

    with pytest.raises(SchemaValidationError):
        adapter.generate_structured(
            system_prompt="system",
            user_prompt="user",
            output_type=ExampleOutput,
            model="gemini-test",
            metadata=_metadata(),
        )


def test_gemini_adapter_attaches_billed_usage_to_schema_errors() -> None:
    response = SimpleNamespace(
        parsed={"wrong": "field"},
        text='{"wrong":"field"}',
        candidates=[SimpleNamespace(finish_reason="STOP")],
        prompt_feedback=None,
        usage_metadata=SimpleNamespace(
            prompt_token_count=120,
            candidates_token_count=8,
            total_token_count=128,
            thoughts_token_count=None,
            cached_content_token_count=None,
        ),
    )
    adapter = GeminiStructuredModel(client=FakeClient(FakeModels(response=response)))

    with pytest.raises(SchemaValidationError) as exc_info:
        adapter.generate_structured(
            system_prompt="system",
            user_prompt="user",
            output_type=ExampleOutput,
            model="gemini-test",
            metadata=_metadata(),
        )

    assert exc_info.value.usage is not None
    assert exc_info.value.usage.input_tokens == 120
    assert exc_info.value.usage.output_tokens == 8


def test_gemini_adapter_attaches_billed_usage_to_safety_errors() -> None:
    response = SimpleNamespace(
        parsed=None,
        text=None,
        candidates=[SimpleNamespace(finish_reason="SAFETY")],
        prompt_feedback=None,
        usage_metadata=SimpleNamespace(
            prompt_token_count=120,
            candidates_token_count=8,
            total_token_count=128,
            thoughts_token_count=None,
            cached_content_token_count=None,
        ),
    )
    adapter = GeminiStructuredModel(client=FakeClient(FakeModels(response=response)))

    with pytest.raises(ModelSafetyError) as exc_info:
        adapter.generate_structured(
            system_prompt="system",
            user_prompt="user",
            output_type=ExampleOutput,
            model="gemini-test",
            metadata=_metadata(),
        )

    assert exc_info.value.usage is not None
    assert exc_info.value.usage.input_tokens == 120


def test_gemini_adapter_maps_rate_limit_errors(tmp_path) -> None:
    # Disable Okian so this path stays a pure Gemini rate-limit mapping check.
    settings = Settings(
        _env_file=None,
        workspace_root=tmp_path / "workspaces",
        observability_database_path=tmp_path / "ledger.sqlite3",
        observability_artifact_root=tmp_path / "artifacts",
    )
    adapter = GeminiStructuredModel(
        client=FakeClient(FakeModels(error=RateLimitException("too many requests"))),
        settings=settings,
    )

    with pytest.raises(ModelRateLimitError):
        adapter.generate_structured(
            system_prompt="system",
            user_prompt="user",
            output_type=ExampleOutput,
            model="gemini-test",
            metadata=_metadata(),
        )


def test_okian_port_is_built_once_under_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parallel evidence extraction reaches one adapter from several threads at once.

    The barrier lines every caller up on `_okian`, and the slow constructor holds the
    check-then-assign window open long enough that all of them would pass the `is None`
    check. Without the lock this builds four ports instead of one.
    """

    built: list[object] = []
    guard = Lock()
    start = Barrier(4, timeout=10)

    class FakeOkian:
        def __init__(self, **_: object) -> None:
            sleep(0.05)
            with guard:
                built.append(self)

    monkeypatch.setattr(
        "thesisound.adapters.models.okian.OkianStructuredModel",
        FakeOkian,
    )
    adapter = GeminiStructuredModel(client=FakeClient(FakeModels()))
    ports: list[object] = []

    def call() -> None:
        start.wait()
        port = adapter._okian()
        with guard:
            ports.append(port)

    threads = [Thread(target=call) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(built) == 1
    assert ports and all(port is built[0] for port in ports)
