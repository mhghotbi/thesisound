"""Ambient tracer for the whole pipeline -- not just model calls.

A **span** is one operation that took time: a name, a start, an end, a
status, and free-form attributes. A **trace** is every span produced by one
user-triggered run, sharing a ``trace_id``. Spans nest (``parent_span_id``),
so a trace is a tree, and the tree is the explanation of what happened.

Nesting is implicit via ``contextvars`` -- opening a span makes it the
ambient parent for anything opened inside the ``with`` block, in this thread
or async task only. No caller ever threads a ``parent_span_id`` argument
through a function signature.

This module has zero dependencies on the rest of ``thesisound``: it only
defines the vocabulary (``SpanContext``, ``SpanRecord``, ``EventRecord``),
the ``SpanSink`` port those records are written through, and the ``Tracer``
that manages the contextvar stack. ``thesisound.observability`` supplies the
concrete ``SpanSink`` that persists into the SQLite ledger.

Named ``tracing.py``, not ``trace.py`` -- ``trace`` is a stdlib module.
"""

from __future__ import annotations

import contextvars
import os
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps
from importlib import metadata
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

SpanKind = Literal["internal", "stage", "subprocess", "fs", "http", "db", "gate", "model"]
SpanStatus = Literal["running", "ok", "error", "blocked", "skipped", "interrupted"]
DetailLevel = Literal["stage", "operation", "verbose"]

_DETAIL_RANK: dict[DetailLevel, int] = {"stage": 0, "operation": 1, "verbose": 2}


def _detect_code_version() -> str:
    """Return the deployed source revision, with deterministic fallbacks.

    Deployments should set ``THESISOUND_CODE_VERSION``. A source checkout can
    resolve Git directly, while an installed wheel falls back to its package
    version. Detection happens once per tracer, never once per span.
    """

    for variable in ("THESISOUND_CODE_VERSION", "GITHUB_SHA", "SOURCE_VERSION"):
        value = os.getenv(variable, "").strip()
        if value:
            return value
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    else:
        revision = completed.stdout.strip()
        if revision:
            return revision
    try:
        return metadata.version("thesisound")
    except metadata.PackageNotFoundError:
        return "unknown"


@dataclass(frozen=True, slots=True)
class SpanContext:
    """The identity of the currently-open span. Cheap to copy; immutable."""

    trace_id: UUID
    span_id: UUID
    project_id: UUID | None = None
    workflow_run_id: UUID | None = None

    def header(self) -> str:
        """Wire format for handing this context to a subprocess.

        ``'<trace-hex>:<span-hex>:<project-hex-or-empty>'``. Hex form (not
        ``str(uuid)``) keeps it a single token with no separators of its own.
        """

        return ":".join(
            [
                self.trace_id.hex,
                self.span_id.hex,
                self.project_id.hex if self.project_id else "",
            ]
        )

    @classmethod
    def parse(cls, raw: str) -> SpanContext | None:
        """Inverse of :meth:`header`. Returns ``None`` on anything malformed
        rather than raising -- a subprocess started without tracing context
        (or with a corrupted one) should run untraced, not crash."""

        parts = raw.split(":")
        if len(parts) != 3 or not parts[0] or not parts[1]:
            return None
        try:
            return cls(
                trace_id=UUID(hex=parts[0]),
                span_id=UUID(hex=parts[1]),
                project_id=UUID(hex=parts[2]) if parts[2] else None,
            )
        except ValueError:
            return None


_CURRENT: contextvars.ContextVar[SpanContext | None] = contextvars.ContextVar(
    "thesisound_span", default=None
)


def current_context() -> SpanContext | None:
    """The innermost open span in this thread/task, or ``None`` outside any span."""

    return _CURRENT.get()


@dataclass
class SpanRecord:
    """Everything a :class:`SpanSink` needs to persist one span.

    Mutable: the same instance is passed to ``begin()`` and, once the work
    finishes, to ``end()`` with the terminal fields filled in.
    """

    context: SpanContext
    parent_span_id: UUID | None
    name: str
    component: str
    kind: SpanKind
    subject_type: str | None
    subject_id: str | None
    started_at: datetime
    process: str
    pid: int
    status: SpanStatus = "running"
    ended_at: datetime | None = None
    duration_ms: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class EventRecord:
    """A point-in-time fact: a cache hit, a state transition, a gate block.

    Unlike a span, an event has no duration and is never updated after it is
    written -- that append-only property is what fixes the "run records are
    mutated in place" lossy-history problem.
    """

    event_id: UUID
    trace_id: UUID | None
    span_id: UUID | None
    project_id: UUID | None
    workflow_run_id: UUID | None
    occurred_at: datetime
    name: str
    component: str
    level: str
    subject_type: str | None
    subject_id: str | None
    attributes: dict[str, Any] = field(default_factory=dict)


