from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from thesisound.modeling import ModelUsage
from thesisound.observability import ModelCallSpec, ProviderMetadata
from thesisound.services.observability_rollup import ObservabilityRollup
from thesisound.tracing import EventRecord, SpanContext, SpanRecord


def _span(ledger, *, trace_id, project_id, span_id, name, duration_ms, parent=None):
    started = datetime(2026, 1, 1, tzinfo=UTC)
    record = SpanRecord(
        context=SpanContext(trace_id=trace_id, span_id=span_id, project_id=project_id),
        parent_span_id=parent,
        name=name,
        component="test",
        kind="stage",
        subject_type=None,
        subject_id=None,
        started_at=started,
        process="test",
        pid=1,
    )
    ledger.start_span(record)
    record.status = "ok"
    record.ended_at = started + timedelta(milliseconds=duration_ms)
    record.duration_ms = duration_ms
    ledger.end_span(record)


def test_rollup_owns_self_time_cache_usage_and_cost_views(ledger) -> None:
    project_id = uuid4()
    trace_id = uuid4()
    root = uuid4()
    child = uuid4()
    _span(
        ledger, trace_id=trace_id, project_id=project_id, span_id=root, name="run", duration_ms=1000
    )
    _span(
        ledger,
        trace_id=trace_id,
        project_id=project_id,
        span_id=child,
        name="child",
        duration_ms=400,
        parent=root,
    )
    for result in ("hit", "miss"):
        ledger.record_event(
            EventRecord(
                event_id=uuid4(),
                trace_id=trace_id,
                span_id=root,
                project_id=project_id,
                workflow_run_id=None,
                level="info",
                subject_type=None,
                subject_id=None,
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
                name="cache.lookup",
                component="cache",
                attributes={"cache": "document_map", "result": result},
            )
        )

    spec = ModelCallSpec(
        project_id=project_id,
        stage="document_map",
        operation="structured_text",
        provider="test",
        requested_model="unpriced-model",
    )
    ledger.begin_call(spec, {"prompt": "x"})
    ledger.provider_succeeded(
        spec.call_id,
        response_payload={"text": "ok"},
        usage=ModelUsage(input_tokens=2, output_tokens=1, total_tokens=3),
        provider_metadata=ProviderMetadata(resolved_model="unpriced-model"),
    )
    ledger.succeed(spec.call_id, {"ok": True})

    rollup = ObservabilityRollup(ledger)
    stages = {row.name: row for row in rollup.stage_summary(project_id)}
    assert stages["run"].total_ms == 1000
    assert stages["run"].self_total_ms == 600
    assert stages["child"].self_total_ms == 400
    cache = rollup.cache_hit_rates(project_id)[0]
    assert cache.cache == "document_map"
    assert cache.hit_rate == 0.5
    summary = rollup.project_summary(project_id)
    assert summary.call_count == 1
    assert summary.total_tokens == 3
    assert summary.unpriced_succeeded_count == 1
    cost = rollup.cost_breakdown(project_id)[0]
    assert cost.unpriced_count == 1
