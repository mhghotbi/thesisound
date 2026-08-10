from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from thesisound import tracing
from thesisound.config import Settings
from thesisound.tracing import NullSpanSink, Tracer
from thesisound.web.app import create_app


def test_span_id_and_status_shape(recording_tracer: Tracer) -> None:
    with tracing.span("corpus.run", component="corpus", kind="stage") as root:
        root.set(source_count=2)

    span = recording_tracer.sink.one("corpus.run")
    assert span.component == "corpus"
    assert span.kind == "stage"
    assert span.status == "ok"
    assert span.attributes["source_count"] == 2
    assert span.duration_ms is not None
    assert span.ended_at is not None


def test_nested_spans_share_trace_id_and_link_parent(recording_tracer: Tracer) -> None:
    with tracing.span("corpus.run", kind="stage"):
        with tracing.span("corpus.source", kind="stage", subject_id="src-1"):
            pass
        with tracing.span("corpus.source", kind="stage", subject_id="src-2"):
            pass

    parent = recording_tracer.sink.one("corpus.run")
    children = recording_tracer.sink.find("corpus.source")
    assert len(children) == 2
    for child in children:
        assert child.parent_span_id == parent.context.span_id
        assert child.context.trace_id == parent.context.trace_id


def test_deeply_nested_spans_form_a_tree(recording_tracer: Tracer) -> None:
    with (
        tracing.span("corpus.run", kind="stage"),
        tracing.span("corpus.source", kind="stage") as source,
        tracing.span("corpus.extract_evidence") as leaf,
    ):
        leaf.measure(block_count=3)

    run_span = recording_tracer.sink.one("corpus.run")
    source_span = recording_tracer.sink.one("corpus.source")
    leaf_span = recording_tracer.sink.one("corpus.extract_evidence")

    assert source_span.parent_span_id == run_span.context.span_id
    assert leaf_span.parent_span_id == source_span.context.span_id
    assert leaf_span.context.trace_id == run_span.context.trace_id
    assert leaf_span.metrics["block_count"] == 3
    assert source.context.span_id == source_span.context.span_id


def test_exception_sets_error_status_and_type_then_reraises(recording_tracer: Tracer) -> None:
    with pytest.raises(ValueError, match="boom"), tracing.span("ingestion.parse"):
        raise ValueError("boom")

    span = recording_tracer.sink.one("ingestion.parse")
    assert span.status == "error"
    assert span.error_type == "ValueError"
    assert span.error_message == "boom"


def test_mark_sets_terminal_status_without_raising(recording_tracer: Tracer) -> None:
    with tracing.span("ingestion.parse", subject_id="mineru") as attempt:
        attempt.mark("skipped", reason="UnsupportedDocument")

    span = recording_tracer.sink.one("ingestion.parse")
    assert span.status == "skipped"
    assert span.attributes["status_reason"] == "UnsupportedDocument"


def test_new_root_detaches_and_records_causal_link(recording_tracer: Tracer) -> None:
    with (
        tracing.span("http.request", kind="http"),
        tracing.span("corpus.run", kind="stage", new_root=True) as background,
    ):
        pass

    request_span = recording_tracer.sink.one("http.request")
    background_span = recording_tracer.sink.one("corpus.run")

    assert background_span.parent_span_id is None
    assert background_span.context.trace_id != request_span.context.trace_id
    assert background_span.attributes["caused_by_span_id"] == str(request_span.context.span_id)
    assert background_span.attributes["caused_by_trace_id"] == str(request_span.context.trace_id)
    assert background.context.trace_id == background_span.context.trace_id


def test_root_span_with_no_ambient_parent_gets_a_fresh_trace(recording_tracer: Tracer) -> None:
    with tracing.span("corpus.run", kind="stage") as root:
        pass

    span = recording_tracer.sink.one("corpus.run")
    assert span.parent_span_id is None
    assert "caused_by_span_id" not in span.attributes
    assert root.context.trace_id == span.context.trace_id


def test_disabled_tracer_never_calls_the_sink() -> None:
    sink = tracing.NullSpanSink()
    calls: list[str] = []
    sink.begin = lambda record: calls.append("begin")  # type: ignore[method-assign]
    sink.end = lambda record: calls.append("end")  # type: ignore[method-assign]
    sink.event = lambda record: calls.append("event")  # type: ignore[method-assign]
    disabled = Tracer(sink, enabled=False, code_version="test")

    with disabled.span("corpus.run") as span:
        span.set(anything="ignored")
        disabled.event("cache.lookup", result="hit")

    assert calls == []


def test_disabled_tracer_span_handle_accepts_all_calls_harmlessly() -> None:
    disabled = Tracer(NullSpanSink(), enabled=False, code_version="test")

    with disabled.span("corpus.run") as span:
        span.set(foo="bar")
        span.measure(count=1)
        span.increment("count")
        span.event("something")
        span.mark("skipped", reason="n/a")
    # No exception means the null span accepted every call the real one does.


