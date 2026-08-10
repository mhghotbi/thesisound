import io
import json
import subprocess
import wave
from difflib import SequenceMatcher
from pathlib import Path

import pytest

from thesisound import tracing
from thesisound.audio import AsrTranscript, AudioChunk
from thesisound.services.audio_assembler import AudioAssembler, concatenate_wav
from thesisound.services.audio_qa import (
    _SENTENCES,
    AudioQaService,
    _best_window_similarity,
    _sentence_similarity,
    _sentences,
)
from thesisound.services.audio_validator import AudioValidator

FIXTURE = Path(__file__).parent / "fixtures" / "audio_qa" / "real_run_chunks.json"


def _real_run_chunks() -> list[dict[str, str]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _wav(seconds: float = 1.0, *, sample_rate: int = 24_000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(b"\x00\x00" * round(sample_rate * seconds))
    return output.getvalue()


def _chunk(text: str, *, chunk_id: str = "audio-0001") -> AudioChunk:
    return AudioChunk(
        chunk_id=chunk_id,
        segment_id="seg-1",
        speaker="A",
        source_turn_ids=["turn-1"],
        text=text,
        sequence=0,
        voice_name="Kore",
        content_hash="a" * 64,
        expected_duration_seconds=3,
    )


def _transcript(chunk: AudioChunk, text: str) -> AsrTranscript:
    return AsrTranscript(
        chunk_id=chunk.chunk_id,
        chunk_hash=chunk.content_hash,
        wav_sha256="b" * 64,
        text=text,
        speaker="A",
        provider="fixture",
        model="gemini-3.6-flash",
    )


def _leave_one_out_scores() -> list[float]:
    scores: list[float] = []
    for record in _real_run_chunks():
        sentences = [item.strip() for item in _SENTENCES.split(record["transcript_text"])]
        for index, sentence in enumerate(sentences):
            if len(sentence.split()) < 4:
                continue
            remainder = " ".join(sentences[:index] + sentences[index + 1 :])
            scores.append(_sentence_similarity(sentence, remainder))
    return scores


@pytest.mark.parametrize("record", _real_run_chunks(), ids=lambda item: item["chunk_id"])
def test_audio_qa_real_run_chunks_pass(record: dict[str, str]) -> None:
    chunk = _chunk(record["expected_text"], chunk_id=record["chunk_id"])
    report = AudioQaService().compare(chunk, _transcript(chunk, record["transcript_text"]))

    assert report.missing_sentences == []
    assert report.verdict == "pass"


def test_audio_qa_best_window_handles_worst_old_ceiling_case() -> None:
    record = next(item for item in _real_run_chunks() if item["chunk_id"] == "audio-0015")
    scores = [
        _sentence_similarity(sentence, record["transcript_text"])
        for sentence in _sentences(record["expected_text"])
    ]

    # The worst old whole-transcript score was 0.135; each sentence now clears 0.85.
    assert all(score >= 0.85 for score in scores)


def test_audio_qa_does_not_reuse_one_window_for_near_duplicate_sentences() -> None:
    filler = " ".join(f"prefix{index}" for index in range(80))
    tail = " ".join(f"tail{index}" for index in range(24))
    expected = (
        f"{filler}. "
        "the archive explains the river crossing in detail. "
        "a archive explains the river crossing in detail. "
        f"{tail}."
    )
    transcript_text = f"{filler}. the archive explains the river crossing in detail. {tail}."
    chunk = _chunk(expected)
    report = AudioQaService().compare(chunk, _transcript(chunk, transcript_text))

    assert report.similarity_ratio > 0.9
    assert report.missing_sentences == ["a archive explains the river crossing in detail."]
    assert report.verdict == "manual_review"


def test_audio_qa_leave_one_out_detects_every_deleted_sentence() -> None:
    deletions = _leave_one_out_scores()

    assert len(deletions) == 67
    assert all(score < 0.85 for score in deletions)


def test_audio_qa_real_run_populations_remain_separated() -> None:
    true_matches = [
        _sentence_similarity(sentence, record["transcript_text"])
        for record in _real_run_chunks()
        for sentence in _sentences(record["expected_text"])
    ]
    deletions = _leave_one_out_scores()

    assert max(deletions) < 0.85 < min(true_matches)


@pytest.mark.parametrize(
    ("sentence", "transcript"),
    [
        ("تأثیری", "تاثیری"),
        ("اشیاء", "اشیا"),
        ("آ", "ا"),
    ],
)
def test_audio_qa_folds_precomposed_hamza_characters(sentence: str, transcript: str) -> None:
    assert _sentence_similarity(sentence, transcript) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("needle", "haystack", "expected"),
    [
        ("", "هر متنی", 1.0),
        ("جمله غیرخالی", "", 0.0),
        (
            "این یک جمله طولانی برای آزمون است",
            "این کوتاه است",
            None,
        ),
        ("متن یکسان", "متن یکسان", 1.0),
        ("یک دو سه", "چهار پنج شش", None),
    ],
)
def test_best_window_similarity_edge_cases(
    needle: str, haystack: str, expected: float | None
) -> None:
    score = _best_window_similarity(needle, haystack)

    if expected is None:
        assert score < 0.85
    else:
        assert score == pytest.approx(expected)
    if len(haystack.split()) <= len(needle.split()):
        assert score == pytest.approx(
            SequenceMatcher(None, needle, haystack, autojunk=False).ratio()
        )


def test_audio_qa_missing_sentence_threshold_validation() -> None:
    with pytest.raises(ValueError):
        AudioQaService(missing_sentence_threshold=0)
    with pytest.raises(ValueError):
        AudioQaService(missing_sentence_threshold=1.1)

    assert AudioQaService(
        missing_sentence_threshold=1.0
    ).missing_sentence_threshold == pytest.approx(1.0)


def test_settings_configure_missing_sentence_threshold() -> None:
    from thesisound.config import Settings

    assert Settings().audio_qa_missing_sentence_threshold == pytest.approx(0.85)
    with pytest.raises(ValueError):
        Settings(audio_qa_missing_sentence_threshold=0.49)
    with pytest.raises(ValueError):
        Settings(audio_qa_missing_sentence_threshold=1.01)


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
