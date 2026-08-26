from __future__ import annotations

from threading import Barrier, Lock, Thread
from time import sleep
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from thesisound.adapters.models.gemini import GeminiStructuredModel
from thesisound.config import Settings
from thesisound.modeling import (
    ModelProviderError,
    ModelRateLimitError,
    ModelSafetyError,
    SchemaValidationError,
)
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


class NotAcceptableException(RuntimeError):
    """Mirrors google.genai.errors.ClientError for a bare HTTP 406.

    Reproduced live against the real API: the Gemini edge/proxy occasionally
    answers with a 406 that carries no JSON error body (just the "Not
    Acceptable" reason phrase), and the identical request succeeds when
    retried immediately after. This must be classified as retryable so the
    contract-level retry loop in ModelRunner.run gets a chance to recover.
    """

    status_code = 406


def _metadata() -> RunMetadata:
    return RunMetadata(stage="test", model_or_provider="fake")


def _settings_without_okian(tmp_path) -> Settings:
    # Beat process env so unit tests do not trigger live Okian fallback.
    return Settings(
        _env_file=None,
        workspace_root=tmp_path / "workspaces",
        observability_database_path=tmp_path / "ledger.sqlite3",
        observability_artifact_root=tmp_path / "artifacts",
        okian_base_url="",
        okian_api_key="",
    )


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


def test_gemini_adapter_rejects_invalid_structured_output(tmp_path) -> None:
    response = SimpleNamespace(
        parsed={"wrong": "field"},
        text='{"wrong":"field"}',
        candidates=[SimpleNamespace(finish_reason="STOP")],
        prompt_feedback=None,
        usage_metadata=None,
    )
    adapter = GeminiStructuredModel(
        client=FakeClient(FakeModels(response=response)),
        settings=_settings_without_okian(tmp_path),
    )

    with pytest.raises(SchemaValidationError):
        adapter.generate_structured(
            system_prompt="system",
            user_prompt="user",
            output_type=ExampleOutput,
            model="gemini-test",
            metadata=_metadata(),
        )


def test_gemini_adapter_attaches_billed_usage_to_schema_errors(tmp_path) -> None:
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
    adapter = GeminiStructuredModel(
        client=FakeClient(FakeModels(response=response)),
        settings=_settings_without_okian(tmp_path),
    )

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


def test_gemini_adapter_attaches_billed_usage_to_safety_errors(tmp_path) -> None:
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
    adapter = GeminiStructuredModel(
        client=FakeClient(FakeModels(response=response)),
        settings=_settings_without_okian(tmp_path),
    )

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
    adapter = GeminiStructuredModel(
        client=FakeClient(FakeModels(error=RateLimitException("too many requests"))),
        settings=_settings_without_okian(tmp_path),
    )

    with pytest.raises(ModelRateLimitError):
        adapter.generate_structured(
            system_prompt="system",
            user_prompt="user",
            output_type=ExampleOutput,
            model="gemini-test",
            metadata=_metadata(),
        )


class DailyQuotaException(RuntimeError):
    """Shaped like google.genai.errors.ClientError for a day-scoped 429.

    Measured live 2026-08-25: the message text says "please retry in 30s" on
    BOTH a daily block and a per-minute one -- only the structured
    `details['error']['details']` QuotaFailure.violations[].quotaId
    ("...PerDay..." vs "...PerMinute...") tells them apart.
    """

    status_code = 429
    details = {
        "error": {
            "code": 429,
            "message": "Please retry in 30s.",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {
                            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                            "quotaValue": "20",
                        }
                    ],
                },
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "30s",
                },
            ],
        }
    }


def test_gemini_adapter_tags_daily_quota_errors_for_the_user_facing_layer(tmp_path) -> None:
    """error_messages.py only sees the ModelError's string message (no
    structured access survives that far) -- this is what lets it tell a
    daily block apart from a per-minute one instead of giving both the same
    "try again in a few minutes" advice.
    """

    adapter = GeminiStructuredModel(
        client=FakeClient(FakeModels(error=DailyQuotaException("please retry in 30s"))),
        settings=_settings_without_okian(tmp_path),
    )

    with pytest.raises(ModelRateLimitError) as exc_info:
        adapter.generate_structured(
            system_prompt="system",
            user_prompt="user",
            output_type=ExampleOutput,
            model="gemini-test",
            metadata=_metadata(),
        )

    assert "daily quota" in str(exc_info.value)


def test_gemini_adapter_treats_406_not_acceptable_as_retryable(tmp_path) -> None:
    adapter = GeminiStructuredModel(
        client=FakeClient(FakeModels(error=NotAcceptableException("Not Acceptable"))),
        settings=_settings_without_okian(tmp_path),
    )

    with pytest.raises(ModelProviderError) as exc_info:
        adapter.generate_structured(
            system_prompt="system",
            user_prompt="user",
            output_type=ExampleOutput,
            model="gemini-test",
            metadata=_metadata(),
        )

    assert exc_info.value.retryable is True


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


def test_gemini_adapter_sends_a_pinned_temperature_and_seed() -> None:
    """Gemini's default is ~1.0, so an analytical stage has to say otherwise.

    Before per-contract sampling existed this config carried no sampling fields
    at all, which is why two extraction runs over one identical document
    disagreed on both claim count and concept-map size.
    """

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

    adapter.generate_structured(
        system_prompt="system",
        user_prompt="user",
        output_type=ExampleOutput,
        model="gemini-test",
        metadata=RunMetadata(
            stage="evidence_extraction",
            model_or_provider="fake",
            temperature=0,
            seed=20260823,
        ),
    )

    config = models.calls[0]["config"]
    assert config["temperature"] == 0
    assert config["seed"] == 20260823
