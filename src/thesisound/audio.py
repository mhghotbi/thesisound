from __future__ import annotations

import hashlib
import io
import json
import wave
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from thesisound.domain import Script


class AudioChunk(BaseModel):
    chunk_id: str = Field(pattern=r"^[a-z0-9-]+$")
    segment_id: str
    speaker: Literal["A", "B"]
    source_turn_ids: list[str] = Field(min_length=1)
    text: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    voice_name: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_duration_seconds: float = Field(gt=0)


class WavValidationReport(BaseModel):
    verdict: Literal["pass", "reject"]
    duration_seconds: float = Field(ge=0)
    sample_rate_hz: int = Field(ge=1)
    channels: int = Field(ge=1)
    sample_width_bytes: int = Field(ge=1)
    frame_count: int = Field(ge=0)
    peak_ratio: float = Field(ge=0, le=1)
    issues: list[str] = Field(default_factory=list)


class AudioSegmentRecord(BaseModel):
    chunk: AudioChunk
    wav_ref: str
    wav_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str
    model: str
    synthesized_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    validation: WavValidationReport
    generation_attempts: int = Field(default=1, ge=1, le=3)


class AsrTranscript(BaseModel):
    chunk_id: str
    chunk_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    wav_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str
    detected_language: str | None = None
    speaker: Literal["A", "B"] | None = None
    provider: str
    model: str


class AudioSegmentQa(BaseModel):
    chunk_id: str
    chunk_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    wav_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: Literal["pass", "regenerate", "manual_review"]
    similarity_ratio: float = Field(ge=0, le=1)
    expected_text: str
    transcript_text: str
    missing_sentences: list[str] = Field(default_factory=list)
    repeated_phrases: list[str] = Field(default_factory=list)
    truncated: bool = False
    pronunciation_review: list[str] = Field(default_factory=list)
    regeneration_instruction: str | None = None


class AudioPipelineManifest(BaseModel):
    project_id: UUID
    script_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal[
        "segmented",
        "segments_ready",
        "qa_ready",
        "assembled",
        "verified",
        "failed",
    ]
    chunk_count: int = Field(default=0, ge=0)
    passed_chunk_count: int = Field(default=0, ge=0)
    regenerated_chunk_ids: list[str] = Field(default_factory=list)
    final_audio_ref: str | None = None
    final_audio_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    final_duration_seconds: float | None = Field(default=None, ge=0)
    normalization: Literal["ffmpeg_loudnorm", "not_run"] = "not_run"
    last_error: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def script_hash(script: Script) -> str:
    payload = json.dumps(
        script.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def content_hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def pcm_to_wav(
    pcm_bytes: bytes,
    *,
    sample_rate_hz: int = 24_000,
    channels: int = 1,
    sample_width_bytes: int = 2,
) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(sample_width_bytes)
        output.setframerate(sample_rate_hz)
        output.writeframes(pcm_bytes)
    return buffer.getvalue()
