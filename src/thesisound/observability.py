from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Callable, Mapping
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Literal, Protocol, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from thesisound import tracing
from thesisound.modeling import GroundingMode, ModelUsage
from thesisound.tracing import EventRecord, SpanRecord, Tracer

CallStatus = Literal[
    "running",
    "provider_succeeded",
    "succeeded",
    "rejected",
    "failed",
]
CallOperation = Literal[
    "structured_text",
    "google_search",
    "url_context",
    "tts",
    "asr",
]

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "cookies",
    "set-cookie",
    "otp",
    "password",
    "password_hash",
    "secret",
    "access_token",
    "refresh_token",
    "session",
    "session_id",
    "phone",
    "phone_number",
    "user_phone",
    "msisdn",
    "otp_code",
    "csrf_token",
    "web_session_secret",
    "token",
    "credential",
}
SENSITIVE_ATTRIBUTES = {"query", "text", "excerpt", "filename", "topic", "phone", "prompt"}

_GEMINI_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
_GENERIC_SECRET_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
_IRAN_PHONE_PATTERN = re.compile(r"(?:\+98|0098|0)9\d{9}")
_HOME_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\Users\\[^\\/\s]+"),
    re.compile(r"/home/[^/\s]+"),
)


def _relativize(path: Path, roots: tuple[Path, ...]) -> str:
    """Render a filesystem path relative to a known root, never absolute.

    Absolute paths embed the OS username (``C:\\Users\\<name>\\...``), which is
    real PII once a trace or log line is exported. Callers that only have a
    workspace-relative concept (project id, call id) should prefer that; this
    helper exists for the remaining cases where an absolute path is the only
    identifier available (e.g. an uploaded file before it has a project home).
    """

    resolved = path.expanduser().resolve()
    for root in roots:
        try:
            return resolved.relative_to(root.expanduser().resolve()).as_posix()
        except ValueError:
            continue
    return redact_text(resolved.as_posix())


def redact_text(value: str) -> str:
    """Scrub known secret and PII patterns out of a free-text string."""

    value = _GEMINI_KEY_PATTERN.sub("[REDACTED_GEMINI_KEY]", value)
    value = _GENERIC_SECRET_KEY_PATTERN.sub("[REDACTED_SECRET]", value)
    value = _IRAN_PHONE_PATTERN.sub("[REDACTED_PHONE]", value)
    for pattern in _HOME_PATH_PATTERNS:
        value = pattern.sub("[HOME]", value)
    return value


def _ambient_trace_id() -> UUID | None:
    context = tracing.current_context()
    return context.trace_id if context else None


def _ambient_span_id() -> UUID | None:
    context = tracing.current_context()
    return context.span_id if context else None


class ModelCallSpec(BaseModel):
    call_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID | None = None
    parent_call_id: UUID | None = None
    # Populated from the ambient span whenever a caller does not supply one
    # explicitly -- the same mechanism as RunMetadata in ports.py, and the
    # only mechanism at all for the TTS/ASR adapters, which construct a
    # ModelCallSpec directly without a RunMetadata in between.
    pipeline_trace_id: UUID | None = Field(default_factory=_ambient_trace_id)
    parent_span_id: UUID | None = Field(default_factory=_ambient_span_id)
    project_id: UUID | None = None
    workflow_run_id: UUID | None = None
    stage: str = Field(min_length=1)
    operation: CallOperation
    provider: str = Field(min_length=1)
    requested_model: str = Field(min_length=1)
    prompt_id: str | None = None
    prompt_version: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    logical_attempt: int = Field(default=1, ge=1)
    timeout_ms: int | None = Field(default=None, ge=1)
    grounding_mode: GroundingMode = "none"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderMetadata(BaseModel):
    resolved_model: str | None = None
    provider_request_id: str | None = None
    http_status: int | None = None
    finish_reason: str | None = None


class AttemptRecord(BaseModel):
    attempt_id: int
    call_id: UUID
    logical_attempt: int
    provider_attempt: int
    key_slot: int | None = None
    key_fingerprint: str | None = None
    credential_type: str | None = None
    status: str
    started_at: datetime
    ended_at: datetime
    latency_ms: int
    http_status: int | None = None
    retryable: bool = False
    retry_reason: str | None = None
    error_type: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class CallSummary(BaseModel):
    call_id: UUID
    trace_id: UUID | None = None
    project_id: UUID | None = None
    stage: str
    operation: str
    provider: str
    requested_model: str
    resolved_model: str | None = None
    status: CallStatus
    started_at: datetime
    ended_at: datetime | None = None
    latency_ms: int | None = None
    provider_attempt_count: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None
    cached_tokens: int | None = None
    total_tokens: int | None = None
    finish_reason: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    cost_micros: int | None = None
    pricing_version: str | None = None


class CallDetail(BaseModel):
    call: CallSummary
    attempts: list[AttemptRecord]
    prompt_id: str | None = None
    prompt_version: str | None = None
    workflow_run_id: UUID | None = None
    parent_call_id: UUID | None = None
    timeout_ms: int | None = None
    grounding_mode: GroundingMode = "none"
    retry_scheduled: bool = False
    retry_reason: str | None = None
    backoff_ms: int | None = None
    request_artifact_path: str | None = None
    raw_response_artifact_path: str | None = None
    parsed_output_artifact_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    pipeline_trace_id: UUID | None = None
    parent_span_id: UUID | None = None


class ProjectUsageSummary(BaseModel):
    """``total_cost_micros`` sums only calls with a known price -- whenever
    ``unpriced_succeeded_count`` is nonzero it is a lower bound, not the true
    total, so callers must show both rather than a single number."""

    project_id: UUID
    call_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    rejected_count: int = 0
    provider_attempt_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    total_latency_ms: int = 0
    total_cost_micros: int = 0
    unpriced_succeeded_count: int = 0


@dataclass(frozen=True)
class PipelineRunSpec:
    workflow_run_id: UUID
    project_id: UUID | None
    trace_id: UUID
    kind: str
    started_at: datetime


class PipelineRunSummary(BaseModel):
    workflow_run_id: UUID
    project_id: UUID | None = None
    trace_id: UUID | None = None
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    call_count: int = 0
    failed_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    models: list[str] = Field(default_factory=list)
    prompt_versions: list[str] = Field(default_factory=list)
    error_message: str | None = None


class SpanSummary(BaseModel):
    span_id: UUID
    trace_id: UUID
    parent_span_id: UUID | None = None
    project_id: UUID | None = None
    workflow_run_id: UUID | None = None
    name: str
    component: str
    kind: str
    subject_type: str | None = None
    subject_id: str | None = None
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    process: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)


class TraceNode(BaseModel):
    """One node in a trace tree -- either a pipeline span or a model call,
    via the ``trace_nodes`` view that unions ``pipeline_spans`` and
    ``model_calls`` so a single query renders the whole tree regardless of
    which table a given node actually lives in."""

    node_id: UUID
    trace_id: UUID
    parent_id: UUID | None = None
    project_id: UUID | None = None
    name: str
    component: str
    kind: str
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    node_source: Literal["span", "model_call"]


class EventSummary(BaseModel):
    event_id: UUID
    trace_id: UUID | None = None
    span_id: UUID | None = None
    project_id: UUID | None = None
    workflow_run_id: UUID | None = None
    occurred_at: datetime
    name: str
    component: str
    level: str
    subject_type: str | None = None
    subject_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class CacheHitRateSummary(BaseModel):
    """One row per distinct ``cache`` attribute seen on ``cache.lookup``
    events -- the single ``GROUP BY`` the plan's cache attribute convention
    was designed to make possible across every cache in the system at once.
    """

    cache: str
    hits: int
    misses: int

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


