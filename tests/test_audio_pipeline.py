from pathlib import Path

import pytest

from thesisound import tracing
from thesisound.audio import AsrTranscript
from thesisound.audio_ports import TtsRequest, TtsResponse
from thesisound.domain import Project, ProjectState, Script, ScriptTurn
from thesisound.pipeline import WorkspaceStore
from thesisound.services.audio_artifact_store import AudioArtifactStore
from thesisound.services.audio_assembler import concatenate_wav
from thesisound.services.audio_pipeline_service import AudioPipelineService
from thesisound.services.audio_qa import AudioQaService
from thesisound.services.audio_validator import AudioValidator
from thesisound.services.tts_segmenter import TtsSegmenter


class FakeScriptStore:
    def __init__(self, script: Script) -> None:
        self.script = script

    def load_latest_script(self, project_id):
        del project_id
        return self.script

    def has_verified_artifacts(self, project_id):
        del project_id
        return True


class FakeTts:
    def __init__(self) -> None:
        self.calls: list[TtsRequest] = []

    def synthesize(self, request: TtsRequest) -> TtsResponse:
        self.calls.append(request)
        return TtsResponse(
            pcm_bytes=b"\x00\x00" * 48_000,
            provider="fake",
            model=request.model,
        )


class FakeAsr:
    def __init__(self, expected: str, *, fail_first: bool = False) -> None:
        self.expected = expected
        self.fail_first = fail_first
        self.calls = 0

    def transcribe(
        self,
        *,
        chunk_id,
        chunk_hash,
        wav_sha256,
        wav_bytes,
        model,
        expected_speaker,
        language="fa",
    ):
        del wav_bytes, language
        self.calls += 1
        text = "متن ناقص" if self.fail_first and self.calls == 1 else self.expected
        return AsrTranscript(
            chunk_id=chunk_id,
            chunk_hash=chunk_hash,
            wav_sha256=wav_sha256,
            text=text,
            speaker=expected_speaker,
            provider="fake",
            model=model,
        )


class FakeAssembler:
    def assemble(self, wav_segments):
        return concatenate_wav(wav_segments, silence_milliseconds=0), "ffmpeg_loudnorm"


def _script() -> Script:
    return Script(
        title="آزمون صوت",
        turns=[
            ScriptTurn(
                turn_id="turn-1",
                segment_id="seg-1",
                speaker="A",
                spoken_text_fa="این یک متن کامل و روشن برای آزمون تولید صوت است.",
                claim_ids=["claim-1"],
                evidence_ids=["evidence-1"],
            )
        ],
    )


def _service(tmp_path: Path, *, fail_first: bool = False):
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(raw_input="topic", state=ProjectState.SCRIPT_VERIFIED, script=_script())
    workspace.save_project(project)
    tts = FakeTts()
    asr = FakeAsr(_script().turns[0].spoken_text_fa, fail_first=fail_first)
    audio_store = AudioArtifactStore(workspace.root)
    service = AudioPipelineService(
        workspace_store=workspace,
        script_store=FakeScriptStore(_script()),  # type: ignore[arg-type]
        audio_store=audio_store,
        tts=tts,
        asr=asr,
        segmenter=TtsSegmenter(max_characters=900, words_per_minute=135),
        validator=AudioValidator(expected_sample_rate_hz=24_000),
        qa=AudioQaService(),
        assembler=FakeAssembler(),  # type: ignore[arg-type]
        tts_model="fake-tts",
        asr_model="fake-asr",
        voices={"A": "Kore", "B": "Puck"},
        style_prompts={"A": "طبیعی و دقیق بخوان", "B": "طبیعی و دقیق بخوان"},
        max_regeneration_attempts=1,
    )
    return workspace, project, service, audio_store, tts, asr


