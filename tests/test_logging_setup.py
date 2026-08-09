from __future__ import annotations

import json
import logging
import logging.config
from pathlib import Path
from uuid import uuid4

from thesisound import tracing
from thesisound.config import Settings
from thesisound.logging_setup import (
    ConsoleFormatter,
    JsonFormatter,
    RedactingFilter,
    TraceContextFilter,
    configure_logging,
    uvicorn_log_config,
)


def _record(
    msg: str,
    *,
    args: tuple[object, ...] = (),
    level: int = logging.INFO,
    extra: dict[str, object] | None = None,
    exc_info: object = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="thesisound.test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=exc_info,
    )
    for key, value in (extra or {}).items():
        setattr(record, key, value)
    return record


def test_trace_context_filter_attaches_ambient_ids(recording_tracer: tracing.Tracer) -> None:
    project_id = uuid4()
    with tracing.span("corpus.run", project_id=project_id) as span:
        record = _record("hello")
        TraceContextFilter().filter(record)

    assert record.trace_id == str(span.context.trace_id)  # type: ignore[attr-defined]
    assert record.span_id == str(span.context.span_id)  # type: ignore[attr-defined]
    assert record.project_id == str(project_id)  # type: ignore[attr-defined]


def test_trace_context_filter_sets_none_outside_any_span() -> None:
    record = _record("hello")

    TraceContextFilter().filter(record)

    assert record.trace_id is None  # type: ignore[attr-defined]
    assert record.span_id is None  # type: ignore[attr-defined]
    assert record.project_id is None  # type: ignore[attr-defined]


def test_redacting_filter_scrubs_the_rendered_message_including_args() -> None:
    record = _record(
        "key=%s phone=%s",
        args=("AIzaSyABCDEFGHIJKLMNOPQRSTUVWXY", "09120000000"),
    )

    RedactingFilter().filter(record)

    assert "AIzaSy" not in record.msg
    assert "09120000000" not in record.msg
    assert "[REDACTED_GEMINI_KEY]" in record.msg
    assert "[REDACTED_PHONE]" in record.msg
    assert record.args == ()


def test_redacting_filter_redacts_extra_fields_by_sensitive_name() -> None:
    record = _record("login attempt", extra={"password": "hunter2", "user_id": "abc"})

    RedactingFilter().filter(record)

    assert record.password == "[REDACTED]"  # type: ignore[attr-defined]
    assert record.user_id == "abc"  # type: ignore[attr-defined]


def test_redacting_filter_redacts_a_gemini_key_found_in_an_unnamed_extra_value() -> None:
    record = _record(
        "provider error", extra={"detail": "token AIzaSyABCDEFGHIJKLMNOPQRSTUVWXY rejected"}
    )

    RedactingFilter().filter(record)

    assert "AIzaSy" not in record.detail  # type: ignore[attr-defined]


def test_redacting_filter_does_not_touch_standard_record_attributes() -> None:
    record = _record("hello")

    RedactingFilter().filter(record)

    assert record.name == "thesisound.test"
    assert record.levelname == "INFO"


def test_json_formatter_produces_valid_json_with_expected_fields(
    recording_tracer: tracing.Tracer,
) -> None:
    with tracing.span("corpus.run") as span:
        record = _record("hello world", extra={"stage": "corpus_run"})
        TraceContextFilter().filter(record)

    line = JsonFormatter().format(record)
    payload = json.loads(line)

    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "thesisound.test"
    assert payload["trace_id"] == str(span.context.trace_id)
    assert payload["span_id"] == str(span.context.span_id)
    assert payload["stage"] == "corpus_run"
    assert "timestamp" in payload


def test_json_formatter_includes_exception_text() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _record("failed", level=logging.ERROR, exc_info=sys.exc_info())

    payload = json.loads(JsonFormatter().format(record))

    assert "boom" in payload["exception"]


def test_console_formatter_includes_a_short_trace_prefix() -> None:
    record = _record("hello")
    record.trace_id = "abcdef1234567890"  # type: ignore[attr-defined]

    line = ConsoleFormatter().format(record)

    assert "[abcdef12]" in line
    assert "hello" in line
    assert "INFO" in line


def test_console_formatter_omits_the_prefix_outside_any_span() -> None:
    record = _record("hello")

    line = ConsoleFormatter().format(record)

    assert "[" not in line
    assert "hello" in line


def test_configure_logging_is_a_valid_dictconfig_and_is_idempotent(
    tmp_path: Path, reset_logging: None
) -> None:
    settings = Settings(log_format="json", log_file=tmp_path / "logs" / "thesisound.jsonl")

    configure_logging(settings)
    configure_logging(settings)  # must not raise or accumulate duplicate handlers

    logger = logging.getLogger()
    logger.info("configuration smoke test")
    assert (tmp_path / "logs" / "thesisound.jsonl").exists()


def test_uvicorn_log_config_disables_existing_loggers_is_false() -> None:
    settings = Settings(log_format="json")

    config = uvicorn_log_config(settings)

    # uvicorn's own default sets this True, which silently discards every
    # logger thesisound configures -- this must override that.
    assert config["disable_existing_loggers"] is False
    assert "uvicorn" in config["loggers"]
    assert "uvicorn.access" in config["loggers"]


def test_configure_logging_accepts_dictconfig_directly(reset_logging: None) -> None:
    """Belt-and-braces: prove the config this module builds is exactly what
    logging.config.dictConfig expects, not just what our own wrapper accepts."""

    from thesisound.logging_setup import _build_config

    logging.config.dictConfig(_build_config(Settings(log_format="text")))
