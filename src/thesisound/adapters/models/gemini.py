from __future__ import annotations

import json
import math
from collections.abc import Sequence
from copy import deepcopy
from threading import Lock
from time import perf_counter
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from thesisound.config import Settings
from thesisound.gemini_key_pool import GeminiKeyPool, shared_gemini_key_pool
from thesisound.model_routing import ModelRouter, ResolvedModelRoute, load_model_router
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
from thesisound.observability import (
    CallOperation,
    ModelCallSpec,
    ObservabilityLedger,
    ObservedModelGateway,
    ProviderMetadata,
    ledger_from_settings,
)
from thesisound.ports import RunMetadata


class GeminiStructuredModel:
    """Gemini structured output through the shared observed model gateway."""

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
        observability: ObservabilityLedger | None = None,
        settings: Settings | None = None,
    ) -> None:
        runtime = settings or _settings()
        self._settings = runtime
        self._router: ModelRouter = load_model_router(runtime)
        self._okian_port: Any | None = None
        self._okian_lock = Lock()
        configured_search = runtime.gemini_google_search_enabled
        configured_urls = runtime.gemini_url_context_enabled
        self.enable_google_search = (
            configured_search if enable_google_search is None else enable_google_search
        )
        self.enable_url_context = (
            configured_urls if enable_url_context is None else enable_url_context
        )
        self.observability = observability or ledger_from_settings(runtime)
        self._gateway = ObservedModelGateway(self.observability)
        self._default_timeout_ms = runtime.model_timeout_seconds * 1000
        self._default_provider_attempts = runtime.provider_max_attempts
        self._default_retry_base = runtime.provider_retry_base_seconds
        if client is not None:
            self._client = client
            self._pool = None
            return
        keys = _configured_keys(api_key, api_keys, runtime)
        if pool is None and not keys:
            raise ModelConfigurationError(
                "GEMINI_API_KEY or GEMINI_API_KEYS is required for live model calls."
            )
        self._client = None
        self._pool = pool or shared_gemini_key_pool(keys)

    def resolve_route(
        self,
        *,
        stage: str,
        requested_model: str,
        model_tier: Literal["fast", "strong"],
    ) -> ResolvedModelRoute:
        return self._router.resolve(
            stage=stage,
            requested_model=requested_model,
            model_tier=model_tier,
        )

    def generate_structured[T: BaseModel](
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_type: type[T],
        model: str,
        metadata: RunMetadata,
    ) -> StructuredModelResponse[T]:
        if metadata.provider == "okian":
            return self._okian().generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                output_type=output_type,
                model=model,
                metadata=metadata,
            )

        started = perf_counter()
        timeout_ms = metadata.timeout_ms or self._default_timeout_ms
        response_schema = gemini_response_json_schema(output_type)
        config: dict[str, Any] = {
            "system_instruction": system_prompt,
            "response_mime_type": "application/json",
            # Prefer response_json_schema over response_schema: the latter validates
            # against a narrower OpenAPI Schema subset and rejects Pydantic/JSON Schema
            # keywords such as exclusiveMinimum.
            "response_json_schema": response_schema,
            "http_options": {
                "timeout": timeout_ms,
                "retry_options": {"attempts": 1},
            },
        }
        tools = self._tools(metadata)
        if tools:
            config["tools"] = tools

        operation = _observed_operation(metadata)
        spec = ModelCallSpec(
            call_id=metadata.call_id,
            trace_id=metadata.trace_id,
            parent_call_id=metadata.parent_call_id,
            pipeline_trace_id=metadata.pipeline_trace_id,
            parent_span_id=metadata.parent_span_id,
            project_id=metadata.project_id,
            workflow_run_id=metadata.workflow_run_id,
            stage=metadata.stage,
            operation=operation,
            provider=self.provider,
            requested_model=model,
            prompt_id=metadata.prompt_id,
            prompt_version=metadata.prompt_version,
            subject_type=metadata.subject_type,
            subject_id=metadata.subject_id,
            logical_attempt=metadata.attempt,
            timeout_ms=timeout_ms,
            grounding_mode=metadata.grounding_mode,
            metadata={
                "input_artifact_hashes": metadata.input_artifact_hashes,
                "grounding_urls": metadata.grounding_urls,
                "output_model": output_type.__name__,
                "model_profile": metadata.model_profile,
            },
        )
        request_payload = {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "model": model,
            "output_schema": response_schema,
            "grounding_mode": metadata.grounding_mode,
            "grounding_urls": metadata.grounding_urls,
            "tools": tools,
            "timeout_ms": timeout_ms,
        }

        try:
            observed = self._gateway.call(
                spec=spec,
                request_payload=request_payload,
                operation=lambda client: client.models.generate_content(
                    model=model,
                    contents=user_prompt,
                    config=config,
                ),
                pool=self._pool,
                client=self._client,
                max_provider_attempts=(
                    metadata.max_provider_attempts or self._default_provider_attempts
                ),
                base_retry_delay_seconds=(
                    metadata.provider_retry_base_seconds or self._default_retry_base
                ),
                retryable_error=_is_retryable_provider_exception,
                response_payload=_provider_snapshot,
                usage=_usage,
                provider_metadata=lambda response: _provider_metadata(response, model),
            )
        except Exception as exc:
            mapped = _map_provider_error(exc)
            self.observability.fail(spec.call_id, mapped, error_code=_error_code(exc))
            if self._should_fallback_to_okian(mapped, metadata):
                fallback_metadata = metadata.model_copy(
                    update={
                        "call_id": uuid4(),
                        "parent_call_id": spec.call_id,
                        "provider": "okian",
                        "okian_fallback_from": "gemini",
                    }
                )
                return self._okian().generate_structured(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    output_type=output_type,
                    model=model,
                    metadata=fallback_metadata,
                )
            raise mapped from exc

        response = observed.response
        # The provider has already billed for this response; keep the counts
        # reachable even on the paths that reject it.
        billed_usage = _usage(response)
        finish_reason = _finish_reason(response)
        if _is_safety_blocked(response, finish_reason):
            error = ModelSafetyError(
                "Gemini blocked the request or response for safety reasons.",
                usage=billed_usage,
            )
            self.observability.fail(spec.call_id, error)
            raise error

        try:
            output = _coerce_output(response, output_type)
            grounding = _grounding_metadata(response, metadata)
        except ModelError as exc:
            exc.usage = billed_usage
            self.observability.fail(spec.call_id, exc)
            raise

        self.observability.succeed(
            spec.call_id,
            {
                "output": output,
                "grounding": grounding,
            },
        )
        return StructuredModelResponse[T](
            output=output,
            provider=self.provider,
            model=model,
            usage=billed_usage,
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            finish_reason=finish_reason,
            grounding=grounding,
            call_id=spec.call_id,
        )

    def _okian(self) -> Any:
        if self._okian_port is not None:
            return self._okian_port
        from thesisound.adapters.models.okian import OkianStructuredModel

        with self._okian_lock:
            # Re-check under the lock: concurrent callers must share one port instead of
            # each building their own and racing to publish it.
            if self._okian_port is None:
                self._okian_port = OkianStructuredModel(
                    settings=self._settings,
                    observability=self.observability,
                )
        return self._okian_port

    def _okian_configured(self) -> bool:
        base_url = (self._settings.okian_base_url or "").strip()
        api_key = (self._settings.okian_api_key or "").strip()
        return bool(base_url and api_key)

    def _should_fallback_to_okian(
        self,
        error: ModelError,
        metadata: RunMetadata,
    ) -> bool:
        return (
            isinstance(error, ModelRateLimitError)
            and metadata.grounding_mode == "none"
            and self._okian_configured()
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


def gemini_response_json_schema(output_type: type[BaseModel]) -> dict[str, Any]:
    """Build a Gemini-safe JSON Schema from a Pydantic model.

    Uses ``response_json_schema`` (JSON Schema) instead of the OpenAPI ``Schema``
    subset. Converts exclusive numeric bounds that Gemini rejects into inclusive
    ``minimum`` / ``maximum`` values.
    """
    schema = deepcopy(output_type.model_json_schema())
    _sanitize_gemini_json_schema(schema)
    return schema


def _sanitize_gemini_json_schema(node: Any) -> None:
    if isinstance(node, list):
        for item in node:
            _sanitize_gemini_json_schema(item)
        return
    if not isinstance(node, dict):
        return

    schema_type = node.get("type")
    if "exclusiveMinimum" in node:
        exclusive = node.pop("exclusiveMinimum")
        node["minimum"] = _inclusive_lower_bound(exclusive, schema_type, node.get("minimum"))
    if "exclusiveMaximum" in node:
        exclusive = node.pop("exclusiveMaximum")
        node["maximum"] = _inclusive_upper_bound(exclusive, schema_type, node.get("maximum"))

    for value in node.values():
        _sanitize_gemini_json_schema(value)


def _inclusive_lower_bound(exclusive: Any, schema_type: Any, current: Any) -> Any:
    candidate: Any
    if schema_type == "integer" and isinstance(exclusive, int | float):
        candidate = int(exclusive) + 1
    elif isinstance(exclusive, int | float):
        candidate = math.nextafter(float(exclusive), math.inf)
    else:
        candidate = exclusive
    if current is None:
        return candidate
    try:
        return max(current, candidate)
    except TypeError:
        return candidate


def _inclusive_upper_bound(exclusive: Any, schema_type: Any, current: Any) -> Any:
    candidate: Any
    if schema_type == "integer" and isinstance(exclusive, int | float):
        candidate = int(exclusive) - 1
    elif isinstance(exclusive, int | float):
        candidate = math.nextafter(float(exclusive), -math.inf)
    else:
        candidate = exclusive
    if current is None:
        return candidate
    try:
        return min(current, candidate)
    except TypeError:
        return candidate


def _settings() -> Settings:
    try:
        return Settings()
    except ValueError:
        return Settings.model_construct()


def _configured_keys(
    api_key: str | None,
    api_keys: Sequence[str] | None,
    settings: Settings,
) -> list[str]:
    keys = list(api_keys) if api_keys is not None else list(settings.gemini_api_keys)
    if api_key:
        keys.append(api_key)
    return list(dict.fromkeys(key.strip() for key in keys if key.strip()))


def _observed_operation(metadata: RunMetadata) -> CallOperation:
    if metadata.operation in {
        "structured_text",
        "google_search",
        "url_context",
        "tts",
        "asr",
    }:
        return cast(CallOperation, metadata.operation)
    if metadata.grounding_mode == "google_search":
        return "google_search"
    if metadata.grounding_mode == "url_context":
        return "url_context"
    return "structured_text"


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
        url = _optional_string(_value(item, "retrieved_url") or _value(item, "url"))
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
            getattr(usage, "prompt_token_count", None) or getattr(usage, "input_token_count", None)
        ),
        output_tokens=_optional_int(
            getattr(usage, "candidates_token_count", None)
            or getattr(usage, "output_token_count", None)
        ),
        total_tokens=_optional_int(getattr(usage, "total_token_count", None)),
        thinking_tokens=_optional_int(getattr(usage, "thoughts_token_count", None)),
        cached_tokens=_optional_int(
            getattr(usage, "cached_content_token_count", None)
            or getattr(usage, "cache_tokens_details", None)
        ),
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


