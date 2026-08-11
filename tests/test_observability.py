from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from thesisound import tracing
from thesisound.modeling import ModelUsage
from thesisound.observability import (
    SENSITIVE_ATTRIBUTES,
    CostResult,
    ModelCallSpec,
    ObservabilityLedger,
    ObservedModelGateway,
    ProviderMetadata,
    redact_value,
)
from thesisound.services.observability_rollup import ObservabilityRollup


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

    summary = ObservabilityRollup(ledger).project_summary(project_id)
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


def test_model_call_spec_picks_up_the_ambient_span_by_default(
    recording_tracer: tracing.Tracer,
) -> None:
    with tracing.span("corpus.extract_evidence") as span:
        spec = ModelCallSpec(
            stage="evidence_extraction",
            operation="structured_text",
            provider="gemini",
            requested_model="gemini-test",
        )

    assert spec.pipeline_trace_id == span.context.trace_id
    assert spec.parent_span_id == span.context.span_id


def test_model_call_spec_has_no_ambient_ids_outside_any_span() -> None:
    spec = ModelCallSpec(
        stage="evidence_extraction",
        operation="structured_text",
        provider="gemini",
        requested_model="gemini-test",
    )

    assert spec.pipeline_trace_id is None
    assert spec.parent_span_id is None


def test_model_call_spec_explicit_ids_override_the_ambient_span(
    recording_tracer: tracing.Tracer,
) -> None:
    explicit_trace = uuid4()
    with tracing.span("corpus.extract_evidence"):
        spec = ModelCallSpec(
            stage="evidence_extraction",
            operation="structured_text",
            provider="gemini",
            requested_model="gemini-test",
            pipeline_trace_id=explicit_trace,
        )

    assert spec.pipeline_trace_id == explicit_trace


