from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel

from thesisound.adapters.models.okian import (
    OkianHttpError,
    OkianHttpResponse,
    OkianStructuredModel,
    _collect_stream,
    _repair_invalid_json_escapes,
    _strip_code_fence,
)
from thesisound.config import Settings
from thesisound.modeling import ModelConfigurationError, ModelProviderError, SchemaValidationError
from thesisound.observability import ObservabilityLedger
from thesisound.ports import RunMetadata


class ExampleOutput(BaseModel):
    answer: str


class FakeOkianClient:
    def __init__(self) -> None:
        self.requests: list[tuple[dict[str, object], float]] = []

    def create_chat_completion(
        self,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> OkianHttpResponse:
        self.requests.append((payload, timeout_seconds))
        return OkianHttpResponse(
            payload={
                "id": "req-okian-1",
                "model": "qwen-private-id",
                "choices": [
                    {
                        "message": {"content": '{"answer":"ok"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 4,
                    "total_tokens": 15,
                    "completion_tokens_details": {"reasoning_tokens": 2},
                    "prompt_tokens_details": {"cached_tokens": 3},
                },
            },
            status_code=200,
            headers={"x-request-id": "req-okian-1"},
        )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        workspace_root=tmp_path / "workspaces",
        observability_database_path=tmp_path / "ledger.sqlite3",
        observability_artifact_root=tmp_path / "artifacts",
    )


def test_okian_structured_output_is_observed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ledger = ObservabilityLedger(
        settings.resolved_observability_database_path,
        settings.resolved_observability_artifact_root,
    )
    client = FakeOkianClient()
    project_id = uuid4()
    adapter = OkianStructuredModel(
        client=client,
        observability=ledger,
        settings=settings,
    )

    response = adapter.generate_structured(
        system_prompt="Return JSON.",
        user_prompt="Answer.",
        output_type=ExampleOutput,
        model="qwen-private-id",
        metadata=RunMetadata(
            stage="document_map",
            model_or_provider="qwen-private-id",
            provider="okian",
            model_profile="okian_qwen",
            project_id=project_id,
        ),
    )

    assert response.output.answer == "ok"
    assert response.provider == "okian"
    assert response.model == "qwen-private-id"
    assert response.usage.input_tokens == 11
    assert response.usage.output_tokens == 4
    assert response.usage.thinking_tokens == 2
    assert response.usage.cached_tokens == 3
    assert client.requests[0][0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "ExampleOutput",
            "strict": True,
            "schema": ExampleOutput.model_json_schema(),
        },
    }

    detail = ledger.get_call(response.call_id)
    assert detail.call.provider == "okian"
    assert detail.call.status == "succeeded"
    assert detail.call.total_tokens == 15
    assert detail.metadata["model_profile"] == "okian_qwen"


def test_okian_carries_the_output_schema_in_the_system_prompt(tmp_path: Path) -> None:
    """Okian answers json_schema with 200 and ignores it, so the prompt must carry it.

    Without this the model never learns the property names, invents its own, and
    every structured call fails validation.
    """

    client = FakeOkianClient()
    adapter = OkianStructuredModel(client=client, settings=_settings(tmp_path))

    adapter.generate_structured(
        system_prompt="Return JSON.",
        user_prompt="Answer.",
        output_type=ExampleOutput,
        model="qwen-private-id",
        metadata=RunMetadata(
            stage="document_map",
            model_or_provider="qwen-private-id",
            provider="okian",
        ),
    )

    system_message = client.requests[0][0]["messages"][0]["content"]
    assert "<OUTPUT_JSON_SCHEMA>" in system_message
    assert '"answer"' in system_message
    assert system_message.startswith("Return JSON.")


def test_okian_streams_so_the_timeout_measures_provider_silence(tmp_path: Path) -> None:
    """A blocking call holds the socket silent for the whole completion.

    document_map generates for ~9 minutes; without streaming the 180s timeout
    fires before the first byte on every attempt.
    """

    client = FakeOkianClient()
    adapter = OkianStructuredModel(client=client, settings=_settings(tmp_path))

    adapter.generate_structured(
        system_prompt="Return JSON.",
        user_prompt="Answer.",
        output_type=ExampleOutput,
        model="qwen-private-id",
        metadata=RunMetadata(
            stage="document_map",
            model_or_provider="qwen-private-id",
            provider="okian",
        ),
    )

    payload = client.requests[0][0]
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


def test_collect_stream_folds_sse_into_a_blocking_envelope() -> None:
    chunks = [
        b'data: {"id":"gen-1","model":"deepseek-v4-flash-0731",'
        b'"choices":[{"delta":{"content":"{\\"ans"}}]}\n',
        b": keep-alive\n",
        b'data: {"choices":[{"delta":{"reasoning_content":"thinking out loud"}}]}\n',
        b'data: {"choices":[{"delta":{"content":"wer\\":\\"ok\\"}"},"finish_reason":"stop"}]}\n',
        b'data: {"usage":{"prompt_tokens":11,"completion_tokens":4,"total_tokens":15}}\n',
        b"data: [DONE]\n",
    ]

    envelope = _collect_stream(iter(chunks))

    assert envelope["choices"][0]["message"]["content"] == '{"answer":"ok"}'
    assert envelope["choices"][0]["finish_reason"] == "stop"
    assert envelope["usage"]["total_tokens"] == 15
    assert envelope["id"] == "gen-1"
    assert envelope["model"] == "deepseek-v4-flash-0731"


def test_collect_stream_survives_a_malformed_frame() -> None:
    chunks = [
        b'data: {"choices":[{"delta":{"content":"{\\"answer\\":\\"ok\\"}"}}]}\n',
        b"data: {not json\n",
        b"data: [DONE]\n",
    ]

    envelope = _collect_stream(iter(chunks))

    assert envelope["choices"][0]["message"]["content"] == '{"answer":"ok"}'


def test_fenced_json_is_parsed_because_nothing_constrains_decoding(tmp_path: Path) -> None:
    class FencedClient(FakeOkianClient):
        def create_chat_completion(
            self,
            payload: dict[str, object],
            *,
            timeout_seconds: float,
        ) -> OkianHttpResponse:
            response = super().create_chat_completion(payload, timeout_seconds=timeout_seconds)
            response.payload["choices"] = [
                {
                    "message": {"content": '```json\n{"answer":"ok"}\n```'},
                    "finish_reason": "stop",
                }
            ]
            return response

    adapter = OkianStructuredModel(client=FencedClient(), settings=_settings(tmp_path))

    response = adapter.generate_structured(
        system_prompt="Return JSON.",
        user_prompt="Answer.",
        output_type=ExampleOutput,
        model="qwen-private-id",
        metadata=RunMetadata(
            stage="document_map",
            model_or_provider="qwen-private-id",
            provider="okian",
        ),
    )

    assert response.output.answer == "ok"


def test_invalid_json_escape_is_repaired_because_nothing_constrains_decoding(
    tmp_path: Path,
) -> None:
    """gemini-3.6-flash via Okian emitted a bare backslash inside a string value.

    Observed in production (persian_script_segment, project 9c4e58b0): pydantic
    rejected the whole payload with "Invalid JSON: invalid escape". Structural
    JSON never contains a backslash outside a string, so doubling the one
    json.loads chokes on recovers the payload without touching the model's
    actual words.
    """

    class InvalidEscapeClient(FakeOkianClient):
        def create_chat_completion(
            self,
            payload: dict[str, object],
            *,
            timeout_seconds: float,
        ) -> OkianHttpResponse:
            response = super().create_chat_completion(payload, timeout_seconds=timeout_seconds)
            # A lone backslash before a Persian letter, not a valid JSON escape.
            response.payload["choices"] = [
                {
                    "message": {"content": '{"answer":"این یک \\نمونه است"}'},
                    "finish_reason": "stop",
                }
            ]
            return response

    adapter = OkianStructuredModel(client=InvalidEscapeClient(), settings=_settings(tmp_path))

    response = adapter.generate_structured(
        system_prompt="Return JSON.",
        user_prompt="Answer.",
        output_type=ExampleOutput,
        model="gemini-3.6-flash",
        metadata=RunMetadata(
            stage="script_segment:seg-005",
            model_or_provider="gemini-3.6-flash",
            provider="okian",
        ),
    )

    assert response.output.answer == "این یک \\نمونه است"


def test_a_real_schema_mismatch_is_not_masked_by_the_escape_repair(tmp_path: Path) -> None:
    """Escape repair only retries the exact malformed-escape shape.

    A wrong-field response is syntactically valid JSON; repairing escapes
    would not change the outcome, so it must not be attempted -- the real
    error (wrong fields) should surface once, not get retried away.
    """

    class WrongFieldClient(FakeOkianClient):
        def create_chat_completion(
            self,
            payload: dict[str, object],
            *,
            timeout_seconds: float,
        ) -> OkianHttpResponse:
            response = super().create_chat_completion(payload, timeout_seconds=timeout_seconds)
            response.payload["choices"] = [
                {"message": {"content": '{"wrong":"field"}'}, "finish_reason": "stop"}
            ]
            return response

    adapter = OkianStructuredModel(client=WrongFieldClient(), settings=_settings(tmp_path))

    with pytest.raises(SchemaValidationError, match="did not match ExampleOutput"):
        adapter.generate_structured(
            system_prompt="Return JSON.",
            user_prompt="Answer.",
            output_type=ExampleOutput,
            model="gemini-3.6-flash",
            metadata=RunMetadata(
                stage="document_map",
                model_or_provider="gemini-3.6-flash",
                provider="okian",
            ),
        )


def test_repair_invalid_json_escapes_doubles_only_invalid_backslashes() -> None:
    broken = '{"text": "این یک \\نمونه است"}'
    with pytest.raises(json.JSONDecodeError):
        json.loads(broken)

    fixed = _repair_invalid_json_escapes(broken)

    assert json.loads(fixed) == {"text": "این یک \\نمونه است"}


def test_repair_invalid_json_escapes_leaves_valid_escapes_untouched() -> None:
    valid = json.dumps(
        {"a": 'line1\nline2\t"quoted"', "b": "emoji é", "c": "slash\\/ok"}
    )

    repaired = _repair_invalid_json_escapes(valid)

    assert repaired == valid
    assert json.loads(repaired) == json.loads(valid)


def test_budget_exhausted_by_reasoning_is_named_in_the_error(tmp_path: Path) -> None:
    """`finish_reason: length` with no content is a reasoning model talking itself out.

    Observed on deepseek-v4-flash for a 53k-char document_map prompt: 10,866
    reasoning deltas, zero answer tokens. The generic "no content" message sent
    operators looking at the wrong thing.
    """

    class OutOfBudgetClient(FakeOkianClient):
        def create_chat_completion(
            self,
            payload: dict[str, object],
            *,
            timeout_seconds: float,
        ) -> OkianHttpResponse:
            response = super().create_chat_completion(payload, timeout_seconds=timeout_seconds)
            response.payload["choices"] = [{"message": {"content": ""}, "finish_reason": "length"}]
            return response

    adapter = OkianStructuredModel(client=OutOfBudgetClient(), settings=_settings(tmp_path))

    with pytest.raises(SchemaValidationError, match="entire output budget on reasoning"):
        adapter.generate_structured(
            system_prompt="Return JSON.",
            user_prompt="Answer.",
            output_type=ExampleOutput,
            model="deepseek-v4-flash-latest",
            metadata=RunMetadata(
                stage="document_map",
                model_or_provider="deepseek-v4-flash-latest",
                provider="okian",
            ),
        )


def test_strip_code_fence_leaves_bare_json_untouched() -> None:
    assert _strip_code_fence('{"answer":"ok"}') == '{"answer":"ok"}'
    assert _strip_code_fence('  {"answer":"ok"}  ') == '{"answer":"ok"}'
    assert _strip_code_fence('```\n{"answer":"ok"}\n```') == '{"answer":"ok"}'


def test_okian_refuses_gemini_grounding_before_http(tmp_path: Path) -> None:
    client = FakeOkianClient()
    adapter = OkianStructuredModel(
        client=client,
        settings=_settings(tmp_path),
    )

    with pytest.raises(ModelConfigurationError, match="Google Search"):
        adapter.generate_structured(
            system_prompt="Return JSON.",
            user_prompt="Answer.",
            output_type=ExampleOutput,
            model="qwen-private-id",
            metadata=RunMetadata(
                stage="source_discovery",
                model_or_provider="qwen-private-id",
                provider="okian",
                grounding_mode="google_search",
            ),
        )

    assert client.requests == []


def test_okian_adapter_treats_406_not_acceptable_as_retryable(tmp_path: Path) -> None:
    """Observed live: the Gemini-fallback call to Okian hit a bare 406 "Not

    Acceptable" (no JSON error body, urllib's HTTPError.reason as the whole
    message) that cleared on an identical retried request. It must be
    classified retryable so ModelRunner.run's contract-level retry loop gets
    a chance to recover instead of failing the whole run on one blip.
    """

    class NotAcceptableClient(FakeOkianClient):
        def create_chat_completion(
            self,
            payload: dict[str, object],
            *,
            timeout_seconds: float,
        ) -> OkianHttpResponse:
            raise OkianHttpError("Not Acceptable", status_code=406)

    adapter = OkianStructuredModel(client=NotAcceptableClient(), settings=_settings(tmp_path))

    with pytest.raises(ModelProviderError) as exc_info:
        adapter.generate_structured(
            system_prompt="Return JSON.",
            user_prompt="Answer.",
            output_type=ExampleOutput,
            model="qwen-private-id",
            metadata=RunMetadata(
                stage="document_map",
                model_or_provider="qwen-private-id",
                provider="okian",
            ),
        )

    assert exc_info.value.retryable is True


def test_okian_adapter_attaches_billed_usage_to_schema_errors(tmp_path: Path) -> None:
    class InvalidOutputClient(FakeOkianClient):
        def create_chat_completion(
            self,
            payload: dict[str, object],
            *,
            timeout_seconds: float,
        ) -> OkianHttpResponse:
            response = super().create_chat_completion(payload, timeout_seconds=timeout_seconds)
            response.payload["choices"] = [
                {
                    "message": {"content": '{"wrong":"field"}'},
                    "finish_reason": "stop",
                }
            ]
            return response

    adapter = OkianStructuredModel(
        client=InvalidOutputClient(),
        settings=_settings(tmp_path),
    )

    with pytest.raises(SchemaValidationError) as exc_info:
        adapter.generate_structured(
            system_prompt="Return JSON.",
            user_prompt="Answer.",
            output_type=ExampleOutput,
            model="qwen-private-id",
            metadata=RunMetadata(
                stage="document_map",
                model_or_provider="qwen-private-id",
                provider="okian",
            ),
        )

    assert exc_info.value.usage is not None
    assert exc_info.value.usage.input_tokens == 11
