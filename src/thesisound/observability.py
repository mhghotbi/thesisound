from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Literal, Protocol, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from thesisound.modeling import GroundingMode, ModelUsage

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
    "secret",
    "access_token",
    "refresh_token",
    "session",
    "session_id",
}
_GEMINI_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_-]{20,}")


class ModelCallSpec(BaseModel):
    call_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID | None = None
    parent_call_id: UUID | None = None
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


class ProjectUsageSummary(BaseModel):
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


class ObservabilityLedger:
    """SQLite metadata ledger plus redacted request/response artifacts."""

    def __init__(
        self,
        database_path: Path,
        artifact_root: Path,
        *,
        store_payloads: bool = True,
    ) -> None:
        self.database_path = database_path.expanduser().resolve()
        self.artifact_root = artifact_root.expanduser().resolve()
        self.store_payloads = store_payloads
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
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO model_calls(
                    call_id, trace_id, parent_call_id, project_id, workflow_run_id,
                    stage, operation, provider, requested_model, prompt_id,
                    prompt_version, subject_type, subject_id, logical_attempt,
                    status, started_at, timeout_ms, grounding_mode,
                    request_artifact_path, request_sha256, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(spec.call_id),
                    _uuid_text(spec.trace_id),
                    _uuid_text(spec.parent_call_id),
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
                    started.isoformat(),
                    spec.timeout_ms,
                    spec.grounding_mode,
                    request_path,
                    request_hash,
                    _json(spec.metadata),
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
        with self._connect() as connection:
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
                    started_at.isoformat(),
                    ended_at.isoformat(),
                    latency_ms,
                    _optional_int(event.get("http_status")),
                    int(retryable),
                    retry_reason,
                    _optional_text(event.get("error_type")),
                    _optional_text(event.get("error_code")),
                    _truncate(_optional_text(event.get("error_message"))),
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
        with self._connect() as connection:
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
        self._finish(
            call_id,
            status="succeeded",
            parsed_output_artifact_path=path,
            parsed_output_sha256=digest,
        )

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
            error_message=_truncate(str(error) or type(error).__name__),
        )

    def reject(self, call_id: UUID, error: Exception) -> None:
        self._finish(
            call_id,
            status="rejected",
            error_type=type(error).__name__,
            error_message=_truncate(str(error) or type(error).__name__),
        )

    def record_retry(
        self,
        call_id: UUID,
        *,
        reason: str,
        backoff_ms: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE model_calls
                SET retry_scheduled = 1, retry_reason = ?, backoff_ms = ?
                WHERE call_id = ?
                """,
                (reason, max(0, backoff_ms), str(call_id)),
            )

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
            "SELECT " + _CALL_SUMMARY_COLUMNS + " FROM model_calls WHERE "
            + " AND ".join(clauses)
            + " ORDER BY started_at DESC LIMIT ?"
        )
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_summary_from_row(row) for row in rows]

    def get_call(self, call_id: UUID) -> CallDetail:
        with self._connect() as connection:
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
            attempts=[_attempt_from_row(item) for item in attempts],
        )

    def project_summary(self, project_id: UUID) -> ProjectUsageSummary:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*),
                       SUM(status = 'succeeded'),
                       SUM(status = 'failed'),
                       SUM(status = 'rejected'),
                       COALESCE(SUM(provider_attempt_count), 0),
                       COALESCE(SUM(input_tokens), 0),
                       COALESCE(SUM(output_tokens), 0),
                       COALESCE(SUM(thinking_tokens), 0),
                       COALESCE(SUM(cached_tokens), 0),
                       COALESCE(SUM(total_tokens), 0),
                       COALESCE(SUM(latency_ms), 0)
                FROM model_calls
                WHERE project_id = ?
                """,
                (str(project_id),),
            ).fetchone()
        values = row or (0,) * 11
        return ProjectUsageSummary(
            project_id=project_id,
            call_count=int(values[0] or 0),
            succeeded_count=int(values[1] or 0),
            failed_count=int(values[2] or 0),
            rejected_count=int(values[3] or 0),
            provider_attempt_count=int(values[4] or 0),
            input_tokens=int(values[5] or 0),
            output_tokens=int(values[6] or 0),
            thinking_tokens=int(values[7] or 0),
            cached_tokens=int(values[8] or 0),
            total_tokens=int(values[9] or 0),
            total_latency_ms=int(values[10] or 0),
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
        params: list[Any] = [status, ended.isoformat()]
        for name, value in fields.items():
            assignments.append(f"{name} = ?")
            params.append(value)
        params.append(str(call_id))
        with self._connect() as connection:
            started_row = connection.execute(
                "SELECT started_at FROM model_calls WHERE call_id = ?",
                (str(call_id),),
            ).fetchone()
            if started_row is None:
                return
            started = datetime.fromisoformat(started_row[0])
            assignments.append("latency_ms = ?")
            params.insert(-1, max(0, round((ended - started).total_seconds() * 1000)))
            connection.execute(
                "UPDATE model_calls SET " + ", ".join(assignments) + " WHERE call_id = ?",
                params,
            )

    def _spec_for_artifact(self, call_id: UUID) -> ModelCallSpec:
        with self._connect() as connection:
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
        serialized = _json(_redact(_jsonable(payload))) + "\n"
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(path)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        relative = path.relative_to(self.artifact_root.parent).as_posix()
        return relative, digest

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection


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
            )
            _SHARED_LEDGERS[key] = ledger
        return ledger


def ledger_from_settings(settings: Any | None = None) -> ObservabilityLedger:
    if settings is None:
        from thesisound.config import Settings

        settings = Settings()
    return shared_observability_ledger(
        settings.resolved_observability_database_path,
        settings.resolved_observability_artifact_root,
        store_payloads=settings.observability_store_payloads,
    )


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            result[str(key)] = "[REDACTED]" if normalized in _SENSITIVE_KEYS else _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _GEMINI_KEY_PATTERN.sub("[REDACTED_GEMINI_KEY]", value)
    return value


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
        started_at=datetime.fromisoformat(row[9]),
        ended_at=datetime.fromisoformat(row[10]) if row[10] else None,
        latency_ms=row[11],
        provider_attempt_count=row[12] or 0,
        input_tokens=row[13],
        output_tokens=row[14],
        thinking_tokens=row[15],
        cached_tokens=row[16],
        total_tokens=row[17],
        finish_reason=row[18],
        error_type=row[19],
        error_message=row[20],
        subject_type=row[21],
        subject_id=row[22],
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
        started_at=datetime.fromisoformat(row[8]),
        ended_at=datetime.fromisoformat(row[9]),
        latency_ms=row[10],
        http_status=row[11],
        retryable=bool(row[12]),
        retry_reason=row[13],
        error_type=row[14],
        error_code=row[15],
        error_message=row[16],
    )


def _now() -> datetime:
    return datetime.now(UTC)


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
error_type, error_message, subject_type, subject_id
""".replace("\n", " ").strip()
_CALL_SUMMARY_FIELD_COUNT = 23
_CALL_DETAIL_COLUMNS = (
    _CALL_SUMMARY_COLUMNS
    + ", prompt_id, prompt_version, workflow_run_id, parent_call_id, timeout_ms, "
    "grounding_mode, retry_scheduled, retry_reason, backoff_ms, "
    "request_artifact_path, raw_response_artifact_path, parsed_output_artifact_path, "
    "metadata_json"
)

_SCHEMA = """
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
