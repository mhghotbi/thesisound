from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from thesisound.audio import (
    AudioChunk,
    AudioPipelineManifest,
    AudioSegmentRecord,
    WavValidationReport,
    script_hash,
)
from thesisound.config import Settings
from thesisound.domain import (
    EpisodePlan,
    EpisodeSegment,
    Project,
    ProjectState,
    ResearchBrief,
    Script,
    ScriptTurn,
    TopicType,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.services.audio_artifact_store import AudioArtifactStore
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.web.app import create_app

SILENCE_MS = 250


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        ingestion_artifact_root=tmp_path / "artifacts",
        web_session_secret="test-secret-that-is-long-enough",
        allow_test_otp=True,
        test_otp_phone="09120000000",
        test_otp_code="999999",
        otp_resend_cooldown_seconds=5,
        audio_silence_milliseconds=SILENCE_MS,
        ui_demo_mode=False,
    )


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _login(client: TestClient) -> None:
    page = client.get("/login")
    client.post(
        "/login/request-code",
        data={
            "phone": "09120000000",
            "csrf_token": _csrf(page.text),
            "next_path": "/projects",
        },
    )
    page = client.get("/login/verify")
    client.post("/login/verify", data={"code": "999999", "csrf_token": _csrf(page.text)})


def _segment(segment_id: str, title: str) -> EpisodeSegment:
    return EpisodeSegment(
        segment_id=segment_id,
        title=title,
        purpose="شرح موضوع",
        estimated_minutes=1,
        claim_ids=["claim-1"],
        key_question="سؤال؟",
        speaker_dynamic="explanation",
    )


def _seed_complete_episode(settings: Settings, durations: dict[str, float]) -> Project:
    """A finished episode: two chapters, one rendered chunk each."""

    workspace = WorkspaceStore(settings.workspace_root)
    project = Project(
        raw_input="موضوع",
        state=ProjectState.COMPLETE,
        brief=ResearchBrief(
            normalized_topic="موضوع",
            topic_type=TopicType.CONCEPT,
            central_question="سؤال مرکزی چیست؟",
            target_duration_minutes=5,
        ),
        episode_plan=EpisodePlan(
            title="طرح آزمون",
            listener_outcome="فهم موضوع",
            estimated_duration_minutes=5,
            segments=[_segment("seg-1", "بخش اول"), _segment("seg-2", "بخش دوم")],
        ),
    )
    script = Script(
        title="متن آزمون",
        turns=[
            ScriptTurn(
                turn_id=f"{segment_id}-turn-001",
                segment_id=segment_id,
                speaker="A",
                spoken_text_fa="این گزاره به منبع متصل است.",
                claim_ids=["claim-1"],
                evidence_ids=["evidence-1"],
            )
            for segment_id in durations
        ],
    )
    project.script = script
    workspace.save_project(project)

    digest = script_hash(script)
    ScriptArtifactStore(settings.workspace_root).save_script(project.project_id, script)
    audio_store = AudioArtifactStore(settings.workspace_root)
    audio_store.prepare_for_script(project.project_id, digest)

    chunks: list[AudioChunk] = []
    for sequence, (segment_id, duration) in enumerate(durations.items()):
        chunks.append(
            AudioChunk(
                chunk_id=f"audio-{sequence + 1:04d}",
                segment_id=segment_id,
                speaker="A",
                source_turn_ids=[f"{segment_id}-turn-001"],
                text="این گزاره به منبع متصل است.",
                sequence=sequence,
                voice_name="Kore",
                content_hash=hashlib.sha256(segment_id.encode()).hexdigest(),
                expected_duration_seconds=duration,
            )
        )
    audio_store.save_chunks(project.project_id, chunks)

    for chunk in chunks:
        payload = chunk.chunk_id.encode()
        audio_store.save_segment(
            project.project_id,
            AudioSegmentRecord(
                chunk=chunk,
                wav_ref=f"{chunk.chunk_id}.wav",
                wav_sha256=hashlib.sha256(payload).hexdigest(),
                provider="fake",
                model="fake-tts",
                validation=WavValidationReport(
                    verdict="pass",
                    duration_seconds=durations[chunk.segment_id],
                    sample_rate_hz=24_000,
                    channels=1,
                    sample_width_bytes=2,
                    frame_count=24_000,
                    peak_ratio=0.5,
                ),
            ),
            payload,
        )

    audio_store.save_manifest(
        AudioPipelineManifest(
            project_id=project.project_id,
            script_hash=digest,
            status="verified",
            chunk_count=len(chunks),
            passed_chunk_count=len(chunks),
            final_duration_seconds=sum(durations.values()) + (len(chunks) - 1) * SILENCE_MS / 1000,
            normalization="ffmpeg_loudnorm",
        )
    )
    return project


def test_listen_page_lists_chapters_with_seekable_start_times(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    project = _seed_complete_episode(settings, {"seg-1": 62.0, "seg-2": 45.0})

    with TestClient(create_app(settings)) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/audio")

    assert page.status_code == 200
    assert "بخش‌ها" in page.text
    assert "بخش اول" in page.text and "بخش دوم" in page.text
    # First chapter opens the episode; the second starts after 62s plus the 250ms gap.
    assert 'data-seek-to="0.0"' in page.text
    assert 'data-seek-to="62.25"' in page.text
    assert "۱:۰۲" in page.text
    assert "data-episode-audio" in page.text


def test_listen_page_keeps_chapter_titles_when_the_timeline_is_unusable(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    project = _seed_complete_episode(settings, {"seg-1": 62.0, "seg-2": 45.0})
    # A manifest from a different assembly: the chunks cannot place these chapters.
    audio_store = AudioArtifactStore(settings.workspace_root)
    manifest = audio_store.load_manifest_optional(project.project_id)
    assert manifest is not None
    manifest.final_duration_seconds = 600.0
    audio_store.save_manifest(manifest)

    with TestClient(create_app(settings)) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/audio")

    assert page.status_code == 200
    assert "بخش اول" in page.text and "بخش دوم" in page.text
    assert "data-seek-to" not in page.text
    assert "زمان‌بندی قطعه‌ها با فایل نهایی بخواند" in page.text
