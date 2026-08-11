from __future__ import annotations

import hashlib
import json
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from pydantic import BaseModel, ValidationError

from thesisound.config import Settings
from thesisound.modeling import (
    GroundingMetadata,
    ModelConfigurationError,
    ModelError,
    ModelProviderError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelUsage,
    SchemaValidationError,
    StructuredModelResponse,
)
from thesisound.observability import (
    ModelCallSpec,
    ObservabilityLedger,
    ObservedModelGateway,
    ProviderMetadata,
    ledger_from_settings,
)
from thesisound.ports import RunMetadata


@dataclass(frozen=True, slots=True)
class OkianHttpResponse:
    payload: dict[str, Any]
    status_code: int
    headers: dict[str, str]


class OkianHttpError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class OkianHttpClient:
    """Minimal OpenAI-compatible HTTP client for the Okian provider."""

    def __init__(self, *, base_url: str, api_key: str) -> None:
        normalized = base_url.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ModelConfigurationError("OKIAN_BASE_URL must start with http:// or https://.")
        if not api_key.strip():
            raise ModelConfigurationError("OKIAN_API_KEY is required when Okian is routed.")
        self.endpoint = (
            normalized
            if normalized.endswith("/chat/completions")
            else f"{normalized}/chat/completions"
        )
        self._api_key = api_key.strip()

    def create_chat_completion(
        self,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> OkianHttpResponse:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        # Empty ProxyHandler disables env HTTP(S)_PROXY so Okian stays direct.
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                raw = response.read()
                headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        except HTTPError as exc:
            raw = exc.read()
            message, error_code = _error_from_body(raw, fallback=str(exc.reason))
            raise OkianHttpError(
                message,
                status_code=exc.code,
                error_code=error_code,
            ) from exc
        except TimeoutError as exc:
            raise OkianHttpError("Okian request timed out.", error_code="timeout") from exc
        except URLError as exc:
            reason = exc.reason
            if isinstance(reason, TimeoutError | socket.timeout):
                raise OkianHttpError(
                    "Okian request timed out.",
                    error_code="timeout",
                ) from exc
            raise OkianHttpError(
                f"Okian request failed: {reason}",
                error_code="connection_error",
            ) from exc

        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OkianHttpError(
                "Okian returned a non-JSON response.",
                status_code=status,
                error_code="invalid_json",
            ) from exc
        if not isinstance(decoded, dict):
            raise OkianHttpError(
                "Okian returned an invalid response envelope.",
                status_code=status,
                error_code="invalid_envelope",
            )
        return OkianHttpResponse(payload=decoded, status_code=status, headers=headers)


class OkianCredentialPool:
    """Single Okian credential with attempt events compatible with the shared gateway."""

    def __init__(self, client: OkianHttpClient, api_key: str) -> None:
        self._client = client
        self._fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]

    def call[T](
        self,
        operation: Any,
        *,
        on_attempt: Any | None = None,
    ) -> T:
        started = datetime.now(UTC)
        try:
            result = operation(self._client)
        except Exception as exc:
            ended = datetime.now(UTC)
            if on_attempt is not None:
                on_attempt(
                    {
                        "key_slot": 1,
                        "key_fingerprint": self._fingerprint,
                        "credential_type": "api_key",
                        "status": "failed",
                        "started_at": started,
                        "ended_at": ended,
                        "latency_ms": max(
                            0,
                            round((ended - started).total_seconds() * 1000),
                        ),
                        "http_status": _status_code(exc),
                        "error_type": type(exc).__name__,
                        "error_code": _error_code(exc),
                        "error_message": str(exc),
                    }
                )
            raise
        ended = datetime.now(UTC)
        if on_attempt is not None:
            on_attempt(
                {
                    "key_slot": 1,
                    "key_fingerprint": self._fingerprint,
                    "credential_type": "api_key",
                    "status": "succeeded",
                    "started_at": started,
                    "ended_at": ended,
                    "latency_ms": max(
                        0,
                        round((ended - started).total_seconds() * 1000),
                    ),
                }
            )
        return result


