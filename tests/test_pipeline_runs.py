from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from thesisound.modeling import ModelUsage
from thesisound.observability import (
    ModelCallSpec,
    ObservabilityLedger,
    PipelineRunSpec,
    ProviderMetadata,
)


def _begin_run(ledger: ObservabilityLedger, run_id: UUID, project_id: UUID) -> None:
    ledger.begin_run(
        PipelineRunSpec(
            workflow_run_id=run_id,
            project_id=project_id,
            trace_id=uuid4(),
            kind="script",
            started_at=datetime.now(UTC),
        )
    )


def _record_call(
    ledger: ObservabilityLedger,
    *,
    run_id: UUID,
    model: str,
    prompt_id: str,
    prompt_version: str,
    status: str = "succeeded",
    input_tokens: int = 3,
    output_tokens: int = 5,
) -> None:
    spec = ModelCallSpec(
        workflow_run_id=run_id,
        stage=prompt_id,
        operation="structured_text",
        provider="gemini",
        requested_model=model,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
    )
    ledger.begin_call(spec, {"prompt": "test"})
    if status == "failed":
        ledger.fail(spec.call_id, RuntimeError("failed"))
        return
    if status == "rejected":
        ledger.reject(spec.call_id, ValueError("rejected"))
        return
    ledger.provider_succeeded(
        spec.call_id,
        response_payload={"ok": True},
        usage=ModelUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=2,
            cached_tokens=1,
            total_tokens=input_tokens + output_tokens + 2,
        ),
        provider_metadata=ProviderMetadata(resolved_model=model),
    )
    ledger.succeed(spec.call_id, {"ok": True})


def test_run_totals_are_scoped_and_collect_distinct_metadata(
    ledger: ObservabilityLedger,
) -> None:
    project_id = uuid4()
    run_id = uuid4()
    other_run_id = uuid4()
    _begin_run(ledger, run_id, project_id)
    _begin_run(ledger, other_run_id, project_id)
    _record_call(
        ledger, run_id=run_id, model="model-a", prompt_id="writer", prompt_version="1.0.0"
    )
    _record_call(
        ledger, run_id=run_id, model="model-a", prompt_id="writer", prompt_version="1.0.0"
    )
    _record_call(
        ledger,
        run_id=run_id,
        model="model-b",
        prompt_id="reviewer",
        prompt_version="1.1.0",
        input_tokens=7,
        output_tokens=11,
    )
    _record_call(
        ledger,
        run_id=run_id,
        model="model-b",
        prompt_id="failed",
        prompt_version="1.0.0",
        status="failed",
    )
    _record_call(
        ledger,
        run_id=run_id,
        model="model-b",
        prompt_id="rejected",
        prompt_version="1.0.0",
        status="rejected",
    )
    _record_call(
        ledger,
        run_id=other_run_id,
        model="leak",
        prompt_id="other",
        prompt_version="9.9.9",
        input_tokens=100,
    )

    ledger.finish_run(run_id, status="succeeded")
    summary = ledger.run_summary(run_id)

    assert summary.call_count == 5
    assert summary.failed_call_count == 2
    assert summary.input_tokens == 13
    assert summary.output_tokens == 21
    assert summary.thinking_tokens == 6
    assert summary.cached_tokens == 3
    assert summary.total_tokens == 40
    assert summary.models == ["model-a", "model-b"]
    assert summary.prompt_versions == [
        "failed@1.0.0",
        "rejected@1.0.0",
        "reviewer@1.1.0",
        "writer@1.0.0",
    ]


def test_zero_call_run_and_finish_are_idempotent(ledger: ObservabilityLedger) -> None:
    project_id = uuid4()
    run_id = uuid4()
    _begin_run(ledger, run_id, project_id)

    ledger.finish_run(run_id, status="succeeded")
    first = ledger.run_summary(run_id)
    ledger.finish_run(run_id, status="succeeded")
    second = ledger.run_summary(run_id)

    assert first == second
    assert second.call_count == 0
    assert second.failed_call_count == 0
    assert second.total_tokens == 0
    assert second.models == []
    assert second.prompt_versions == []


def test_finish_unknown_run_is_a_no_op(ledger: ObservabilityLedger) -> None:
    ledger.finish_run(uuid4(), status="failed", error_message="missing")
