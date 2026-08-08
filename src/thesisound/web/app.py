from __future__ import annotations

import secrets
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware
from starlette.status import HTTP_303_SEE_OTHER

from thesisound.config import Settings
from thesisound.domain import (
    Project,
    ProjectState,
    ResearchBrief,
    SourceAccess,
    SourceCandidate,
    SourceDecision,
    SourceRole,
    TopicType,
)
from thesisound.pipeline import WorkspaceStore, transition
from thesisound.web.auth import NullOtpSender, OtpError, OtpService
from thesisound.web.corpus_runtime import corpus_source_inputs, create_corpus_builder
from thesisound.web.read_models import build_project_read_model
from thesisound.web.source_ingestion import ingest_uploaded_source
from thesisound.web.source_manifest import (
    UiSourceManifest,
    UiSourceManifestStore,
    UiSourceStatus,
)

_WEB_ROOT = Path(__file__).parent
_TEMPLATES_ROOT = _WEB_ROOT / "templates"
_STATIC_ROOT = _WEB_ROOT / "static"
_SUPPORTED_UPLOAD_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}
_EDITABLE_SOURCE_STATES = {
    ProjectState.SOURCES_COLLECTING,
    ProjectState.SOURCE_SELECTION_REQUIRED,
}


def _safe_filename(value: str) -> str:
    name = Path(value).name.replace("\x00", "").strip()
    if not name or name in {".", ".."}:
        raise ValueError("نام فایل معتبر نیست.")
    return name[:180]


