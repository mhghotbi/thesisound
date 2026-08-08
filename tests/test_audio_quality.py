import io
import wave

from thesisound.audio import AsrTranscript, AudioChunk
from thesisound.services.audio_assembler import concatenate_wav
from thesisound.services.audio_qa import AudioQaService
from thesisound.services.audio_validator import AudioValidator


def _wav(seconds: float = 1.0, *, sample_rate: int = 24_000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(b"\x00\x00" * round(sample_rate * seconds))
    return output.getvalue()


def _chunk(text: str) -> AudioChunk:
    return AudioChunk(
        chunk_id="audio-0001",
        segment_id="seg-1",
        speaker="A",
        source_turn_ids=["turn-1"],
        text=text,
        sequence=0,
        voice_name="Kore",
        content_hash="a" * 64,
        expected_duration_seconds=3,
    )


def test_audio_validator_and_concatenation() -> None:
    validator = AudioValidator(expected_sample_rate_hz=24_000)
    joined = concatenate_wav([_wav(), _wav()], silence_milliseconds=250)
    report = validator.validate(joined)

    assert report.verdict == "pass"
    assert 2.2 <= report.duration_seconds <= 2.3


def test_audio_qa_detects_missing_or_truncated_content() -> None:
    chunk = _chunk("این جمله باید کامل خوانده شود. پایان مهم متن نیز نباید حذف شود.")
    transcript = AsrTranscript(
        chunk_id=chunk.chunk_id,
        chunk_hash=chunk.content_hash,
        wav_sha256="b" * 64,
        text="این جمله باید کامل خوانده شود.",
        speaker="A",
        provider="fake",
        model="fake",
    )

    report = AudioQaService().compare(chunk, transcript)

    assert report.verdict == "regenerate"
    assert report.wav_sha256 == transcript.wav_sha256
    assert report.truncated or report.missing_sentences
    assert report.regeneration_instruction
