"""Single write path for product events. Never raises into the request path."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from thesisound.config import Settings
from thesisound.product_metrics.events import PAYLOAD_MODELS, ProductEvent
from thesisound.product_metrics.store import ProductEventStore

_logger = logging.getLogger(__name__)

_store: ProductEventStore | None = None
_settings: Settings | None = None
_user_resolver: Callable[[UUID | str], int | None] | None = None
_emit_failed = 0

ErrorClass = Literal["parser", "model", "coverage", "timeout", "other", "unknown"]
GateReason = Literal["coverage", "quality", "preflight", "selection", "other"]


def configure_product_metrics(
    settings: Settings,
    store: ProductEventStore,
    user_resolver: Callable[[UUID | str], int | None] | None = None,
) -> None:
    global _store, _settings, _user_resolver, _emit_failed
    _settings = settings
    _store = store
    _user_resolver = user_resolver
    _emit_failed = 0


def reset_product_metrics() -> None:
    global _store, _settings, _user_resolver, _emit_failed
    _store = None
    _settings = None
    _user_resolver = None
    _emit_failed = 0


def emit_failed_count() -> int:
    return _emit_failed


def emit(
    event: ProductEvent,
    payload: BaseModel,
    *,
    user_id: int | None = None,
    project_id: UUID | None = None,
    session_id: str | None = None,
    anon_id: str | None = None,
) -> None:
    """Validate, stamp, resolve user, and write. Swallows all failures (D10)."""

    global _emit_failed
    try:
        if _store is None or _settings is None:
            return
        expected = PAYLOAD_MODELS[event]
        if type(payload) is not expected:
            # Re-validate / coerce so callers can pass a compatible model instance.
            payload = expected.model_validate(payload.model_dump())
        else:
            # Ensure constraints hold even if constructed loosely.
            expected.model_validate(payload.model_dump())

        resolved_user = user_id
        if resolved_user is None and project_id is not None and _user_resolver is not None:
            resolved_user = _user_resolver(project_id)

        is_synthetic = _settings.environment == "test"
        properties_json = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
        _store.write(
            name=event.value,
            properties_json=properties_json,
            environment=_settings.environment,
            is_synthetic=is_synthetic,
            user_id=resolved_user,
            anon_id=anon_id,
            project_id=str(project_id) if project_id is not None else None,
            session_id=session_id,
        )
    except Exception:
        _emit_failed += 1
        _logger.exception("product_metrics.emit_failed name=%s", getattr(event, "value", event))


def classify_error(message: str | None) -> ErrorClass:
    text = (message or "").casefold()
    if not text:
        return "unknown"
    if any(token in text for token in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(token in text for token in ("coverage", "insufficient", "material gap")):
        return "coverage"
    if any(
        token in text
        for token in ("parse", "parser", "json", "schema", "validation", "docling", "mineru")
    ):
        return "parser"
    if any(
        token in text
        for token in ("model", "gemini", "openai", "llm", "token", "rate limit", "quota")
    ):
        return "model"
    return "other"


def classify_gate_reason(reason: str) -> GateReason:
    text = (reason or "").casefold()
    if any(token in text for token in ("coverage", "budget", "insufficient", "material")):
        return "coverage"
    if any(token in text for token in ("quality", "verdict", "unsupported")):
        return "quality"
    if any(token in text for token in ("preflight", "ready", "credential", "api key")):
        return "preflight"
    if any(token in text for token in ("selection", "source", "corpus")):
        return "selection"
    return "other"
