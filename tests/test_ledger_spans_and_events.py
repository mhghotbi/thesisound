"""End-to-end tests for the tracer writing through a real SQLite ledger:
LedgerSpanSink -> ObservabilityLedger.{start_span,end_span,record_event} ->
pipeline_spans / pipeline_events. tests/test_tracing.py covers the pure
Tracer/Span logic against an in-memory sink; this file proves the SQL side.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from thesisound import tracing
from thesisound.modeling import ModelUsage
from thesisound.observability import (
    LedgerSpanSink,
    ModelCallSpec,
    ObservabilityLedger,
    ProviderMetadata,
)
from thesisound.tracing import EventRecord, SpanContext, SpanRecord, Tracer


def _ledger_tracer(ledger: ObservabilityLedger, **kwargs: object) -> Tracer:
    return Tracer(LedgerSpanSink(ledger), **kwargs)


def test_a_completed_span_round_trips_through_the_ledger(ledger: ObservabilityLedger) -> None:
    project_id = uuid4()
    ledger_tracer = _ledger_tracer(ledger)

    with ledger_tracer.span(
        "corpus.run", component="corpus", kind="stage", project_id=project_id
    ) as span:
        span.set(source_count=2)
        span.measure(claim_count=7)

    stored = ledger.get_span(span.context.span_id)
    assert stored.name == "corpus.run"
    assert stored.component == "corpus"
    assert stored.kind == "stage"
    assert stored.status == "ok"
    assert stored.project_id == project_id
    assert stored.attributes["source_count"] == 2
    assert stored.metrics["claim_count"] == 7
    assert stored.duration_ms is not None
    assert stored.ended_at is not None


def test_span_is_visible_as_running_before_it_completes(ledger: ObservabilityLedger) -> None:
    """Every span writes through on begin (not just 'stage' kind), so an
    in-progress operation is visible in the ledger while it is still open."""

    ledger_tracer = _ledger_tracer(ledger)
    context: SpanContext | None = None
    with ledger_tracer.span("ingestion.parse", subject_id="mineru") as span:
        context = span.context
        mid_flight = ledger.get_span(span.context.span_id)
        assert mid_flight.status == "running"
        assert mid_flight.ended_at is None

    assert context is not None
    finished = ledger.get_span(context.span_id)
    assert finished.status == "ok"


def test_parent_child_spans_persist_with_a_shared_trace_id(ledger: ObservabilityLedger) -> None:
    ledger_tracer = _ledger_tracer(ledger)
    project_id = uuid4()

    with (
        ledger_tracer.span("corpus.run", kind="stage", project_id=project_id) as root,
        ledger_tracer.span("corpus.source", kind="stage", subject_id="src-1"),
        ledger_tracer.span("corpus.extract_evidence"),
    ):
        pass

    spans = ledger.list_spans(root.context.trace_id)
    by_name = {span.name: span for span in spans}
    assert len(spans) == 3
    assert by_name["corpus.source"].parent_span_id == by_name["corpus.run"].span_id
    assert by_name["corpus.extract_evidence"].parent_span_id == by_name["corpus.source"].span_id
    assert all(span.trace_id == root.context.trace_id for span in spans)


def test_error_status_and_message_persist(ledger: ObservabilityLedger) -> None:
    ledger_tracer = _ledger_tracer(ledger)
    with pytest.raises(ValueError, match="boom"), ledger_tracer.span("ingestion.parse") as span:
        raise ValueError("boom")

    stored = ledger.get_span(span.context.span_id)
    assert stored.status == "error"
    assert stored.error_type == "ValueError"
    assert stored.error_message == "boom"


def test_span_attributes_are_redacted_before_storage(ledger: ObservabilityLedger) -> None:
    ledger_tracer = _ledger_tracer(ledger)
    leaked_key = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXY"
    with ledger_tracer.span("web_source_capture.import", api_key=leaked_key) as span:
        pass

    stored = ledger.get_span(span.context.span_id)
    assert stored.attributes["api_key"] == "[REDACTED]"


def test_events_are_append_only_and_link_to_the_open_span(ledger: ObservabilityLedger) -> None:
    ledger_tracer = _ledger_tracer(ledger)
    with ledger_tracer.span("corpus.map_document") as span:
        ledger_tracer.event("cache.lookup", cache="document_map", result="hit")

    events = ledger.list_events(span.context.trace_id)
    assert len(events) == 1
    assert events[0].name == "cache.lookup"
    assert events[0].span_id == span.context.span_id
    assert events[0].attributes == {"cache": "document_map", "result": "hit"}


def test_state_transition_event_has_no_span_when_recorded_outside_a_span(
    ledger: ObservabilityLedger,
) -> None:
    import sqlite3

    project_id = uuid4()
    ledger_tracer = _ledger_tracer(ledger)
    ledger_tracer.event(
        "project.state_changed", project_id=project_id, previous="DRAFT", current="BRIEF_READY"
    )

    # No trace_id was supplied and there is no ambient span, so this event
    # is only reachable by project_id -- pipeline.transition() runs outside
    # any span today, and this is exactly that shape.
    connection = sqlite3.connect(ledger.database_path)
    try:
        row = connection.execute(
            "SELECT name, trace_id, span_id, level FROM pipeline_events WHERE project_id = ?",
            (str(project_id),),
        ).fetchone()
    finally:
        connection.close()

    assert row == ("project.state_changed", None, None, "info")


def test_list_recent_traces_returns_newest_first(ledger: ObservabilityLedger) -> None:
    project_id = uuid4()
    ledger_tracer = _ledger_tracer(ledger)

    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}

    def advancing_clock() -> datetime:
        clock["now"] += timedelta(seconds=1)
        return clock["now"]

    ledger_tracer.clock = advancing_clock
    trace_ids = []
    for _ in range(3):
        with ledger_tracer.span("corpus.run", kind="stage", project_id=project_id) as root:
            pass
        trace_ids.append(root.context.trace_id)

    recent = ledger.list_recent_traces(project_id, limit=2)
    assert recent == [trace_ids[2], trace_ids[1]]


def test_reap_orphaned_spans_marks_stale_running_spans_interrupted(
    ledger: ObservabilityLedger,
) -> None:
    context = SpanContext(trace_id=uuid4(), span_id=uuid4(), project_id=uuid4())
    stale_record = SpanRecord(
        context=context,
        parent_span_id=None,
        name="corpus.run",
        component="corpus",
        kind="stage",
        subject_type=None,
        subject_id=None,
        started_at=datetime.now(UTC) - timedelta(hours=2),
        process="web",
        pid=1234,
    )
    ledger.start_span(stale_record)

    reaped = ledger.reap_orphaned_spans(older_than_minutes=60)

    assert reaped == 1
    stored = ledger.get_span(context.span_id)
    assert stored.status == "interrupted"
    assert stored.ended_at is not None
    events = ledger.list_events(context.trace_id)
    assert len(events) == 1
    assert events[0].name == "run.recovered"
    assert events[0].level == "warn"


def test_reap_orphaned_spans_leaves_recent_running_spans_alone(
    ledger: ObservabilityLedger,
) -> None:
    context = SpanContext(trace_id=uuid4(), span_id=uuid4())
    fresh_record = SpanRecord(
        context=context,
        parent_span_id=None,
        name="corpus.run",
        component="corpus",
        kind="stage",
        subject_type=None,
        subject_id=None,
        started_at=datetime.now(UTC),
        process="web",
        pid=1234,
    )
    ledger.start_span(fresh_record)

    reaped = ledger.reap_orphaned_spans(older_than_minutes=60)

    assert reaped == 0
    assert ledger.get_span(context.span_id).status == "running"


def test_reap_orphaned_spans_does_not_touch_completed_spans(ledger: ObservabilityLedger) -> None:
    ledger_tracer = _ledger_tracer(ledger)
    with ledger_tracer.span("corpus.run", kind="stage") as span:
        pass

    reaped = ledger.reap_orphaned_spans(older_than_minutes=0)

    assert reaped == 0
    assert ledger.get_span(span.context.span_id).status == "ok"


def test_installed_ledger_tracer_is_reachable_through_module_functions(
    ledger: ObservabilityLedger,
) -> None:
    real_tracer = _ledger_tracer(ledger)
    previous = tracing.tracer()
    tracing.install_tracer(real_tracer)
    try:
        with tracing.span("corpus.run", kind="stage") as span:
            pass
    finally:
        tracing.install_tracer(previous)

    assert ledger.get_span(span.context.span_id).status == "ok"


def test_event_record_type_is_exported_for_sink_implementers() -> None:
    # EventRecord/SpanRecord are the public contract a SpanSink implements
    # against; guard that observability.py's re-use of them still matches
    # tracing.py's shape (a refactor that silently drops a field here would
    # otherwise only surface as a TypeError deep inside a request handler).
    assert {"event_id", "trace_id", "span_id", "attributes"} <= set(EventRecord.__annotations__)


def test_list_events_by_project_includes_events_recorded_outside_any_span(
    ledger: ObservabilityLedger,
) -> None:
    ledger_tracer = _ledger_tracer(ledger)
    project_id = uuid4()
    ledger_tracer.event(
        "project.state_changed", project_id=project_id, previous="DRAFT", current="BRIEF_READY"
    )
    with ledger_tracer.span("corpus.run", kind="stage", project_id=project_id):
        ledger_tracer.event("cache.lookup", project_id=project_id, result="hit")

    events = ledger.list_events_by_project(project_id)

    assert {event.name for event in events} == {"project.state_changed", "cache.lookup"}


def test_list_events_by_project_is_newest_first(ledger: ObservabilityLedger) -> None:
    project_id = uuid4()
    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}

    def advancing_clock() -> datetime:
        clock["now"] += timedelta(seconds=1)
        return clock["now"]

    ledger_tracer = _ledger_tracer(ledger, clock=advancing_clock)
    ledger_tracer.event("first", project_id=project_id)
    ledger_tracer.event("second", project_id=project_id)

    events = ledger.list_events_by_project(project_id)

    assert [event.name for event in events] == ["second", "first"]


def test_stage_summary_ranks_by_total_duration(ledger: ObservabilityLedger) -> None:
    project_id = uuid4()
    clock = {"now": 0.0}

    def advancing_monotonic() -> float:
        clock["now"] += 1
        return clock["now"]

    ledger_tracer = _ledger_tracer(ledger, monotonic=advancing_monotonic)
    with ledger_tracer.span("corpus.run", kind="stage", project_id=project_id):
        with ledger_tracer.span("corpus.source", kind="stage"):
            pass  # 1 second
        with ledger_tracer.span("corpus.extract_evidence"):
            pass  # 1 second
        with ledger_tracer.span("corpus.extract_evidence"):
            pass  # 1 second

    summary = {row.name: row for row in ledger.stage_summary(project_id)}

    assert summary["corpus.extract_evidence"].call_count == 2
    assert summary["corpus.source"].call_count == 1
    names_by_total_desc = [row.name for row in ledger.stage_summary(project_id)]
    # corpus.run's own span duration includes all its children's time, so it
    # naturally ranks first in this simple (non-self-time) rollup.
    assert names_by_total_desc[0] == "corpus.run"


def test_get_trace_unions_spans_and_model_calls_into_one_tree(
    ledger: ObservabilityLedger,
) -> None:
    """The trace_nodes view was created by the Phase 1 migration but never
    actually queried until get_trace() -- this proves it really unions the
    two tables rather than just being schema-valid SQL that happens to
    parse."""

    ledger_tracer = _ledger_tracer(ledger)
    project_id = uuid4()
    with ledger_tracer.span(
        "corpus.map_document", kind="stage", project_id=project_id
    ) as step:
        spec = ModelCallSpec(
            stage="document_map",
            operation="structured_text",
            provider="gemini",
            requested_model="gemini-test",
            project_id=project_id,
        )
        ledger.begin_call(spec, {"prompt": "x"})
        ledger.provider_succeeded(
            spec.call_id,
            response_payload={"text": "ok"},
            usage=ModelUsage(total_tokens=10),
            provider_metadata=ProviderMetadata(),
        )
        ledger.succeed(spec.call_id, {"value": "ok"})

    nodes = {node.node_id: node for node in ledger.get_trace(step.context.trace_id)}

    assert len(nodes) == 2
    step_node = nodes[step.context.span_id]
    call_node = nodes[spec.call_id]
    assert step_node.node_source == "span"
    assert call_node.node_source == "model_call"
    assert call_node.parent_id == step_node.node_id
    assert call_node.trace_id == step_node.trace_id
    assert call_node.name == "document_map/structured_text"
    assert call_node.status == "succeeded"


def test_get_trace_excludes_model_calls_made_outside_any_span(
    ledger: ObservabilityLedger,
) -> None:
    spec = ModelCallSpec(
        stage="document_map",
        operation="structured_text",
        provider="gemini",
        requested_model="gemini-test",
    )
    ledger.begin_call(spec, {"prompt": "x"})

    # No ambient span was open, so pipeline_trace_id is None -- this call
    # simply is not part of any trace, and get_trace() for some unrelated
    # trace_id must not accidentally surface it.
    assert ledger.get_trace(uuid4()) == []


def test_stage_summary_counts_errors_per_stage(ledger: ObservabilityLedger) -> None:
    project_id = uuid4()
    ledger_tracer = _ledger_tracer(ledger)
    for _ in range(2):
        try:
            with ledger_tracer.span("ingestion.parse", project_id=project_id):
                raise ValueError("boom")
        except ValueError:
            pass
    with ledger_tracer.span("ingestion.parse", project_id=project_id):
        pass

    summary = ledger.stage_summary(project_id)

    row = next(item for item in summary if item.name == "ingestion.parse")
    assert row.call_count == 3
    assert row.error_count == 2


def test_stage_summary_ranks_by_self_time_not_total_time(ledger: ObservabilityLedger) -> None:
    """A parent span's total_ms always includes everything nested inside it,
    so a total-time ranking always puts the outermost span first regardless
    of how little work it does itself. corpus.extract_evidence is where the
    5 leaf calls' time actually went; self time is what reveals that."""

    project_id = uuid4()
    clock = {"now": 0.0}

    def advancing_monotonic() -> float:
        clock["now"] += 1
        return clock["now"]

    ledger_tracer = _ledger_tracer(ledger, monotonic=advancing_monotonic)
    with (
        ledger_tracer.span("corpus.run", kind="stage", project_id=project_id),
        ledger_tracer.span("corpus.extract_evidence"),
    ):
        for _ in range(5):
            with ledger_tracer.span("model_call_leaf"):
                pass

    rows = {row.name: row for row in ledger.stage_summary(project_id)}

    assert rows["corpus.run"].total_ms > rows["corpus.extract_evidence"].total_ms
    assert rows["corpus.extract_evidence"].self_total_ms > rows["corpus.run"].self_total_ms
    ranked_by_self_time = [row.name for row in ledger.stage_summary(project_id)]
    assert ranked_by_self_time[0] == "corpus.extract_evidence"


