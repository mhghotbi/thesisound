import io
import subprocess
import wave
from pathlib import Path

import pytest

from thesisound import tracing
from thesisound.audio import AsrTranscript, AudioChunk
from thesisound.services.audio_assembler import AudioAssembler, concatenate_wav
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


def test_audio_qa_passes_near_identical_persian_despite_zwnj_and_punctuation() -> None:
    expected = (
        "خیر، آرنت فعالیت‌ها و قلمروهای زندگی انسانی را در سه سطح کاملاً متمایز و بر اساس "
        "مرتبه، ارزش و اصالت دسته‌بندی می‌کند. در پایین‌ترین مرتبه، قلمرو خصوصی قرار دارد "
        "که حیطه حضور انسان زحمت‌کش و انجام زحمت برای رفع نیازهای زیستی است. در طرف دیگر "
        "این طیف، قلمرو عمومی قرار می‌گیرد که بالاترین و برترین قلمرو به شمار می‌رود. "
        "قلمرو عمومی جایگاه اصلی کنش است؛ جایی که فعل انسان دیگر یک رفتار یا تبعیت ساده "
        "از ضرورت محسوب نمی‌شود، بلکه کنشی اصیل در عرصه میان‌انسانی است."
    )
    actual = (
        "خیر. آرنت فعالیت‌ها و قلمروهای زندگی انسانی را در سه سطح کاملاً متمایز و بر اساس "
        "مرتبه، ارزش و اصالت دسته‌بندی می‌کند. در پایین‌ترین مرتبه، قلمرو خصوصی قرار دارد "
        "که حیطه حضور انسان زحمتکش و انجام زحمت برای رفع نیازهای زیستی است. در طرف دیگر "
        "این طیف، قلمرو عمومی قرار می‌گیرد که بالاترین و برترین قلمرو به شمار می‌رود. "
        "قلمرو عمومی جایگاه اصلی کنش است. جایی که فعل انسان دیگر یک رفتار یا تبعیت ساده "
        "از ضرورت محسوب نمی‌شود، بلکه کنشی اصیل در عرصه میان‌انسانی است."
    )
    chunk = _chunk(expected)
    transcript = AsrTranscript(
        chunk_id=chunk.chunk_id,
        chunk_hash=chunk.content_hash,
        wav_sha256="b" * 64,
        text=actual,
        speaker="A",
        provider="fake",
        model="fake",
    )

    report = AudioQaService().compare(chunk, transcript)

    assert report.similarity_ratio >= 0.9
    assert report.verdict == "pass"
    assert not report.missing_sentences


def test_audio_qa_records_the_verdict_and_similarity_as_a_span(
    recording_tracer: tracing.Tracer,
) -> None:
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

    AudioQaService().compare(chunk, transcript)

    span = recording_tracer.sink.one("audio.qa")
    assert span.subject_id == "audio-0001"
    assert span.attributes["verdict"] == "regenerate"
    assert 0 <= span.metrics["similarity_ratio"] <= 1
    assert span.metrics["missing_sentence_count"] >= 0


def test_audio_assembler_records_a_successful_ffmpeg_span(
    monkeypatch: pytest.MonkeyPatch, recording_tracer: tracing.Tracer
) -> None:
    """AudioAssembler.assemble() had no test coverage before this instrumentation
    -- neither the ffmpeg call nor its failure path was exercised anywhere."""

    monkeypatch.setattr(
        "thesisound.services.audio_assembler.shutil.which", lambda _: "/usr/bin/ffmpeg"
    )

    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(_wav(seconds=0.5))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("thesisound.services.audio_assembler.subprocess.run", fake_run)

    AudioAssembler().assemble([_wav(), _wav()])

    span = recording_tracer.sink.one("audio.assemble.ffmpeg")
    assert span.kind == "subprocess"
    assert span.status == "ok"
    assert span.attributes["exit_code"] == 0
    assert span.metrics["input_bytes"] > 0
    assert span.metrics["output_bytes"] > 0


def test_audio_assembler_records_a_failed_ffmpeg_span(
    monkeypatch: pytest.MonkeyPatch, recording_tracer: tracing.Tracer
) -> None:
    monkeypatch.setattr(
        "thesisound.services.audio_assembler.shutil.which", lambda _: "/usr/bin/ffmpeg"
    )

    def failing_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="loudnorm failed\n")

    monkeypatch.setattr("thesisound.services.audio_assembler.subprocess.run", failing_run)

    with pytest.raises(RuntimeError, match="loudnorm failed"):
        AudioAssembler().assemble([_wav()])

    span = recording_tracer.sink.one("audio.assemble.ffmpeg")
    assert span.status == "error"
    assert span.attributes["exit_code"] == 1
    assert span.attributes["stderr_tail"] == "loudnorm failed"
