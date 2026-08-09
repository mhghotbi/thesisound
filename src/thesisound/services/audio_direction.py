from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from thesisound.tts_voices import GEMINI_TTS_VOICE_NAMES

Pace = Literal["slow", "moderate", "energetic"]

DEFAULT_PACE: Pace = "moderate"
DEFAULT_TONE = "جدی و صمیمی، گفت‌وگوی طبیعی"
DEFAULT_ACCENT = "فارسی معیار (تهرانی)"

_PACE_PHRASES: dict[Pace, str] = {
    "slow": "با سرعت آهسته و شمرده بخوان",
    "moderate": "با سرعت متوسط و طبیعی بخوان",
    "energetic": "با سرعت پرانرژی و ریتم تندتر بخوان",
}

_TEXT_FIELD_MAX = 200
_NOTES_MAX = 600


class AudioDirectionSettings(BaseModel):
    voice_a: str
    voice_b: str
    pace: Pace = DEFAULT_PACE
    tone: str = Field(default=DEFAULT_TONE, max_length=_TEXT_FIELD_MAX)
    accent: str = Field(default=DEFAULT_ACCENT, max_length=_TEXT_FIELD_MAX)
    speaker_a_notes: str = Field(default="", max_length=_NOTES_MAX)
    speaker_b_notes: str = Field(default="", max_length=_NOTES_MAX)

    @field_validator("voice_a", "voice_b")
    @classmethod
    def _voice_must_be_known(cls, value: str) -> str:
        if value not in GEMINI_TTS_VOICE_NAMES:
            raise ValueError(f"Unknown Gemini TTS voice: {value}")
        return value

    @field_validator("tone", "accent", "speaker_a_notes", "speaker_b_notes")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _voices_must_differ(self) -> AudioDirectionSettings:
        if self.voice_a == self.voice_b:
            raise ValueError("Voice A and Voice B must be different.")
        return self

    @property
    def voices_map(self) -> dict[str, str]:
        return {"A": self.voice_a, "B": self.voice_b}

    def style_prompt_for(self, speaker: Literal["A", "B"]) -> str:
        notes = self.speaker_a_notes if speaker == "A" else self.speaker_b_notes
        lines = [
            _PACE_PHRASES[self.pace],
            f"لحن: {self.tone}" if self.tone else None,
            f"لهجه: {self.accent}" if self.accent else None,
            f"ویژگی این گوینده: {notes}" if notes else None,
        ]
        return "\n".join(line for line in lines if line)