class CostResult(BaseModel):
    """What one model call cost, and against which pricing table version --
    persisted once at ``succeed()`` time so it survives later price changes.
    """

    cost_micros: int = Field(ge=0)
    pricing_version: str


class CostBreakdownRow(BaseModel):
    """Cost and token totals grouped by stage/provider/model for one
    project -- ``unpriced_count`` flags groups where ``total_cost_micros``
    understates the true total because some calls have no known price."""

    stage: str
    provider: str
    model: str
    call_count: int
    unpriced_count: int
    total_cost_micros: int
    total_tokens: int


class StageSummary(BaseModel):
    """Per-span-name rollup across every trace for a project, ranked by self
    time -- total minus children -- because that is where the wall clock
    actually goes; a span that only orchestrates children should not outrank
    the child doing the real work. ``total_ms`` (each span's own duration
    including children) is kept alongside it for the "how long overall"
    question ``self_ms`` does not answer.
    """

    name: str
    component: str
    call_count: int
    total_ms: int
    avg_ms: int
    self_total_ms: int
    self_avg_ms: int
    error_count: int


@dataclass(frozen=True)
class ProviderCallResult:
    call_id: UUID
    response: Any


class KeyPoolLike(Protocol):
    def call[T](
        self,
        operation: Callable[[Any], T],
        *,
        on_attempt: Callable[[dict[str, Any]], None] | None = None,
    ) -> T: ...


class CostPricer(Protocol):
    """What ``ObservabilityLedger`` needs from a pricing table -- structural,
    so the ledger stays a pure store with no import of (or dependency on)
    ``services.model_pricing.CostCalculator``'s TOML-loading and effective-
    date logic. ``None`` means "no known price for this model/operation",
    which callers must render as unknown, never as a silent zero."""

    def price(
        self,
        *,
        provider: str,
        model: str,
        operation: str,
        started_at: datetime,
        input_tokens: int | None,
        output_tokens: int | None,
        cached_tokens: int | None,
    ) -> CostResult | None: ...