class OkianStructuredModel:
    """OpenAI-compatible structured output through the unified observability gateway."""

    provider = "okian"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        client: Any | None = None,
        observability: ObservabilityLedger | None = None,
        settings: Settings | None = None,
    ) -> None:
        runtime = settings or _settings()
        self.observability = observability or ledger_from_settings(runtime)
        self._gateway = ObservedModelGateway(self.observability)
        self._timeout_ms = runtime.okian_timeout_seconds * 1000
        self._max_provider_attempts = runtime.provider_max_attempts
        self._retry_base_seconds = runtime.provider_retry_base_seconds
        if client is not None:
            self._client = client
            self._pool = None
            return

        resolved_base_url = (base_url or runtime.okian_base_url or "").strip()
        resolved_api_key = (api_key or runtime.okian_api_key or "").strip()
        if not resolved_base_url or not resolved_api_key:
            raise ModelConfigurationError(
                "Okian is routed but OKIAN_BASE_URL and OKIAN_API_KEY are not both set."
            )
        client_instance = OkianHttpClient(
            base_url=resolved_base_url,
            api_key=resolved_api_key,
        )
        self._client = None
        self._pool = OkianCredentialPool(client_instance, resolved_api_key)

    def generate_structured[T: BaseModel](
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_type: type[T],
        model: str,
        metadata: RunMetadata,
    ) -> StructuredModelResponse[T]:
        if metadata.grounding_mode != "none":
            raise ModelConfigurationError(
                "Okian does not provide Gemini Google Search or URL Context. "
                "Keep grounded stages routed to Gemini."
            )

        started = perf_counter()
        timeout_ms = metadata.timeout_ms or self._timeout_ms
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": output_type.__name__,
                    "strict": True,
                    "schema": output_type.model_json_schema(),
                },
            },
        }
        spec = ModelCallSpec(
            call_id=metadata.call_id,
            trace_id=metadata.trace_id,
            parent_call_id=metadata.parent_call_id,
            pipeline_trace_id=metadata.pipeline_trace_id,
            parent_span_id=metadata.parent_span_id,
            project_id=metadata.project_id,
            workflow_run_id=metadata.workflow_run_id,
            stage=metadata.stage,
            operation="structured_text",
            provider=self.provider,
            requested_model=model,
            prompt_id=metadata.prompt_id,
            prompt_version=metadata.prompt_version,
            subject_type=metadata.subject_type,
            subject_id=metadata.subject_id,
            logical_attempt=metadata.attempt,
            timeout_ms=timeout_ms,
            grounding_mode="none",
            metadata={
                "input_artifact_hashes": metadata.input_artifact_hashes,
                "output_model": output_type.__name__,
                "model_profile": metadata.model_profile,
                **(
                    {"okian_fallback_from": metadata.okian_fallback_from}
                    if metadata.okian_fallback_from
                    else {}
                ),
            },
        )
        request_payload = {
            **payload,
            "timeout_ms": timeout_ms,
            "base_url": _redacted_base_url(self._client),
        }

        try:
            observed = self._gateway.call(
                spec=spec,
                request_payload=request_payload,
                operation=lambda client: client.create_chat_completion(
                    payload,
                    timeout_seconds=timeout_ms / 1000,
                ),
                client=self._client,
                pool=self._pool,
                max_provider_attempts=(
                    metadata.max_provider_attempts or self._max_provider_attempts
                ),
                base_retry_delay_seconds=(
                    metadata.provider_retry_base_seconds or self._retry_base_seconds
                ),
                retryable_error=_is_retryable_provider_exception,
                response_payload=lambda response: response.payload,
                usage=_usage,
                provider_metadata=lambda response: _provider_metadata(response, model),
            )
        except Exception as exc:
            mapped = _map_provider_error(exc)
            self.observability.fail(spec.call_id, mapped, error_code=_error_code(exc))
            raise mapped from exc

        response = observed.response
        billed_usage = _usage(response)
        try:
            output = _coerce_output(response.payload, output_type)
        except ModelError as exc:
            exc.usage = billed_usage
            self.observability.fail(spec.call_id, exc)
            raise

        self.observability.succeed(spec.call_id, {"output": output})
        return StructuredModelResponse[T](
            output=output,
            provider=self.provider,
            model=_resolved_model(response.payload) or model,
            usage=billed_usage,
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            finish_reason=_finish_reason(response.payload),
            grounding=GroundingMetadata(),
            call_id=spec.call_id,
        )