def test_ledger_persists_and_returns_the_pipeline_trace_join(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    ledger = _ledger(tmp_path)
    with tracing.span("corpus.extract_evidence") as span:
        spec = ModelCallSpec(
            stage="evidence_extraction",
            operation="structured_text",
            provider="gemini",
            requested_model="gemini-test",
        )
        ledger.begin_call(spec, {"prompt": "x"})

    detail = ledger.get_call(spec.call_id)
    assert detail.pipeline_trace_id == span.context.trace_id
    assert detail.parent_span_id == span.context.span_id


def test_artifact_path_cannot_escape_root(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    with pytest.raises(ValueError):
        ledger.read_artifact("../../etc/passwd")


def test_redaction_covers_phone_numbers_secrets_and_home_paths(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    spec = ModelCallSpec(
        stage="web_source_capture",
        operation="url_context",
        provider="gemini",
        requested_model="gemini-test",
    )
    ledger.begin_call(
        spec,
        {
            "user_phone": "09120000000",
            "note": "caller is 0912 000 0000-free text: 09121234567",
            "generic_token": "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "path": r"C:\Users\mhghotbi\Documents\Git\thesisound\workspaces\p\file.pdf",
            "web_session_secret": "development-only-session-key",
        },
    )
    request = ledger.read_artifact(ledger.get_call(spec.call_id).request_artifact_path or "")
    assert "09120000000" not in request
    assert "09121234567" not in request
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in request
    assert r"Users\mhghotbi" not in request
    assert "development-only-session-key" not in request
    assert "[REDACTED_PHONE]" in request
    assert "[REDACTED_SECRET]" in request
    assert "[HOME]" in request
    assert "[REDACTED]" in request


class FakePricer:
    """A ``CostPricer`` test double: prices anything named ``priced-model``
    at a fixed per-token rate, and returns ``None`` for everything else --
    the same "unknown, not zero" contract ``CostCalculator`` has to honor."""

    def __init__(self, *, version: str = "test-2026-01") -> None:
        self.version = version
        self.calls: list[str] = []

    def price(
        self,
        *,
        provider,
        model,
        operation,
        started_at,
        input_tokens,
        output_tokens,
        cached_tokens,
    ) -> CostResult | None:
        self.calls.append(model)
        if model != "priced-model":
            return None
        return CostResult(
            cost_micros=(input_tokens or 0) * 10 + (output_tokens or 0) * 20,
            pricing_version=self.version,
        )


def _succeed_a_call(ledger: ObservabilityLedger, *, model: str, started_at=None) -> ModelCallSpec:
    spec = ModelCallSpec(
        stage="document_map",
        operation="structured_text",
        provider="gemini",
        requested_model=model,
    )
    ledger.begin_call(spec, {"prompt": "x"})
    if started_at is not None:
        connection = sqlite3.connect(ledger.database_path)
        try:
            connection.execute(
                "UPDATE model_calls SET started_at = ? WHERE call_id = ?",
                (started_at.astimezone(UTC).isoformat(), str(spec.call_id)),
            )
            connection.commit()
        finally:
            connection.close()
    ledger.provider_succeeded(
        spec.call_id,
        response_payload={"text": "ok"},
        usage=ModelUsage(input_tokens=100, output_tokens=50, total_tokens=150),
        provider_metadata=ProviderMetadata(),
    )
    ledger.succeed(spec.call_id, {"value": "ok"})
    return spec


def test_succeed_persists_cost_from_the_configured_pricer(tmp_path: Path) -> None:
    pricer = FakePricer()
    ledger = ObservabilityLedger(
        tmp_path / "ledger.sqlite3", tmp_path / "artifacts", cost_pricer=pricer
    )

    spec = _succeed_a_call(ledger, model="priced-model")

    detail = ledger.get_call(spec.call_id)
    assert detail.call.cost_micros == 100 * 10 + 50 * 20
    assert detail.call.pricing_version == "test-2026-01"


def test_succeed_leaves_cost_unset_when_the_pricer_returns_none(tmp_path: Path) -> None:
    """An unpriced model must render as unknown, never a silent 0 -- this is
    the single most important behavior the whole cost feature promises."""

    ledger = ObservabilityLedger(
        tmp_path / "ledger.sqlite3", tmp_path / "artifacts", cost_pricer=FakePricer()
    )

    spec = _succeed_a_call(ledger, model="unpriced-model")

    detail = ledger.get_call(spec.call_id)
    assert detail.call.cost_micros is None
    assert detail.call.pricing_version is None


def test_succeed_leaves_cost_unset_with_no_pricer_configured(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)  # no cost_pricer at all

    spec = _succeed_a_call(ledger, model="priced-model")

    detail = ledger.get_call(spec.call_id)
    assert detail.call.cost_micros is None


@pytest.mark.parametrize("terminal", ["reject", "fail"])
def test_terminal_failures_persist_priced_retry_spend(tmp_path: Path, terminal: str) -> None:
    ledger = ObservabilityLedger(
        tmp_path / "ledger.sqlite3", tmp_path / "artifacts", cost_pricer=FakePricer()
    )
    spec = ModelCallSpec(
        stage="evidence_extraction",
        operation="structured_text",
        provider="gemini",
        requested_model="priced-model",
    )
    ledger.begin_call(spec, {"prompt": "x"})
    ledger.provider_succeeded(
        spec.call_id,
        response_payload={"text": "bad"},
        usage=ModelUsage(input_tokens=100, output_tokens=50, total_tokens=150),
        provider_metadata=ProviderMetadata(),
    )

    getattr(ledger, terminal)(spec.call_id, ValueError("bad output"))

    detail = ledger.get_call(spec.call_id)
    assert detail.call.status == ("rejected" if terminal == "reject" else "failed")
    assert detail.call.cost_micros == 2_000
    assert detail.call.pricing_version == "test-2026-01"


def test_failed_call_without_usage_is_priced_as_zero_not_unknown(tmp_path: Path) -> None:
    ledger = ObservabilityLedger(
        tmp_path / "ledger.sqlite3", tmp_path / "artifacts", cost_pricer=FakePricer()
    )
    spec = ModelCallSpec(
        stage="evidence_extraction",
        operation="structured_text",
        provider="gemini",
        requested_model="priced-model",
    )
    ledger.begin_call(spec, {"prompt": "x"})
    ledger.fail(spec.call_id, ConnectionError("reset"))

    assert ledger.get_call(spec.call_id).call.cost_micros == 0


def test_reprice_includes_rejected_and_failed_calls(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    rejected = ModelCallSpec(
        stage="evidence_extraction",
        operation="structured_text",
        provider="gemini",
        requested_model="priced-model",
    )
    failed = rejected.model_copy(update={"call_id": uuid4()})
    for spec, terminal in ((rejected, "reject"), (failed, "fail")):
        ledger.begin_call(spec, {"prompt": "x"})
        ledger.provider_succeeded(
            spec.call_id,
            response_payload={"text": "bad"},
            usage=ModelUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            provider_metadata=ProviderMetadata(),
        )
        getattr(ledger, terminal)(spec.call_id, ValueError("bad output"))

    assert ledger.reprice(FakePricer()) == 2
    assert ledger.get_call(rejected.call_id).call.cost_micros == 2_000
    assert ledger.get_call(failed.call_id).call.cost_micros == 2_000


def test_reprice_recomputes_cost_for_already_succeeded_calls(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    spec = _succeed_a_call(ledger, model="priced-model")
    assert ledger.get_call(spec.call_id).call.cost_micros is None

    updated = ledger.reprice(FakePricer(version="retroactive-2026-02"))

    assert updated == 1
    detail = ledger.get_call(spec.call_id)
    assert detail.call.cost_micros == 100 * 10 + 50 * 20
    assert detail.call.pricing_version == "retroactive-2026-02"


def test_reprice_skips_calls_the_pricer_still_does_not_know(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _succeed_a_call(ledger, model="still-unpriced")

    updated = ledger.reprice(FakePricer())

    assert updated == 0


def test_reprice_only_touches_calls_on_or_after_since(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    old = _succeed_a_call(ledger, model="priced-model", started_at=datetime(2025, 1, 1, tzinfo=UTC))
    recent = _succeed_a_call(
        ledger, model="priced-model", started_at=datetime(2026, 6, 1, tzinfo=UTC)
    )

    updated = ledger.reprice(FakePricer(), since=datetime(2026, 1, 1, tzinfo=UTC))

    assert updated == 1
    assert ledger.get_call(old.call_id).call.cost_micros is None
    assert ledger.get_call(recent.call_id).call.cost_micros is not None


def test_cost_breakdown_groups_by_stage_provider_and_model(tmp_path: Path) -> None:
    pricer = FakePricer()
    ledger = ObservabilityLedger(
        tmp_path / "ledger.sqlite3", tmp_path / "artifacts", cost_pricer=pricer
    )
    project_id = uuid4()
    for _ in range(2):
        spec = ModelCallSpec(
            project_id=project_id,
            stage="document_map",
            operation="structured_text",
            provider="gemini",
            requested_model="priced-model",
        )
        ledger.begin_call(spec, {"prompt": "x"})
        ledger.provider_succeeded(
            spec.call_id,
            response_payload={"text": "ok"},
            usage=ModelUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            provider_metadata=ProviderMetadata(),
        )
        ledger.succeed(spec.call_id, {"value": "ok"})

    rows = ObservabilityRollup(ledger).cost_breakdown(project_id)

    assert len(rows) == 1
    row = rows[0]
    assert (row.stage, row.provider, row.model) == ("document_map", "gemini", "priced-model")
    assert row.call_count == 2
    assert row.unpriced_count == 0
    assert row.total_cost_micros == 2 * (100 * 10 + 50 * 20)
    assert row.total_tokens == 2 * 150


def test_project_summary_reports_cost_and_unpriced_count(tmp_path: Path) -> None:
    pricer = FakePricer()
    ledger = ObservabilityLedger(
        tmp_path / "ledger.sqlite3", tmp_path / "artifacts", cost_pricer=pricer
    )
    project_id = uuid4()
    for model in ("priced-model", "unpriced-model"):
        spec = ModelCallSpec(
            project_id=project_id,
            stage="document_map",
            operation="structured_text",
            provider="gemini",
            requested_model=model,
        )
        ledger.begin_call(spec, {"prompt": "x"})
        ledger.provider_succeeded(
            spec.call_id,
            response_payload={"text": "ok"},
            usage=ModelUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            provider_metadata=ProviderMetadata(),
        )
        ledger.succeed(spec.call_id, {"value": "ok"})

    summary = ObservabilityRollup(ledger).project_summary(project_id)

    assert summary.total_cost_micros == 100 * 10 + 50 * 20  # only priced-model counted
    assert summary.unpriced_succeeded_count == 1


def test_cost_rollups_keep_delivered_and_wasted_spend_separate(tmp_path: Path) -> None:
    ledger = ObservabilityLedger(
        tmp_path / "ledger.sqlite3", tmp_path / "artifacts", cost_pricer=FakePricer()
    )
    project_id = uuid4()
    for terminal in ("succeed", "reject"):
        spec = ModelCallSpec(
            project_id=project_id,
            stage="evidence_extraction",
            operation="structured_text",
            provider="gemini",
            requested_model="priced-model",
        )
        ledger.begin_call(spec, {"prompt": "x"})
        ledger.provider_succeeded(
            spec.call_id,
            response_payload={"text": "ok"},
            usage=ModelUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            provider_metadata=ProviderMetadata(),
        )
        if terminal == "succeed":
            ledger.succeed(spec.call_id, {"value": "ok"})
        else:
            ledger.reject(spec.call_id, ValueError("bad output"))

    summary = ObservabilityRollup(ledger).project_summary(project_id)
    row = ObservabilityRollup(ledger).cost_breakdown(project_id)[0]
    assert summary.total_cost_micros == 2_000
    assert summary.wasted_cost_micros == 2_000
    assert row.call_count == 2
    assert row.wasted_call_count == 1
    assert row.total_cost_micros == row.wasted_cost_micros == 2_000


def test_sensitive_attribute_policy_uses_one_payload_switch(tmp_path: Path) -> None:
    project_id = uuid4()
    metadata = {
        "query": "پرسش خصوصی",
        "topic": "موضوع خصوصی",
        "filename": "نام شخصی.pdf",
        "size_bytes": 1234,
        "phone": "09121234567",
    }

    private = ObservabilityLedger(
        tmp_path / "private.sqlite3",
        tmp_path / "private-artifacts",
        store_payloads=False,
    )
    spec = ModelCallSpec(
        project_id=project_id,
        stage="source_discovery",
        operation="google_search",
        provider="gemini",
        requested_model="gemini-test",
        metadata=metadata,
    )
    private.begin_call(spec, {"prompt": "متن خصوصی"})
    stored = private.get_call(spec.call_id).metadata
    assert stored["query"]["sha256"]
    assert stored["query"]["length"] == len("پرسش خصوصی")
    assert stored["topic"]["sha256"]
    assert stored["filename"] == {
        "filename_sha256": stored["filename"]["filename_sha256"],
        "extension": ".pdf",
        "size_bytes": 1234,
    }
    assert len(stored["filename"]["filename_sha256"]) == 16
    assert stored["phone"] == "[REDACTED]"
    assert set(SENSITIVE_ATTRIBUTES) == {
        "query",
        "text",
        "excerpt",
        "filename",
        "topic",
        "phone",
        "prompt",
    }

    private_second = ObservabilityLedger(
        tmp_path / "private-second.sqlite3",
        tmp_path / "private-second-artifacts",
        store_payloads=False,
    )
    second_spec = spec.model_copy(update={"call_id": uuid4()})
    private_second.begin_call(second_spec, {"prompt": "متن خصوصی"})
    second = private_second.get_call(second_spec.call_id).metadata
    assert second["query"]["sha256"] == stored["query"]["sha256"]
    assert second["filename"]["filename_sha256"] == stored["filename"]["filename_sha256"]
    assert (
        redact_value({"query": stored["query"]}, store_payloads=False)["query"] == stored["query"]
    )

    payloads = ObservabilityLedger(
        tmp_path / "payloads.sqlite3",
        tmp_path / "payload-artifacts",
        store_payloads=True,
    )
    payload_spec = spec.model_copy(update={"call_id": uuid4()})
    payloads.begin_call(payload_spec, {"prompt": "متن خصوصی"})
    visible = payloads.get_call(payload_spec.call_id).metadata
    assert visible["query"] == "پرسش خصوصی"
    assert visible["topic"] == "موضوع خصوصی"
    assert "نام شخصی.pdf" not in str(visible["filename"])
    assert visible["phone"] == "[REDACTED]"


def test_exception_messages_are_redacted_before_model_persistence(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    spec = ModelCallSpec(
        stage="document_map",
        operation="structured_text",
        provider="gemini",
        requested_model="gemini-test",
    )
    ledger.begin_call(spec, {"prompt": "x"})
    ledger.record_attempt(
        spec.call_id,
        logical_attempt=1,
        provider_attempt=1,
        event={
            "status": "failed",
            "error_message": "phone 09121234567 key sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ /home/alice/file",
        },
    )
    ledger.fail(
        spec.call_id,
        RuntimeError("phone 09121234567 key sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ /home/alice/file"),
    )

    detail = ledger.get_call(spec.call_id)
    rendered = f"{detail.call.error_message} {detail.attempts[0].error_message}"
    assert "09121234567" not in rendered
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in rendered
    assert "/home/alice" not in rendered
    assert "[REDACTED_PHONE]" in rendered
    assert "[REDACTED_SECRET]" in rendered
    assert "[HOME]" in rendered
