from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from thesisound.adapters.audio.gemini import GeminiTtsAdapter
from thesisound.adapters.audio.openai import OpenAiSpeechResponse, OpenAiTtsAdapter
from thesisound.audio_ports import TtsRequest
from thesisound.config import Settings
from thesisound.modeling import ModelProviderError, ModelRateLimitError
from thesisound.observability import ObservabilityLedger


class RateLimitException(RuntimeError):
    status_code = 429


class FakeModels:
    def __init__(self, *, error: Exception) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        raise self.error


class FakeClient:
    def __init__(self, models: FakeModels) -> None:
        self.models = models


class FakeOpenAiClient:
    def __init__(self, pcm: bytes = b"\x00\x01" * 120) -> None:
        self.pcm = pcm
        self.requests: list[tuple[dict[str, object], float]] = []

    def create_speech(
        self,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> OpenAiSpeechResponse:
        self.requests.append((payload, timeout_seconds))
        return OpenAiSpeechResponse(
            pcm_bytes=self.pcm,
            status_code=200,
            headers={"x-request-id": "req-openai-tts"},
            request_id="req-openai-tts",
        )


def _settings(tmp_path: Path, *, with_openai: bool) -> Settings:
    kwargs: dict[str, object] = {
        "_env_file": None,
        "workspace_root": tmp_path / "workspaces",
        "observability_database_path": tmp_path / "ledger.sqlite3",
        "observability_artifact_root": tmp_path / "artifacts",
        "gemini_api_keys_value": "[]",
        "gemini_api_key": "test-gemini-key",
    }
    if with_openai:
        kwargs["openai_api_key"] = "test-openai-key"
        kwargs["openai_base_url"] = "https://api.openai.com/v1"
        kwargs["model_tts_fallback"] = "gpt-4o-mini-tts"
        kwargs["openai_tts_voice_a"] = "coral"
        kwargs["openai_tts_voice_b"] = "ash"
    return Settings(**kwargs)


def _request(*, speaker: str = "A") -> TtsRequest:
    return TtsRequest(
        chunk_id="chunk-1",
        text="سلام دنیا",
        speaker=speaker,
        voice_name="Kore" if speaker == "A" else "Puck",
        model="gemini-3.1-flash-tts-preview",
        style_prompt="طبیعی بخوان",
    )


def _latest_call(ledger: ObservabilityLedger, *, provider: str):
    with sqlite3.connect(ledger.database_path) as connection:
        row = connection.execute(
            """
            SELECT call_id FROM model_calls
            WHERE provider = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (provider,),
        ).fetchone()
    assert row is not None
    return ledger.get_call(UUID(row[0]))


def test_tts_rate_limit_falls_back_to_openai(tmp_path: Path) -> None:
    settings = _settings(tmp_path, with_openai=True)
    ledger = ObservabilityLedger(
        settings.resolved_observability_database_path,
        settings.resolved_observability_artifact_root,
    )
    models = FakeModels(error=RateLimitException("quota exhausted"))
    adapter = GeminiTtsAdapter(
        client=FakeClient(models),
        settings=settings,
        observability=ledger,
        project_id=uuid4(),
    )
    openai_client = FakeOpenAiClient()
    adapter._openai_port = OpenAiTtsAdapter(
        client=openai_client,
        settings=settings,
        observability=ledger,
        project_id=adapter.project_id,
    )

    response = adapter.synthesize(_request(speaker="A"))

    assert response.provider == "openai"
    assert response.model == "gpt-4o-mini-tts"
    assert response.pcm_bytes == openai_client.pcm
    assert len(openai_client.requests) == 1
    assert openai_client.requests[0][0]["voice"] == "coral"
    assert openai_client.requests[0][0]["response_format"] == "pcm"
    assert openai_client.requests[0][0]["instructions"] == "طبیعی بخوان"
    assert models.calls

    detail_gemini = _latest_call(ledger, provider="gemini")
    detail_openai = _latest_call(ledger, provider="openai")
    assert detail_gemini.call.status == "failed"
    assert detail_openai.call.status == "succeeded"
    assert detail_openai.parent_call_id == detail_gemini.call.call_id
    assert detail_openai.metadata["openai_tts_fallback_from"] == "gemini"


def test_tts_fallback_maps_speaker_b_to_ash(tmp_path: Path) -> None:
    settings = _settings(tmp_path, with_openai=True)
    ledger = ObservabilityLedger(
        settings.resolved_observability_database_path,
        settings.resolved_observability_artifact_root,
    )
    adapter = GeminiTtsAdapter(
        client=FakeClient(FakeModels(error=RateLimitException("quota"))),
        settings=settings,
        observability=ledger,
    )
    openai_client = FakeOpenAiClient()
    adapter._openai_port = OpenAiTtsAdapter(
        client=openai_client,
        settings=settings,
        observability=ledger,
    )

    adapter.synthesize(_request(speaker="B"))

    assert openai_client.requests[0][0]["voice"] == "ash"


def test_tts_rate_limit_without_openai_key_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path, with_openai=False)
    adapter = GeminiTtsAdapter(
        client=FakeClient(FakeModels(error=RateLimitException("too many requests"))),
        settings=settings,
    )

    with pytest.raises(ModelRateLimitError, match="too many requests"):
        adapter.synthesize(_request())


def test_tts_non_rate_limit_does_not_fall_back(tmp_path: Path) -> None:
    settings = _settings(tmp_path, with_openai=True)
    adapter = GeminiTtsAdapter(
        client=FakeClient(FakeModels(error=RuntimeError("boom"))),
        settings=settings,
    )
    recording: list[object] = []

    class RecordingOpenAi:
        def synthesize(self, *args, **kwargs):
            recording.append((args, kwargs))
            raise AssertionError("should not be called")

    adapter._openai_port = RecordingOpenAi()

    with pytest.raises(ModelProviderError, match="boom"):
        adapter.synthesize(_request())

    assert recording == []