def _settings() -> Settings:
    try:
        return Settings()
    except ValueError:
        return Settings.model_construct()


def _coerce_output[T: BaseModel](payload: dict[str, Any], output_type: type[T]) -> T:
    try:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise SchemaValidationError("Okian returned no completion choices.")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise SchemaValidationError("Okian returned no assistant message.")
        content = message.get("content")
        if isinstance(content, dict):
            return output_type.model_validate(content)
        if not isinstance(content, str) or not content.strip():
            raise SchemaValidationError("Okian returned no structured response content.")
        return output_type.model_validate_json(content)
    except SchemaValidationError:
        raise
    except (ValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SchemaValidationError(
            f"Okian output did not match {output_type.__name__}: {exc}"
        ) from exc


def _usage(response: OkianHttpResponse) -> ModelUsage:
    usage = response.payload.get("usage")
    if not isinstance(usage, dict):
        return ModelUsage()
    prompt_details = usage.get("prompt_tokens_details")
    completion_details = usage.get("completion_tokens_details")
    return ModelUsage(
        input_tokens=_optional_int(usage.get("prompt_tokens")),
        output_tokens=_optional_int(usage.get("completion_tokens")),
        total_tokens=_optional_int(usage.get("total_tokens")),
        thinking_tokens=_optional_int(
            completion_details.get("reasoning_tokens")
            if isinstance(completion_details, dict)
            else None
        ),
        cached_tokens=_optional_int(
            prompt_details.get("cached_tokens") if isinstance(prompt_details, dict) else None
        ),
    )


def _provider_metadata(
    response: OkianHttpResponse,
    requested_model: str,
) -> ProviderMetadata:
    request_id = (
        response.headers.get("x-request-id")
        or response.headers.get("request-id")
        or _optional_text(response.payload.get("id"))
    )
    return ProviderMetadata(
        resolved_model=_resolved_model(response.payload) or requested_model,
        provider_request_id=request_id,
        http_status=response.status_code,
        finish_reason=_finish_reason(response.payload),
    )


def _resolved_model(payload: dict[str, Any]) -> str | None:
    return _optional_text(payload.get("model"))


def _finish_reason(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    return _optional_text(choices[0].get("finish_reason"))


def _map_provider_error(exc: Exception) -> ModelError:
    if isinstance(exc, ModelError):
        return exc
    status = _status_code(exc)
    message = str(exc) or type(exc).__name__
    code = (_error_code(exc) or "").casefold()
    name = type(exc).__name__.casefold()
    if status == 429 or "rate" in code or "quota" in code:
        return ModelRateLimitError(message)
    if status == 408 or "timeout" in code or "timeout" in name:
        return ModelTimeoutError(message)
    retryable = status is None or status >= 500
    return ModelProviderError(message, retryable=retryable)


def _is_retryable_provider_exception(exc: Exception) -> bool:
    return _map_provider_error(exc).retryable


def _status_code(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    return value if isinstance(value, int) else None


def _error_code(exc: Exception) -> str | None:
    value = getattr(exc, "error_code", None)
    return _optional_text(value)


def _error_from_body(raw: bytes, *, fallback: str) -> tuple[str, str | None]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return fallback or "Okian request failed.", None
    if not isinstance(payload, dict):
        return fallback or "Okian request failed.", None
    error = payload.get("error")
    if isinstance(error, dict):
        message = _optional_text(error.get("message")) or fallback
        code = _optional_text(error.get("code") or error.get("type"))
        return message or "Okian request failed.", code
    return fallback or "Okian request failed.", None


def _redacted_base_url(client: Any) -> str | None:
    endpoint = getattr(client, "endpoint", None)
    return _optional_text(endpoint)


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
