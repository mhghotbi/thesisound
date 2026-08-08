from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel

from thesisound.audio import AsrTranscript
from thesisound.audio_ports import TtsRequest, TtsResponse
from thesisound.gemini_key_pool import (
    GeminiKeyPool,
    is_gemini_quota_error,
    shared_gemini_key_pool,
)
from thesisound.modeling import ModelConfigurationError, ModelProviderError, ModelRateLimitError


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
    ) -> None:
        self._client, self._pool = _resolve_client(api_key, api_keys, pool, client)

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

        def operation(client: Any) -> Any:
            return client.models.generate_content(
                model=request.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=request.voice_name
                            )
                        )
                    ),
                ),
            )

        try:
            response = self._pool.call(operation) if self._pool else operation(self._client)
            data = _audio_data(response)
        except Exception as exc:
            raise _audio_provider_error(exc) from exc
        return TtsResponse(
            pcm_bytes=data,
            provider=self.provider,
            model=request.model,
        )


class GeminiAsrAdapter:
    provider = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_keys: Sequence[str] | None = None,
        pool: GeminiKeyPool | None = None,
        client: Any | None = None,
    ) -> None:
        self._client, self._pool = _resolve_client(api_key, api_keys, pool, client)

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

        def operation(client: Any) -> Any:
            return client.models.generate_content(
                model=model,
                contents=[
                    prompt,
                    types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_AsrOutput,
                ),
            )

        try:
            response = self._pool.call(operation) if self._pool else operation(self._client)
            output = _coerce_asr(response)
        except Exception as exc:
            raise _audio_provider_error(exc) from exc
        return AsrTranscript(
            chunk_id=chunk_id,
            chunk_hash=chunk_hash,
            wav_sha256=wav_sha256,
            text=output.transcript,
            detected_language=output.detected_language,
            speaker=output.speaker,
            provider=self.provider,
            model=model,
        )


def _resolve_client(
    api_key: str | None,
    api_keys: Sequence[str] | None,
    pool: GeminiKeyPool | None,
    client: Any | None,
) -> tuple[Any | None, GeminiKeyPool | None]:
    if client is not None:
        return client, None
    keys = list(api_keys or [])
    if api_key:
        keys.append(api_key)
    if pool is None and not keys:
        raise ModelConfigurationError(
            "GEMINI_API_KEY or GEMINI_API_KEYS is required for live Gemini calls."
        )
    return None, pool or shared_gemini_key_pool(keys)


def _audio_provider_error(exc: Exception) -> Exception:
    if is_gemini_quota_error(exc):
        return ModelRateLimitError(str(exc) or type(exc).__name__)
    return ModelProviderError(str(exc) or type(exc).__name__, retryable=True)


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
