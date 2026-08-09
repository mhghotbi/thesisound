"""Regression tests for the two ways span context can silently go missing:
a raw ``ThreadPoolExecutor`` (contextvars are not copied into new threads)
and a detached background task (the parent's ``with`` block has already
exited by the time the task runs). Both are real shapes used in this
codebase -- ``services/evidence_extractor.py`` for the former,
``BackgroundTasks.add_task`` for the latter.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from starlette.concurrency import run_in_threadpool

from thesisound import tracing
from thesisound.tracing import Tracer


def test_threadpoolexecutor_orphans_children_without_bind_context(
    recording_tracer: Tracer,
) -> None:
    """Documents the trap so nobody re-introduces it: a bare
    ``pool.submit(work, item)`` loses the parent span entirely."""

    def work() -> None:
        with tracing.span("corpus.extract_evidence"):
            pass

    with tracing.span("corpus.source", kind="stage"), ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(work) for _ in range(3)]
        for future in futures:
            future.result()

    parent_span = recording_tracer.sink.one("corpus.source")
    children = recording_tracer.sink.find("corpus.extract_evidence")
    assert len(children) == 3
    assert all(child.parent_span_id is None for child in children)
    assert all(child.context.trace_id != parent_span.context.trace_id for child in children)


def test_bind_context_reattaches_parent_across_threadpoolexecutor(
    recording_tracer: Tracer,
) -> None:
    def work() -> None:
        with tracing.span("corpus.extract_evidence"):
            pass

    with tracing.span("corpus.source", kind="stage"), ThreadPoolExecutor(max_workers=2) as pool:
        bound = tracing.bind_context(work)
        futures = [pool.submit(bound) for _ in range(3)]
        for future in futures:
            future.result()

    parent_span = recording_tracer.sink.one("corpus.source")
    children = recording_tracer.sink.find("corpus.extract_evidence")
    assert len(children) == 3
    assert all(child.parent_span_id == parent_span.context.span_id for child in children)
    assert all(child.context.trace_id == parent_span.context.trace_id for child in children)


def test_bind_context_propagates_the_exception_from_the_wrapped_call(
    recording_tracer: Tracer,
) -> None:
    def failing() -> None:
        raise RuntimeError("worker failed")

    bound = tracing.bind_context(failing)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(bound)
        try:
            future.result()
        except RuntimeError as exc:
            assert str(exc) == "worker failed"
        else:
            raise AssertionError("expected the wrapped exception to propagate")


def test_run_in_threadpool_inherits_context_for_free(recording_tracer: Tracer) -> None:
    """Unlike ThreadPoolExecutor, anyio (and therefore Starlette's
    run_in_threadpool) copies the calling context into the worker thread."""

    async def scenario() -> tracing.Span:
        with tracing.span("http.request", kind="http") as parent:

            def work() -> None:
                with tracing.span("ingestion.parse"):
                    pass

            await run_in_threadpool(work)
            return parent

    parent = asyncio.run(scenario())

    parent_span = recording_tracer.sink.one("http.request")
    child_span = recording_tracer.sink.one("ingestion.parse")
    assert child_span.parent_span_id == parent_span.context.span_id
    assert child_span.context.trace_id == parent.context.trace_id


def test_background_run_uses_new_root_instead_of_a_dangling_parent(
    recording_tracer: Tracer,
) -> None:
    """A BackgroundTasks-style run must not try to attach to the HTTP span
    that scheduled it -- that span's ``with`` block exits before the
    background work runs, so its context would already be closed. The run
    should open its own root and record what caused it instead."""

    with tracing.span("http.request", kind="http"):
        pass  # the request handler returns; its span is now closed

    # ... time passes; BackgroundTasks invokes the queued run later, with no
    # ambient span active (a fresh contextvar in whatever thread runs it).
    with tracing.span("corpus.run", kind="stage", new_root=True) as background:
        pass

    request_span = recording_tracer.sink.one("http.request")
    background_span = recording_tracer.sink.one("corpus.run")
    assert background_span.parent_span_id is None
    assert background_span.context.trace_id != request_span.context.trace_id
    assert background.context.trace_id == background_span.context.trace_id
