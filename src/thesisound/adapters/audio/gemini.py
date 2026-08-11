from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Sequence
from threading import Lock
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel

from thesisound.audio import AsrTranscript
from thesisound.audio_ports import TtsRequest, TtsResponse
from thesisound.config import Settings
from thesisound.gemini_key_pool import (
    GeminiKeyPool,
    is_gemini_quota_error,
    shared_gemini_key_pool,
)
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


class _AsrOutput(BaseModel):
    transcript: str
    detected_language: str | None = None
    speaker: Literal["A", "B"] | None = None


class GeminiTtsAdapter:
    provider = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_keys: Sequence[str] | None = None,
        pool: GeminiKeyPool | None = None,
        client: Any | None = None,
        project_id: UUID | None = None,
        workflow_run_id: UUID | None = None,
        observability: ObservabilityLedger | None = None,
        settings: Settings | None = None,
    ) -> None:
        runtime = settings or _settings()
        self._settings = runtime
        self._client, self._pool = _resolve_client(api_key, api_keys, pool, client, runtime)
        self.project_id = project_id
        self.workflow_run_id = workflow_run_id
        self.observability = observability or ledger_from_settings(runtime)
        self._gateway = ObservedModelGateway(self.observability)
        self._timeout_ms = runtime.tts_timeout_seconds * 1000
        self._max_provider_attempts = runtime.provider_max_attempts
        self._retry_base_seconds = runtime.provider_retry_base_seconds
        self._openai_port: Any | None = None
        self._openai_lock = Lock()

    def synthesize(self, request: TtsRequest) -> TtsResponse:
        try:
            from google.genai import types
        except ImportError as exc:
            raise ModelConfigurationError(
                "Install the Gemini extra with: uv sync --extra gemini"
            ) from exc

        prompt = (
            f"{request.style_prompt.strip()}\n\n"
            f"متن را دقیقاً و بدون افزودن توضیح بخوان:\n{request.text}"
        )
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=request.voice_name
                    )
                )
            ),
            http_options={
                "timeout": self._timeout_ms,
                "retry_options": {"attempts": 1},
            },
        )
        spec = ModelCallSpec(
            project_id=self.project_id,
            workflow_run_id=self.workflow_run_id,
            stage="audio_tts",
            operation="tts",
            provider=self.provider,
            requested_model=request.model,
            subject_type="audio_chunk",
            subject_id=request.chunk_id,
            timeout_ms=self._timeout_ms,
            metadata={
                "speaker": request.speaker,
                "voice_name": request.voice_name,
            },
        )
        try:
            observed = self._gateway.call(
                spec=spec,
                request_payload={
                    "chunk_id": request.chunk_id,
                    "text": request.text,
                    "speaker": request.speaker,
                    "voice_name": request.voice_name,
                    "style_prompt": request.style_prompt,
                    "model": request.model,
                    "timeout_ms": self._timeout_ms,
                },
                operation=lambda client: client.models.generate_content(
                    model=request.model,
                    contents=prompt,
                    config=config,
                ),
                pool=self._pool,
                client=self._client,
                max_provider_attempts=self._max_provider_attempts,
                base_retry_delay_seconds=self._retry_base_seconds,
                retryable_error=_is_retryable_provider_exception,
                response_payload=_tts_provider_snapshot,
                usage=_usage,
                provider_metadata=lambda response: _provider_metadata(response, request.model),
            )
            data = _audio_data(observed.response)
        except Exception as exc:
            mapped = _audio_provider_error(exc)
            self.observability.fail(spec.call_id, mapped, error_code=_error_code(exc))
            if self._should_fallback_to_openai(mapped):
                fallback_request = request.model_copy(
                    update={"model": self._settings.model_tts_fallback}
                )
                return self._openai().synthesize(
                    fallback_request,
                    call_id=uuid4(),
                    parent_call_id=spec.call_id,
                    extra_metadata={"openai_tts_fallback_from": "gemini"},
                )
            raise mapped from exc

        self.observability.succeed(
            spec.call_id,
            {
                "chunk_id": request.chunk_id,
                "provider": self.provider,
                "model": request.model,
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
            model=request.model,
        )

    def _openai(self) -> Any:
        if self._openai_port is not None:
            return self._openai_port
        from thesisound.adapters.audio.openai import OpenAiTtsAdapter

        with self._openai_lock:
            if self._openai_port is None:
                self._openai_port = OpenAiTtsAdapter(
                    settings=self._settings,
                    observability=self.observability,
                    project_id=self.project_id,
                    workflow_run_id=self.workflow_run_id,
                )
        return self._openai_port

    def _openai_configured(self) -> bool:
        return bool((self._settings.openai_api_key or "").strip())

    def _should_fallback_to_openai(self, error: Exception) -> bool:
        return isinstance(error, ModelRateLimitError) and self._openai_configured()


class GeminiAsrAdapter:
    provider = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_keys: Sequence[str] | None = None,
        pool: GeminiKeyPool | None = None,
        client: Any | None = None,
        project_id: UUID | None = None,
        workflow_run_id: UUID | None = None,
        observability: ObservabilityLedger | None = None,
        settings: Settings | None = None,
    ) -> None:
        runtime = settings or _settings()
        self._client, self._pool = _resolve_client(api_key, api_keys, pool, client, runtime)
        self.project_id = project_id
        self.workflow_run_id = workflow_run_id
        self.observability = observability or ledger_from_settings(runtime)
        self._gateway = ObservedModelGateway(self.observability)
        self._timeout_ms = runtime.asr_timeout_seconds * 1000
        self._max_provider_attempts = runtime.provider_max_attempts
        self._retry_base_seconds = runtime.provider_retry_base_seconds

    def transcribe(
        self,
        *,
        chunk_id: str,
        chunk_hash: str,
        wav_sha256: str,
        wav_bytes: bytes,
        model: str,
        expected_speaker: str,
        language: str = "fa",
    ) -> AsrTranscript:
        try:
            from google.genai import types
        except ImportError as exc:
            raise ModelConfigurationError(
                "Install the Gemini extra with: uv sync --extra gemini"
            ) from exc
        prompt = (
            "گفتار این فایل را بدون خلاصه‌سازی و بدون اصلاح محتوایی رونویسی کن. "
            f"زبان مورد انتظار {language} و گوینده مورد انتظار {expected_speaker} است."
        )
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_AsrOutput,
            http_options={
                "timeout": self._timeout_ms,
                "retry_options": {"attempts": 1},
            },
        )
        spec = ModelCallSpec(
            project_id=self.project_id,
            workflow_run_id=self.workflow_run_id,
            stage="audio_asr",
            operation="asr",
            provider=self.provider,
            requested_model=model,
            subject_type="audio_chunk",
            subject_id=chunk_id,
            timeout_ms=self._timeout_ms,
            metadata={
                "chunk_hash": chunk_hash,
                "wav_sha256": wav_sha256,
                "expected_speaker": expected_speaker,
                "language": language,
            },
        )
        try:
            observed = self._gateway.call(
                spec=spec,
                request_payload={
                    "chunk_id": chunk_id,
                    "chunk_hash": chunk_hash,
                    "wav_sha256": wav_sha256,
                    "wav_size_bytes": len(wav_bytes),
                    "model": model,
                    "expected_speaker": expected_speaker,
                    "language": language,
                    "prompt": prompt,
                    "timeout_ms": self._timeout_ms,
                },
                operation=lambda client: client.models.generate_content(
                    model=model,
                    contents=[
                        prompt,
                        types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                    ],
                    config=config,
                ),
                pool=self._pool,
                client=self._client,
                max_provider_attempts=self._max_provider_attempts,
                base_retry_delay_seconds=self._retry_base_seconds,
                retryable_error=_is_retryable_provider_exception,
                response_payload=_asr_provider_snapshot,
                usage=_usage,
                provider_metadata=lambda response: _provider_metadata(response, model),
            )
            output = _coerce_asr(observed.response)
        except Exception as exc:
            mapped = _audio_provider_error(exc)
            self.observability.fail(spec.call_id, mapped, error_code=_error_code(exc))
            raise mapped from exc

        transcript = AsrTranscript(
            chunk_id=chunk_id,
            chunk_hash=chunk_hash,
            wav_sha256=wav_sha256,
            text=output.transcript,
            detected_language=output.detected_language,
            speaker=output.speaker,
            provider=self.provider,
            model=model,
        )
        self.observability.succeed(spec.call_id, transcript)
        return transcript


