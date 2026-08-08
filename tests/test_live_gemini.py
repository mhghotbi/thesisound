from __future__ import annotations

import os

import pytest
from pydantic import BaseModel

from thesisound.adapters.models.gemini import GeminiStructuredModel
from thesisound.config import Settings
from thesisound.ports import RunMetadata


class LiveSmokeOutput(BaseModel):
    status: str


@pytest.mark.live
def test_live_gemini_structured_output_smoke() -> None:
    if os.getenv("THESISOUND_RUN_LIVE_MODEL_TESTS", "").casefold() != "true":
        pytest.skip("Set THESISOUND_RUN_LIVE_MODEL_TESTS=true to call Gemini.")
    settings = Settings()
    if not settings.gemini_api_keys:
        pytest.skip("GEMINI_API_KEYS or GEMINI_API_KEY is not configured.")
    model = os.getenv("THESISOUND_MODEL_FAST", "gemini-3.5-flash-lite")
    adapter = GeminiStructuredModel(api_keys=settings.gemini_api_keys)

    result = adapter.generate_structured(
        system_prompt="Return the requested structured status without extra prose.",
        user_prompt="Set status to ok.",
        output_type=LiveSmokeOutput,
        model=model,
        metadata=RunMetadata(stage="live_smoke", model_or_provider=model),
    )

    assert result.output.status.casefold() == "ok"
    assert result.provider == "gemini"
