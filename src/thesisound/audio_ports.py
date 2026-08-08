from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from thesisound.audio import AsrTranscript


class TtsRequest(BaseModel):
    chunk_id: str
    text: str = Field(min_length=1)
    speaker: str
    voice_name: str
    model: str
    style_prompt: str


class TtsResponse(BaseModel):
    pcm_bytes: bytes
    sample_rate_hz: int = 24_000
    channels: int = 1
    sample_width_bytes: int = 2
    provider: str
    model: str


class TextToSpeechPort(Protocol):
    def synthesize(self, request: TtsRequest) -> TtsResponse: ...


class SpeechToTextPort(Protocol):
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
    ) -> AsrTranscript: ...
