from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import Annotated
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.status import HTTP_303_SEE_OTHER

from thesisound.audio import AudioPipelineManifest, script_hash
from thesisound.config import Settings
from thesisound.domain import Project, ProjectState
from thesisound.pipeline import WorkspaceStore
from thesisound.product_metrics import ProductEvent, emit
from thesisound.product_metrics.events import EpisodeAudioDownloaded
from thesisound.services.audio_artifact_store import AudioArtifactStore
from thesisound.services.audio_direction import (
    DEFAULT_ACCENT,
    DEFAULT_PACE,
    DEFAULT_TONE,
    AudioDirectionSettings,
)
from thesisound.services.audio_run import AudioBuildRunService
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.tts_voices import GEMINI_TTS_VOICES
from thesisound.web.error_messages import user_facing_error

Render = Callable[..., HTMLResponse]
LoginRedirect = Callable[[Request], RedirectResponse | None]
ProjectRedirect = Callable[[Request, UUID], RedirectResponse | None]
ValidateCsrf = Callable[[Request, str], None]


def register_audio_routes(
    app: FastAPI,
    *,
    workspace: WorkspaceStore,
    builder: AudioBuildRunService,
    execute: Callable[[UUID], None],
    render: Render,
    login_redirect: LoginRedirect,
    project_redirect: ProjectRedirect,
    validate_csrf: ValidateCsrf,
    settings: Settings,
) -> None:
    audio_store = AudioArtifactStore(workspace.root)
    script_store = ScriptArtifactStore(workspace.root)

    @app.get("/projects/{project_id}/audio", response_class=HTMLResponse)
    def audio_page(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        return _render_audio_page(
            request,
            project_id,
            workspace=workspace,
            builder=builder,
            audio_store=audio_store,
            script_store=script_store,
            render=render,
            settings=settings,
        )

    @app.get("/projects/{project_id}/audio/live", response_class=HTMLResponse)
    def audio_live(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        response = _render_audio_page(
            request,
            project_id,
            workspace=workspace,
            builder=builder,
            audio_store=audio_store,
            script_store=script_store,
            render=render,
            settings=settings,
            template_name="projects/_audio_live.html",
        )
        run = builder.run_store.load_optional(project_id)
        if not (run and run.status in {"queued", "running"}):
            response.headers["HX-Refresh"] = "true"
        return response

    @app.post("/projects/{project_id}/audio/generate")
    def generate_audio(
        request: Request,
        background_tasks: BackgroundTasks,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
        voice_a: Annotated[str, Form()],
        voice_b: Annotated[str, Form()],
        pace: Annotated[str, Form()],
        tone: Annotated[str, Form()],
        accent: Annotated[str, Form()],
        speaker_a_notes: Annotated[str, Form()],
        speaker_b_notes: Annotated[str, Form()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        submitted = {
            "voice_a": voice_a,
            "voice_b": voice_b,
            "pace": pace,
            "tone": tone,
            "accent": accent,
            "speaker_a_notes": speaker_a_notes,
            "speaker_b_notes": speaker_b_notes,
        }
        try:
            validate_csrf(request, csrf_token)
            direction = AudioDirectionSettings(**submitted)
            builder.queue(project_id, direction=direction)
            background_tasks.add_task(execute, project_id)
        except (OSError, RuntimeError, ValueError) as error:
            return _render_audio_page(
                request,
                project_id,
                workspace=workspace,
                builder=builder,
                audio_store=audio_store,
                script_store=script_store,
                render=render,
                settings=settings,
                error=user_facing_error(error, action="audio"),
                values=submitted,
                status_code=422,
            )
        return _audio_redirect(project_id)

    @app.post("/projects/{project_id}/audio/retry")
    def retry_audio(
        request: Request,
        background_tasks: BackgroundTasks,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        try:
            validate_csrf(request, csrf_token)
            builder.retry(project_id)
            background_tasks.add_task(execute, project_id)
        except (OSError, RuntimeError, ValueError) as error:
            return _render_audio_page(
                request,
                project_id,
                workspace=workspace,
                builder=builder,
                audio_store=audio_store,
                script_store=script_store,
                render=render,
                settings=settings,
                error=user_facing_error(error, action="audio"),
                status_code=422,
            )
        return _audio_redirect(project_id)

    @app.get("/projects/{project_id}/audio/final.wav")
    def final_audio(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        project = workspace.load_project(project_id)
        if project.state != ProjectState.COMPLETE:
            return Response(status_code=404)
        try:
            digest = script_hash(script_store.load_latest_script(project_id))
        except FileNotFoundError:
            return Response(status_code=404)
        if not audio_store.has_verified_artifacts(
            project_id,
            script_hash=digest,
            accept_manual_review=builder.accept_manual_review,
        ):
            return Response(status_code=404)
        emit(
            ProductEvent.EPISODE_AUDIO_DOWNLOADED,
            EpisodeAudioDownloaded(format="wav"),
            user_id=getattr(request.state.account, "user_id", None),
            project_id=project_id,
        )
        return FileResponse(
            audio_store.final_audio_path(project_id),
            media_type="audio/wav",
            filename="final.wav",
        )

    @app.get("/projects/{project_id}/audio/final.mp3")
    def final_audio_mp3(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        project = workspace.load_project(project_id)
        if project.state != ProjectState.COMPLETE:
            return Response(status_code=404)
        try:
            digest = script_hash(script_store.load_latest_script(project_id))
        except FileNotFoundError:
            return Response(status_code=404)
        if not audio_store.has_verified_artifacts(
            project_id,
            script_hash=digest,
            accept_manual_review=builder.accept_manual_review,
        ):
            return Response(status_code=404)
        mp3_path = audio_store.final_mp3_path(project_id)
        if not mp3_path.exists():
            try:
                mp3_path = audio_store.write_final_mp3_from_wav(project_id)
            except (OSError, RuntimeError):
                return Response(status_code=404)
        emit(
            ProductEvent.EPISODE_AUDIO_DOWNLOADED,
            EpisodeAudioDownloaded(format="mp3"),
            user_id=getattr(request.state.account, "user_id", None),
            project_id=project_id,
        )
        return FileResponse(
            mp3_path,
            media_type="audio/mpeg",
            filename="final.mp3",
        )

    @app.get("/projects/{project_id}/audio/segments/{chunk_id}.wav")
    def segment_audio(request: Request, project_id: UUID, chunk_id: str) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        if not chunk_id.startswith("audio-") or not chunk_id[6:].isdigit():
            return Response(status_code=404)
        try:
            digest = script_hash(script_store.load_latest_script(project_id))
            chunks = audio_store.load_chunks(project_id)
        except (FileNotFoundError, ValueError):
            return Response(status_code=404)
        if not audio_store.artifacts_match_script(project_id, digest):
            return Response(status_code=404)
        chunk = next((item for item in chunks if item.chunk_id == chunk_id), None)
        if chunk is None:
            return Response(status_code=404)
        segment = audio_store.load_segment_optional(
            project_id,
            chunk.chunk_id,
            chunk.content_hash,
        )
        if segment is None:
            return Response(status_code=404)
        return FileResponse(
            audio_store.segment_wav_path(project_id, chunk_id),
            media_type="audio/wav",
        )


def _render_audio_page(
    request: Request,
    project_id: UUID,
    *,
    workspace: WorkspaceStore,
    builder: AudioBuildRunService,
    audio_store: AudioArtifactStore,
    script_store: ScriptArtifactStore,
    render: Render,
    settings: Settings,
    values: dict[str, str] | None = None,
    error: str | None = None,
    status_code: int = 200,
    template_name: str = "projects/audio.html",
) -> HTMLResponse:
    project = workspace.load_project(project_id)
    stored_run = builder.run_store.load_optional(project_id)
    manifest = audio_store.load_manifest_optional(project_id)
    chunks = audio_store.load_chunks_optional(project_id) or []
    script_digest = None
    with suppress(FileNotFoundError):
        script_digest = script_hash(script_store.load_latest_script(project_id))
    current = bool(
        script_digest and audio_store.artifacts_match_script(project_id, script_digest)
    )
    run = (
        stored_run
        if stored_run is not None
        and stored_run.verified_script_hash == script_digest
        else None
    )
    segment_views: list[dict[str, object]] = []
    if current:
        for chunk in chunks:
            segment = audio_store.load_segment_optional(
                project_id,
                chunk.chunk_id,
                chunk.content_hash,
            )
            record = segment[0] if segment else None
            transcript = None
            qa = None
            if record is not None:
                transcript = audio_store.load_transcript_optional(
                    project_id,
                    chunk.chunk_id,
                    chunk.content_hash,
                    record.wav_sha256,
                )
                qa = audio_store.load_qa_optional(
                    project_id,
                    chunk.chunk_id,
                    chunk.content_hash,
                    record.wav_sha256,
                )
            segment_views.append(
                {
                    "chunk": chunk,
                    "record": record,
                    "transcript": transcript,
                    "qa": qa,
                }
            )
    defaults = {
        "voice_a": settings.tts_voice_a,
        "voice_b": settings.tts_voice_b,
        "pace": DEFAULT_PACE,
        "tone": DEFAULT_TONE,
        "accent": DEFAULT_ACCENT,
        "speaker_a_notes": "",
        "speaker_b_notes": "",
    }
    chapters = _chapters(
        project,
        segment_views,
        manifest if current else None,
        silence_seconds=settings.audio_silence_milliseconds / 1000,
    )
    return render(
        request,
        template_name,
        {
            "project": project,
            "audio_run": run,
            "audio_active": bool(run and run.status in {"queued", "running"}),
            "audio_attempt": len(builder.run_store.load_history(project_id)),
            "manifest": manifest if current else None,
            "segment_views": segment_views,
            "chapters": chapters,
            "can_generate": project.state == ProjectState.SCRIPT_VERIFIED,
            "can_retry": bool(
                run
                and run.status == "failed"
                and project.state == ProjectState.FAILED_RETRYABLE
            ),
            "voices": GEMINI_TTS_VOICES,
            "selected": values or defaults,
            "error": error,
        },
        status_code=status_code,
    )


def _audio_redirect(project_id: UUID) -> RedirectResponse:
    return RedirectResponse(
        f"/projects/{project_id}/audio",
        status_code=HTTP_303_SEE_OTHER,
    )


# The final file is the chunks concatenated in order with a fixed silence between each,
# so a chapter starts where its segment's first chunk starts. Every duration below is
# measured from a rendered WAV; nothing here is estimated.
def _chapters(
    project: Project,
    segment_views: list[dict[str, object]],
    manifest: AudioPipelineManifest | None,
    *,
    silence_seconds: float,
) -> list[dict[str, object]]:
    if project.episode_plan is None or not segment_views:
        return []

    starts: dict[str, float] = {}
    elapsed = 0.0
    for index, view in enumerate(segment_views):
        chunk = view["chunk"]
        record = view["record"]
        if record is None:
            # One unrendered chunk and every later offset is guesswork.
            return _chapters_without_times(project)
        if index:
            elapsed += silence_seconds
        starts.setdefault(chunk.segment_id, elapsed)
        elapsed += record.validation.duration_seconds

    measured = manifest.final_duration_seconds if manifest else None
    if not measured or elapsed <= 0:
        return _chapters_without_times(project)
    # Normalisation re-encodes the concatenated file, so allow it to shift the total by
    # a hair and stretch the offsets onto the real timeline. A wider gap means these
    # chunks did not produce this file, and guessed timestamps are worse than none.
    drift = abs(measured - elapsed) / elapsed
    if drift > 0.02:
        return _chapters_without_times(project)
    scale = measured / elapsed

    chapters: list[dict[str, object]] = []
    for segment in project.episode_plan.segments:
        if segment.segment_id not in starts:
            continue
        start = starts[segment.segment_id] * scale
        chapters.append(
            {
                "title": segment.title,
                "start_seconds": round(start, 2),
                "start_label": _timestamp(start),
            }
        )
    return chapters


def _chapters_without_times(project: Project) -> list[dict[str, object]]:
    if project.episode_plan is None:
        return []
    return [
        {"title": segment.title, "start_seconds": None, "start_label": ""}
        for segment in project.episode_plan.segments
    ]


def _timestamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"
