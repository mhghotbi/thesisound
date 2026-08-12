"""Classify run-level failures and decide whether automatic recovery may retry.

Per-call provider retries live in ``model_retry``; this module sits one level up
around a whole pipeline attempt (spec 10). Fail closed: unknown errors are
structural and are not retried.
"""

from __future__ import annotations

import re
from typing import Literal

from thesisound.modeling import (
    DeterministicValidationError,
    ModelConfigurationError,
    ModelError,
    ModelProviderError,
    ModelRateLimitError,
    ModelSafetyError,
    ModelTimeoutError,
    SchemaValidationError,
    StructuredOutputError,
)
from thesisound.services.model_retry import classify_error

RunFailureClass = Literal[
    "transport",
    "model_contract",
    "model_quality",
    "structural",
]

_TRANSPORT_MESSAGE = re.compile(
    r"(?i)("
    r"timed?\s*out|timeout|not acceptable|connection\s*(reset|aborted|refused)|"
    r"disconnected|temporarily unavailable|bad gateway|service unavailable|"
    r"gateway timeout|http\s*5\d\d|\b406\b"
    r")"
)

_STRUCTURAL_MESSAGE = re.compile(
    r"(?i)("
    r"not retryable|cannot build script|no longer matches the approved|"
    r"changed after approval|approve the current plan|"
    r"insufficient coverage|coverage insufficient|missing plan|"
    r"configuration error|belong to a different|"
    r"only a retryable|already active|from the current state"
    r")"
)


def classify_run_failure(exc: BaseException) -> RunFailureClass:
    if isinstance(exc, DeterministicValidationError):
        # Still-fatal deterministic checks after spec 09 degrade paths.
        return "model_quality" if exc.retryable else "structural"
    if isinstance(exc, (SchemaValidationError, StructuredOutputError)):
        return "model_contract" if exc.retryable else "structural"
    if isinstance(exc, (ModelTimeoutError, ModelRateLimitError)):
        return "transport"
    if isinstance(exc, ModelProviderError):
        return "transport" if exc.retryable else "structural"
    if isinstance(exc, (ModelSafetyError, ModelConfigurationError)):
        return "structural"
    if isinstance(exc, ModelError):
        error_class = classify_error(exc)
        if error_class in {"provider", "rate_limit", "timeout"}:
            return "transport"
        if error_class in {"schema"}:
            return "model_contract"
        if error_class == "deterministic":
            return "model_quality"
        return "structural"

    message = str(exc) or type(exc).__name__
    if _STRUCTURAL_MESSAGE.search(message):
        return "structural"
    if _TRANSPORT_MESSAGE.search(message):
        return "transport"
    # ValueError and other non-model exceptions: fail closed.
    return "structural"


def should_auto_retry(
    classification: RunFailureClass,
    *,
    quality_retries_used: int,
) -> bool:
    if classification == "structural":
        return False
    if classification == "model_quality":
        return quality_retries_used == 0
    return classification in {"transport", "model_contract"}


def recovery_backoff_seconds(attempt_index: int, base_seconds: float) -> float:
    """Exponential backoff for automatic recovery after failed attempt ``attempt_index``.

    ``attempt_index`` is 1-based (first failure → index 1).
    """

    if attempt_index < 1:
        raise ValueError("attempt_index must be >= 1")
    if base_seconds <= 0:
        return 0.0
    return float(base_seconds) * (2 ** (attempt_index - 1))
