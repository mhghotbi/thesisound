"""Structured logging correlated with the ambient tracer (thesisound.tracing).

Activates ``Settings.log_level``, which until this module existed was dead
config -- nothing in the codebase called ``logging.basicConfig`` or any
other setup, so no log line was ever produced anywhere. ``log_format="json"``
gives one JSON object per line for machine ingestion; the default
``"text"`` is a compact, human-readable line for local development.

Every record -- in either format -- is redacted with the exact same rules
``observability.py`` already applies to spans and payloads, and is tagged
with ``trace_id``/``span_id``/``project_id`` from whatever span is open when
the log call happens, so a log line and the span it occurred inside
correlate without the call site doing anything.
"""

from __future__ import annotations

import json
import logging
import logging.config
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from thesisound import tracing
from thesisound.observability import redact_text, redact_value

if TYPE_CHECKING:
    from thesisound.config import Settings

# The attribute names a fresh LogRecord already has. Anything else on a
# record's __dict__ was added by a caller (logger.info(..., extra={...})) or
# by our own TraceContextFilter, and is worth redacting / including in JSON
# output. Computed rather than hardcoded so it stays correct across Python
# versions (e.g. 3.12 added `taskName`).
_STANDARD_LOG_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


class TraceContextFilter(logging.Filter):
    """Attaches trace_id/span_id/project_id from the ambient tracer to every
    record. No call site has to do anything for this to work."""

    def filter(self, record: logging.LogRecord) -> bool:
        context = tracing.current_context()
        record.trace_id = str(context.trace_id) if context else None
        record.span_id = str(context.span_id) if context else None
        record.project_id = str(context.project_id) if context and context.project_id else None
        return True


class RedactingFilter(logging.Filter):
    """Scrubs secrets and PII from the rendered message and from any extra
    fields a caller attached via ``logger.info(..., extra={...})``.

    Renders the message (merging in %-style args) before redacting so a
    secret passed as an argument -- ``logger.info("key=%s", api_key)`` -- is
    caught too, not just literal text already in the format string.
    """

    def __init__(self, *, store_payloads: bool = False) -> None:
        super().__init__()
        self.store_payloads = store_payloads

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = ()
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_LOG_RECORD_ATTRS
        }
        redacted_extras = redact_value(extras, store_payloads=self.store_payloads)
        for key, value in redacted_extras.items():
            record.__dict__[key] = value
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", None),
            "span_id": getattr(record, "span_id", None),
            "project_id": getattr(record, "project_id", None),
            "process": record.processName,
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_ATTRS or key in payload:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """A compact, human-readable line for local development.

    Includes a short trace_id prefix when one is available, so a developer
    watching the console can still correlate a line to `thesisound trace
    <id>` without needing full JSON output.
    """

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).strftime("%H:%M:%S")
        trace_id = getattr(record, "trace_id", None)
        trace_marker = f"[{trace_id[:8]}] " if trace_id else ""
        line = (
            f"{timestamp} {record.levelname:<8} {record.name} {trace_marker}{record.getMessage()}"
        )
        if record.exc_info:
            line = f"{line}\n{redact_text(self.formatException(record.exc_info))}"
        return line


def uvicorn_log_config(settings: Settings) -> dict[str, Any]:
    """Uvicorn's own logging config for ``uvicorn.error``/``uvicorn.access``,
    sharing this module's formatters and filters instead of uvicorn's
    defaults. Pass to ``uvicorn.run(..., log_config=...)``.

    Critical: uvicorn's own default log config sets
    ``disable_existing_loggers: True``, which would silently discard every
    logger this module configures. This config sets it ``False``.
    """

    return _build_config(settings, logger_names=("uvicorn", "uvicorn.error", "uvicorn.access"))


def configure_logging(settings: Settings) -> None:
    """The composition-root call that activates structured logging.

    Safe to call more than once in the same process -- ``dictConfig``
    replaces the configured handlers/filters each time rather than
    accumulating duplicates.
    """

    logging.config.dictConfig(_build_config(settings))


def _build_config(settings: Settings, *, logger_names: tuple[str, ...] = ()) -> dict[str, Any]:
    formatter_name = "json" if settings.log_format == "json" else "console"
    handlers: dict[str, Any] = {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": formatter_name,
            "filters": ["trace_context", "redact"],
            "stream": "ext://sys.stderr",
        }
    }
    if settings.log_file is not None:
        settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "json",
            "filters": ["trace_context", "redact"],
            "filename": str(settings.log_file),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        }
    handler_names = list(handlers)
    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "trace_context": {"()": TraceContextFilter},
            "redact": {
                "()": RedactingFilter,
                "store_payloads": settings.observability_store_payloads,
            },
        },
        "formatters": {
            "console": {"()": ConsoleFormatter},
            "json": {"()": JsonFormatter},
        },
        "handlers": handlers,
        "root": {
            "level": settings.log_level,
            "handlers": handler_names,
        },
    }
    if logger_names:
        config["loggers"] = {
            name: {
                "level": settings.log_level,
                "handlers": handler_names,
                "propagate": False,
            }
            for name in logger_names
        }
    return config