class ObservabilityLedger:
    """SQLite metadata ledger plus redacted request/response artifacts."""

    def __init__(
        self,
        database_path: Path,
        artifact_root: Path,
        *,
        store_payloads: bool = True,
        cost_pricer: CostPricer | None = None,
    ) -> None:
        self.database_path = database_path.expanduser().resolve()
        self.artifact_root = artifact_root.expanduser().resolve()
        self.store_payloads = store_payloads
        self.cost_pricer = cost_pricer
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def begin_call(self, spec: ModelCallSpec, request_payload: Any) -> UUID:
        started = _now()
        request_path = None
        request_hash = None
        if self.store_payloads:
            request_path, request_hash = self._write_artifact(
                spec,
                "request.json",
                request_payload,
            )
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO model_calls(
                    call_id, trace_id, parent_call_id, pipeline_trace_id, parent_span_id,
                    project_id, workflow_run_id,
                    stage, operation, provider, requested_model, prompt_id,
                    prompt_version, subject_type, subject_id, logical_attempt,
                    status, started_at, timeout_ms, grounding_mode,
                    request_artifact_path, request_sha256, metadata_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    str(spec.call_id),
                    _uuid_text(spec.trace_id),
                    _uuid_text(spec.parent_call_id),
                    _uuid_text(spec.pipeline_trace_id),
                    _uuid_text(spec.parent_span_id),
                    _uuid_text(spec.project_id),
                    _uuid_text(spec.workflow_run_id),
                    spec.stage,
                    spec.operation,
                    spec.provider,
                    spec.requested_model,
                    spec.prompt_id,
                    spec.prompt_version,
                    spec.subject_type,
                    spec.subject_id,
                    spec.logical_attempt,
                    _to_db_timestamp(started),
                    spec.timeout_ms,
                    spec.grounding_mode,
                    request_path,
                    request_hash,
                    _json(redact_value(spec.metadata, store_payloads=self.store_payloads)),
                ),
            )
        return spec.call_id

    def record_attempt(
        self,
        call_id: UUID,
        *,
        logical_attempt: int,
        provider_attempt: int,
        event: Mapping[str, Any],
        retryable: bool = False,
        retry_reason: str | None = None,
    ) -> None:
        started_at = _coerce_datetime(event.get("started_at")) or _now()
        ended_at = _coerce_datetime(event.get("ended_at")) or started_at
        latency_ms = _nonnegative_int(event.get("latency_ms")) or 0
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO model_attempts(
                    call_id, logical_attempt, provider_attempt, key_slot,
                    key_fingerprint, credential_type, status, started_at,
                    ended_at, latency_ms, http_status, retryable, retry_reason,
                    error_type, error_code, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(call_id),
                    logical_attempt,
                    provider_attempt,
                    _optional_int(event.get("key_slot")),
                    _optional_text(event.get("key_fingerprint")),
                    _optional_text(event.get("credential_type")),
                    _optional_text(event.get("status")) or "unknown",
                    _to_db_timestamp(started_at),
                    _to_db_timestamp(ended_at),
                    latency_ms,
                    _optional_int(event.get("http_status")),
                    int(retryable),
                    retry_reason,
                    _optional_text(event.get("error_type")),
                    _optional_text(event.get("error_code")),
                    redact_exception_message(_optional_text(event.get("error_message"))),
                ),
            )
            connection.execute(
                """
                UPDATE model_calls
                SET provider_attempt_count = (
                    SELECT COUNT(*) FROM model_attempts WHERE call_id = ?
                )
                WHERE call_id = ?
                """,
                (str(call_id), str(call_id)),
            )

    def provider_succeeded(
        self,
        call_id: UUID,
        *,
        response_payload: Any,
        usage: ModelUsage,
        provider_metadata: ProviderMetadata,
    ) -> None:
        path = None
        digest = None
        spec = self._spec_for_artifact(call_id)
        if self.store_payloads:
            path, digest = self._write_artifact(spec, "raw-response.json", response_payload)
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE model_calls
                SET status = 'provider_succeeded', resolved_model = ?,
                    provider_request_id = ?, http_status = ?, finish_reason = ?,
                    input_tokens = ?, output_tokens = ?, thinking_tokens = ?,
                    cached_tokens = ?, total_tokens = ?, raw_response_artifact_path = ?,
                    raw_response_sha256 = ?
                WHERE call_id = ?
                """,
                (
                    provider_metadata.resolved_model,
                    provider_metadata.provider_request_id,
                    provider_metadata.http_status,
                    provider_metadata.finish_reason,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.thinking_tokens,
                    getattr(usage, "cached_tokens", None),
                    usage.total_tokens,
                    path,
                    digest,
                    str(call_id),
                ),
            )

    def succeed(self, call_id: UUID, parsed_output: Any) -> None:
        path = None
        digest = None
        spec = self._spec_for_artifact(call_id)
        if self.store_payloads:
            path, digest = self._write_artifact(spec, "parsed-output.json", parsed_output)
        cost_fields: dict[str, Any] = {}
        if self.cost_pricer is not None:
            priced = self._price_call(call_id, self.cost_pricer)
            if priced is not None:
                cost_fields = {
                    "cost_micros": priced.cost_micros,
                    "pricing_version": priced.pricing_version,
                }
        self._finish(
            call_id,
            status="succeeded",
            parsed_output_artifact_path=path,
            parsed_output_sha256=digest,
            **cost_fields,
        )

    def _price_call(self, call_id: UUID, pricer: CostPricer) -> CostResult | None:
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT provider, requested_model, resolved_model, operation,
                       started_at, input_tokens, output_tokens, cached_tokens
                FROM model_calls WHERE call_id = ?
                """,
                (str(call_id),),
            ).fetchone()
        if row is None:
            return None
        return pricer.price(
            provider=row[0],
            model=row[2] or row[1],
            operation=row[3],
            started_at=_from_db_timestamp(row[4]),
            input_tokens=row[5],
            output_tokens=row[6],
            cached_tokens=row[7],
        )

    def reprice(self, pricer: CostPricer, *, since: datetime | None = None) -> int:
        """Recompute ``cost_micros``/``pricing_version`` for already-succeeded
        calls against a (possibly updated) pricing table -- the "what-if"
        number from ``thesisound observability-reprice``, distinct from the
        audit number ``succeed()`` persists once at call time. Returns how
        many calls got a price (calls still unpriced after this are simply
        missing from the table, not touched)."""

        clauses = ["status = 'succeeded'"]
        params: list[Any] = []
        if since is not None:
            clauses.append("started_at >= ?")
            params.append(_to_db_timestamp(since))
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT call_id, provider, requested_model, resolved_model, operation, "
                "started_at, input_tokens, output_tokens, cached_tokens FROM model_calls "
                "WHERE " + " AND ".join(clauses),
                params,
            ).fetchall()
            updated = 0
            for row in rows:
                priced = pricer.price(
                    provider=row[1],
                    model=row[3] or row[2],
                    operation=row[4],
                    started_at=_from_db_timestamp(row[5]),
                    input_tokens=row[6],
                    output_tokens=row[7],
                    cached_tokens=row[8],
                )
                if priced is None:
                    continue
                connection.execute(
                    "UPDATE model_calls SET cost_micros = ?, pricing_version = ? WHERE call_id = ?",
                    (priced.cost_micros, priced.pricing_version, row[0]),
                )
                updated += 1
        return updated

    def fail(
        self,
        call_id: UUID,
        error: Exception,
        *,
        error_code: str | None = None,
    ) -> None:
        self._finish(
            call_id,
            status="failed",
            error_type=type(error).__name__,
            error_code=error_code,
            error_message=redact_exception_message(str(error) or type(error).__name__),
        )

    def reject(self, call_id: UUID, error: Exception) -> None:
        self._finish(
            call_id,
            status="rejected",
            error_type=type(error).__name__,
            error_message=redact_exception_message(str(error) or type(error).__name__),
        )

    def record_retry(
        self,
        call_id: UUID,
        *,
        reason: str,
        backoff_ms: int,
    ) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE model_calls
                SET retry_scheduled = 1, retry_reason = ?, backoff_ms = ?
                WHERE call_id = ?
                """,
                (reason, max(0, backoff_ms), str(call_id)),
            )

    def begin_run(self, spec: PipelineRunSpec) -> UUID:
        """Insert a root workflow run if it is not already present.

        ``INSERT OR IGNORE`` is intentional: a workflow may open more than one
        root span with the same run id, and all calls still belong to one rollup.
        """

        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO pipeline_runs(
                    workflow_run_id, project_id, trace_id, kind, status, started_at
                ) VALUES (?, ?, ?, ?, 'running', ?)
                """,
                (
                    str(spec.workflow_run_id),
                    _uuid_text(spec.project_id),
                    str(spec.trace_id),
                    spec.kind,
                    _to_db_timestamp(spec.started_at),
                ),
            )
        return spec.workflow_run_id

    def finish_run(
        self,
        workflow_run_id: UUID,
        *,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Finish a run and recompute its call/token aggregates idempotently.

        Cost is deliberately absent: calls are not priced until a pricing table
        exists, so a run-level zero would be misleading rather than useful.
        """

        with self._lock, closing(self._connect()) as connection, connection:
            existing = connection.execute(
                "SELECT started_at FROM pipeline_runs WHERE workflow_run_id = ?",
                (str(workflow_run_id),),
            ).fetchone()
            if existing is None:
                return
            aggregate = connection.execute(
                """
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE status IN ('failed', 'rejected')),
                       COALESCE(SUM(input_tokens), 0),
                       COALESCE(SUM(output_tokens), 0),
                       COALESCE(SUM(thinking_tokens), 0),
                       COALESCE(SUM(cached_tokens), 0),
                       COALESCE(SUM(total_tokens), 0)
                FROM model_calls WHERE workflow_run_id = ?
                """,
                (str(workflow_run_id),),
            ).fetchone()
            models = [
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT resolved_model FROM model_calls "
                    "WHERE workflow_run_id = ? AND resolved_model IS NOT NULL "
                    "ORDER BY resolved_model",
                    (str(workflow_run_id),),
                ).fetchall()
            ]
            prompt_versions = [
                f"{row[0]}@{row[1]}"
                for row in connection.execute(
                    "SELECT DISTINCT prompt_id, prompt_version FROM model_calls "
                    "WHERE workflow_run_id = ? AND prompt_id IS NOT NULL "
                    "AND prompt_version IS NOT NULL ORDER BY prompt_id, prompt_version",
                    (str(workflow_run_id),),
                ).fetchall()
            ]
            # A workflow may have multiple root spans sharing this run id.
            # Each terminal root refreshes the rollup so the final span contributes
            # both its model calls and the actual run finish time.
            finished_at = _now()
            started_at = _from_db_timestamp(existing[0])
            connection.execute(
                """
                UPDATE pipeline_runs
                SET status = ?, finished_at = ?, duration_ms = ?,
                    call_count = ?, failed_call_count = ?, input_tokens = ?,
                    output_tokens = ?, thinking_tokens = ?, cached_tokens = ?,
                    total_tokens = ?, models_json = ?, prompt_versions_json = ?,
                    error_message = ?
                WHERE workflow_run_id = ?
                """,
                (
                    status,
                    _to_db_timestamp(finished_at),
                    _elapsed_ms(started_at, finished_at),
                    aggregate[0],
                    aggregate[1],
                    aggregate[2],
                    aggregate[3],
                    aggregate[4],
                    aggregate[5],
                    aggregate[6],
                    json.dumps(models, ensure_ascii=False),
                    json.dumps(prompt_versions, ensure_ascii=False),
                    redact_exception_message(error_message),
                    str(workflow_run_id),
                ),
            )

    def run_summary(self, workflow_run_id: UUID) -> PipelineRunSummary:
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT " + _PIPELINE_RUN_COLUMNS + " FROM pipeline_runs WHERE workflow_run_id = ?",
                (str(workflow_run_id),),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Pipeline run not found: {workflow_run_id}")
        return _pipeline_run_from_row(row)

    def list_runs(self, project_id: UUID, *, limit: int = 50) -> list[PipelineRunSummary]:
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT " + _PIPELINE_RUN_COLUMNS + " FROM pipeline_runs "
                "WHERE project_id = ? ORDER BY started_at DESC LIMIT ?",
                (str(project_id), max(1, min(limit, 2_000))),
            ).fetchall()
        return [_pipeline_run_from_row(row) for row in rows]

    def start_span(self, record: SpanRecord) -> None:
        """Insert a span as ``running``. Writes through immediately (no
        buffering) so any open span -- not just long-running stages -- can
        be found and reaped after a crash."""

        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO pipeline_spans(
                    span_id, trace_id, parent_span_id, project_id, workflow_run_id,
                    name, component, kind, subject_type, subject_id, status,
                    started_at, process, pid, attributes_json, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)
                """,
                (
                    str(record.context.span_id),
                    str(record.context.trace_id),
                    _uuid_text(record.parent_span_id),
                    _uuid_text(record.context.project_id),
                    _uuid_text(record.context.workflow_run_id),
                    record.name,
                    record.component,
                    record.kind,
                    record.subject_type,
                    record.subject_id,
                    _to_db_timestamp(record.started_at),
                    record.process,
                    record.pid,
                    _json(redact_value(record.attributes, store_payloads=self.store_payloads)),
                    _json(record.metrics),
                ),
            )

    def end_span(self, record: SpanRecord) -> None:
        """Update a span with its terminal status, duration, and final
        attributes/metrics. A no-op if the span row is missing (e.g. tracing
        was enabled mid-span, or the ledger was pruned)."""

        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE pipeline_spans
                SET status = ?, ended_at = ?, duration_ms = ?, error_type = ?,
                    error_message = ?, attributes_json = ?, metrics_json = ?
                WHERE span_id = ?
                """,
                (
                    record.status,
                    _to_db_timestamp(record.ended_at) if record.ended_at else None,
                    record.duration_ms,
                    record.error_type,
                    redact_exception_message(record.error_message),
                    _json(redact_value(record.attributes, store_payloads=self.store_payloads)),
                    _json(record.metrics),
                    str(record.context.span_id),
                ),
            )

    def record_event(self, record: EventRecord) -> None:
        """Insert one append-only event row. Events are never updated after
        the fact -- that is what fixes run records being mutated in place."""

        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO pipeline_events(
                    event_id, trace_id, span_id, project_id, workflow_run_id,
                    occurred_at, name, component, level, subject_type, subject_id,
                    attributes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.event_id),
                    _uuid_text(record.trace_id),
                    _uuid_text(record.span_id),
                    _uuid_text(record.project_id),
                    _uuid_text(record.workflow_run_id),
                    _to_db_timestamp(record.occurred_at),
                    record.name,
                    record.component,
                    record.level,
                    record.subject_type,
                    record.subject_id,
                    _json(redact_value(record.attributes, store_payloads=self.store_payloads)),
                ),
            )

    def reap_orphaned_spans(
        self,
        *,
        older_than_minutes: int = 60,
        process: str | None = None,
    ) -> int:
        """Close spans a crashed process left ``running``.

        Called from the same composition-root path that already calls
        ``recover_interrupted_runs()`` on each stage's run service. Marks
        every stale ``running`` span ``interrupted`` and records one
        ``run.recovered`` event per span, so crash recovery -- previously
        silent -- becomes visible in the trace.
        """

        cutoff = _to_db_timestamp(_now() - timedelta(minutes=older_than_minutes))
        with self._lock, closing(self._connect()) as connection, connection:
            clauses = ["status = 'running'", "started_at < ?"]
            params: list[Any] = [cutoff]
            if process is not None:
                clauses.append("process = ?")
                params.append(process)
            stale = connection.execute(
                f"SELECT span_id, trace_id, project_id, workflow_run_id, name "  # noqa: S608
                f"FROM pipeline_spans WHERE {' AND '.join(clauses)}",
                params,
            ).fetchall()
            if not stale:
                return 0
            now = _now()
            connection.executemany(
                "UPDATE pipeline_spans SET status = 'interrupted', ended_at = ? WHERE span_id = ?",
                [(_to_db_timestamp(now), row[0]) for row in stale],
            )
            connection.executemany(
                """
                INSERT INTO pipeline_events(
                    event_id, trace_id, span_id, project_id, workflow_run_id,
                    occurred_at, name, component, level, attributes_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'run.recovered', 'observability', 'warn', ?)
                """,
                [
                    (
                        str(uuid4()),
                        row[1],
                        row[0],
                        row[2],
                        row[3],
                        _to_db_timestamp(now),
                        _json({"span_name": row[4], "reason": "interrupted_by_restart"}),
                    )
                    for row in stale
                ],
            )
        return len(stale)

    def get_span(self, span_id: UUID) -> SpanSummary:
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT " + _SPAN_COLUMNS + " FROM pipeline_spans WHERE span_id = ?",
                (str(span_id),),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Span not found: {span_id}")
        return _span_from_row(row)

    def list_spans(self, trace_id: UUID) -> list[SpanSummary]:
        """Every span in one trace, in start order -- the tree is implicit
        in each row's ``parent_span_id``."""

        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT " + _SPAN_COLUMNS + " FROM pipeline_spans "
                "WHERE trace_id = ? ORDER BY started_at",
                (str(trace_id),),
            ).fetchall()
        return [_span_from_row(row) for row in rows]

    def list_recent_traces(self, project_id: UUID, *, limit: int = 20) -> list[UUID]:
        """The most recent distinct trace IDs for a project, newest first --
        the natural starting point for "show me the latest run"."""

        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT trace_id, MAX(started_at) AS latest
                FROM pipeline_spans
                WHERE project_id = ? AND parent_span_id IS NULL
                GROUP BY trace_id
                ORDER BY latest DESC
                LIMIT ?
                """,
                (str(project_id), max(1, min(limit, 500))),
            ).fetchall()
        return [UUID(row[0]) for row in rows]

    def list_events(self, trace_id: UUID) -> list[EventSummary]:
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT " + _EVENT_COLUMNS + " FROM pipeline_events "
                "WHERE trace_id = ? ORDER BY occurred_at",
                (str(trace_id),),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def get_trace(self, trace_id: UUID) -> list[TraceNode]:
        """Every node in one trace -- spans and model calls together, via
        the ``trace_nodes`` view -- in start order. The tree is implicit in
        each row's ``parent_id``, same as ``list_spans``."""

        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT node_id, trace_id, parent_id, project_id, name, component,
                       kind, status, started_at, ended_at, duration_ms,
                       subject_type, subject_id, node_source
                FROM trace_nodes
                WHERE trace_id = ?
                ORDER BY started_at
                """,
                (str(trace_id),),
            ).fetchall()
        return [_trace_node_from_row(row) for row in rows]

    def list_events_by_project(self, project_id: UUID, *, limit: int = 200) -> list[EventSummary]:
        """Every event for a project, newest first, regardless of trace.

        Unlike ``list_events``, this also surfaces events recorded with no
        ambient span at all -- state transitions from ``pipeline.transition``
        are the common case, since most of that module runs outside any
        span today.
        """

        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT " + _EVENT_COLUMNS + " FROM pipeline_events "
                "WHERE project_id = ? ORDER BY occurred_at DESC LIMIT ?",
                (str(project_id), max(1, min(limit, 2_000))),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def list_calls(
        self,
        project_id: UUID,
        *,
        stage: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[CallSummary]:
        clauses = ["project_id = ?"]
        params: list[Any] = [str(project_id)]
        if stage:
            clauses.append("stage = ?")
            params.append(stage)
        if status:
            clauses.append("status = ?")
            params.append(status)
        params.append(max(1, min(limit, 2_000)))
        query = (
            "SELECT "
            + _CALL_SUMMARY_COLUMNS
            + " FROM model_calls WHERE "
            + " AND ".join(clauses)
            + " ORDER BY started_at DESC LIMIT ?"
        )
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(query, params).fetchall()
        return [_summary_from_row(row) for row in rows]

    def get_call(self, call_id: UUID) -> CallDetail:
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT " + _CALL_DETAIL_COLUMNS + " FROM model_calls WHERE call_id = ?",
                (str(call_id),),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f"Model call not found: {call_id}")
            attempts = connection.execute(
                """
                SELECT attempt_id, call_id, logical_attempt, provider_attempt,
                       key_slot, key_fingerprint, credential_type, status,
                       started_at, ended_at, latency_ms, http_status, retryable,
                       retry_reason, error_type, error_code, error_message
                FROM model_attempts
                WHERE call_id = ?
                ORDER BY attempt_id
                """,
                (str(call_id),),
            ).fetchall()
        summary = _summary_from_row(row[:_CALL_SUMMARY_FIELD_COUNT])
        offset = _CALL_SUMMARY_FIELD_COUNT
        metadata = json.loads(row[offset + 12] or "{}")
        return CallDetail(
            call=summary,
            prompt_id=row[offset],
            prompt_version=row[offset + 1],
            workflow_run_id=_optional_uuid(row[offset + 2]),
            parent_call_id=_optional_uuid(row[offset + 3]),
            timeout_ms=row[offset + 4],
            grounding_mode=row[offset + 5] or "none",
            retry_scheduled=bool(row[offset + 6]),
            retry_reason=row[offset + 7],
            backoff_ms=row[offset + 8],
            request_artifact_path=row[offset + 9],
            raw_response_artifact_path=row[offset + 10],
            parsed_output_artifact_path=row[offset + 11],
            metadata=metadata,
            pipeline_trace_id=_optional_uuid(row[offset + 13]),
            parent_span_id=_optional_uuid(row[offset + 14]),
            attempts=[_attempt_from_row(item) for item in attempts],
        )

    def read_artifact(self, relative_path: str, *, max_characters: int = 200_000) -> str:
        path = (self.artifact_root.parent / relative_path).resolve()
        allowed = self.artifact_root.parent.resolve()
        if path != allowed and allowed not in path.parents:
            raise ValueError("Artifact path escapes the observability root.")
        text = path.read_text(encoding="utf-8")
        return text[:max_characters]

    def _finish(self, call_id: UUID, *, status: CallStatus, **fields: Any) -> None:
        ended = _now()
        assignments = ["status = ?", "ended_at = ?"]
        params: list[Any] = [status, _to_db_timestamp(ended)]
        for name, value in fields.items():
            assignments.append(f"{name} = ?")
            params.append(value)
        params.append(str(call_id))
        with self._lock, closing(self._connect()) as connection, connection:
            started_row = connection.execute(
                "SELECT started_at FROM model_calls WHERE call_id = ?",
                (str(call_id),),
            ).fetchone()
            if started_row is None:
                return
            started = _from_db_timestamp(started_row[0])
            assignments.append("latency_ms = ?")
            params.insert(-1, max(0, round((ended - started).total_seconds() * 1000)))
            connection.execute(
                "UPDATE model_calls SET " + ", ".join(assignments) + " WHERE call_id = ?",
                params,
            )

    def _spec_for_artifact(self, call_id: UUID) -> ModelCallSpec:
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT trace_id, parent_call_id, project_id, workflow_run_id,
                       stage, operation, provider, requested_model, prompt_id,
                       prompt_version, subject_type, subject_id, logical_attempt,
                       timeout_ms, grounding_mode, metadata_json
                FROM model_calls WHERE call_id = ?
                """,
                (str(call_id),),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Model call not found: {call_id}")
        return ModelCallSpec(
            call_id=call_id,
            trace_id=_optional_uuid(row[0]),
            parent_call_id=_optional_uuid(row[1]),
            project_id=_optional_uuid(row[2]),
            workflow_run_id=_optional_uuid(row[3]),
            stage=row[4],
            operation=row[5],
            provider=row[6],
            requested_model=row[7],
            prompt_id=row[8],
            prompt_version=row[9],
            subject_type=row[10],
            subject_id=row[11],
            logical_attempt=row[12],
            timeout_ms=row[13],
            grounding_mode=row[14] or "none",
            metadata=json.loads(row[15] or "{}"),
        )

    def _write_artifact(
        self,
        spec: ModelCallSpec,
        filename: str,
        payload: Any,
    ) -> tuple[str, str]:
        project_segment = str(spec.project_id) if spec.project_id else "_global"
        directory = self.artifact_root / project_segment / str(spec.call_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        serialized = (
            _json(redact_value(_jsonable(payload), store_payloads=self.store_payloads)) + "\n"
        )
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(path)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        relative = path.relative_to(self.artifact_root.parent).as_posix()
        return relative, digest

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta("
                "  key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            current = int(row[0]) if row else 0
            if current > len(_MIGRATIONS):
                raise RuntimeError(
                    f"Ledger schema v{current} is newer than this build supports "
                    f"(v{len(_MIGRATIONS)}). Upgrade Thesisound or point at another ledger."
                )
            for index in range(current, len(_MIGRATIONS)):
                migration = _MIGRATIONS[index]
                if callable(migration):
                    migration(connection)
                else:
                    connection.executescript(migration)
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(index + 1),),
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection


class LedgerSpanSink:
    """Adapts :class:`ObservabilityLedger` to ``tracing.SpanSink``.

    Writes every span and event through immediately -- the same
    INSERT-then-UPDATE shape the ``model_calls`` table already uses for
    ``begin_call``/``_finish`` -- rather than batching in memory. Simpler
    and safer than a buffered writer, at the cost of one SQL statement per
    span; ``Settings.tracing_detail`` is the primary lever for keeping
    volume down (see ``Tracer.span(detail=...)``), and batching remains a
    reasonable follow-up if measured write volume ever demands it.
    """

    def __init__(self, ledger: ObservabilityLedger) -> None:
        self.ledger = ledger

    def begin(self, record: SpanRecord) -> None:
        self.ledger.start_span(record)
        if (
            record.kind == "stage"
            and record.context.workflow_run_id is not None
            and record.parent_span_id is None
        ):
            with suppress(Exception):
                self.ledger.begin_run(
                    PipelineRunSpec(
                        workflow_run_id=record.context.workflow_run_id,
                        project_id=record.context.project_id,
                        trace_id=record.context.trace_id,
                        kind=record.component,
                        started_at=record.started_at,
                    )
                )

    def end(self, record: SpanRecord) -> None:
        self.ledger.end_span(record)
        if (
            record.kind == "stage"
            and record.context.workflow_run_id is not None
            and record.parent_span_id is None
        ):
            with suppress(Exception):
                self.ledger.finish_run(
                    record.context.workflow_run_id,
                    status="failed" if record.status == "error" else "succeeded",
                    error_message=record.error_message,
                )

    def event(self, record: EventRecord) -> None:
        self.ledger.record_event(record)


T = TypeVar("T")


class ObservedModelGateway:
    """One provider-call entry point shared by text, search, TTS, and ASR."""

    def __init__(
        self,
        ledger: ObservabilityLedger,
        *,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.ledger = ledger
        self.sleeper = sleeper

    def call(
        self,
        *,
        spec: ModelCallSpec,
        request_payload: Any,
        operation: Callable[[Any], T],
        pool: KeyPoolLike | None = None,
        client: Any | None = None,
        max_provider_attempts: int = 1,
        base_retry_delay_seconds: float = 1,
        retryable_error: Callable[[Exception], bool] | None = None,
        response_payload: Callable[[T], Any] | None = None,
        usage: Callable[[T], ModelUsage] | None = None,
        provider_metadata: Callable[[T], ProviderMetadata] | None = None,
    ) -> ProviderCallResult:
        self.ledger.begin_call(spec, request_payload)
        provider_attempt = 0
        started = _now()

        def on_key_attempt(event: dict[str, Any]) -> None:
            nonlocal provider_attempt
            provider_attempt += 1
            self.ledger.record_attempt(
                spec.call_id,
                logical_attempt=spec.logical_attempt,
                provider_attempt=provider_attempt,
                event=event,
                retryable=event.get("status") in {"quota_failed", "auth_failed"},
                retry_reason=_optional_text(event.get("failure_scope")),
            )

        predicate = retryable_error or (lambda _: False)
        for provider_round in range(1, max(1, max_provider_attempts) + 1):
            events_before = provider_attempt
            direct_started = _now()
            try:
                if pool is not None:
                    response = pool.call(operation, on_attempt=on_key_attempt)
                elif client is not None:
                    response = operation(client)
                else:
                    raise ValueError("ObservedModelGateway requires a key pool or client.")
            except Exception as exc:
                if provider_attempt == events_before:
                    provider_attempt += 1
                    ended = _now()
                    self.ledger.record_attempt(
                        spec.call_id,
                        logical_attempt=spec.logical_attempt,
                        provider_attempt=provider_attempt,
                        event={
                            "credential_type": "injected_client" if client is not None else None,
                            "status": "failed",
                            "started_at": direct_started,
                            "ended_at": ended,
                            "latency_ms": _elapsed_ms(direct_started, ended),
                            "http_status": _status_code(exc),
                            "error_type": type(exc).__name__,
                            "error_code": _error_code(exc),
                            "error_message": str(exc),
                        },
                        retryable=predicate(exc),
                        retry_reason="transient_provider_error" if predicate(exc) else None,
                    )
                if provider_round < max_provider_attempts and predicate(exc):
                    delay = base_retry_delay_seconds * (2 ** (provider_round - 1))
                    self.ledger.record_retry(
                        spec.call_id,
                        reason=type(exc).__name__,
                        backoff_ms=round(delay * 1000),
                    )
                    if delay:
                        self.sleeper(delay)
                    continue
                self.ledger.fail(spec.call_id, exc, error_code=_error_code(exc))
                raise

            if provider_attempt == events_before:
                provider_attempt += 1
                ended = _now()
                self.ledger.record_attempt(
                    spec.call_id,
                    logical_attempt=spec.logical_attempt,
                    provider_attempt=provider_attempt,
                    event={
                        "credential_type": "injected_client",
                        "status": "succeeded",
                        "started_at": direct_started,
                        "ended_at": ended,
                        "latency_ms": _elapsed_ms(direct_started, ended),
                    },
                )
            payload = response_payload(response) if response_payload else _jsonable(response)
            usage_value = usage(response) if usage else ModelUsage()
            metadata_value = (
                provider_metadata(response) if provider_metadata else ProviderMetadata()
            )
            self.ledger.provider_succeeded(
                spec.call_id,
                response_payload=payload,
                usage=usage_value,
                provider_metadata=metadata_value,
            )
            return ProviderCallResult(call_id=spec.call_id, response=response)

        error = RuntimeError(
            f"Provider call exhausted attempts after {_elapsed_ms(started, _now())} ms."
        )
        self.ledger.fail(spec.call_id, error)
        raise error


_SHARED_LEDGERS: dict[tuple[str, str, bool], ObservabilityLedger] = {}
_SHARED_LEDGERS_LOCK = RLock()


def shared_observability_ledger(
    database_path: Path,
    artifact_root: Path,
    *,
    store_payloads: bool = True,
    cost_pricer: CostPricer | None = None,
) -> ObservabilityLedger:
    key = (
        str(database_path.expanduser().resolve()),
        str(artifact_root.expanduser().resolve()),
        store_payloads,
    )
    with _SHARED_LEDGERS_LOCK:
        ledger = _SHARED_LEDGERS.get(key)
        if ledger is None:
            ledger = ObservabilityLedger(
                database_path,
                artifact_root,
                store_payloads=store_payloads,
                cost_pricer=cost_pricer,
            )
            _SHARED_LEDGERS[key] = ledger
        return ledger


def ledger_from_settings(settings: Any | None = None) -> ObservabilityLedger:
    if settings is None:
        from thesisound.config import Settings

        settings = Settings()
    # Local import: services.model_pricing imports CostResult from this module,
    # so importing CostCalculator at module level here would be circular.
    from thesisound.services.model_pricing import CostCalculator

    return shared_observability_ledger(
        settings.resolved_observability_database_path,
        settings.resolved_observability_artifact_root,
        store_payloads=settings.observability_store_payloads,
        cost_pricer=CostCalculator(settings.pricing_file),
    )


def tracer_from_settings(settings: Any | None = None) -> Tracer:
    """The composition-root factory for the ambient tracer, matching
    ``ledger_from_settings``'s pattern. Returns a disabled ``Tracer`` (not a
    ``NullTracer`` -- there is only one ``Tracer`` class; disabling it makes
    every span/event call a cheap no-op) when
    ``Settings.tracing_enabled`` is false, so callers can install the result
    unconditionally without an if/else at every call site."""

    if settings is None:
        from thesisound.config import Settings

        settings = Settings()
    ledger = ledger_from_settings(settings)
    return Tracer(
        LedgerSpanSink(ledger),
        enabled=settings.tracing_enabled,
        detail=settings.tracing_detail,
    )


def is_sensitive_key(name: str) -> bool:
    """Whether a field/attribute name is a known secret carrier by name
    alone (``password``, ``api_key``, ...), independent of what its value
    looks like. Shared by dict-shaped redaction (``redact_value``) and
    attribute-shaped redaction (``logging_setup.RedactingFilter``, for
    ``logger.info(..., extra={...})`` fields)."""

    return str(name).casefold().replace("-", "_") in _SENSITIVE_KEYS


def _sensitive_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _hashed_sensitive_value(value: Any) -> dict[str, Any]:
    text = _sensitive_text(value)
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "length": len(text),
    }


def _filename_identity(value: Any, container: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        digest = value.get("filename_sha256")
        extension = value.get("extension")
        if isinstance(digest, str) and isinstance(extension, str):
            identity: dict[str, Any] = {
                "filename_sha256": digest[:16],
                "extension": extension,
            }
            size = value.get("size_bytes")
            if isinstance(size, int | float) and size >= 0:
                identity["size_bytes"] = int(size)
            return identity

    filename = str(value)
    identity: dict[str, Any] = {
        "filename_sha256": hashlib.sha256(filename.encode("utf-8")).hexdigest()[:16],
        "extension": Path(filename).suffix.lower(),
    }
    for key in ("size_bytes", "file_size_bytes", "byte_count"):
        size = container.get(key)
        if isinstance(size, int | float) and size >= 0:
            identity["size_bytes"] = int(size)
            break
    return identity


def redact_value(value: Any, *, store_payloads: bool = False) -> Any:
    """Apply the single observability privacy policy recursively.

    Credential/identity carriers are always redacted. User-content attributes
    are deterministic hash+length unless the one existing payload-storage
    switch is enabled. Filenames are always represented by a deterministic
    short hash plus extension (and file size when the caller supplied it), so
    plaintext filenames remain confined to the project manifest.
    """

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.casefold().replace("-", "_")
            if is_sensitive_key(key):
                redacted[key] = "[REDACTED]"
            elif normalized == "filename":
                redacted[key] = _filename_identity(item, value)
            elif normalized in SENSITIVE_ATTRIBUTES and not store_payloads:
                redacted[key] = _hashed_sensitive_value(item)
            else:
                redacted[key] = redact_value(item, store_payloads=store_payloads)
        return redacted
    if isinstance(value, list):
        return [redact_value(item, store_payloads=store_payloads) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item, store_payloads=store_payloads) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_exception_message(value: str | None) -> str | None:
    if value is None:
        return None
    return redact_text(str(value))[:1_000]


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, bytes):
        return {
            "binary": True,
            "size_bytes": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _jsonable(model_dump(mode="json"))
        except TypeError:
            return _jsonable(model_dump())
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _summary_from_row(row: tuple[Any, ...]) -> CallSummary:
    return CallSummary(
        call_id=UUID(row[0]),
        trace_id=_optional_uuid(row[1]),
        project_id=_optional_uuid(row[2]),
        stage=row[3],
        operation=row[4],
        provider=row[5],
        requested_model=row[6],
        resolved_model=row[7],
        status=row[8],
        started_at=_from_db_timestamp(row[9]),
        ended_at=_from_db_timestamp(row[10]) if row[10] else None,
        latency_ms=row[11],
        provider_attempt_count=row[12] or 0,
        input_tokens=row[13],
        output_tokens=row[14],
        thinking_tokens=row[15],
        cached_tokens=row[16],
        total_tokens=row[17],
        finish_reason=row[18],
        error_type=row[19],
        error_message=redact_exception_message(row[20]),
        subject_type=row[21],
        subject_id=row[22],
        cost_micros=row[23],
        pricing_version=row[24],
    )


def _attempt_from_row(row: tuple[Any, ...]) -> AttemptRecord:
    return AttemptRecord(
        attempt_id=row[0],
        call_id=UUID(row[1]),
        logical_attempt=row[2],
        provider_attempt=row[3],
        key_slot=row[4],
        key_fingerprint=row[5],
        credential_type=row[6],
        status=row[7],
        started_at=_from_db_timestamp(row[8]),
        ended_at=_from_db_timestamp(row[9]),
        latency_ms=row[10],
        http_status=row[11],
        retryable=bool(row[12]),
        retry_reason=row[13],
        error_type=row[14],
        error_code=row[15],
        error_message=redact_exception_message(row[16]),
    )


_SPAN_COLUMNS = """
span_id, trace_id, parent_span_id, project_id, workflow_run_id, name,
component, kind, subject_type, subject_id, status, started_at, ended_at,
duration_ms, process, error_type, error_message, attributes_json, metrics_json
""".replace("\n", " ").strip()

_EVENT_COLUMNS = """
event_id, trace_id, span_id, project_id, workflow_run_id, occurred_at,
name, component, level, subject_type, subject_id, attributes_json
""".replace("\n", " ").strip()


def _span_from_row(row: tuple[Any, ...]) -> SpanSummary:
    return SpanSummary(
        span_id=UUID(row[0]),
        trace_id=UUID(row[1]),
        parent_span_id=_optional_uuid(row[2]),
        project_id=_optional_uuid(row[3]),
        workflow_run_id=_optional_uuid(row[4]),
        name=row[5],
        component=row[6],
        kind=row[7],
        subject_type=row[8],
        subject_id=row[9],
        status=row[10],
        started_at=_from_db_timestamp(row[11]),
        ended_at=_from_db_timestamp(row[12]) if row[12] else None,
        duration_ms=row[13],
        process=row[14],
        error_type=row[15],
        error_message=redact_exception_message(row[16]),
        attributes=json.loads(row[17] or "{}"),
        metrics=json.loads(row[18] or "{}"),
    )


def _event_from_row(row: tuple[Any, ...]) -> EventSummary:
    return EventSummary(
        event_id=UUID(row[0]),
        trace_id=_optional_uuid(row[1]),
        span_id=_optional_uuid(row[2]),
        project_id=_optional_uuid(row[3]),
        workflow_run_id=_optional_uuid(row[4]),
        occurred_at=_from_db_timestamp(row[5]),
        name=row[6],
        component=row[7],
        level=row[8],
        subject_type=row[9],
        subject_id=row[10],
        attributes=json.loads(row[11] or "{}"),
    )


def _trace_node_from_row(row: tuple[Any, ...]) -> TraceNode:
    return TraceNode(
        node_id=UUID(row[0]),
        trace_id=UUID(row[1]),
        parent_id=_optional_uuid(row[2]),
        project_id=_optional_uuid(row[3]),
        name=row[4],
        component=row[5],
        kind=row[6],
        status=row[7],
        started_at=_from_db_timestamp(row[8]),
        ended_at=_from_db_timestamp(row[9]) if row[9] else None,
        duration_ms=row[10],
        subject_type=row[11],
        subject_id=row[12],
        node_source=row[13],
    )


_PIPELINE_RUN_COLUMNS = """
workflow_run_id, project_id, trace_id, kind, status, started_at, finished_at,
duration_ms, call_count, failed_call_count, input_tokens, output_tokens,
thinking_tokens, cached_tokens, total_tokens, models_json,
prompt_versions_json, error_message
""".replace("\n", " ").strip()


def _pipeline_run_from_row(row: tuple[Any, ...]) -> PipelineRunSummary:
    return PipelineRunSummary(
        workflow_run_id=UUID(row[0]),
        project_id=_optional_uuid(row[1]),
        trace_id=_optional_uuid(row[2]),
        kind=row[3],
        status=row[4],
        started_at=_from_db_timestamp(row[5]),
        finished_at=_from_db_timestamp(row[6]) if row[6] else None,
        duration_ms=row[7],
        call_count=row[8],
        failed_call_count=row[9],
        input_tokens=row[10],
        output_tokens=row[11],
        thinking_tokens=row[12],
        cached_tokens=row[13],
        total_tokens=row[14],
        models=json.loads(row[15] or "[]"),
        prompt_versions=json.loads(row[16] or "[]"),
        error_message=redact_exception_message(row[17]),
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _to_db_timestamp(value: datetime) -> str:
    """Render a datetime for storage. One function so a later engine swap
    (e.g. to a native TIMESTAMPTZ column) touches only this pair."""

    return value.astimezone(UTC).isoformat()


def _from_db_timestamp(value: str) -> datetime:
    """Parse a timestamp column value written by ``_to_db_timestamp``."""

    return datetime.fromisoformat(value)


def _elapsed_ms(started: datetime, ended: datetime) -> int:
    return max(0, round((ended - started).total_seconds() * 1000))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _uuid_text(value: UUID | None) -> str | None:
    return str(value) if value else None


def _optional_uuid(value: Any) -> UUID | None:
    return UUID(value) if value else None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _truncate(value: str | None, limit: int = 4_000) -> str | None:
    if value is None:
        return None
    return value[:limit]


def _status_code(exc: Exception) -> int | None:
    for attribute in ("status_code", "code"):
        value = getattr(exc, attribute, None)
        if callable(value):
            value = value()
        if isinstance(value, int):
            return value
        enum_value = getattr(value, "value", None)
        if isinstance(enum_value, int):
            return enum_value
    return None


def _error_code(exc: Exception) -> str | None:
    for attribute in ("reason", "error_code", "code"):
        value = getattr(exc, attribute, None)
        if callable(value):
            value = value()
        if value is not None and not isinstance(value, int):
            return str(getattr(value, "value", value))
    status = _status_code(exc)
    return str(status) if status is not None else None


_CALL_SUMMARY_COLUMNS = """
call_id, trace_id, project_id, stage, operation, provider,
requested_model, resolved_model, status, started_at, ended_at,
latency_ms, provider_attempt_count, input_tokens, output_tokens,
thinking_tokens, cached_tokens, total_tokens, finish_reason,
error_type, error_message, subject_type, subject_id,
cost_micros, pricing_version
""".replace("\n", " ").strip()
_CALL_SUMMARY_FIELD_COUNT = 25
_CALL_DETAIL_COLUMNS = (
    _CALL_SUMMARY_COLUMNS
    + ", prompt_id, prompt_version, workflow_run_id, parent_call_id, timeout_ms, "
    "grounding_mode, retry_scheduled, retry_reason, backoff_ms, "
    "request_artifact_path, raw_response_artifact_path, parsed_output_artifact_path, "
    "metadata_json, pipeline_trace_id, parent_span_id"
)

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS model_calls(
    call_id TEXT PRIMARY KEY,
    trace_id TEXT,
    parent_call_id TEXT,
    project_id TEXT,
    workflow_run_id TEXT,
    stage TEXT NOT NULL,
    operation TEXT NOT NULL,
    provider TEXT NOT NULL,
    requested_model TEXT NOT NULL,
    resolved_model TEXT,
    prompt_id TEXT,
    prompt_version TEXT,
    subject_type TEXT,
    subject_id TEXT,
    logical_attempt INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    latency_ms INTEGER,
    timeout_ms INTEGER,
    provider_attempt_count INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER,
    output_tokens INTEGER,
    thinking_tokens INTEGER,
    cached_tokens INTEGER,
    total_tokens INTEGER,
    finish_reason TEXT,
    grounding_mode TEXT NOT NULL DEFAULT 'none',
    provider_request_id TEXT,
    http_status INTEGER,
    error_type TEXT,
    error_code TEXT,
    error_message TEXT,
    retry_scheduled INTEGER NOT NULL DEFAULT 0,
    retry_reason TEXT,
    backoff_ms INTEGER,
    request_artifact_path TEXT,
    request_sha256 TEXT,
    raw_response_artifact_path TEXT,
    raw_response_sha256 TEXT,
    parsed_output_artifact_path TEXT,
    parsed_output_sha256 TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_model_calls_project_started
    ON model_calls(project_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_calls_trace
    ON model_calls(trace_id, logical_attempt);
CREATE INDEX IF NOT EXISTS idx_model_calls_status
    ON model_calls(status, stage);

CREATE TABLE IF NOT EXISTS model_attempts(
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT NOT NULL REFERENCES model_calls(call_id) ON DELETE CASCADE,
    logical_attempt INTEGER NOT NULL,
    provider_attempt INTEGER NOT NULL,
    key_slot INTEGER,
    key_fingerprint TEXT,
    credential_type TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    http_status INTEGER,
    retryable INTEGER NOT NULL DEFAULT 0,
    retry_reason TEXT,
    error_type TEXT,
    error_code TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_model_attempts_call
    ON model_attempts(call_id, provider_attempt);
"""

_SCHEMA_V2_SPANS_AND_EVENTS = """
CREATE TABLE IF NOT EXISTS pipeline_spans(
    span_id         TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL,
    parent_span_id  TEXT,
    project_id      TEXT,
    workflow_run_id TEXT,
    name            TEXT NOT NULL,
    component       TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'internal',
    subject_type    TEXT,
    subject_id      TEXT,
    status          TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    duration_ms     INTEGER,
    process         TEXT,
    pid             INTEGER,
    error_type      TEXT,
    error_message   TEXT,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    metrics_json    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_spans_trace
    ON pipeline_spans(trace_id, started_at);
CREATE INDEX IF NOT EXISTS idx_spans_project_start
    ON pipeline_spans(project_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_spans_parent
    ON pipeline_spans(parent_span_id);
CREATE INDEX IF NOT EXISTS idx_spans_open
    ON pipeline_spans(started_at) WHERE ended_at IS NULL;

CREATE TABLE IF NOT EXISTS pipeline_events(
    event_id        TEXT PRIMARY KEY,
    trace_id        TEXT,
    span_id         TEXT,
    project_id      TEXT,
    workflow_run_id TEXT,
    occurred_at     TEXT NOT NULL,
    name            TEXT NOT NULL,
    component       TEXT NOT NULL,
    level           TEXT NOT NULL DEFAULT 'info',
    subject_type    TEXT,
    subject_id      TEXT,
    attributes_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_project_time
    ON pipeline_events(project_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_trace
    ON pipeline_events(trace_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_name_time
    ON pipeline_events(name, occurred_at DESC);
"""

# One row per node in the tree view: a pipeline span or a model call, keyed
# so a single recursive query can walk the whole trace regardless of which
# table a given node actually lives in.
_SCHEMA_V2_TRACE_NODES_VIEW = """
CREATE VIEW IF NOT EXISTS trace_nodes AS
    SELECT span_id AS node_id, trace_id, parent_span_id AS parent_id, project_id,
           name, component, kind, status, started_at, ended_at, duration_ms,
           subject_type, subject_id, 'span' AS node_source
      FROM pipeline_spans
    UNION ALL
    SELECT call_id AS node_id, pipeline_trace_id AS trace_id, parent_span_id AS parent_id,
           project_id, stage || '/' || operation AS name, 'model' AS component,
           'model' AS kind, status, started_at, ended_at, latency_ms AS duration_ms,
           subject_type, subject_id, 'model_call' AS node_source
      FROM model_calls;
"""

_SCHEMA_V3_PIPELINE_RUNS = """
CREATE TABLE IF NOT EXISTS pipeline_runs(
    workflow_run_id TEXT PRIMARY KEY,
    project_id      TEXT,
    trace_id        TEXT,
    kind            TEXT NOT NULL,
    status          TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    duration_ms     INTEGER,
    call_count      INTEGER NOT NULL DEFAULT 0,
    failed_call_count INTEGER NOT NULL DEFAULT 0,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    thinking_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens   INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    models_json     TEXT NOT NULL DEFAULT '[]',
    prompt_versions_json TEXT NOT NULL DEFAULT '[]',
    error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_project_started
    ON pipeline_runs(project_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_kind_status
    ON pipeline_runs(kind, status);
"""

# New model_calls columns added by migration 2. `trace_id` already existed
# (meaning "one ModelRunRecord") before this migration and keeps that
# meaning unchanged; `pipeline_trace_id` is the new, distinct concept of
# "one pipeline_spans tree", added rather than repurposing the existing
# column so historical queries and docs/29-model-observability.md stay
# correct on both sides of the migration boundary.
_MODEL_CALLS_V2_COLUMNS: tuple[tuple[str, str], ...] = (
    ("pipeline_trace_id", "pipeline_trace_id TEXT"),
    ("parent_span_id", "parent_span_id TEXT"),
    ("cost_micros", "cost_micros INTEGER"),
    ("pricing_version", "pricing_version TEXT"),
)


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Add a column if it is not already there. ``ALTER TABLE ADD COLUMN``
    has no ``IF NOT EXISTS`` form in SQLite, so migrations that add columns
    must guard it themselves to stay idempotent."""

    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _migrate_v2_pipeline_spans_and_events(connection: sqlite3.Connection) -> None:
    for column, ddl in _MODEL_CALLS_V2_COLUMNS:
        _ensure_column(connection, "model_calls", column, ddl)
    connection.executescript(_SCHEMA_V2_SPANS_AND_EVENTS)
    connection.executescript(_SCHEMA_V2_TRACE_NODES_VIEW)


# Ordered, append-only migration history. Every entry must be idempotent
# (CREATE TABLE/INDEX ... IF NOT EXISTS; guarded ALTER TABLE via
# _ensure_column) because sqlite3's executescript() issues an implicit
# COMMIT before it runs, so a migration is not atomic across its own
# statements -- re-running a half-applied migration must be a safe no-op.
# Never edit a migration that has shipped; add a new one instead. An entry
# may be either a raw SQL script (executed via executescript) or a callable
# taking the connection, for migrations that need conditional logic.
_MIGRATIONS: tuple[str | Callable[[sqlite3.Connection], None], ...] = (
    _SCHEMA_V1,
    _migrate_v2_pipeline_spans_and_events,
    _SCHEMA_V3_PIPELINE_RUNS,
)
