from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from thesisound.modeling import ModelUsage
from thesisound.observability import (
    ModelCallSpec,
    ObservabilityLedger,
    ObservedModelGateway,
    ProviderMetadata,
)


class FakePool:
    def __init__(self, responses):
        self.responses = list(responses)

    def call(self, operation, *, on_attempt=None):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            if on_attempt:
                on_attempt(
                    {
                        "status": "quota_failed",
                        "key_slot": 1,
                        "key_fingerprint": "abc123",
                        "credential_type": "api_key",
                        "latency_ms": 4,
                        "http_status": 429,
                        "error_type": type(response).__name__,
                        "error_message": str(response),
                        "failure_scope": "rate_limit",
                    }
                )
            raise response
        if on_attempt:
            on_attempt(
                {
                    "status": "succeeded",
                    "key_slot": 2,
                    "key_fingerprint": "def456",
                    "credential_type": "api_key",
                    "latency_ms": 6,
                }
            )
        return operation(response)


class RateLimit(RuntimeError):
    status_code = 429


def _ledger(tmp_path: Path) -> ObservabilityLedger:
    return ObservabilityLedger(
        tmp_path / "ledger.sqlite3",
        tmp_path / "artifacts",
    )


def test_ledger_persists_redacted_payload_usage_and_attempts(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    project_id = uuid4()
    spec = ModelCallSpec(
        project_id=project_id,
        stage="document_map",
        operation="structured_text",
        provider="gemini",
        requested_model="gemini-test",
        timeout_ms=30_000,
    )

    ledger.begin_call(
        spec,
        {
            "api_key": "AIzaABCDEFGHIJKLMNOPQRSTUVWXY",
            "authorization": "Bearer private",
            "prompt": "safe text",
        },
    )
    ledger.record_attempt(
        spec.call_id,
        logical_attempt=1,
        provider_attempt=1,
        event={
            "status": "succeeded",
            "key_slot": 2,
            "key_fingerprint": "deadbeef",
            "credential_type": "api_key",
            "latency_ms": 12,
        },
    )
    ledger.provider_succeeded(
        spec.call_id,
        response_payload={"text": "raw"},
        usage=ModelUsage(
            input_tokens=10,
            output_tokens=4,
            thinking_tokens=2,
            cached_tokens=3,
            total_tokens=16,
        ),
        provider_metadata=ProviderMetadata(
            resolved_model="gemini-test-001",
            finish_reason="STOP",
        ),
    )
    ledger.succeed(spec.call_id, {"value": "parsed"})

    detail = ledger.get_call(spec.call_id)
    assert detail.call.status == "succeeded"
    assert detail.call.total_tokens == 16
    assert detail.call.provider_attempt_count == 1
    assert detail.attempts[0].key_slot == 2
    request = ledger.read_artifact(detail.request_artifact_path or "")
    assert "Bearer private" not in request
    assert "AIzaABCDEFGHIJKLMNOPQRSTUVWXY" not in request
    assert "[REDACTED]" in request

    summary = ledger.project_summary(project_id)
    assert summary.call_count == 1
    assert summary.total_tokens == 16
    assert summary.cached_tokens == 3


def test_gateway_records_retry_backoff_and_final_success(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    project_id = uuid4()
    spec = ModelCallSpec(
        project_id=project_id,
        stage="source_discovery",
        operation="google_search",
        provider="gemini",
        requested_model="gemini-test",
    )
    gateway = ObservedModelGateway(ledger, sleeper=lambda _: None)
    pool = FakePool([RateLimit("quota"), SimpleNamespace(text="ok")])

    result = gateway.call(
        spec=spec,
        request_payload={"query": "topic"},
        operation=lambda client: client,
        pool=pool,
        max_provider_attempts=2,
        retryable_error=lambda error: isinstance(error, RateLimit),
        response_payload=lambda response: {"text": response.text},
        usage=lambda _: ModelUsage(input_tokens=2, output_tokens=1, total_tokens=3),
        provider_metadata=lambda _: ProviderMetadata(resolved_model="gemini-test"),
    )
    ledger.succeed(result.call_id, {"result": "ok"})

    detail = ledger.get_call(spec.call_id)
    assert detail.call.status == "succeeded"
    assert detail.retry_scheduled is True
    assert detail.call.provider_attempt_count == 2
    assert [attempt.status for attempt in detail.attempts] == [
        "quota_failed",
        "succeeded",
    ]


def test_rejected_call_remains_linked_to_trace(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    trace_id = uuid4()
    spec = ModelCallSpec(
        trace_id=trace_id,
        project_id=uuid4(),
        stage="evidence_extraction",
        operation="structured_text",
        provider="gemini",
        requested_model="gemini-test",
    )
    ledger.begin_call(spec, {"prompt": "x"})
    ledger.provider_succeeded(
        spec.call_id,
        response_payload={"text": "bad schema"},
        usage=ModelUsage(total_tokens=1),
        provider_metadata=ProviderMetadata(),
    )
    ledger.reject(spec.call_id, ValueError("validator rejected output"))

    detail = ledger.get_call(spec.call_id)
    assert detail.call.trace_id == trace_id
    assert detail.call.status == "rejected"
    assert detail.call.error_type == "ValueError"


def test_artifact_path_cannot_escape_root(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    with pytest.raises(ValueError):
        ledger.read_artifact("../../etc/passwd")