def test_module_level_span_uses_the_installed_ambient_tracer(recording_tracer: Tracer) -> None:
    with tracing.span("web.request", kind="http"):
        tracing.event("cache.lookup", result="hit", cache="document_map")

    assert recording_tracer.sink.one("web.request")
    event = recording_tracer.sink.events[0]
    assert event.name == "cache.lookup"
    assert event.attributes == {"result": "hit", "cache": "document_map"}


def test_event_attaches_to_the_ambient_span(recording_tracer: Tracer) -> None:
    with tracing.span("corpus.map_document") as span:
        span.event("cache.lookup", result="miss")

    parent = recording_tracer.sink.one("corpus.map_document")
    event = recording_tracer.sink.events[0]
    assert event.span_id == parent.context.span_id
    assert event.trace_id == parent.context.trace_id


def test_event_outside_any_span_has_no_span_id(recording_tracer: Tracer) -> None:
    tracing.event("project.state_changed", previous="DRAFT", current="BRIEF_READY")

    event = recording_tracer.sink.events[0]
    assert event.span_id is None
    assert event.trace_id is None


def test_detail_gates_low_value_spans(recording_tracer: Tracer) -> None:
    recording_tracer.detail = "stage"

    with (
        tracing.span("corpus.run", kind="stage", detail="stage"),
        tracing.span("corpus.extract_evidence", detail="operation"),
    ):
        pass

    assert recording_tracer.sink.one("corpus.run")
    assert recording_tracer.sink.find("corpus.extract_evidence") == []


def test_gated_span_children_attach_to_nearest_recorded_ancestor(
    recording_tracer: Tracer,
) -> None:
    """An unsampled/gated span must not leave a dangling parent_span_id: its
    children should attach to the nearest ancestor that *was* recorded."""

    recording_tracer.detail = "stage"
    with (
        tracing.span("corpus.run", kind="stage", detail="stage"),
        tracing.span("corpus.plan_extraction", detail="verbose"),
        tracing.span("corpus.build_blocks", detail="stage") as grandchild,
    ):
        pass

    root_span = recording_tracer.sink.one("corpus.run")
    child_span = recording_tracer.sink.one("corpus.build_blocks")
    assert child_span.parent_span_id == root_span.context.span_id
    assert grandchild.context.trace_id == root_span.context.trace_id


def test_span_context_header_round_trips() -> None:
    context = tracing.SpanContext(trace_id=uuid4(), span_id=uuid4(), project_id=uuid4())
    parsed = tracing.SpanContext.parse(context.header())
    assert parsed == context


def test_span_context_header_round_trips_without_project() -> None:
    context = tracing.SpanContext(trace_id=uuid4(), span_id=uuid4())
    parsed = tracing.SpanContext.parse(context.header())
    assert parsed == context


def test_span_context_parse_rejects_malformed_input() -> None:
    assert tracing.SpanContext.parse("") is None
    assert tracing.SpanContext.parse("not-a-valid-header") is None
    assert tracing.SpanContext.parse("::") is None


def test_create_app_tracer_install_can_be_undone_like_the_autouse_fixture_does(
    tmp_path: Path,
) -> None:
    """Regression test for a real isolation bug found while wiring this up:
    web.app.create_app() is a production composition root that calls
    tracing.install_tracer() unconditionally, correct for a real process
    that calls it exactly once. Tests call create_app() many times in one
    pytest process, so without conftest.py's autouse _reset_ambient_tracer
    fixture, the last test to build an app would leave its real,
    ledger-backed tracer installed globally for every test running after it
    -- including ones that construct services directly and expect the
    disabled default. This proves the exact save/restore mechanism that
    fixture relies on, on every test run rather than only when test order
    happens to expose the leak.
    """

    before = tracing.tracer()

    create_app(
        Settings(
            environment="test",
            workspace_root=tmp_path / "workspaces",
            web_session_secret="test-secret-that-is-long-enough",
        ),
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
        audio_executor=lambda _: None,
    )
    installed = tracing.tracer()
    assert installed is not before
    assert installed.enabled is True

    tracing.install_tracer(before)  # exactly what the autouse fixture does after every test
    assert tracing.tracer() is before


def test_create_app_reaps_spans_a_prior_process_left_running(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    from thesisound.observability import ledger_from_settings
    from thesisound.tracing import SpanContext, SpanRecord

    settings = Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        web_session_secret="test-secret-that-is-long-enough",
    )
    # Simulate a span still open when a previous process crashed -- the
    # exact scenario recover_interrupted_runs() already handles for run
    # records; this is that same moment for spans.
    ledger = ledger_from_settings(settings)
    context = SpanContext(trace_id=uuid4(), span_id=uuid4())
    ledger.start_span(
        SpanRecord(
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
    )

    create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
        audio_executor=lambda _: None,
    )

    assert ledger.get_span(context.span_id).status == "interrupted"
