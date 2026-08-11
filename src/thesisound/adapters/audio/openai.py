from __future__ import annotations

import hashlib
import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import UUID, uuid4

from thesisound.audio_ports import TtsRequest, TtsResponse
from thesisound.config import Settings
from thesisound.modeling import (
    ModelConfigurationError,
    ModelProviderError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelUsage,
)
from thesisound.observability import (
    ModelCallSpec,
    ObservabilityLedger,
    ObservedModelGateway,
    ProviderMetadata,
    ledger_from_settings,
)


@dataclass(frozen=True, slots=True)
class OpenAiSpeechResponse:
    pcm_bytes: bytes
    status_code: int
    headers: dict[str, str]
    request_id: str | None = None


class OpenAiHttpError(RuntimeError):
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


class OpenAiHttpClient:
    """Minimal OpenAI Audio Speech client (no SDK)."""

    def __init__(self, *, base_url: str, api_key: str) -> None:
        normalized = base_url.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ModelConfigurationError("OPENAI_BASE_URL must start with http:// or https://.")
        if not api_key.strip():
            raise ModelConfigurationError("OPENAI_API_KEY is required for OpenAI TTS.")
        self.endpoint = (
            normalized
            if normalized.endswith("/audio/speech")
            else f"{normalized}/audio/speech"
        )
        self._api_key = api_key.strip()
        self.base_url = normalized

    def create_speech(
        self,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> OpenAiSpeechResponse:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "audio/pcm, application/json, */*",
            },
        )
        # Empty ProxyHandler disables env HTTP(S)_PROXY so OpenAI stays direct.
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                raw = response.read()
                headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        except HTTPError as exc:
            raw = exc.read()
            message, error_code = _error_from_body(raw, fallback=str(exc.reason))
            raise OpenAiHttpError(
                message,
                status_code=exc.code,
                error_code=error_code,
            ) from exc
        except TimeoutError as exc:
            raise OpenAiHttpError("OpenAI TTS request timed out.", error_code="timeout") from exc
        except URLError as exc:
            reason = exc.reason
            if isinstance(reason, TimeoutError | socket.timeout):
                raise OpenAiHttpError(
                    "OpenAI TTS request timed out.",
                    error_code="timeout",
                ) from exc
            raise OpenAiHttpError(
                f"OpenAI TTS request failed: {reason}",
                error_code="connection_error",
            ) from exc

        content_type = headers.get("content-type", "")
        if "application/json" in content_type:
            message, error_code = _error_from_body(raw, fallback="OpenAI TTS returned JSON error.")
            raise OpenAiHttpError(message, status_code=status, error_code=error_code)
        if not raw:
            raise OpenAiHttpError(
                "OpenAI TTS returned empty audio.",
                status_code=status,
                error_code="empty_audio",
            )
        return OpenAiSpeechResponse(
            pcm_bytes=raw,
            status_code=status,
            headers=headers,
            request_id=headers.get("x-request-id"),
        )


