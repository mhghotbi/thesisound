from __future__ import annotations

import shutil
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.status import HTTP_303_SEE_OTHER

from thesisound.config import Settings
from thesisound.domain import (
    Project,
    ProjectState,
    SourceAccess,
    SourceCandidate,
    SourceDecision,
    SourceRole,
)
from thesisound.pipeline import WorkspaceStore, transition
from thesisound.services.corpus_building import CorpusBuildingService, CorpusBuildRun
from thesisound.services.episode_planning_run import (
    EpisodePlanningRun,
    EpisodePlanningRunService,
)
from thesisound.services.runtime_preflight import RuntimePreflight
from thesisound.services.workflow_revision import WorkflowRevisionService
from thesisound.web.corpus_runtime import corpus_source_inputs
from thesisound.web.source_discovery import (
    WebSourceCandidate,
    WebSourceCandidateStore,
    WebSourceDiscoveryService,
)
from thesisound.web.source_ingestion import ingest_uploaded_source
from thesisound.web.source_manifest import (
    UiSourceManifest,
    UiSourceManifestStore,
    UiSourceStatus,
)

Render = Callable[..., HTMLResponse]
LoginRedirect = Callable[[Request], RedirectResponse | None]
ValidateCsrf = Callable[[Request, str], None]

_SUPPORTED_UPLOAD_SUFFIXES = {".pdf", ".epub", ".docx", ".txt", ".md"}
_EDITABLE_SOURCE_STATES = {
    ProjectState.SOURCES_COLLECTING,
    ProjectState.SOURCE_SELECTION_REQUIRED,
}


