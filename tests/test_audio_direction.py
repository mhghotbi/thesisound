from pydantic import ValidationError

from thesisound.services.audio_direction import (
    DEFAULT_ACCENT,
    DEFAULT_PACE,
    DEFAULT_TONE,
    AudioDirectionSettings,
)


def test_rejects_unknown_voice() -> None:
    try:
        AudioDirectionSettings(voice_a="NotAVoice", voice_b="Puck")
    except ValidationError as error:
        assert "Unknown Gemini TTS voice" in str(error)
    else:
        raise AssertionError("expected ValidationError")


def test_rejects_identical_voices() -> None:
    try:
        AudioDirectionSettings(voice_a="Kore", voice_b="Kore")
    except ValidationError as error:
        assert "Voice A and Voice B must be different" in str(error)
    else:
        raise AssertionError("expected ValidationError")


def test_style_prompt_for_includes_speaker_notes_only() -> None:
    direction = AudioDirectionSettings(
        voice_a="Kore",
        voice_b="Puck",
        pace="slow",
        tone="جدی",
        accent="تهرانی",
        speaker_a_notes="کنجکاو",
        speaker_b_notes="آرام",
    )
    prompt_a = direction.style_prompt_for("A")
    assert "با سرعت آهسته و شمرده بخوان" in prompt_a
    assert "لحن: جدی" in prompt_a
    assert "لهجه: تهرانی" in prompt_a
    assert "ویژگی این گوینده: کنجکاو" in prompt_a
    assert "آرام" not in prompt_a


def test_defaults_apply_when_only_voices_given() -> None:
    direction = AudioDirectionSettings(voice_a="Kore", voice_b="Puck")
    assert direction.pace == DEFAULT_PACE
    assert direction.tone == DEFAULT_TONE
    assert direction.accent == DEFAULT_ACCENT
    assert direction.speaker_a_notes == ""
    assert direction.speaker_b_notes == ""
    assert direction.voices_map == {"A": "Kore", "B": "Puck"}


def test_defaults_include_voices() -> None:
    direction = AudioDirectionSettings()
    assert direction.voice_a == "Kore"
    assert direction.voice_b == "Puck"
    assert direction.pace == DEFAULT_PACE