def test_cache_hit_rates_groups_by_the_cache_attribute(ledger: ObservabilityLedger) -> None:
    project_id = uuid4()
    ledger_tracer = _ledger_tracer(ledger)
    ledger_tracer.event(
        "cache.lookup", project_id=project_id, cache="shared_document_map", result="hit"
    )
    ledger_tracer.event(
        "cache.lookup", project_id=project_id, cache="shared_document_map", result="hit"
    )
    ledger_tracer.event(
        "cache.lookup", project_id=project_id, cache="shared_document_map", result="miss"
    )
    ledger_tracer.event("cache.lookup", project_id=project_id, cache="episode_plan", result="miss")
    ledger_tracer.event("project.state_changed", project_id=project_id, previous="a", current="b")

    rows = {row.cache: row for row in ledger.cache_hit_rates(project_id)}

    assert rows["shared_document_map"].hits == 2
    assert rows["shared_document_map"].misses == 1
    assert rows["shared_document_map"].hit_rate == pytest.approx(2 / 3)
    assert rows["episode_plan"].hits == 0
    assert rows["episode_plan"].misses == 1
    assert rows["episode_plan"].hit_rate == 0.0
    assert "project.state_changed" not in [row.cache for row in ledger.cache_hit_rates(project_id)]


def test_root_stage_span_with_run_id_writes_one_pipeline_run(
    ledger: ObservabilityLedger,
) -> None:
    project_id = uuid4()
    run_id = uuid4()
    ledger_tracer = _ledger_tracer(ledger)

    with ledger_tracer.span(
        "script.run",
        component="script",
        kind="stage",
        project_id=project_id,
        workflow_run_id=run_id,
    ):
        pass

    runs = ledger.list_runs(project_id)
    assert len(runs) == 1
    assert runs[0].workflow_run_id == run_id
    assert runs[0].status == "succeeded"


def test_nested_stage_span_with_run_id_does_not_write_another_pipeline_run(
    ledger: ObservabilityLedger,
) -> None:
    project_id = uuid4()
    run_id = uuid4()
    ledger_tracer = _ledger_tracer(ledger)

    with (
        ledger_tracer.span(
            "script.run",
            component="script",
            kind="stage",
            project_id=project_id,
            workflow_run_id=run_id,
        ),
        ledger_tracer.span(
            "script.child",
            component="script",
            kind="stage",
            workflow_run_id=run_id,
        ),
    ):
        pass

    assert len(ledger.list_runs(project_id)) == 1


def test_root_stage_span_without_run_id_writes_no_pipeline_run(
    ledger: ObservabilityLedger,
) -> None:
    project_id = uuid4()
    ledger_tracer = _ledger_tracer(ledger)

    with ledger_tracer.span(
        "script.run", component="script", kind="stage", project_id=project_id
    ):
        pass

    assert ledger.list_runs(project_id) == []
