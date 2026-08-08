from __future__ import annotations

import json
from time import perf_counter
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from thesisound.modeling import (
    ModelConfigurationError,
    ModelProviderError,
    ModelRateLimitError,
    ModelSafetyError,
    ModelTimeoutError,
    ModelUsage,
    SchemaValidationError,
    StructuredModelResponse,
)
from thesisound.ports import RunMetadata

T = TypeVar("T", bound=BaseModel)


class GeminiStructuredModel:
    """Gemini generateContent adapter with Pydantic structured outputs.

    The adapter deliberately sends no temperature, top-p, or top-k parameters.
    Those parameters are deprecated for the current Gemini 3.5/3.6 model family.
    """

    provider = "gemini"

    def __init__(self, *, api_key: str | None = None, client: Any | None = None) -> None:
        if client is not None:
            self._client = client
            return
        if not api_key:
            raise ModelConfigurationError("GEMINI_API_KEY is required for live model calls.")
        try:
            from google import genai
        except ImportError as exc:
            raise ModelConfigurationError(
                "Install the Gemini extra with: uv sync --extra gemini"
            ) from exc
        self._client = genai.Client(api_key=api_key)

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_type: type[T],
        model: str,
        metadata: RunMetadata,
    ) -> StructuredModelResponse[T]:
        _ = metadata
        started = perf_counter()
        config = {
            "system_instruction": system_prompt,
            "response_mime_type": "application/json",
            "response_schema": output_type,
        }
        try:
            response = self._client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=config,
            )
        except Exception as exc:  # provider SDK exceptions vary by transport
            raise _map_provider_error(exc) from exc

        latency_ms = max(0, round((perf_counter() - started) * 1000))
        finish_reason = _finish_reason(response)
        if _is_safety_blocked(response, finish_reason):
            raise ModelSafetyError("Gemini blocked the request or response for safety reasons.")

        output = _coerce_output(response, output_type)
        return StructuredModelResponse[T](
            output=output,
            provider=self.provider,
            model=model,
            usage=_usage(response),
            latency_ms=latency_ms,
            finish_reason=finish_reason,
        )


def _coerce_output(response: Any, output_type: type[T]) -> T:
    parsed = getattr(response, "parsed", None)
    try:
        if isinstance(parsed, output_type):
            return parsed
        if isinstance(parsed, BaseModel):
            return output_type.model_validate(parsed.model_dump())
        if parsed is not None:
            return output_type.model_validate(parsed)

        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise SchemaValidationError("Gemini returned no structured response content.")
        return output_type.model_validate_json(text)
    except SchemaValidationError:
        raise
    except (ValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SchemaValidationError(
            f"Gemini output did not match {output_type.__name__}: {exc}"
        ) from exc


def _usage(response: Any) -> ModelUsage:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return ModelUsage()
    return ModelUsage(
        input_tokens=_optional_int(
            getattr(usage, "prompt_token_count", None)
            or getattr(usage, "input_token_count", None)
        ),
        output_tokens=_optional_int(
            getattr(usage, "candidates_token_count", None)
            or getattr(usage, "output_token_count", None)
        ),
        total_tokens=_optional_int(getattr(usage, "total_token_count", None)),
        thinking_tokens=_optional_int(getattr(usage, "thoughts_token_count", None)),
    )


def _finish_reason(response: Any) -> str | None:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return None
    reason = getattr(candidates[0], "finish_reason", None)
    if reason is None:
        return None
    value = getattr(reason, "value", reason)
    return str(value)


def _is_safety_blocked(response: Any, finish_reason: str | None) -> bool:
    if finish_reason and "SAFETY" in finish_reason.upper():
        return True
    feedback = getattr(response, "prompt_feedback", None)
    block_reason = getattr(feedback, "block_reason", None) if feedback is not None else None
    if block_reason is None:
        return False
    value = str(getattr(block_reason, "value", block_reason)).upper()
    return value not in {"", "NONE", "BLOCKED_REASON_UNSPECIFIED"}


def _map_provider_error(exc: Exception) -> ModelProviderError:
    name = type(exc).__name__.casefold()
    message = str(exc) or type(exc).__name__
    status = _status_code(exc)

    if status == 429 or "resourceexhausted" in name or "ratelimit" in name:
        return ModelRateLimitError(message)
    if "timeout" in name or "deadline" in name:
        return ModelTimeoutError(message)
    if "safety" in name or "blocked" in name:
        return ModelSafetyError(message)
    retryable = status is None or status >= 500
    return ModelProviderError(message, retryable=retryable)


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


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None