def _ensure_csrf(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def _validate_csrf(request: Request, submitted: str) -> None:
    expected = request.session.get("csrf_token", "")
    if not expected or not secrets.compare_digest(expected, submitted):
        raise ValueError("درخواست نامعتبر است. صفحه را تازه کنید.")


def _is_authenticated(request: Request) -> bool:
    return bool(request.session.get("user_phone"))


def _login_redirect(request: Request) -> RedirectResponse | None:
    if _is_authenticated(request):
        return None
    next_path = request.url.path
    return RedirectResponse(f"/login?next={next_path}", status_code=HTTP_303_SEE_OTHER)


def _topic_type(raw_input: str) -> TopicType:
    return TopicType.QUESTION if "؟" in raw_input or "?" in raw_input else TopicType.MIXED


def _project_title(project: Project) -> str:
    if project.brief and project.brief.normalized_topic:
        return project.brief.normalized_topic
    return project.raw_input


def _corpus_stage_label(stage: str) -> str:
    return {
        "queued": "در صف اجرا",
        "building_blocks": "ساخت بلوک‌های معنایی",
        "mapping_document": "ساخت نقشه سند",
        "extracting_evidence": "استخراج شواهد",
        "building_claims": "ساخت دفتر ادعاها",
        "complete": "آماده",
        "failed": "متوقف‌شده",
    }.get(stage, stage)


def create_app(
    settings: Settings | None = None,
    *,
    corpus_executor: Callable[[UUID], None] | None = None,
) -> FastAPI:
    runtime = settings or Settings()
    workspace = WorkspaceStore(runtime.ensure_workspace_root())
    corpus_builder = create_corpus_builder(runtime, workspace)
    execute_corpus = corpus_executor or corpus_builder.run

    docs_url = "/api/docs" if runtime.environment != "production" else None
    app = FastAPI(title="Thesisound", docs_url=docs_url)
    app.add_middleware(
        SessionMiddleware,
        secret_key=runtime.web_session_secret,
        same_site="lax",
        https_only=runtime.web_secure_cookies,
        max_age=60 * 60 * 24 * 14,
    )
    app.mount("/static", StaticFiles(directory=_STATIC_ROOT), name="static")

    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory=_TEMPLATES_ROOT)
    templates.env.globals["project_title"] = _project_title
    templates.env.globals["corpus_stage_label"] = _corpus_stage_label

    otp = OtpService(
        secret=runtime.web_session_secret,
        sender=NullOtpSender(),
        ttl_seconds=runtime.otp_ttl_seconds,
        resend_cooldown_seconds=runtime.otp_resend_cooldown_seconds,
        max_attempts=runtime.otp_max_attempts,
        allow_test_otp=runtime.allow_test_otp,
        test_phone=runtime.test_otp_phone,
        test_code=runtime.test_otp_code,
    )

    app.state.settings = runtime
    app.state.workspace = workspace
    app.state.otp = otp
    app.state.corpus_builder = corpus_builder

    def render(
        request: Request,
        template_name: str,
        context: dict[str, object] | None = None,
        *,
        status_code: int = 200,
    ) -> HTMLResponse:
        payload: dict[str, object] = {
            "request": request,
            "csrf_token": _ensure_csrf(request),
            "current_user": request.session.get("user_phone"),
            "environment": runtime.environment,
            "test_otp_enabled": runtime.allow_test_otp,
        }
        if context:
            payload.update(context)
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context=payload,
            status_code=status_code,
        )

    @app.get("/", include_in_schema=False)
    def root(request: Request) -> RedirectResponse:
        return RedirectResponse(
            "/projects" if _is_authenticated(request) else "/login",
            status_code=HTTP_303_SEE_OTHER,
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next: str = "/projects") -> Response:
        if _is_authenticated(request):
            return RedirectResponse("/projects", status_code=HTTP_303_SEE_OTHER)
        safe_next = next if next.startswith("/") and not next.startswith("//") else "/projects"
        return render(request, "auth/login.html", {"next_path": safe_next})

    @app.post("/login/request-code", response_class=HTMLResponse)
    def request_code(
        request: Request,
        phone: Annotated[str, Form()],
        csrf_token: Annotated[str, Form()],
        next_path: Annotated[str, Form()] = "/projects",
    ) -> Response:
        try:
            _validate_csrf(request, csrf_token)
            normalized = otp.request_code(phone)
        except (OtpError, ValueError) as error:
            return render(
                request,
                "auth/login.html",
                {"error": str(error), "phone": phone, "next_path": next_path},
                status_code=422,
            )
        request.session["pending_phone"] = normalized
        safe_next = next_path.startswith("/") and not next_path.startswith("//")
        request.session["login_next"] = next_path if safe_next else "/projects"
        return RedirectResponse("/login/verify", status_code=HTTP_303_SEE_OTHER)

    @app.get("/login/verify", response_class=HTMLResponse)
    def verify_page(request: Request) -> Response:
        phone = request.session.get("pending_phone")
        if not phone:
            return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)
        return render(request, "auth/verify.html", {"phone": phone})

    @app.post("/login/verify", response_class=HTMLResponse)
    def verify_code(
        request: Request,
        code: Annotated[str, Form()],
        csrf_token: Annotated[str, Form()],
    ) -> Response:
        phone = request.session.get("pending_phone")
        if not phone:
            return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)
        try:
            _validate_csrf(request, csrf_token)
            otp.verify(phone, code)
        except (OtpError, ValueError) as error:
            return render(
                request,
                "auth/verify.html",
                {"error": str(error), "phone": phone},
                status_code=422,
            )
        request.session.pop("pending_phone", None)
        request.session["user_phone"] = phone
        destination = request.session.pop("login_next", "/projects")
        return RedirectResponse(destination, status_code=HTTP_303_SEE_OTHER)

    @app.post("/logout")
    def logout(
        request: Request,
        csrf_token: Annotated[str, Form()],
    ) -> RedirectResponse:
        _validate_csrf(request, csrf_token)
        request.session.clear()
        return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)

    @app.get("/projects", response_class=HTMLResponse)
    def projects_page(request: Request) -> Response:
        if redirect := _login_redirect(request):
            return redirect
        projects = workspace.list_projects()
        models = [build_project_read_model(project) for project in projects]
        return render(request, "projects/index.html", {"projects": models})

    @app.get("/projects/new", response_class=HTMLResponse)
    def new_project_page(request: Request) -> Response:
        if redirect := _login_redirect(request):
            return redirect
        return render(request, "projects/new.html")

    @app.post("/projects", response_class=HTMLResponse)
    def create_project(
        request: Request,
        csrf_token: Annotated[str, Form()],
        topic: Annotated[str, Form()],
        audience: Annotated[str, Form()] = "دانشجوی علوم انسانی",
        prior_knowledge: Annotated[str, Form()] = "introductory",
        duration: Annotated[int, Form()] = 20,
        mode: Annotated[str, Form()] = "explanatory",
    ) -> Response:
        if redirect := _login_redirect(request):
            return redirect
        try:
            _validate_csrf(request, csrf_token)
            topic = topic.strip()
            if not topic:
                raise ValueError("موضوع را بنویسید.")
            brief = ResearchBrief(
                normalized_topic=topic,
                topic_type=_topic_type(topic),
                central_question=topic,
                audience=audience,
                prior_knowledge=prior_knowledge,
                target_duration_minutes=duration,
                modes=[mode],
                learning_objectives=["فهم روشن موضوع و ایده‌های اصلی آن"],
            )
            project = Project(raw_input=topic, brief=brief)
            transition(project, ProjectState.BRIEF_READY)
            workspace.save_project(project)
        except ValueError as error:
            return render(
                request,
                "projects/new.html",
                {
                    "error": str(error),
                    "values": {
                        "topic": topic,
                        "audience": audience,
                        "prior_knowledge": prior_knowledge,
                        "duration": duration,
                        "mode": mode,
                    },
                },
                status_code=422,
            )
        return RedirectResponse(
            f"/projects/{project.project_id}/brief",
            status_code=HTTP_303_SEE_OTHER,
        )

    @app.get("/projects/{project_id}/brief", response_class=HTMLResponse)
    def brief_page(request: Request, project_id: UUID) -> Response:
        if redirect := _login_redirect(request):
            return redirect
        project = workspace.load_project(project_id)
        return render(request, "projects/brief.html", {"project": project})

    @app.post("/projects/{project_id}/brief", response_class=HTMLResponse)
    def save_brief(
        request: Request,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
        central_question: Annotated[str, Form()],
        must_include: Annotated[str, Form()] = "",
        exclusions: Annotated[str, Form()] = "",
        action: Annotated[str, Form()] = "save",
    ) -> Response:
        if redirect := _login_redirect(request):
            return redirect
        project = workspace.load_project(project_id)
        try:
            _validate_csrf(request, csrf_token)
            if project.brief is None:
                raise ValueError("برداشت پژوهش وجود ندارد.")
            project.brief.central_question = central_question.strip()
            project.brief.scope_inclusions = [
                item.strip() for item in must_include.splitlines() if item.strip()
            ]
            project.brief.scope_exclusions = [
                item.strip() for item in exclusions.splitlines() if item.strip()
            ]
            if not project.brief.central_question:
                raise ValueError("سؤال مرکزی نمی‌تواند خالی باشد.")
            if action == "confirm" and project.state == ProjectState.BRIEF_READY:
                transition(project, ProjectState.SOURCES_COLLECTING)
            workspace.save_project(project)
        except ValueError as error:
            return render(
                request,
                "projects/brief.html",
                {"project": project, "error": str(error)},
                status_code=422,
            )
        destination = (
            f"/projects/{project_id}/sources"
            if action == "confirm"
            else f"/projects/{project_id}/brief?saved=1"
        )
        return RedirectResponse(destination, status_code=HTTP_303_SEE_OTHER)

    @app.get("/projects/{project_id}/sources", response_class=HTMLResponse)
    def sources_page(request: Request, project_id: UUID) -> Response:
        if redirect := _login_redirect(request):
            return redirect
        project = workspace.load_project(project_id)
        if project.state == ProjectState.BRIEF_READY:
            return RedirectResponse(
                f"/projects/{project_id}/brief",
                status_code=HTTP_303_SEE_OTHER,
            )
        manifest_store = UiSourceManifestStore(workspace.project_dir(project_id))
        sources = manifest_store.load()
        return render(
            request,
            "projects/sources.html",
            {
                "project": project,
                "sources": sources,
                "selected_count": sum(source.selected for source in sources),
                "selection_locked": project.state not in _EDITABLE_SOURCE_STATES,
            },
        )

    @app.post("/projects/{project_id}/sources/upload", response_class=HTMLResponse)
    async def upload_source(
        request: Request,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
        source_file: Annotated[UploadFile, File()],
    ) -> Response:
        if redirect := _login_redirect(request):
            return redirect
        project = workspace.load_project(project_id)
        _validate_csrf(request, csrf_token)

        if project.state == ProjectState.SOURCE_SELECTION_REQUIRED:
            transition(project, ProjectState.SOURCES_COLLECTING)
        if project.state != ProjectState.SOURCES_COLLECTING:
            return RedirectResponse(
                f"/projects/{project_id}/sources?error=selection-locked",
                status_code=HTTP_303_SEE_OTHER,
            )

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
                if size > runtime.web_upload_limit_bytes:
                    output.close()
                    destination.unlink(missing_ok=True)
                    return RedirectResponse(
                        f"/projects/{project_id}/sources?error=file-too-large",
                        status_code=HTTP_303_SEE_OTHER,
                    )
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
                runtime.ensure_ingestion_artifact_root() / str(project_id) / str(source_id)
            )
            manifest = await run_in_threadpool(
                partial(
                    ingest_uploaded_source,
                    destination,
                    source_id=source_id,
                    filename=filename,
                    content_type=source_file.content_type,
                    size_bytes=size,
                    settings=runtime,
                    artifact_root=artifact_root,
                )
            )

        manifest_store = UiSourceManifestStore(workspace.project_dir(project_id))
        manifest_store.add(manifest)
        sources = manifest_store.load()
        if (
            project.state == ProjectState.SOURCES_COLLECTING
            and any(source.status == UiSourceStatus.READY for source in sources)
        ):
            transition(project, ProjectState.SOURCE_SELECTION_REQUIRED)
        workspace.save_project(project)
        return RedirectResponse(
            f"/projects/{project_id}/sources",
            status_code=HTTP_303_SEE_OTHER,
        )

    @app.post("/projects/{project_id}/sources/{source_id}/toggle")
    def toggle_source(
        request: Request,
        project_id: UUID,
        source_id: UUID,
        csrf_token: Annotated[str, Form()],
    ) -> RedirectResponse:
        if redirect := _login_redirect(request):
            return redirect
        _validate_csrf(request, csrf_token)
        project = workspace.load_project(project_id)
        if project.state not in _EDITABLE_SOURCE_STATES:
            return RedirectResponse(
                f"/projects/{project_id}/sources?error=selection-locked",
                status_code=HTTP_303_SEE_OTHER,
            )
        manifest_store = UiSourceManifestStore(workspace.project_dir(project_id))
        manifest_store.toggle(source_id)
        return RedirectResponse(
            f"/projects/{project_id}/sources",
            status_code=HTTP_303_SEE_OTHER,
        )

    @app.post("/projects/{project_id}/corpus/confirm", response_class=HTMLResponse)
    def confirm_corpus(
        request: Request,
        background_tasks: BackgroundTasks,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
    ) -> Response:
        if redirect := _login_redirect(request):
            return redirect
        project = workspace.load_project(project_id)
        manifest_store = UiSourceManifestStore(workspace.project_dir(project_id))
        sources = manifest_store.load()
        try:
            _validate_csrf(request, csrf_token)
            if project.state not in _EDITABLE_SOURCE_STATES:
                raise ValueError("انتخاب منابع برای این پروژه قفل شده است.")
            selected = [
                source
                for source in sources
                if source.selected and source.status == UiSourceStatus.READY
            ]
            if not selected:
                raise ValueError("حداقل یک منبع آماده را انتخاب کنید.")
            if any(not source.safe_for_claim_extraction for source in selected):
                raise ValueError("همه منابع انتخاب‌شده باید از quality gate عبور کرده باشند.")
            inputs = corpus_source_inputs(runtime, project_id, selected)

            project.sources = [
                SourceCandidate(
                    source_id=source.source_id,
                    title=source.filename,
                    role=SourceRole.USER_CONTEXT,
                    source_type=Path(source.filename).suffix.lstrip(".") or "file",
                    origin="local_upload",
                    language=None,
                    access=SourceAccess.FULL_TEXT,
                    user_decision=SourceDecision.INCLUDE,
                    relevance_reasons=[
                        "Selected by the user after the real parse-quality gate "
                        f"using {source.parser_name or 'an available parser'}"
                    ],
                    limitations=[source.issue_summary] if source.issue_summary else [],
                )
                for source in selected
            ]
            if project.state == ProjectState.SOURCES_COLLECTING:
                transition(project, ProjectState.SOURCE_SELECTION_REQUIRED)
            transition(project, ProjectState.CORPUS_BUILDING)
            workspace.save_project(project)
            corpus_builder.queue(project_id, inputs)
            background_tasks.add_task(execute_corpus, project_id)
        except ValueError as error:
            return render(
                request,
                "projects/sources.html",
                {
                    "project": project,
                    "sources": sources,
                    "selected_count": sum(source.selected for source in sources),
                    "selection_locked": project.state not in _EDITABLE_SOURCE_STATES,
                    "error": str(error),
                },
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
        if redirect := _login_redirect(request):
            return redirect
        _validate_csrf(request, csrf_token)
        corpus_builder.retry(project_id)
        background_tasks.add_task(execute_corpus, project_id)
        return RedirectResponse(
            f"/projects/{project_id}/processing",
            status_code=HTTP_303_SEE_OTHER,
        )

    @app.get("/projects/{project_id}/processing", response_class=HTMLResponse)
    def processing_page(request: Request, project_id: UUID) -> Response:
        if redirect := _login_redirect(request):
            return redirect
        project = workspace.load_project(project_id)
        run = corpus_builder.run_store.load_optional(project_id)
        stages = [
            ("برداشت هدف", True),
            (
                "افزودن و تأیید منابع",
                project.state
                not in {
                    ProjectState.DRAFT,
                    ProjectState.BRIEF_READY,
                    ProjectState.SOURCES_COLLECTING,
                    ProjectState.SOURCE_SELECTION_REQUIRED,
                },
            ),
            (
                "ساخت مجموعه شواهد",
                project.state
                in {
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
                },
            ),
            (
                "ساخت طرح اپیزود",
                project.state
                in {
                    ProjectState.EPISODE_PLANNED,
                    ProjectState.SCRIPT_DRAFTING,
                    ProjectState.SCRIPT_READY,
                    ProjectState.SCRIPT_VERIFYING,
                    ProjectState.SCRIPT_VERIFIED,
                    ProjectState.AUDIO_GENERATING,
                    ProjectState.AUDIO_READY,
                    ProjectState.AUDIO_VERIFYING,
                    ProjectState.COMPLETE,
                },
            ),
        ]
        return render(
            request,
            "projects/processing.html",
            {
                "project": project,
                "stages": stages,
                "corpus_run": run,
                "corpus_active": bool(run and run.status in {"queued", "running"}),
            },
        )

    return app


app = create_app()


def main() -> None:
    uvicorn.run(
        "thesisound.web.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