def register_source_routes(
    app: FastAPI,
    *,
    settings: Settings,
    workspace: WorkspaceStore,
    corpus_builder: CorpusBuildingService,
    episode_planner: EpisodePlanningRunService,
    execute_corpus: Callable[[UUID], None],
    render: Render,
    login_redirect: LoginRedirect,
    validate_csrf: ValidateCsrf,
) -> None:
    discovery = WebSourceDiscoveryService(settings, workspace)
    revision = WorkflowRevisionService(workspace)

    def source_context(
        project: Project,
        sources: list[UiSourceManifest],
        *,
        error: str | None = None,
    ) -> dict[str, object]:
        candidates = WebSourceCandidateStore(workspace.project_dir(project.project_id)).load()
        return {
            "project": project,
            "sources": sources,
            "search_candidates": candidates,
            "search_query": (
                project.brief.central_question if project.brief is not None else project.raw_input
            ),
            "selected_count": sum(source.selected for source in sources),
            "selection_locked": project.state not in _EDITABLE_SOURCE_STATES,
            "error": error,
        }

    @app.get("/projects/{project_id}/sources", response_class=HTMLResponse)
    def sources_page(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        project = workspace.load_project(project_id)
        if project.state == ProjectState.BRIEF_READY:
            return RedirectResponse(
                f"/projects/{project_id}/brief",
                status_code=HTTP_303_SEE_OTHER,
            )
        sources = UiSourceManifestStore(workspace.project_dir(project_id)).load()
        return render(
            request,
            "projects/sources.html",
            source_context(project, sources),
        )

    @app.post("/projects/{project_id}/sources/upload", response_class=HTMLResponse)
    async def upload_source(
        request: Request,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
        source_file: Annotated[UploadFile, File()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        project = workspace.load_project(project_id)
        validate_csrf(request, csrf_token)

        if project.state == ProjectState.SOURCE_SELECTION_REQUIRED:
            transition(project, ProjectState.SOURCES_COLLECTING)
        if project.state != ProjectState.SOURCES_COLLECTING:
            return _source_redirect(project_id, error="selection-locked")

        filename = _safe_filename(source_file.filename or "source")
        source_id = uuid4()
        suffix = Path(filename).suffix.lower()
        upload_root = workspace.project_dir(project_id) / "uploads" / str(source_id)
        upload_root.mkdir(parents=True, exist_ok=True)
        destination = upload_root / filename

        size = 0
        with destination.open("wb") as output:
            while chunk := await source_file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.web_upload_limit_bytes:
                    output.close()
                    destination.unlink(missing_ok=True)
                    return _source_redirect(project_id, error="file-too-large")
                output.write(chunk)

        if suffix not in _SUPPORTED_UPLOAD_SUFFIXES:
            manifest = UiSourceManifest(
                source_id=source_id,
                filename=filename,
                content_type=source_file.content_type,
                size_bytes=size,
                status=UiSourceStatus.BLOCKED,
                issue_summary="نوع فایل در این نسخه پشتیبانی نمی‌شود.",
            )
        else:
            artifact_root = (
                settings.ensure_ingestion_artifact_root() / str(project_id) / str(source_id)
            )
            manifest = await run_in_threadpool(
                partial(
                    ingest_uploaded_source,
                    destination,
                    source_id=source_id,
                    filename=filename,
                    content_type=source_file.content_type,
                    size_bytes=size,
                    settings=settings,
                    artifact_root=artifact_root,
                )
            )

        manifest_store = UiSourceManifestStore(workspace.project_dir(project_id))
        manifest_store.add(manifest)
        sources = manifest_store.load()
        if project.state == ProjectState.SOURCES_COLLECTING and any(
            source.status == UiSourceStatus.READY for source in sources
        ):
            transition(project, ProjectState.SOURCE_SELECTION_REQUIRED)
        workspace.save_project(project)
        return _source_redirect(project_id)

    @app.post("/projects/{project_id}/sources/search", response_class=HTMLResponse)
    async def search_sources(
        request: Request,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
        query: Annotated[str, Form()] = "",
        mode: Annotated[str, Form()] = "preview",
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        validate_csrf(request, csrf_token)
        project = workspace.load_project(project_id)
        if project.state not in _EDITABLE_SOURCE_STATES:
            return _source_redirect(project_id, error="selection-locked")
        try:
            RuntimePreflight(settings).require("model")
        except RuntimeError:
            return RedirectResponse(
                "/system-check?blocked=1&scope=model",
                status_code=HTTP_303_SEE_OTHER,
            )

        manifest_store = UiSourceManifestStore(workspace.project_dir(project_id))
        candidate_store = WebSourceCandidateStore(workspace.project_dir(project_id))
        try:
            candidates = await run_in_threadpool(discovery.search, project, query)
            candidate_store.replace_results(candidates)
            if mode == "auto":
                await _auto_import_candidates(
                    project_id=project_id,
                    candidates=candidates,
                    discovery=discovery,
                    candidate_store=candidate_store,
                    manifest_store=manifest_store,
                )
                sources = manifest_store.load()
                if project.state == ProjectState.SOURCES_COLLECTING and any(
                    source.status == UiSourceStatus.READY for source in sources
                ):
                    transition(project, ProjectState.SOURCE_SELECTION_REQUIRED)
                    workspace.save_project(project)
        except (OSError, RuntimeError, ValueError) as error:
            sources = manifest_store.load()
            return render(
                request,
                "projects/sources.html",
                source_context(
                    project,
                    sources,
                    error=(
                        "جست‌وجوی وب یا بازیابی منبع انجام نشد. تنظیمات Gemini و "
                        f"اتصال را بررسی کنید. جزئیات: {str(error)[:300]}"
                    ),
                ),
                status_code=422,
            )
        suffix = "?auto-search=1" if mode == "auto" else "?searched=1"
        return RedirectResponse(
            f"/projects/{project_id}/sources{suffix}",
            status_code=HTTP_303_SEE_OTHER,
        )

    @app.post(
        "/projects/{project_id}/sources/web/{candidate_id}/add",
        response_class=HTMLResponse,
    )
    async def add_web_source(
        request: Request,
        project_id: UUID,
        candidate_id: UUID,
        csrf_token: Annotated[str, Form()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        validate_csrf(request, csrf_token)
        project = workspace.load_project(project_id)
        if project.state not in _EDITABLE_SOURCE_STATES:
            return _source_redirect(project_id, error="selection-locked")
        try:
            RuntimePreflight(settings).require("model")
        except RuntimeError:
            return RedirectResponse(
                "/system-check?blocked=1&scope=model",
                status_code=HTTP_303_SEE_OTHER,
            )

        candidate_store = WebSourceCandidateStore(workspace.project_dir(project_id))
        manifest_store = UiSourceManifestStore(workspace.project_dir(project_id))
        try:
            candidate = candidate_store.get(candidate_id)
            existing = _source_for_url(manifest_store.load(), str(candidate.url))
            if existing is None:
                manifest = await run_in_threadpool(
                    discovery.import_candidate,
                    project_id,
                    candidate,
                )
                manifest_store.add(manifest)
            else:
                manifest = existing
            candidate.status = "added" if manifest.status == UiSourceStatus.READY else "failed"
            candidate.source_id = manifest.source_id
            candidate.issue_summary = manifest.issue_summary
            candidate_store.replace(candidate)
            if (
                project.state == ProjectState.SOURCES_COLLECTING
                and manifest.status == UiSourceStatus.READY
            ):
                transition(project, ProjectState.SOURCE_SELECTION_REQUIRED)
                workspace.save_project(project)
        except (OSError, RuntimeError, ValueError, FileNotFoundError) as error:
            return render(
                request,
                "projects/sources.html",
                source_context(
                    project,
                    manifest_store.load(),
                    error=(
                        f"بازیابی این منبع کامل نشد و وارد شاهدها نشد. جزئیات: {str(error)[:300]}"
                    ),
                ),
                status_code=422,
            )
        return _source_redirect(project_id)

    @app.post("/projects/{project_id}/sources/{source_id}/retry")
    async def retry_source_ingestion(
        request: Request,
        project_id: UUID,
        source_id: UUID,
        csrf_token: Annotated[str, Form()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        try:
            validate_csrf(request, csrf_token)
            project = workspace.load_project(project_id)
            if project.state not in _EDITABLE_SOURCE_STATES:
                raise ValueError("Source selection is locked")
            store = UiSourceManifestStore(workspace.project_dir(project_id))
            source = store.get(source_id)
            upload = _uploaded_source_path(workspace, project_id, source)
            if not upload.is_file():
                raise FileNotFoundError("Original upload is missing")
            artifact_root = (
                settings.ensure_ingestion_artifact_root() / str(project_id) / str(source_id)
            )
            reparsed = await run_in_threadpool(
                partial(
                    ingest_uploaded_source,
                    upload,
                    source_id=source_id,
                    filename=source.filename,
                    content_type=source.content_type,
                    size_bytes=source.size_bytes,
                    settings=settings,
                    artifact_root=artifact_root,
                )
            )
            reparsed.display_title = source.display_title
            reparsed.origin = source.origin
            reparsed.canonical_url = source.canonical_url
            reparsed.retrieval_scope = source.retrieval_scope
            reparsed.quality_issues = [
                *reparsed.quality_issues,
                *source.quality_issues,
            ]
            if source.origin == "gemini_web_search" and source.retrieval_scope != "full_text":
                reparsed.status = UiSourceStatus.REVIEW
                reparsed.safe_for_claim_extraction = False
            reparsed.selected = source.selected and reparsed.status == UiSourceStatus.READY
            store.replace(reparsed)
            sources = store.load()
            has_ready_source = any(item.status == UiSourceStatus.READY for item in sources)
            if project.state == ProjectState.SOURCES_COLLECTING and has_ready_source:
                transition(project, ProjectState.SOURCE_SELECTION_REQUIRED)
            elif project.state == ProjectState.SOURCE_SELECTION_REQUIRED and not has_ready_source:
                transition(project, ProjectState.SOURCES_COLLECTING)
            workspace.save_project(project)
        except (OSError, RuntimeError, ValueError):
            return _source_redirect(project_id, error="source-retry-failed")
        return _source_redirect(project_id)

    @app.post("/projects/{project_id}/sources/{source_id}/delete")
    def delete_source(
        request: Request,
        project_id: UUID,
        source_id: UUID,
        csrf_token: Annotated[str, Form()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        try:
            validate_csrf(request, csrf_token)
            project = workspace.load_project(project_id)
            if project.state not in _EDITABLE_SOURCE_STATES:
                raise ValueError("Source selection is locked")
            store = UiSourceManifestStore(workspace.project_dir(project_id))
            store.remove(source_id)
            shutil.rmtree(
                workspace.project_dir(project_id) / "uploads" / str(source_id),
                ignore_errors=True,
            )
            shutil.rmtree(
                workspace.project_dir(project_id) / "uploads" / "web" / str(source_id),
                ignore_errors=True,
            )
            shutil.rmtree(
                settings.ensure_ingestion_artifact_root() / str(project_id) / str(source_id),
                ignore_errors=True,
            )
            sources = store.load()
            if project.state == ProjectState.SOURCE_SELECTION_REQUIRED and not any(
                item.status == UiSourceStatus.READY for item in sources
            ):
                transition(project, ProjectState.SOURCES_COLLECTING)
            workspace.save_project(project)
        except (OSError, ValueError):
            return _source_redirect(project_id, error="source-delete-failed")
        return _source_redirect(project_id)

    @app.post("/projects/{project_id}/sources/{source_id}/toggle")
    def toggle_source(
        request: Request,
        project_id: UUID,
        source_id: UUID,
        csrf_token: Annotated[str, Form()],
    ) -> RedirectResponse:
        if redirect := login_redirect(request):
            return redirect
        validate_csrf(request, csrf_token)
        project = workspace.load_project(project_id)
        if project.state not in _EDITABLE_SOURCE_STATES:
            return _source_redirect(project_id, error="selection-locked")
        UiSourceManifestStore(workspace.project_dir(project_id)).toggle(source_id)
        return _source_redirect(project_id)

    @app.post("/projects/{project_id}/workflow/rewind")
    def rewind_workflow(
        request: Request,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
        target: Annotated[str, Form()],
        reason: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        if redirect := login_redirect(request):
            return redirect
        validate_csrf(request, csrf_token)
        destination = "brief" if target == "brief" else "sources"
        try:
            if target not in {"brief", "sources"}:
                raise ValueError("مرحله مقصد معتبر نیست.")
            actor = str(request.session.get("user_phone") or "unknown")
            revision.rewind(
                project_id,
                target=target,
                actor=actor,
                reason=reason,
            )
        except (OSError, ValueError) as error:
            return RedirectResponse(
                f"/projects/{project_id}/{destination}?workflow_error="
                + quote(str(error), safe=""),
                status_code=HTTP_303_SEE_OTHER,
            )
        return RedirectResponse(
            f"/projects/{project_id}/{destination}?rewound=1",
            status_code=HTTP_303_SEE_OTHER,
        )

    @app.post("/projects/{project_id}/corpus/confirm", response_class=HTMLResponse)
    def confirm_corpus(
        request: Request,
        background_tasks: BackgroundTasks,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        original_project = workspace.load_project(project_id)
        project = original_project.model_copy(deep=True)
        manifest_store = UiSourceManifestStore(workspace.project_dir(project_id))
        sources = manifest_store.load()
        try:
            validate_csrf(request, csrf_token)
            if project.state not in _EDITABLE_SOURCE_STATES:
                raise ValueError("انتخاب منابع برای این گفتار قفل شده است.")
            selected = [
                source
                for source in sources
                if source.selected and source.status == UiSourceStatus.READY
            ]
            if not selected:
                raise ValueError(
                    "حداقل یک منبع آماده را انتخاب کنید یا جست‌وجوی خودکار وب را اجرا کنید."
                )
            if any(not source.safe_for_claim_extraction for source in selected):
                raise ValueError("همه منابع انتخاب‌شده باید از کنترل کیفیت عبور کرده باشند.")
            inputs = corpus_source_inputs(settings, project_id, selected)

            project.sources = [_source_candidate(source) for source in selected]
            if project.state == ProjectState.SOURCES_COLLECTING:
                transition(project, ProjectState.SOURCE_SELECTION_REQUIRED)
            transition(project, ProjectState.CORPUS_BUILDING)
            corpus_builder.confirm_project(original_project, project, inputs)
            background_tasks.add_task(execute_corpus, project_id)
        except (OSError, RuntimeError, ValueError) as error:
            current = workspace.load_project(project_id)
            return render(
                request,
                "projects/sources.html",
                source_context(current, sources, error=str(error)),
                status_code=422,
            )
        return RedirectResponse(
            f"/projects/{project_id}/processing",
            status_code=HTTP_303_SEE_OTHER,
        )

    @app.post("/projects/{project_id}/corpus/retry")
    def retry_corpus(
        request: Request,
        background_tasks: BackgroundTasks,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
    ) -> RedirectResponse:
        if redirect := login_redirect(request):
            return redirect
        try:
            validate_csrf(request, csrf_token)
            corpus_builder.retry(project_id)
            background_tasks.add_task(execute_corpus, project_id)
        except ValueError:
            return RedirectResponse(
                f"/projects/{project_id}/processing?error=retry-unavailable",
                status_code=HTTP_303_SEE_OTHER,
            )
        return RedirectResponse(
            f"/projects/{project_id}/processing",
            status_code=HTTP_303_SEE_OTHER,
        )

    @app.get("/projects/{project_id}/processing", response_class=HTMLResponse)
    def processing_page(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        project = workspace.load_project(project_id)
        corpus_run = corpus_builder.run_store.load_optional(project_id)
        planning_run = episode_planner.run_store.load_optional(project_id)
        stages = _project_stages(project.state, corpus_run, planning_run)
        return render(
            request,
            "projects/processing.html",
            {
                "project": project,
                "stages": stages,
                "corpus_run": corpus_run,
                "corpus_active": bool(corpus_run and corpus_run.status in {"queued", "running"}),
                "planning_run": planning_run,
                "planning_active": bool(
                    planning_run and planning_run.status in {"queued", "running"}
                ),
            },
        )


async def _auto_import_candidates(
    *,
    project_id: UUID,
    candidates: list[WebSourceCandidate],
    discovery: WebSourceDiscoveryService,
    candidate_store: WebSourceCandidateStore,
    manifest_store: UiSourceManifestStore,
    target_ready_count: int = 3,
) -> None:
    ready_count = 0
    existing_sources = manifest_store.load()
    for candidate in candidates:
        if ready_count >= target_ready_count:
            break
        existing = _source_for_url(existing_sources, str(candidate.url))
        if existing is not None:
            candidate.status = "added"
            candidate.source_id = existing.source_id
            candidate_store.replace(candidate)
            if existing.status == UiSourceStatus.READY:
                ready_count += 1
            continue
        try:
            manifest = await run_in_threadpool(
                discovery.import_candidate,
                project_id,
                candidate,
            )
            manifest_store.add(manifest)
            existing_sources.append(manifest)
            candidate.source_id = manifest.source_id
            candidate.issue_summary = manifest.issue_summary
            candidate.status = "added" if manifest.status == UiSourceStatus.READY else "failed"
            if manifest.status == UiSourceStatus.READY:
                ready_count += 1
        except (OSError, RuntimeError, ValueError) as error:
            candidate.status = "failed"
            candidate.issue_summary = str(error)[:300]
        candidate_store.replace(candidate)


def _source_candidate(source: UiSourceManifest) -> SourceCandidate:
    is_web = source.origin == "gemini_web_search"
    relevance = (
        "Discovered through Gemini Google Search, captured through URL Context, "
        "then passed the same parse-quality gate."
        if is_web
        else "Selected by the user after the real parse-quality gate using "
        f"{source.parser_name or 'an available parser'}."
    )
    limitations = [item for item in [source.issue_summary, *source.quality_issues] if item]
    return SourceCandidate(
        source_id=source.source_id,
        title=source.title,
        role=SourceRole.REFERENCE if is_web else SourceRole.USER_CONTEXT,
        source_type="web" if is_web else Path(source.filename).suffix.lstrip(".") or "file",
        origin=source.origin,
        language=None,
        canonical_url=source.canonical_url,
        access=SourceAccess.FULL_TEXT,
        user_decision=SourceDecision.INCLUDE,
        relevance_reasons=[relevance],
        limitations=limitations,
    )


def _uploaded_source_path(
    workspace: WorkspaceStore,
    project_id: UUID,
    source: UiSourceManifest,
) -> Path:
    local = workspace.project_dir(project_id) / "uploads" / str(source.source_id) / source.filename
    if local.is_file():
        return local
    return (
        workspace.project_dir(project_id)
        / "uploads"
        / "web"
        / str(source.source_id)
        / source.filename
    )


def _source_for_url(
    sources: list[UiSourceManifest],
    url: str,
) -> UiSourceManifest | None:
    return next((source for source in sources if source.canonical_url == url), None)


def _project_stages(
    state: ProjectState,
    corpus_run: CorpusBuildRun | None,
    planning_run: EpisodePlanningRun | None,
) -> list[tuple[str, bool]]:
    after_sources = corpus_run is not None or state not in {
        ProjectState.DRAFT,
        ProjectState.BRIEF_READY,
        ProjectState.SOURCES_COLLECTING,
        ProjectState.SOURCE_SELECTION_REQUIRED,
    }
    corpus_ready = bool(corpus_run and corpus_run.status == "succeeded") or state in {
        ProjectState.CORPUS_READY,
        ProjectState.EPISODE_PLANNING,
        ProjectState.EPISODE_PLANNED,
        ProjectState.SCRIPT_DRAFTING,
        ProjectState.SCRIPT_READY,
        ProjectState.SCRIPT_VERIFYING,
        ProjectState.SCRIPT_VERIFIED,
        ProjectState.AUDIO_GENERATING,
        ProjectState.AUDIO_READY,
        ProjectState.AUDIO_VERIFYING,
        ProjectState.COMPLETE,
    }
    plan_ready = bool(planning_run and planning_run.status == "succeeded") or state in {
        ProjectState.EPISODE_PLANNED,
        ProjectState.SCRIPT_DRAFTING,
        ProjectState.SCRIPT_READY,
        ProjectState.SCRIPT_VERIFYING,
        ProjectState.SCRIPT_VERIFIED,
        ProjectState.AUDIO_GENERATING,
        ProjectState.AUDIO_READY,
        ProjectState.AUDIO_VERIFYING,
        ProjectState.COMPLETE,
    }
    return [
        ("برداشت هدف", True),
        ("افزودن و تأیید منابع", after_sources),
        ("ساخت مجموعه شاهدها", corpus_ready),
        ("سنجش کفایت و ساخت طرح گفتار", plan_ready),
    ]


def _safe_filename(value: str) -> str:
    name = Path(value).name.replace("\x00", "").strip()
    if not name or name in {".", ".."}:
        raise ValueError("نام فایل معتبر نیست.")
    return name[:180]


def _source_redirect(project_id: UUID, *, error: str | None = None) -> RedirectResponse:
    url = f"/projects/{project_id}/sources"
    if error:
        url += f"?error={error}"
    return RedirectResponse(url, status_code=HTTP_303_SEE_OTHER)
