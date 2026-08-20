"""Per-part audio assembly (`10c` P3 Step 9).

Ffmpeg (needed for the streamable-MP3 transcode inside
`AudioArtifactStore.save_part_final_audio`) is not assumed to be installed in
every dev environment, so this exercises `AudioPipelineService._assemble_part_audio`
directly against a recording fake store, rather than the full `run()` pipeline.
"""

from __future__ import annotations

from uuid import uuid4

from thesisound.audio import AudioChunk, pcm_to_wav
from thesisound.domain import EpisodePlan, EpisodeSegment
from thesisound.services.audio_assembler import concatenate_wav
from thesisound.services.audio_pipeline_service import AudioPipelineService
from thesisound.services.audio_validator import AudioValidator


class _FakeAssembler:
    def assemble(self, wav_segments):
        return concatenate_wav(wav_segments, silence_milliseconds=0), "ffmpeg_loudnorm"


class _RecordingAudioStore:
    def __init__(self) -> None:
        self.saved: dict[int, bytes] = {}

    def save_part_final_audio(self, project_id, part_index, wav_bytes):
        del project_id
        self.saved[part_index] = wav_bytes
        return f"audio/parts/{part_index}/final.wav", "sha"


def _chunk(chunk_id: str, segment_id: str, *, sequence: int) -> AudioChunk:
    return AudioChunk(
        chunk_id=chunk_id,
        segment_id=segment_id,
        speaker="A",
        source_turn_ids=[f"{segment_id}-turn-001"],
        text="متن آزمون",
        sequence=sequence,
        voice_name="Kore",
        content_hash="a" * 64,
        expected_duration_seconds=1.0,
    )


def _plan_with_two_parts() -> EpisodePlan:
    return EpisodePlan(
        title="عنوان",
        listener_outcome="فهم",
        estimated_duration_minutes=2.0,
        segments=[
            EpisodeSegment(
                segment_id="seg-001",
                title="بخش ۱",
                purpose="شرح",
                estimated_minutes=1.0,
                claim_ids=["clm-1"],
                key_question="چرا؟",
                speaker_dynamic="explanation",
                part_index=1,
            ),
            EpisodeSegment(
                segment_id="seg-002",
                title="بخش ۲",
                purpose="شرح",
                estimated_minutes=1.0,
                claim_ids=["clm-2"],
                key_question="چگونه؟",
                speaker_dynamic="explanation",
                part_index=2,
            ),
        ],
    )


def _service(audio_store) -> AudioPipelineService:
    return AudioPipelineService(
        workspace_store=None,  # not used by _assemble_part_audio
        script_store=None,  # type: ignore[arg-type]
        audio_store=audio_store,  # type: ignore[arg-type]
        tts=None,  # type: ignore[arg-type]
        asr=None,  # type: ignore[arg-type]
        segmenter=None,  # type: ignore[arg-type]
        validator=AudioValidator(expected_sample_rate_hz=24_000),
        qa=None,  # type: ignore[arg-type]
        assembler=_FakeAssembler(),  # type: ignore[arg-type]
        tts_model="fake-tts",
        asr_model="fake-asr",
        voices={"A": "Kore", "B": "Puck"},
        style_prompts={"A": "", "B": ""},
    )


def _one_second_wav() -> bytes:
    return pcm_to_wav(
        b"\x00\x00" * 24_000, sample_rate_hz=24_000, channels=1, sample_width_bytes=2
    )


def test_chunks_are_regrouped_by_part_and_assembled_separately() -> None:
    plan = _plan_with_two_parts()
    chunks = [_chunk("chunk-1", "seg-001", sequence=0), _chunk("chunk-2", "seg-002", sequence=1)]
    wav_segments = [_one_second_wav(), _one_second_wav()]
    store = _RecordingAudioStore()
    service = _service(store)

    service._assemble_part_audio(uuid4(), plan, chunks, wav_segments)

    assert set(store.saved) == {1, 2}
    assert store.saved[1] != b""
    assert store.saved[2] != b""


def test_a_chunk_with_no_matching_segment_is_skipped_not_a_crash() -> None:
    plan = _plan_with_two_parts()
    chunks = [_chunk("chunk-1", "seg-999", sequence=0)]  # unknown segment_id
    wav_segments = [_one_second_wav()]
    store = _RecordingAudioStore()
    service = _service(store)

    service._assemble_part_audio(uuid4(), plan, chunks, wav_segments)

    assert store.saved == {}
