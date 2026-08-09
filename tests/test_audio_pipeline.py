from pathlib import Path

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