class SpanSink(Protocol):
    """Where spans and events go. ``Tracer`` only ever talks to this port."""

    def begin(self, record: SpanRecord) -> None: ...

    def end(self, record: SpanRecord) -> None: ...

    def event(self, record: EventRecord) -> None: ...


class NullSpanSink:
    """A sink that discards everything. Used when tracing is disabled."""

    def begin(self, record: SpanRecord) -> None:
        return None

    def end(self, record: SpanRecord) -> None:
        return None

    def event(self, record: EventRecord) -> None:
        return None


@dataclass
class Span:
    """The handle a ``with tracer.span(...)`` body uses to enrich its span."""

    context: SpanContext
    _tracer: Tracer
    attributes: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    status: SpanStatus = "running"

    def set(self, **attributes: Any) -> None:
        """Attach descriptive facts. Redacted and size-capped before storage."""

        self.attributes.update(attributes)

    def measure(self, **metrics: float) -> None:
        """Attach numeric measurements: counts, byte sizes, scores."""

        self.metrics.update(metrics)

    def increment(self, name: str, amount: float = 1) -> None:
        """Aggregate a running count into this span instead of creating a
        child row per occurrence -- use for per-block/per-page tallies."""

        self.metrics[name] = self.metrics.get(name, 0) + amount

    def event(self, name: str, *, level: str = "info", **attributes: Any) -> None:
        """Record a point-in-time fact scoped to this span."""

        self._tracer.event(name, level=level, **attributes)

    def mark(self, status: SpanStatus, *, reason: str | None = None) -> None:
        """Set a terminal status without raising.

        For the no-raise failure case: e.g. a parser attempt that failed but
        whose caller deliberately continues on to the next parser.
        """

        self.status = status
        if reason:
            self.attributes["status_reason"] = reason


class _NullSpan:
    """Every method is a no-op. One module-level singleton, never mutated."""

    def set(self, **attributes: Any) -> None:
        return None

    def measure(self, **metrics: float) -> None:
        return None

    def increment(self, name: str, amount: float = 1) -> None:
        return None

    def event(self, name: str, *, level: str = "info", **attributes: Any) -> None:
        return None

    def mark(self, status: str, *, reason: str | None = None) -> None:
        return None


_NULL_SPAN = _NullSpan()


class Tracer:
    """Owns the contextvar stack and hands finished records to a sink."""

    def __init__(
        self,
        sink: SpanSink,
        *,
        enabled: bool = True,
        process: str = "app",
        detail: DetailLevel = "operation",
        code_version: str | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = perf_counter,
    ) -> None:
        self.sink = sink
        self.enabled = enabled
        self.process = process
        self.detail = detail
        self.code_version = code_version or _detect_code_version()
        self.clock = clock
        self.monotonic = monotonic

    @contextmanager
    def span(
        self,
        name: str,
        *,
        component: str | None = None,
        kind: SpanKind = "internal",
        subject_type: str | None = None,
        subject_id: str | None = None,
        project_id: UUID | None = None,
        workflow_run_id: UUID | None = None,
        new_root: bool = False,
        detail: DetailLevel = "operation",
        **attributes: Any,
    ) -> Iterator[Span]:
        """Open a span for the duration of the ``with`` block.

        ``new_root=True`` detaches from the ambient parent and starts a new
        trace -- use it where the caller's lifetime does not contain the
        callee's (a background run started from an HTTP request, for
        example). ``detail`` gates low-value, high-volume spans (per-block,
        per-page) behind ``Settings.tracing_detail``; the default
        ``"operation"`` always records unless the tracer itself was
        configured at the coarser ``"stage"`` level.
        """

        if not self.enabled or _DETAIL_RANK[detail] > _DETAIL_RANK[self.detail]:
            yield _NULL_SPAN
            return

        parent = _CURRENT.get()
        detached = parent is None or new_root
        context = SpanContext(
            trace_id=uuid4() if detached else parent.trace_id,
            span_id=uuid4(),
            project_id=project_id or (parent.project_id if parent else None),
            workflow_run_id=workflow_run_id or (parent.workflow_run_id if parent else None),
        )
        initial_attributes = dict(attributes)
        if detached:
            initial_attributes.setdefault("pipeline_code_version", self.code_version)
        if new_root and parent is not None:
            initial_attributes["caused_by_span_id"] = str(parent.span_id)
            initial_attributes["caused_by_trace_id"] = str(parent.trace_id)

        span = Span(context=context, _tracer=self, attributes=initial_attributes)
        record = SpanRecord(
            context=context,
            parent_span_id=None if detached else parent.span_id,
            name=name,
            component=component or name.split(".", 1)[0],
            kind=kind,
            subject_type=subject_type,
            subject_id=subject_id,
            started_at=self.clock(),
            process=self.process,
            pid=os.getpid(),
            attributes=dict(initial_attributes),
        )
        token = _CURRENT.set(context)
        started = self.monotonic()
        self.sink.begin(record)
        try:
            yield span
        except BaseException as exc:
            # KeyboardInterrupt/SystemExit included on purpose: a server
            # shutdown mid-run is exactly the case this must record.
            span.status = "error"
            record.error_type = type(exc).__name__
            record.error_message = str(exc)[:1_000]
            raise
        else:
            if span.status == "running":
                span.status = "ok"
        finally:
            _CURRENT.reset(token)
            record.status = span.status
            record.ended_at = self.clock()
            record.duration_ms = max(0, round((self.monotonic() - started) * 1000))
            record.attributes = span.attributes
            record.metrics = span.metrics
            self.sink.end(record)

    def event(
        self,
        name: str,
        *,
        component: str | None = None,
        level: str = "info",
        project_id: UUID | None = None,
        workflow_run_id: UUID | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        **attributes: Any,
    ) -> None:
        """Record a point-in-time fact. Attaches to the ambient span if any."""

        if not self.enabled:
            return
        parent = _CURRENT.get()
        self.sink.event(
            EventRecord(
                event_id=uuid4(),
                trace_id=parent.trace_id if parent else None,
                span_id=parent.span_id if parent else None,
                project_id=project_id or (parent.project_id if parent else None),
                workflow_run_id=workflow_run_id or (parent.workflow_run_id if parent else None),
                occurred_at=self.clock(),
                name=name,
                component=component or name.split(".", 1)[0],
                level=level,
                subject_type=subject_type,
                subject_id=subject_id,
                attributes=dict(attributes),
            )
        )


