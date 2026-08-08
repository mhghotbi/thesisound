from __future__ import annotations

import base64
import json
from typing import Any, Literal

from pydantic import BaseModel

from thesisound.audio import AsrTranscript
from thesisound.audio_ports import TtsRequest, TtsResponse
from thesisound.modeling import ModelConfigurationError, ModelProviderError


class _AsrOutput(BaseModel):
    transcript: str
    detected_language: str | None = None
    speaker: Literal["A", "B"] | None = None


class GeminiTtsAdapter:
    provider = "gemini"

    def __init__(self, *, api_key: str | None = None, client: Any | None = None) -> None:
        if client is not None:
            self._client = client
            return
        if not api_key:
            raise ModelConfigurationError("GEMINI_API_KEY is required for live TTS calls.")
        try:
            from google import genai
        except ImportError as exc:
            raise ModelConfigurationError(
                "Install the Gemini extra with: uv sync --extra gemini"
            ) from exc
        self._client = genai.Client(api_key=api_key)

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
        try:
            response = self._client.models.generate_content(
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
            data = _audio_data(response)
        except Exception as exc:
            raise ModelProviderError(str(exc) or type(exc).__name__, retryable=True) from exc
        return TtsResponse(
            pcm_bytes=data,
            provider=self.provider,
            model=request.model,
        )


class GeminiAsrAdapter:
    provider = "gemini"

    def __init__(self, *, api_key: str | None = None, client: Any | None = None) -> None:
        if client is not None:
            self._client = client
            return
        if not api_key:
            raise ModelConfigurationError("GEMINI_API_KEY is required for live ASR calls.")
        try:
            from google import genai
        except ImportError as exc:
            raise ModelConfigurationError(
                "Install the Gemini extra with: uv sync --extra gemini"
            ) from exc
        self._client = genai.Client(api_key=api_key)

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
        try:
            response = self._client.models.generate_content(
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
            output = _coerce_asr(response)
        except Exception as exc:
            raise ModelProviderError(str(exc) or type(exc).__name__, retryable=True) from exc
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
