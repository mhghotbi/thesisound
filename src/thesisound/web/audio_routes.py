from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import Annotated
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.status import HTTP_303_SEE_OTHER

from thesisound.audio import script_hash
from thesisound.domain import ProjectState
from thesisound.pipeline import WorkspaceStore
from thesisound.services.audio_artifact_store import AudioArtifactStore
from thesisound.services.audio_run import AudioBuildRunService
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.web.error_messages import user_facing_error

Render = Callable[..., HTMLResponse]
LoginRedirect = Callable[[Request], RedirectResponse | None]
ValidateCsrf = Callable[[Request, str], None]


def register_audio_routes(
    app: FastAPI,
    *,
    workspace: WorkspaceStore,
    builder: AudioBuildRunService,
    execute: Callable[[UUID], None],
    render: Render,
    login_redirect: LoginRedirect,
    validate_csrf: ValidateCsrf,
) -> None:
    audio_store = AudioArtifactStore(workspace.root)
    script_store = ScriptArtifactStore(workspace.root)

    @app.get("/projects/{project_id}/audio", response_class=HTMLResponse)
    def audio_page(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        return _render_audio_page(
            request,
            project_id,
            workspace=workspace,
            builder=builder,
            audio_store=audio_store,
            script_store=script_store,
            render=render,
        )

    @app.post("/projects/{project_id}/audio/generate")
    def generate_audio(
        request: Request,
        background_tasks: BackgroundTasks,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        try:
            validate_csrf(request, csrf_token)
            builder.queue(project_id)
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
                error=user_facing_error(error, action="audio"),
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
                error=user_facing_error(error, action="audio"),
                status_code=422,
            )
        return _audio_redirect(project_id)

    @app.get("/projects/{project_id}/audio/final.wav")
    def final_audio(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        project = workspace.load_project(project_id)
        if project.state != ProjectState.COMPLETE:
            return Response(status_code=404)
        try:
            digest = script_hash(script_store.load_latest_script(project_id))
        except FileNotFoundError:
            return Response(status_code=404)
        if not audio_store.has_verified_artifacts(project_id, script_hash=digest):
            return Response(status_code=404)
        return FileResponse(audio_store.final_audio_path(project_id), media_type="audio/wav")

    @app.get("/projects/{project_id}/audio/segments/{chunk_id}.wav")
    def segment_audio(request: Request, project_id: UUID, chunk_id: str) -> Response:
        if redirect := login_redirect(request):
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
    error: str | None = None,
    status_code: int = 200,
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
    return render(
        request,
        "projects/audio.html",
        {
            "project": project,
            "audio_run": run,
            "audio_active": bool(run and run.status in {"queued", "running"}),
            "manifest": manifest if current else None,
            "segment_views": segment_views,
            "can_generate": project.state == ProjectState.SCRIPT_VERIFIED,
            "can_retry": bool(
                run
                and run.status == "failed"
                and project.state == ProjectState.FAILED_RETRYABLE
            ),
            "error": error,
        },
        status_code=status_code,
    )


def _audio_redirect(project_id: UUID) -> RedirectResponse:
    return RedirectResponse(
        f"/projects/{project_id}/audio",
        status_code=HTTP_303_SEE_OTHER,
    )