def _settings() -> Settings:
    try:
        return Settings()
    except ValueError:
        return Settings.model_construct()


def _resolve_client(
    api_key: str | None,
    api_keys: Sequence[str] | None,
    pool: GeminiKeyPool | None,
    client: Any | None,
    settings: Settings,
) -> tuple[Any | None, GeminiKeyPool | None]:
    if client is not None:
        return client, None
    keys = list(api_keys or settings.gemini_api_keys)
    if api_key:
        keys.append(api_key)
    if pool is None and not keys:
        raise ModelConfigurationError(
            "GEMINI_API_KEY or GEMINI_API_KEYS is required for live Gemini calls."
        )
    return None, pool or shared_gemini_key_pool(keys)


def _audio_provider_error(exc: Exception) -> Exception:
    if isinstance(exc, ModelProviderError):
        return exc
    if is_gemini_quota_error(exc):
        return ModelRateLimitError(str(exc) or type(exc).__name__)
    name = type(exc).__name__.casefold()
    if "timeout" in name or "deadline" in name:
        return ModelTimeoutError(str(exc) or type(exc).__name__)
    status = _status_code(exc)
    retryable = status is None or status >= 500
    return ModelProviderError(str(exc) or type(exc).__name__, retryable=retryable)


def _is_retryable_provider_exception(exc: Exception) -> bool:
    mapped = _audio_provider_error(exc)
    return bool(getattr(mapped, "retryable", False)) and not isinstance(
        mapped, ModelRateLimitError
    )


