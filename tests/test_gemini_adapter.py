from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from thesisound.adapters.models.gemini import GeminiStructuredModel
from thesisound.modeling import ModelRateLimitError, SchemaValidationError
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
    assert config["response_schema"] is ExampleOutput
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


def test_gemini_adapter_maps_rate_limit_errors() -> None:
    adapter = GeminiStructuredModel(
        client=FakeClient(FakeModels(error=RateLimitException("too many requests")))
    )

    with pytest.raises(ModelRateLimitError):
        adapter.generate_structured(
            system_prompt="system",
            user_prompt="user",
            output_type=ExampleOutput,
            model="gemini-test",
            metadata=_metadata(),
        )
