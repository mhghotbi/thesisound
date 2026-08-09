from __future__ import annotations

from uuid import uuid4

import pytest

from thesisound.audio import (
    AudioChunk,
    AudioPipelineManifest,
    AudioSegmentRecord,
    WavValidationReport,
)
from thesisound.domain import EpisodePlan, EpisodeSegment, Project
from thesisound.web.audio_routes import _chapters

SILENCE = 0.25


def _segment(segment_id: str, title: str) -> EpisodeSegment:
    return EpisodeSegment(
        segment_id=segment_id,
        title=title,
        purpose="هدف این بخش",
        estimated_minutes=2,
        claim_ids=["c-1"],
        key_question="این بخش به چه پرسشی پاسخ می‌دهد؟",
        speaker_dynamic="explanation",
    )


def _project(segment_ids: list[str]) -> Project:
    project = Project(raw_input="پرسش آزمون")
    project.episode_plan = EpisodePlan(
        title="گفتار آزمون",
        listener_outcome="نتیجهٔ آزمون",
        estimated_duration_minutes=10,
        segments=[
            _segment(segment_id, f"بخش {index}")
            for index, segment_id in enumerate(segment_ids, start=1)
        ],
    )
    return project


def _view(segment_id: str, sequence: int, duration: float | None) -> dict[str, object]:
    chunk = AudioChunk(
        chunk_id=f"audio-{sequence + 1:04d}",
        segment_id=segment_id,
        speaker="A",
        source_turn_ids=[f"t-{sequence}"],
        text="متن قطعه",
        sequence=sequence,
        voice_name="Kore",
        content_hash="a" * 64,
        expected_duration_seconds=max(duration or 1, 1),
    )
    record = None
    if duration is not None:
        record = AudioSegmentRecord(
            chunk=chunk,
            wav_ref=f"{chunk.chunk_id}.wav",
            wav_sha256="b" * 64,
            provider="fake",
            model="fake-tts",
            validation=WavValidationReport(
                verdict="pass",
                duration_seconds=duration,
                sample_rate_hz=24_000,
                channels=1,
                sample_width_bytes=2,
                frame_count=int(duration * 24_000),
                peak_ratio=0.5,
            ),
        )
    return {"chunk": chunk, "record": record, "transcript": None, "qa": None}


def _manifest(total: float | None) -> AudioPipelineManifest:
    return AudioPipelineManifest(
        project_id=uuid4(),
        script_hash="c" * 64,
        status="verified",
        chunk_count=1,
        final_duration_seconds=total,
    )


def test_chapter_starts_where_its_first_chunk_starts() -> None:
    project = _project(["seg-1", "seg-2"])
    views = [
        _view("seg-1", 0, 10),
        _view("seg-1", 1, 20),
        _view("seg-2", 2, 30),
    ]
    # Three chunks means two gaps of silence between them.
    total = 60 + 2 * SILENCE

    chapters = _chapters(project, views, _manifest(total), silence_seconds=SILENCE)

    assert [chapter["title"] for chapter in chapters] == ["بخش 1", "بخش 2"]
    assert chapters[0]["start_seconds"] == 0
    # 10s + gap + 20s + gap
    assert chapters[1]["start_seconds"] == pytest.approx(30 + 2 * SILENCE, abs=0.01)
    assert chapters[0]["start_label"] == "0:00"
    assert chapters[1]["start_label"] == "0:30"


def test_offsets_stretch_onto_the_measured_duration() -> None:
    project = _project(["seg-1", "seg-2"])
    views = [_view("seg-1", 0, 100), _view("seg-2", 1, 100)]
    computed = 200 + SILENCE
    # Normalisation re-encoded the file a shade longer than the chunks predict.
    chapters = _chapters(
        project,
        views,
        _manifest(computed * 1.01),
        silence_seconds=SILENCE,
    )

    assert chapters[1]["start_seconds"] == pytest.approx((100 + SILENCE) * 1.01, abs=0.01)


def test_titles_stay_but_times_go_when_the_timeline_cannot_be_trusted() -> None:
    project = _project(["seg-1", "seg-2"])
    trustworthy = [_view("seg-1", 0, 100), _view("seg-2", 1, 100)]

    missing_record = _chapters(
        project,
        [_view("seg-1", 0, 100), _view("seg-2", 1, None)],
        _manifest(200 + SILENCE),
        silence_seconds=SILENCE,
    )
    wrong_total = _chapters(
        project,
        trustworthy,
        _manifest((200 + SILENCE) * 1.5),
        silence_seconds=SILENCE,
    )
    unmeasured = _chapters(project, trustworthy, _manifest(None), silence_seconds=SILENCE)

    for chapters in (missing_record, wrong_total, unmeasured):
        assert [chapter["title"] for chapter in chapters] == ["بخش 1", "بخش 2"]
        assert all(chapter["start_seconds"] is None for chapter in chapters)
        assert all(chapter["start_label"] == "" for chapter in chapters)


def test_no_plan_or_no_audio_means_no_chapter_list() -> None:
    planned = _project(["seg-1"])
    unplanned = Project(raw_input="پرسش آزمون")

    assert _chapters(planned, [], _manifest(10), silence_seconds=SILENCE) == []
    assert (
        _chapters(
            unplanned,
            [_view("seg-1", 0, 10)],
            _manifest(10),
            silence_seconds=SILENCE,
        )
        == []
    )


def test_a_segment_with_no_audio_is_left_out() -> None:
    project = _project(["seg-1", "seg-2", "seg-3"])
    views = [_view("seg-1", 0, 10), _view("seg-3", 1, 10)]

    chapters = _chapters(project, views, _manifest(20 + SILENCE), silence_seconds=SILENCE)

    assert [chapter["title"] for chapter in chapters] == ["بخش 1", "بخش 3"]