class OpenAiTtsAdapter:
    """OpenAI `/audio/speech` TTS through the unified observability gateway."""

    provider = "openai"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        client: OpenAiHttpClient | None = None,
        project_id: UUID | None = None,
        workflow_run_id: UUID | None = None,
        observability: ObservabilityLedger | None = None,
        settings: Settings | None = None,
    ) -> None:
        runtime = settings or _settings()
        self._settings = runtime
        self.project_id = project_id
        self.workflow_run_id = workflow_run_id
        self.observability = observability or ledger_from_settings(runtime)
        self._gateway = ObservedModelGateway(self.observability)
        self._timeout_ms = runtime.tts_timeout_seconds * 1000
        self._max_provider_attempts = runtime.provider_max_attempts
        self._retry_base_seconds = runtime.provider_retry_base_seconds
        if client is not None:
            self._client = client
            return
        resolved_base = (base_url or runtime.openai_base_url or "").strip()
        resolved_key = (api_key or runtime.openai_api_key or "").strip()
        if not resolved_base or not resolved_key:
            raise ModelConfigurationError(
                "OPENAI_API_KEY is required for OpenAI TTS (and OPENAI_BASE_URL must be set)."
            )
        self._client = OpenAiHttpClient(base_url=resolved_base, api_key=resolved_key)

    def synthesize(
        self,
        request: TtsRequest,
        *,
        call_id: UUID | None = None,
        parent_call_id: UUID | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> TtsResponse:
        model = request.model or self._settings.model_tts_fallback
        voice = self._voice_for_speaker(request.speaker)
        payload = {
            "model": model,
            "input": request.text,
            "voice": voice,
            "response_format": "pcm",
            "instructions": request.style_prompt,
        }
        metadata = {
            "speaker": request.speaker,
            "voice_name": voice,
            "gemini_voice_name": request.voice_name,
            **(extra_metadata or {}),
        }
        spec = ModelCallSpec(
            call_id=call_id or uuid4(),
            parent_call_id=parent_call_id,
            project_id=self.project_id,
            workflow_run_id=self.workflow_run_id,
            stage="audio_tts",
            operation="tts",
            provider=self.provider,
            requested_model=model,
            subject_type="audio_chunk",
            subject_id=request.chunk_id,
            timeout_ms=self._timeout_ms,
            metadata=metadata,
        )
        try:
            observed = self._gateway.call(
                spec=spec,
                request_payload={
                    "chunk_id": request.chunk_id,
                    "text": request.text,
                    "speaker": request.speaker,
                    "voice": voice,
                    "style_prompt": request.style_prompt,
                    "model": model,
                    "response_format": "pcm",
                    "timeout_ms": self._timeout_ms,
                    "base_url": _redacted_base_url(self._client),
                },
                operation=lambda client: client.create_speech(
                    payload,
                    timeout_seconds=self._timeout_ms / 1000,
                ),
                client=self._client,
                max_provider_attempts=self._max_provider_attempts,
                base_retry_delay_seconds=self._retry_base_seconds,
                retryable_error=_is_retryable_provider_exception,
                response_payload=_speech_snapshot,
                usage=lambda _response: ModelUsage(),
                provider_metadata=lambda response: _provider_metadata(response, model),
            )
            data = observed.response.pcm_bytes
        except Exception as exc:
            mapped = _map_provider_error(exc)
            self.observability.fail(spec.call_id, mapped, error_code=_error_code(exc))
            raise mapped from exc

        self.observability.succeed(
            spec.call_id,
            {
                "chunk_id": request.chunk_id,
                "provider": self.provider,
                "model": model,
                "pcm_size_bytes": len(data),
                "pcm_sha256": hashlib.sha256(data).hexdigest(),
                "sample_rate_hz": 24_000,
                "channels": 1,
                "sample_width_bytes": 2,
            },
        )
        return TtsResponse(
            pcm_bytes=data,
            provider=self.provider,
            model=model,
        )

    def _voice_for_speaker(self, speaker: str) -> str:
        if speaker.strip().upper() == "B":
            return self._settings.openai_tts_voice_b
        return self._settings.openai_tts_voice_a


def _settings() -> Settings:
    try:
        return Settings()
    except ValueError:
        return Settings.model_construct()


def _speech_snapshot(response: OpenAiSpeechResponse) -> dict[str, Any]:
    return {
        "status_code": response.status_code,
        "request_id": response.request_id,
        "pcm_size_bytes": len(response.pcm_bytes),
        "pcm_sha256": hashlib.sha256(response.pcm_bytes).hexdigest(),
    }


def _provider_metadata(response: OpenAiSpeechResponse, model: str) -> ProviderMetadata:
    return ProviderMetadata(
        resolved_model=model,
        provider_request_id=response.request_id,
        http_status=response.status_code,
        finish_reason="stop",
    )


def _map_provider_error(exc: Exception) -> Exception:
    if isinstance(exc, (ModelProviderError, ModelRateLimitError, ModelTimeoutError)):
        return exc
    status = getattr(exc, "status_code", None)
    message = str(exc) or type(exc).__name__
    error_code = getattr(exc, "error_code", None)
    if status == 429 or (isinstance(error_code, str) and "rate" in error_code.casefold()):
        return ModelRateLimitError(message)
    if error_code == "timeout" or "timeout" in type(exc).__name__.casefold():
        return ModelTimeoutError(message)
    retryable = status is None or (isinstance(status, int) and status >= 500)
    return ModelProviderError(message, retryable=retryable)


def _is_retryable_provider_exception(exc: Exception) -> bool:
    mapped = _map_provider_error(exc)
    return bool(getattr(mapped, "retryable", False)) and not isinstance(
        mapped, ModelRateLimitError
    )


def _error_code(exc: Exception) -> str | None:
    value = getattr(exc, "error_code", None)
    if value is not None:
        return str(value)
    status = getattr(exc, "status_code", None)
    return str(status) if isinstance(status, int) else None


def _error_from_body(raw: bytes, *, fallback: str) -> tuple[str, str | None]:
    if not raw:
        return fallback or "OpenAI TTS request failed.", None
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return fallback or "OpenAI TTS request failed.", None
    if not isinstance(decoded, dict):
        return fallback or "OpenAI TTS request failed.", None
    error = decoded.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or fallback)
        code = error.get("code") or error.get("type")
        return message, str(code) if code is not None else None
    return fallback or "OpenAI TTS request failed.", None


def _redacted_base_url(client: OpenAiHttpClient) -> str:
    return getattr(client, "base_url", "https://api.openai.com/v1")