# --------------------------------------------------------------------------
# Ambient tracer. A deliberate exception to this codebase's usual hexagonal
# discipline: pipeline.transition() is a pure module function called from
# ~15 sites, and services/ has ~60 modules. Threading a Tracer constructor
# argument through all of them is a multi-week refactor with no
# observability payoff. Leaf and pure functions use the module-level
# span()/event() below; the four run services (and anything that already
# takes collaborators) accept an explicit `tracer=` argument defaulting to
# this ambient one, so tests can inject a recording tracer without touching
# process globals. Because the default tracer is disabled, the cost at an
# uninstrumented call site is one attribute read and one branch.
# --------------------------------------------------------------------------

_TRACER: Tracer = Tracer(NullSpanSink(), enabled=False)


def install_tracer(new_tracer: Tracer) -> None:
    """Replace the ambient tracer. Call once from a composition root
    (``web.app.create_app``, the CLI's Typer callback, ``ocr_worker.main``)."""

    global _TRACER
    _TRACER = new_tracer


def tracer() -> Tracer:
    """The ambient tracer -- a disabled no-op until ``install_tracer`` runs."""

    return _TRACER


@contextmanager
def span(name: str, **kwargs: Any) -> Iterator[Span]:
    """Open a span on the ambient tracer. See ``Tracer.span`` for kwargs."""

    with _TRACER.span(name, **kwargs) as active:
        yield active


def event(name: str, **kwargs: Any) -> None:
    """Record an event on the ambient tracer. See ``Tracer.event`` for kwargs."""

    _TRACER.event(name, **kwargs)


def bind_context(
    function: Callable[..., Any],
    context: SpanContext | None = None,
) -> Callable[..., Any]:
    """Re-attach a span context inside a worker thread.

    ``concurrent.futures.ThreadPoolExecutor`` does NOT copy contextvars into
    the worker thread -- unlike ``anyio`` (and therefore
    ``starlette.concurrency.run_in_threadpool``), which does this for free.
    Wrap any callable submitted to a raw ``ThreadPoolExecutor`` with this, or
    every span it opens is silently orphaned at the trace root:

        bound = tracing.bind_context(work)
        futures = [pool.submit(bound, item) for item in pending]

    Captures the *current* context at wrap time by default, so wrap the
    callable on the submitting thread, not inside the worker.
    """

    captured = context if context is not None else _CURRENT.get()

    @wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        token = _CURRENT.set(captured)
        try:
            return function(*args, **kwargs)
        finally:
            _CURRENT.reset(token)

    return wrapper