def _is_retryable_provider_exception(exc: Exception) -> bool:
    mapped = _map_provider_error(exc)
    return mapped.retryable and not isinstance(mapped, ModelRateLimitError)


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


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _provider_metadata(response: Any, model: str) -> ProviderMetadata:
    http_response = getattr(response, "sdk_http_response", None)
    headers = getattr(http_response, "headers", None) or {}
    request_id = None
    for name in ("x-request-id", "x-goog-request-id", "request-id"):
        if isinstance(headers, dict) and headers.get(name):
            request_id = str(headers[name])
            break
    status = getattr(http_response, "status_code", None)
    return ProviderMetadata(
        resolved_model=_optional_string(getattr(response, "model_version", None)) or model,
        provider_request_id=request_id,
        http_status=status if isinstance(status, int) else None,
        finish_reason=_finish_reason(response),
    )


def _provider_snapshot(response: Any) -> dict[str, Any]:
    candidates = getattr(response, "candidates", None) or []
    return {
        "text": getattr(response, "text", None),
        "parsed": getattr(response, "parsed", None),
        "usage_metadata": getattr(response, "usage_metadata", None),
        "prompt_feedback": getattr(response, "prompt_feedback", None),
        "model_version": getattr(response, "model_version", None),
        "candidates": [
            {
                "finish_reason": getattr(candidate, "finish_reason", None),
                "grounding_metadata": getattr(candidate, "grounding_metadata", None),
                "url_context_metadata": getattr(candidate, "url_context_metadata", None),
                "safety_ratings": getattr(candidate, "safety_ratings", None),
                "content": getattr(candidate, "content", None),
            }
            for candidate in candidates
        ],
    }
