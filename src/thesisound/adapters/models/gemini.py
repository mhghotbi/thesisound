from __future__ import annotations

import json
from collections.abc import Sequence
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ValidationError

from thesisound.gemini_key_pool import GeminiKeyPool, shared_gemini_key_pool
from thesisound.modeling import (
    GroundingMetadata,
    GroundingSource,
    ModelConfigurationError,
    ModelError,
    ModelProviderError,
    ModelRateLimitError,
    ModelSafetyError,
    ModelTimeoutError,
    ModelUsage,
    SchemaValidationError,
    StructuredModelResponse,
    UrlRetrieval,
)
from thesisound.ports import RunMetadata


class GeminiStructuredModel:
    """Gemini generateContent adapter with structured output and built-in tools."""

    provider = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_keys: Sequence[str] | None = None,
        pool: GeminiKeyPool | None = None,
        client: Any | None = None,
        enable_google_search: bool | None = None,
        enable_url_context: bool | None = None,
    ) -> None:
        configured_search, configured_urls = _grounding_settings()
        self.enable_google_search = (
            configured_search if enable_google_search is None else enable_google_search
        )
        self.enable_url_context = (
            configured_urls if enable_url_context is None else enable_url_context
        )
        if client is not None:
            self._client = client
            self._pool = None
            return
        keys = _configured_keys(api_key, api_keys)
        if pool is None and not keys:
            raise ModelConfigurationError(
                "GEMINI_API_KEY or GEMINI_API_KEYS is required for live model calls."
            )
        self._client = None
        self._pool = pool or shared_gemini_key_pool(keys)

    def generate_structured[T: BaseModel](
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_type: type[T],
        model: str,
        metadata: RunMetadata,
    ) -> StructuredModelResponse[T]:
        started = perf_counter()
        config: dict[str, Any] = {
            "system_instruction": system_prompt,
            "response_mime_type": "application/json",
            "response_schema": output_type,
        }
        tools = self._tools(metadata)
        if tools:
            config["tools"] = tools

        try:
            if self._pool is not None:
                response = self._pool.call(
                    lambda client: client.models.generate_content(
                        model=model,
                        contents=user_prompt,
                        config=config,
                    )
                )
            else:
                response = self._client.models.generate_content(
                    model=model,
                    contents=user_prompt,
                    config=config,
                )
        except Exception as exc:
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
            grounding=_grounding_metadata(response, metadata),
        )

    def _tools(self, metadata: RunMetadata) -> list[dict[str, dict[str, object]]]:
        wants_search = metadata.grounding_mode in {
            "google_search",
            "google_search_and_url_context",
        }
        wants_urls = metadata.grounding_mode in {
            "url_context",
            "google_search_and_url_context",
        }
        if wants_search and not self.enable_google_search:
            raise ModelConfigurationError(
                "Google Search grounding is disabled by THESISOUND_GEMINI_GOOGLE_SEARCH_ENABLED."
            )
        if wants_urls and metadata.grounding_urls and not self.enable_url_context:
            raise ModelConfigurationError(
                "URL Context is disabled by THESISOUND_GEMINI_URL_CONTEXT_ENABLED."
            )

        tools: list[dict[str, dict[str, object]]] = []
        if wants_search:
            tools.append({"google_search": {}})
        if wants_urls and metadata.grounding_urls:
            tools.append({"url_context": {}})
        return tools


def _grounding_settings() -> tuple[bool, bool]:
    try:
        from thesisound.config import Settings

        settings = Settings()
        return (
            settings.gemini_google_search_enabled,
            settings.gemini_url_context_enabled,
        )
    except ValueError:
        return True, True


def _configured_keys(
    api_key: str | None,
    api_keys: Sequence[str] | None,
) -> list[str]:
    if api_keys is not None:
        keys = list(api_keys)
    else:
        try:
            from thesisound.config import Settings

            keys = list(Settings().gemini_api_keys)
        except ValueError:
            keys = []
    if api_key:
        keys.append(api_key)
    return list(dict.fromkeys(key.strip() for key in keys if key.strip()))


def _coerce_output[T: BaseModel](response: Any, output_type: type[T]) -> T:
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


def _grounding_metadata(response: Any, metadata: RunMetadata) -> GroundingMetadata:
    candidates = _value(response, "candidates", []) or []
    if not candidates:
        return GroundingMetadata(mode=metadata.grounding_mode)

    candidate = candidates[0]
    grounding = _value(candidate, "grounding_metadata")
    queries = _string_list(_value(grounding, "web_search_queries", []))

    sources: list[GroundingSource] = []
    for chunk in _value(grounding, "grounding_chunks", []) or []:
        web = _value(chunk, "web")
        uri = _optional_string(_value(web, "uri"))
        if not uri:
            continue
        sources.append(
            GroundingSource(
                uri=uri,
                title=_optional_string(_value(web, "title")),
                domain=_optional_string(_value(web, "domain")),
            )
        )

    url_context = _value(candidate, "url_context_metadata")
    url_retrievals: list[UrlRetrieval] = []
    for item in _value(url_context, "url_metadata", []) or []:
        url = _optional_string(
            _value(item, "retrieved_url") or _value(item, "url")
        )
        if not url:
            continue
        status = _value(item, "url_retrieval_status")
        status_value = _value(status, "value", status)
        url_retrievals.append(
            UrlRetrieval(
                url=url,
                status=_optional_string(status_value),
            )
        )

    return GroundingMetadata(
        mode=metadata.grounding_mode,
        web_search_queries=list(dict.fromkeys(queries)),
        sources=_deduplicate_sources(sources),
        url_retrievals=url_retrievals,
    )


def _deduplicate_sources(sources: list[GroundingSource]) -> list[GroundingSource]:
    unique: dict[str, GroundingSource] = {}
    for source in sources:
        unique.setdefault(source.uri, source)
    return list(unique.values())


def _value(value: Any, name: str, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def _map_provider_error(exc: Exception) -> ModelError:
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
