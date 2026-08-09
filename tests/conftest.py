from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from thesisound import tracing
from thesisound.observability import ObservabilityLedger
from thesisound.tracing import EventRecord, SpanRecord, Tracer


@pytest.fixture(autouse=True)
def _reset_ambient_tracer():
    """Isolate every test from the process-global ambient tracer.

    ``web.app.create_app`` (a production composition root, meant to run
    once per process) calls ``tracing.install_tracer(...)`` on every
    invocation. Tests call ``create_app()`` many times in one pytest
    process, so without this, a test that builds an app leaves its real,
    ledger-backed tracer installed globally for every test that runs after
    it -- including ones that construct services directly and expect the
    disabled default. This restores whatever was ambient before each test
    regardless of what the test itself does, autouse so no test file has to
    remember to ask for it.
    """

    previous = tracing.tracer()
    yield
    tracing.install_tracer(previous)


@pytest.fixture
def reset_logging():
    """Restores the root logger's handlers/level/filters for a test that
    calls ``logging_setup.configure_logging()`` or ``dictConfig`` directly.

    Without this, a test-scoped ``RotatingFileHandler`` pointing at that
    test's ``tmp_path`` stays installed on the root logger for the rest of
    the pytest process. On Windows specifically, an unclosed handler keeps
    the log file open, which can make pytest's own ``tmp_path`` cleanup
    fail with a PermissionError well after the test that opened it.
    """

    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    previous_level = root.level
    previous_filters = list(root.filters)
    yield
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    for handler in previous_handlers:
        root.addHandler(handler)
    root.setLevel(previous_level)
    for existing in list(root.filters):
        root.removeFilter(existing)
    for restored in previous_filters:
        root.addFilter(restored)


@pytest.fixture
def ledger(tmp_path: Path) -> ObservabilityLedger:
    """A file-backed observability ledger under a fresh temp directory.

    Not ``:memory:`` -- ``ObservabilityLedger`` opens a new connection per
    call and creates its parent directories on construction, so it needs a
    real path on disk.
    """

    return ObservabilityLedger(tmp_path / "ledger.sqlite3", tmp_path / "artifacts")


class FrozenClock:
    """Deterministic wall clock + monotonic pair, so span durations in tests
    are exact integers instead of depending on how fast the test runs."""

    def __init__(self, start: datetime | None = None) -> None:
        self._wall = start or datetime(2026, 1, 1, tzinfo=UTC)
        self._monotonic = 0.0

    def advance(self, seconds: float) -> None:
        self._wall += timedelta(seconds=seconds)
        self._monotonic += seconds

    def now(self) -> datetime:
        return self._wall

    def perf_counter(self) -> float:
        return self._monotonic


@pytest.fixture
def frozen_clock() -> FrozenClock:
    return FrozenClock()


class RecordingSpanSink:
    """An in-memory ``SpanSink`` for tests.

    ``spans`` holds the final, completed record for each span (appended in
    ``end()``, in completion order) -- that is what test assertions care
    about. ``open_span_ids`` tracks which spans are currently open, so a
    test can simulate a crash mid-span and assert on what was left running.
    """

    def __init__(self) -> None:
        self.spans: list[SpanRecord] = []
        self.events: list[EventRecord] = []
        self.open_span_ids: set[UUID] = set()

    def begin(self, record: SpanRecord) -> None:
        self.open_span_ids.add(record.context.span_id)

    def end(self, record: SpanRecord) -> None:
        self.open_span_ids.discard(record.context.span_id)
        self.spans.append(record)

    def event(self, record: EventRecord) -> None:
        self.events.append(record)

    def find(self, name: str) -> list[SpanRecord]:
        return [item for item in self.spans if item.name == name]

    def one(self, name: str) -> SpanRecord:
        matches = self.find(name)
        assert len(matches) == 1, (
            f"expected exactly one span named {name!r}, found {len(matches)}"
        )
        return matches[0]

    def children_of(self, span_id: UUID) -> list[SpanRecord]:
        return [item for item in self.spans if item.parent_span_id == span_id]


@pytest.fixture
def recording_tracer(frozen_clock: FrozenClock) -> Tracer:
    """A ``Tracer`` over an in-memory sink, installed as the ambient tracer
    for the duration of the test and restored afterward. Access
    ``recording_tracer.sink`` (a ``RecordingSpanSink``) to inspect spans and
    events recorded through either the returned tracer or the module-level
    ``tracing.span()`` / ``tracing.event()`` functions.
    """

    sink = RecordingSpanSink()
    test_tracer = Tracer(sink, clock=frozen_clock.now, monotonic=frozen_clock.perf_counter)
    previous = tracing.tracer()
    tracing.install_tracer(test_tracer)
    try:
        yield test_tracer
    finally:
        tracing.install_tracer(previous)