def _audio_data(response: Any) -> bytes:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        raise ValueError("Gemini TTS returned no candidates.")
    content = getattr(candidates[0], "content", None)
    parts = getattr(content, "parts", None) or []
    for part in parts:
        inline = getattr(part, "inline_data", None)
        data = getattr(inline, "data", None) if inline is not None else None
        if isinstance(data, bytes):
            return data
        if isinstance(data, str) and data:
            return base64.b64decode(data)
    raise ValueError("Gemini TTS returned no inline audio data.")


def _coerce_asr(response: Any) -> _AsrOutput:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, _AsrOutput):
        return parsed
    if parsed is not None:
        return _AsrOutput.model_validate(parsed)
    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Gemini ASR returned no transcript.")
    try:
        return _AsrOutput.model_validate_json(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Gemini ASR returned invalid JSON.") from exc


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
        cached_tokens=_optional_int(getattr(usage, "cached_content_token_count", None)),
    )


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
        resolved_model=str(getattr(response, "model_version", None) or model),
        provider_request_id=request_id,
        http_status=status if isinstance(status, int) else None,
        finish_reason=_finish_reason(response),
    )


def _finish_reason(response: Any) -> str | None:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return None
    reason = getattr(candidates[0], "finish_reason", None)
    if reason is None:
        return None
    return str(getattr(reason, "value", reason))


def _tts_provider_snapshot(response: Any) -> dict[str, Any]:
    chunks: list[dict[str, Any]] = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            data = getattr(inline, "data", None) if inline is not None else None
            if isinstance(data, str):
                try:
                    payload = base64.b64decode(data)
                except ValueError:
                    payload = data.encode("utf-8")
            elif isinstance(data, bytes):
                payload = data
            else:
                payload = b""
            if payload:
                chunks.append(
                    {
                        "mime_type": getattr(inline, "mime_type", None),
                        "size_bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )
    return {
        "model_version": getattr(response, "model_version", None),
        "finish_reason": _finish_reason(response),
        "usage_metadata": getattr(response, "usage_metadata", None),
        "audio_parts": chunks,
    }


def _asr_provider_snapshot(response: Any) -> dict[str, Any]:
    return {
        "model_version": getattr(response, "model_version", None),
        "finish_reason": _finish_reason(response),
        "usage_metadata": getattr(response, "usage_metadata", None),
        "text": getattr(response, "text", None),
        "parsed": getattr(response, "parsed", None),
    }


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


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
