from uuid import uuid4

from thesisound.audio import AsrTranscript, AudioSegmentQa
from thesisound.services.audio_artifact_store import AudioArtifactStore


def test_asr_and_qa_require_the_exact_wav_checksum(tmp_path) -> None:
    store = AudioArtifactStore(tmp_path / "workspaces")
    project_id = uuid4()
    transcript = AsrTranscript(
        chunk_id="audio-0001",
        chunk_hash="a" * 64,
        wav_sha256="b" * 64,
        text="متن رونویسی‌شده",
        speaker="A",
        provider="fake",
        model="fake-asr",
    )
    qa = AudioSegmentQa(
        chunk_id="audio-0001",
        chunk_hash="a" * 64,
        wav_sha256="b" * 64,
        verdict="pass",
        similarity_ratio=1,
        expected_text="متن رونویسی‌شده",
        transcript_text="متن رونویسی‌شده",
    )
    store.save_transcript(project_id, transcript)
    store.save_qa(project_id, qa)

    assert (
        store.load_transcript_optional(
            project_id,
            "audio-0001",
            "a" * 64,
            "b" * 64,
        )
        == transcript
    )
    assert (
        store.load_qa_optional(
            project_id,
            "audio-0001",
            "a" * 64,
            "b" * 64,
        )
        == qa
    )
    assert (
        store.load_transcript_optional(
            project_id,
            "audio-0001",
            "a" * 64,
            "c" * 64,
        )
        is None
    )
    assert (
        store.load_qa_optional(
            project_id,
            "audio-0001",
            "a" * 64,
            "c" * 64,
        )
        is None
    )