def test_audio_pipeline_reaches_complete_with_verified_artifacts(tmp_path: Path) -> None:
    workspace, project, service, store, tts, asr = _service(tmp_path)

    manifest = service.run(project.project_id)

    assert manifest.status == "verified"
    assert manifest.passed_chunk_count == manifest.chunk_count == 1
    assert workspace.load_project(project.project_id).state == ProjectState.COMPLETE
    assert store.has_verified_artifacts(project.project_id, script_hash=manifest.script_hash)
    assert len(tts.calls) == 1
    assert tts.calls[0].style_prompt == "طبیعی و دقیق بخوان"
    assert asr.calls == 1


def test_audio_pipeline_regenerates_only_failed_chunk_once(tmp_path: Path) -> None:
    workspace, project, service, _, tts, asr = _service(tmp_path, fail_first=True)

    manifest = service.run(project.project_id)

    assert workspace.load_project(project.project_id).state == ProjectState.COMPLETE
    assert manifest.regenerated_chunk_ids == ["audio-0001"]
    assert len(tts.calls) == 2
    assert asr.calls == 2


def _run_tolerating_missing_ffmpeg(service, project_id) -> None:
    """Segmenting/synthesizing/transcribing are pure Python; only the final
    assembly step needs a real ffmpeg binary (see write_final_mp3_from_wav in
    audio_artifact_store.py). Tests that only care about the earlier stages
    run this instead of service.run() directly so they pass whether or not
    ffmpeg happens to be installed on the machine running them -- the two
    tests above already carry this exact, pre-existing environment
    dependency for the happy path this helper does not need to assert on.
    """

    try:
        service.run(project_id)
    except RuntimeError as exc:
        if "FFmpeg" not in str(exc):
            raise


def test_pipeline_stages_produce_spans_with_useful_measurements(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    workspace, project, service, store, tts, asr = _service(tmp_path)

    _run_tolerating_missing_ffmpeg(service, project.project_id)

    segmenting = recording_tracer.sink.one("audio.segmenting")
    assert segmenting.metrics["chunk_count"] == 1
    synthesizing = recording_tracer.sink.one("audio.synthesizing")
    assert synthesizing.metrics == {"chunk_count": 1, "synthesized_count": 1}
    transcribing = recording_tracer.sink.one("audio.transcribing")
    assert transcribing.metrics == {"chunk_count": 1, "regenerated_count": 0}
    assert recording_tracer.sink.find("audio.regenerating") == []


def test_regeneration_produces_a_nested_verbose_span_per_chunk(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    recording_tracer.detail = "verbose"  # audio.regenerating is per-chunk, verbose-gated
    workspace, project, service, _, tts, asr = _service(tmp_path, fail_first=True)

    _run_tolerating_missing_ffmpeg(service, project.project_id)

    transcribing = recording_tracer.sink.one("audio.transcribing")
    assert transcribing.metrics == {"chunk_count": 1, "regenerated_count": 1}
    regeneration = recording_tracer.sink.one("audio.regenerating")
    assert regeneration.subject_id == "audio-0001"
    assert regeneration.parent_span_id == transcribing.context.span_id
    assert regeneration.status == "ok"


class _FailingAssembler:
    """Raises inside assemble() itself, before the real ffmpeg-dependent
    save_final_audio() is ever reached -- so unlike the tests above, this one
    exercises a genuine assembly failure regardless of whether ffmpeg happens
    to be installed on the machine running it."""

    def assemble(self, wav_segments):
        raise RuntimeError("synthetic assembly failure")


def test_assembly_failure_marks_only_the_assembling_span_as_error(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    workspace, project, service, _, tts, asr = _service(tmp_path)
    service.assembler = _FailingAssembler()  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="synthetic assembly failure"):
        service.run(project.project_id)

    assert recording_tracer.sink.one("audio.segmenting").status == "ok"
    assert recording_tracer.sink.one("audio.synthesizing").status == "ok"
    assert recording_tracer.sink.one("audio.transcribing").status == "ok"
    assert recording_tracer.sink.one("audio.assembling").status == "error"
    assert asr.calls == 1
