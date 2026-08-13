from __future__ import annotations

import html
import logging
import secrets
import shutil
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.status import HTTP_303_SEE_OTHER

from thesisound import logging_setup, tracing
from thesisound.accounts import AccountError, AccountLockedError, accounts_store_from_settings
from thesisound.adapters.sms import KavenegarOtpSender
from thesisound.audio_runtime import create_audio_builder
from thesisound.config import Settings
from thesisound.domain import Project, ProjectState, ResearchBrief, TopicType
from thesisound.observability import ledger_from_settings, tracer_from_settings
from thesisound.pipeline import WorkspaceStore, transition
from thesisound.product_metrics import ProductEvent, configure_product_metrics, emit, emit_failed_count
from thesisound.product_metrics.events import (
    AuthCodeFailed,
    AuthCodeRequested,
    AuthCodeVerified,
    AuthLockedOut,
    AuthLoggedOut,
    AuthPasswordFailed,
    AuthPasswordSucceeded,
    GateBriefConfirmed,
    GateBriefEdited,
    ProjectCreated,
    UserRegistered,
)
from thesisound.product_metrics.store import ProductEventStore
from thesisound.services.observability_reporting import ObservabilityReporter
from thesisound.services.product_metrics_rollup import ProductMetricsRollup
from thesisound.services.readiness import project_readiness
from thesisound.services.runtime_preflight import PreflightScope, RuntimePreflight
from thesisound.web.audio_routes import register_audio_routes
from thesisound.web.auth import NullOtpSender, OtpError, OtpSenderPort, OtpService
from thesisound.web.corpus_runtime import create_corpus_builder
from thesisound.web.episode_routes import register_episode_routes
from thesisound.web.episode_runtime import create_episode_planner
from thesisound.web.error_messages import user_facing_error
from thesisound.web.observability_routes import register_observability_routes
from thesisound.web.read_models import build_project_read_model
from thesisound.web.readiness_routes import register_readiness_routes
from thesisound.web.script_routes import register_script_routes
from thesisound.web.script_runtime import create_script_builder
from thesisound.web.source_routes import register_source_routes
_WEB_ROOT = Path(__file__).parent
_TEMPLATES_ROOT = _WEB_ROOT / "templates"
_STATIC_ROOT = _WEB_ROOT / "static"
_logger = logging.getLogger(__name__)
# The four /live HTMX fragments poll every 2s (see static/app.js) -- tracing
# them would add roughly 1,800 http.request spans per hour per open tab,
# swamping the table for the requests that actually matter. Excluded by
# name rather than sampled, since a sampled-out request is still a wasted
# random draw and still pollutes the count.
_UNTRACED_PATH_SUFFIXES = ("/live",)
_EDITABLE_BRIEF_STATES = {
    ProjectState.BRIEF_READY,
    ProjectState.SOURCES_COLLECTING,
    ProjectState.SOURCE_SELECTION_REQUIRED,
}
# Mode biases evidence extraction, so it stays editable only while extraction has not
# run yet — exactly the states above. An empty submission leaves the stored mode alone.
_BRIEF_MODES = ("explanatory", "critical", "comparative", "debate")
_PREFLIGHT_POST_SCOPES: tuple[tuple[str, PreflightScope], ...] = (
    ("/corpus/confirm", "model"),
    ("/corpus/retry", "model"),
    ("/skip", "model"),
    ("/episode/prepare", "model"),
    ("/episode/retry", "model"),
    ("/episode/duration", "model"),
    ("/script/approve", "script"),
    ("/script/retry", "script"),
    ("/audio/generate", "audio"),
    ("/audio/retry", "audio"),
)
_VALID_UI_THEMES = {"cobalt", "wood", "olive", "slate"}
_VALID_UI_MODES = {"simple", "operator"}
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_JALALI_MONTHS = (
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)


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


def _safe_next_path(value: str) -> str:
    return value if value.startswith("/") and not value.startswith("//") else "/projects"


def _ensure_anon_id(request: Request) -> str:
    anon_id = request.session.get("anon_id")
    if not isinstance(anon_id, str) or not anon_id:
        anon_id = secrets.token_urlsafe(16)
        request.session["anon_id"] = anon_id
    return anon_id


def _topic_type(raw_input: str) -> TopicType:
    return TopicType.QUESTION if "؟" in raw_input or "?" in raw_input else TopicType.MIXED


def _project_title(project: Project) -> str:
    if project.brief and project.brief.normalized_topic:
        return project.brief.normalized_topic
    return project.raw_input


def _corpus_stage_label(stage: str) -> str:
    return {
        "queued": "در صف اجرا",
        "building_blocks": "ساخت پاره‌متن‌ها",
        "mapping_document": "ساخت نقشهٔ منبع",
        "extracting_evidence": "استخراج شاهدها",
        "building_claims": "ساخت دفتر مدعاها",
        "complete": "آماده",
        "skipped": "کنار گذاشته شد",
        "failed": "متوقف‌شده",
    }.get(stage, stage)


def _fa_digits(value: object) -> str:
    return str(value).translate(_PERSIAN_DIGITS)


def _gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    month_offsets = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    adjusted_year = gy + 1 if gm > 2 else gy
    days = (
        355666
        + (365 * gy)
        + ((adjusted_year + 3) // 4)
        - ((adjusted_year + 99) // 100)
        + ((adjusted_year + 399) // 400)
        + gd
        + month_offsets[gm - 1]
    )
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def _jalali_date(value: date | datetime | None) -> str:
    if value is None:
        return "—"
    jy, jm, jd = _gregorian_to_jalali(value.year, value.month, value.day)
    return f"{_fa_digits(jd)} {_JALALI_MONTHS[jm - 1]} {_fa_digits(jy)}"


def _user_error_filter(value: object, action: str = "generic") -> str:
    if value is None or value == "":
        return ""
    return user_facing_error(
        value if isinstance(value, BaseException) else str(value),
        action=action,
    )


def _unhandled_error_page(message: str, request_id: str | None) -> str:
    """A minimal, dependency-free error page for the global exception
    handler. Deliberately does not go through Jinja2Templates: that
    machinery expects request-scoped context (CSRF token, current user,
    project state) that may not be safely available when an unexpected
    exception has already occurred somewhere upstream, and a second
    exception raised while rendering the error page for the first would
    defeat the whole point of this handler."""

    safe_message = html.escape(message)
    id_line = (
        f'<p class="request-id">شناسه پیگیری: <code>{html.escape(request_id)}</code></p>'
        if request_id
        else ""
    )
    return f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>خطا - مقال</title>
<style>
  body {{
    font-family: Tahoma, Vazirmatn, sans-serif;
    background: #1c1f16;
    color: #e8e6df;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    margin: 0;
  }}
  .card {{
    max-width: 32rem;
    padding: 2rem;
    background: #262a1e;
    border-radius: 0.75rem;
    text-align: center;
  }}
  .request-id code {{
    background: #33372a;
    padding: 0.15rem 0.4rem;
    border-radius: 0.3rem;
  }}
</style>
</head>
<body>
  <div class="card">
    <h1>خطایی رخ داد</h1>
    <p>{safe_message}</p>
    {id_line}
  </div>
</body>
</html>"""


def _preflight_scope(request: Request) -> PreflightScope | None:
    if request.method != "POST":
        return None
    for suffix, scope in _PREFLIGHT_POST_SCOPES:
        if request.url.path.endswith(suffix):
            return scope
    return None


def _build_otp_sender(runtime: Settings) -> OtpSenderPort:
    api_key = (runtime.kavenegar_api_key or "").strip()
    template = (runtime.kavenegar_otp_template or "").strip()
    if not api_key or not template:
        return NullOtpSender()
    return KavenegarOtpSender(api_key=api_key, template=template)


def create_app(
    settings: Settings | None = None,
    *,
    corpus_executor: Callable[[UUID], None] | None = None,
    episode_executor: Callable[[UUID], None] | None = None,
    script_executor: Callable[[UUID], None] | None = None,
    audio_executor: Callable[[UUID], None] | None = None,
) -> FastAPI:
    runtime = settings or Settings()
    # Close any span a previous process left "running" before this one takes
    # over -- the same crash-recovery moment as the four recover_interrupted_runs()
    # calls below, just for spans rather than run records. One call here (not one
    # per create_*() factory) since it scans the whole ledger, not one run store.
    observability_ledger = ledger_from_settings(runtime)
    observability_ledger.reap_orphaned_spans()
    observability = ObservabilityReporter(observability_ledger)
    tracing.install_tracer(tracer_from_settings(runtime))
    workspace = WorkspaceStore(runtime.ensure_workspace_root())
    accounts = accounts_store_from_settings(runtime)
    configure_product_metrics(
        runtime,
        ProductEventStore(runtime.resolved_observability_database_path),
        user_resolver=accounts.primary_user_id_for_project,
    )
    preflight = RuntimePreflight(runtime)
    corpus_builder = create_corpus_builder(runtime, workspace)
    episode_planner = create_episode_planner(runtime, workspace)
    script_builder = create_script_builder(runtime, workspace)
    audio_builder = create_audio_builder(runtime, workspace)
    execute_corpus = corpus_executor or corpus_builder.run
    execute_episode = episode_executor or episode_planner.run
    execute_script = script_executor or script_builder.run
    execute_audio = audio_executor or audio_builder.run

    docs_url = "/api/docs" if runtime.environment != "production" else None
    app = FastAPI(title="مقال", docs_url=docs_url)
    app.add_middleware(
        SessionMiddleware,
        secret_key=runtime.web_session_secret,
        same_site="lax",
        https_only=runtime.web_secure_cookies,
        max_age=60 * 60 * 24 * 14,
    )
    app.mount("/static", StaticFiles(directory=_STATIC_ROOT), name="static")

    @app.middleware("http")
    async def dynamic_response_headers(
        request: Request, call_next: Callable
    ) -> Response:
        """Keep session HTML off shared caches and visible behind WCDN.

        WCDN's SMART policy was caching `/login` (and other form pages) with an
        embedded CSRF token, so POSTs failed validation. It also replaces HTML
        422 bodies with a generic "Upstream Error" page, hiding our form errors.
        """
        response = await call_next(request)
        if not request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = (
                "private, no-store, max-age=0, must-revalidate"
            )
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        if (
            runtime.environment != "test"
            and response.status_code == 422
            and "text/html" in response.headers.get("content-type", "")
        ):
            response.status_code = 200
        return response

    @app.middleware("http")
    async def guard_live_runs(request: Request, call_next: Callable) -> Response:
        scope = _preflight_scope(request)
        if runtime.environment != "test" and scope is not None and not preflight.ready(scope):
            return RedirectResponse(
                f"/system-check?blocked=1&scope={scope}",
                status_code=HTTP_303_SEE_OTHER,
            )
        return await call_next(request)

    # Added after guard_live_runs: Starlette runs the most-recently-added
    # middleware outermost, so this wraps the preflight guard and its
    # redirects too -- the http.request span covers the whole request no
    # matter which branch above handles it.
    @app.middleware("http")
    async def request_trace(request: Request, call_next: Callable) -> Response:
        if request.url.path.endswith(_UNTRACED_PATH_SUFFIXES):
            return await call_next(request)
        with tracing.span(
            "http.request",
            component="web",
            kind="http",
            new_root=True,
            method=request.method,
            route=request.url.path,  # path only -- never the query string
        ) as span:
            request.state.request_id = str(span.context.span_id)
            response = await call_next(request)
            span.set(status_code=response.status_code)
            response.headers["X-Request-Id"] = request.state.request_id
            return response

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> Response:
        """The last line of defense: today an unhandled route exception
        produces a bare Starlette 500 recorded nowhere at all. This logs it,
        records it as a trace event, and shows the same Persian error
        phrasing the rest of the app uses, with a request ID an operator can
        hand to `thesisound observability` support tooling."""

        request_id = getattr(request.state, "request_id", None)
        _logger.exception(
            "Unhandled request error",
            extra={"route": request.url.path, "request_id": request_id},
        )
        tracing.event(
            "web.unhandled_error",
            component="web",
            level="error",
            route=request.url.path,
            error_type=type(exc).__name__,
        )
        message = user_facing_error(exc, action="generic")
        error_response = HTMLResponse(_unhandled_error_page(message, request_id), status_code=500)
        # request_trace normally sets this after call_next() returns, but an
        # exception here means call_next() raised instead of returning -- this
        # handler is the only place left to still carry the ID on the response.
        if request_id:
            error_response.headers["X-Request-Id"] = request_id
        return error_response

    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory=_TEMPLATES_ROOT)
    templates.env.globals["project_title"] = _project_title
    templates.env.globals["corpus_stage_label"] = _corpus_stage_label
    templates.env.globals["observability_current_span"] = observability.current_open_span
    templates.env.filters["fa_num"] = _fa_digits
    templates.env.filters["jalali_date"] = _jalali_date
    templates.env.filters["user_error"] = _user_error_filter

    otp = OtpService(
        secret=runtime.web_session_secret,
        sender=_build_otp_sender(runtime),
        ttl_seconds=runtime.otp_ttl_seconds,
        resend_cooldown_seconds=runtime.otp_resend_cooldown_seconds,
        max_attempts=runtime.otp_max_attempts,
        allow_test_otp=runtime.allow_test_otp,
        test_phone=runtime.test_otp_phone,
        test_code=runtime.test_otp_code,
    )

    app.state.settings = runtime
    app.state.workspace = workspace
    app.state.accounts = accounts
    app.state.otp = otp
    app.state.preflight = preflight
    app.state.observability_ledger = observability_ledger
    app.state.observability = observability
    app.state.corpus_builder = corpus_builder
    app.state.episode_planner = episode_planner
    app.state.script_builder = script_builder
    app.state.audio_builder = audio_builder

    def _current_account(request: Request):
        cached = getattr(request.state, "account", None)
        if cached is not None:
            return cached
        user_id = request.session.get("user_id")
        if not isinstance(user_id, int):
            return None
        account = accounts.get_active_user(user_id)
        if account is None:
            request.session.pop("user_id", None)
            return None
        request.state.account = account
        return account

    def _is_authenticated(request: Request) -> bool:
        return _current_account(request) is not None

    def _login_redirect(request: Request) -> RedirectResponse | None:
        if _is_authenticated(request):
            return None
        next_path = request.url.path
        return RedirectResponse(
            f"/auth/login?next={next_path}",
            status_code=HTTP_303_SEE_OTHER,
        )

    def _project_redirect(
        request: Request,
        project_id: UUID,
    ) -> RedirectResponse | None:
        account = _current_account(request)
        if account is not None and (
            account.role == "operator" or accounts.is_project_member(project_id, account.user_id)
        ):
            return None
        return RedirectResponse("/projects", status_code=HTTP_303_SEE_OTHER)

    def render(
        request: Request,
        template_name: str,
        context: dict[str, object] | None = None,
        *,
        status_code: int = 200,
    ) -> HTMLResponse:
        theme = request.session.get("ui_theme", "cobalt")
        mode = request.session.get("ui_mode", "simple")
        if theme not in _VALID_UI_THEMES:
            theme = "cobalt"
        if mode not in _VALID_UI_MODES:
            mode = "simple"
        account = _current_account(request)
        payload: dict[str, object] = {
            "request": request,
            "csrf_token": _ensure_csrf(request),
            "current_user": account.label if account else None,
            "is_operator": account is not None and account.role == "operator",
            "environment": runtime.environment,
            "test_otp_enabled": runtime.allow_test_otp,
            "ui_theme": theme,
            "ui_mode": mode,
        }
        if context:
            payload.update(context)
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context=payload,
            status_code=status_code,
        )

    def failure_action_url(project: Project) -> str | None:
        if project.state not in {
            ProjectState.FAILED_RETRYABLE,
            ProjectState.FAILED_PERMANENT,
        }:
            return None
        audio_run = audio_builder.run_store.load_optional(project.project_id)
        script_run = script_builder.run_store.load_optional(project.project_id)
        episode_run = episode_planner.run_store.load_optional(project.project_id)
        if audio_run is not None and audio_run.status == "failed":
            return f"/projects/{project.project_id}/audio"
        if script_run is not None and script_run.status == "failed":
            return f"/projects/{project.project_id}/script"
        if episode_run is not None and episode_run.status == "failed":
            return f"/projects/{project.project_id}/episode"
        return f"/projects/{project.project_id}/processing"

    @app.get("/", include_in_schema=False)
    def root(request: Request) -> RedirectResponse:
        return RedirectResponse(
            "/projects" if _is_authenticated(request) else "/auth/login",
            status_code=HTTP_303_SEE_OTHER,
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/csrf/refresh")
    def refresh_csrf(request: Request) -> dict[str, str]:
        """Issue a session-matching CSRF token.

        Shared CDNs may cache HTML form pages with a stale embedded token.
        POSTs are not cached, so clients refresh the token before submit.
        """
        return {"csrf_token": _ensure_csrf(request)}

    def login_page(request: Request, next: str = "/projects") -> Response:
        if _is_authenticated(request):
            return RedirectResponse("/projects", status_code=HTTP_303_SEE_OTHER)
        safe_next = _safe_next_path(next)
        return render(request, "auth/login.html", {"next_path": safe_next})

    # /auth/login is the live entrypoint: WCDN had cached /login HTML with a
    # stale CSRF token, which made every POST look like a 422 upstream error.
    app.add_api_route("/auth/login", login_page, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route("/login", login_page, methods=["GET"], response_class=HTMLResponse)

    def password_login_page(request: Request, next: str = "/projects") -> Response:
        if _is_authenticated(request):
            return RedirectResponse("/projects", status_code=HTTP_303_SEE_OTHER)
        return render(
            request,
            "auth/password.html",
            {"next_path": _safe_next_path(next)},
        )

    app.add_api_route(
        "/auth/login/password",
        password_login_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    app.add_api_route(
        "/login/password",
        password_login_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )

    @app.post("/login/password", response_class=HTMLResponse)
    def password_login(
        request: Request,
        username: Annotated[str, Form()],
        password: Annotated[str, Form()],
        csrf_token: Annotated[str, Form()],
        next_path: Annotated[str, Form()] = "/projects",
    ) -> Response:
        safe_next = _safe_next_path(next_path)
        anon_id = _ensure_anon_id(request)
        try:
            _validate_csrf(request, csrf_token)
            account = accounts.verify_password(username, password)
        except AccountLockedError as error:
            emit(
                ProductEvent.AUTH_LOCKED_OUT,
                AuthLockedOut(method="password"),
                anon_id=anon_id,
            )
            emit(
                ProductEvent.AUTH_PASSWORD_FAILED,
                AuthPasswordFailed(reason="locked"),
                anon_id=anon_id,
            )
            return render(
                request,
                "auth/password.html",
                {
                    "error": str(error),
                    "username": username,
                    "next_path": safe_next,
                },
                status_code=422,
            )
        except (AccountError, ValueError) as error:
            reason = "locked" if "تلاش‌ها" in str(error) else "invalid"
            emit(
                ProductEvent.AUTH_PASSWORD_FAILED,
                AuthPasswordFailed(reason=reason),  # type: ignore[arg-type]
                anon_id=anon_id,
            )
            return render(
                request,
                "auth/password.html",
                {
                    "error": str(error),
                    "username": username,
                    "next_path": safe_next,
                },
                status_code=422,
            )
        is_first = accounts.record_login(account.user_id)
        emit(
            ProductEvent.AUTH_PASSWORD_SUCCEEDED,
            AuthPasswordSucceeded(),
            user_id=account.user_id,
            anon_id=anon_id,
        )
        if is_first:
            emit(
                ProductEvent.USER_REGISTERED,
                UserRegistered(method="password"),
                user_id=account.user_id,
                anon_id=anon_id,
            )
        request.session.pop("pending_phone", None)
        request.session.pop("login_next", None)
        request.session["user_id"] = account.user_id
        request.state.account = account
        return RedirectResponse(safe_next, status_code=HTTP_303_SEE_OTHER)

    @app.post("/login/request-code", response_class=HTMLResponse)
    def request_code(
        request: Request,
        phone: Annotated[str, Form()],
        csrf_token: Annotated[str, Form()],
        next_path: Annotated[str, Form()] = "/projects",
    ) -> Response:
        anon_id = _ensure_anon_id(request)
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
        emit(
            ProductEvent.AUTH_CODE_REQUESTED,
            AuthCodeRequested(),
            anon_id=anon_id,
            session_id=anon_id,
        )
        request.session["pending_phone"] = normalized
        request.session["login_next"] = _safe_next_path(next_path)
        return RedirectResponse("/auth/login/verify", status_code=HTTP_303_SEE_OTHER)

    def verify_page(request: Request) -> Response:
        phone = request.session.get("pending_phone")
        if not phone:
            return RedirectResponse("/auth/login", status_code=HTTP_303_SEE_OTHER)
        return render(request, "auth/verify.html", {"phone": phone})

    app.add_api_route(
        "/auth/login/verify",
        verify_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    app.add_api_route("/login/verify", verify_page, methods=["GET"], response_class=HTMLResponse)

    @app.post("/login/verify", response_class=HTMLResponse)
    def verify_code(
        request: Request,
        code: Annotated[str, Form()],
        csrf_token: Annotated[str, Form()],
    ) -> Response:
        phone = request.session.get("pending_phone")
        if not phone:
            return RedirectResponse("/auth/login", status_code=HTTP_303_SEE_OTHER)
        anon_id = _ensure_anon_id(request)
        try:
            _validate_csrf(request, csrf_token)
            otp.verify(phone, code)
        except (OtpError, ValueError) as error:
            message = str(error)
            if "منقضی" in message:
                reason = "expired"
            elif "تلاش‌ها" in message:
                reason = "locked"
                emit(
                    ProductEvent.AUTH_LOCKED_OUT,
                    AuthLockedOut(method="otp"),
                    anon_id=anon_id,
                )
            elif "درست نیست" in message or "شش رقم" in message:
                reason = "invalid"
            else:
                reason = "other"
            emit(
                ProductEvent.AUTH_CODE_FAILED,
                AuthCodeFailed(reason=reason),  # type: ignore[arg-type]
                anon_id=anon_id,
            )
            return render(
                request,
                "auth/verify.html",
                {"error": message, "phone": phone},
                status_code=422,
            )
        account = accounts.get_or_create_phone_user(phone)
        is_first = accounts.record_login(account.user_id)
        emit(
            ProductEvent.AUTH_CODE_VERIFIED,
            AuthCodeVerified(),
            user_id=account.user_id,
            anon_id=anon_id,
        )
        if is_first:
            emit(
                ProductEvent.USER_REGISTERED,
                UserRegistered(method="otp"),
                user_id=account.user_id,
                anon_id=anon_id,
            )
        request.session.pop("pending_phone", None)
        request.session["user_id"] = account.user_id
        destination = request.session.pop("login_next", "/projects")
        return RedirectResponse(destination, status_code=HTTP_303_SEE_OTHER)

    @app.post("/logout")
    def logout(
        request: Request,
        csrf_token: Annotated[str, Form()],
    ) -> RedirectResponse:
        _validate_csrf(request, csrf_token)
        user_id = request.session.get("user_id")
        emit(
            ProductEvent.AUTH_LOGGED_OUT,
            AuthLoggedOut(),
            user_id=user_id if isinstance(user_id, int) else None,
            anon_id=request.session.get("anon_id")
            if isinstance(request.session.get("anon_id"), str)
            else None,
        )
        request.session.clear()
        return RedirectResponse("/auth/login", status_code=HTTP_303_SEE_OTHER)

    @app.post("/ui/preferences", status_code=204)
    def save_ui_preferences(
        request: Request,
        csrf_token: Annotated[str, Form()],
        theme: Annotated[str | None, Form()] = None,
        mode: Annotated[str | None, Form()] = None,
    ) -> Response:
        _validate_csrf(request, csrf_token)
        if theme is not None and theme in _VALID_UI_THEMES:
            request.session["ui_theme"] = theme
        if mode is not None and mode in _VALID_UI_MODES:
            request.session["ui_mode"] = mode
        return Response(status_code=204)

    @app.get("/system-check", response_class=HTMLResponse)
    def system_check(request: Request, scope: str = "full") -> Response:
        if redirect := _login_redirect(request):
            return redirect
        selected_scope: PreflightScope = (
            scope if scope in {"model", "script", "audio", "full"} else "full"
        )
        checks = preflight.run(selected_scope)
        return render(
            request,
            "system-check.html",
            {
                "checks": checks,
                "ready": not any(check.blocking for check in checks),
                "selected_scope": selected_scope,
                "blocked": request.query_params.get("blocked") == "1",
            },
        )

    @app.get("/projects", response_class=HTMLResponse)
    def projects_page(request: Request) -> Response:
        if redirect := _login_redirect(request):
            return redirect
        account = request.state.account
        projects = workspace.list_projects()
        if account.role != "operator":
            visible_project_ids = accounts.project_ids_for_user(account.user_id)
            projects = [
                project for project in projects if str(project.project_id) in visible_project_ids
            ]
        models = [
            build_project_read_model(
                project,
                failure_action_url=failure_action_url(project),
            )
            for project in projects
        ]
        group_order = {"attention": 0, "running": 1, "complete": 2}
        models.sort(
            key=lambda item: (
                group_order.get(item.group_key, 9),
                -item.project.updated_at.timestamp(),
            )
        )
        return render(request, "projects/index.html", {"projects": models})

    @app.get("/projects/new", response_class=HTMLResponse)
    @app.get("/projects/create", response_class=HTMLResponse)
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
        must_include: Annotated[str, Form()] = "",
        exclusions: Annotated[str, Form()] = "",
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
                scope_inclusions=[
                    item.strip() for item in must_include.splitlines() if item.strip()
                ],
                scope_exclusions=[
                    item.strip() for item in exclusions.splitlines() if item.strip()
                ],
            )
            project = Project(raw_input=topic, brief=brief)
            # This form is the whole gate: the operator wrote the question and
            # (optionally) the scope, so submitting it is the real confirmation --
            # there is no separate approval screen to stop at. BRIEF_READY is
            # still visited (not skipped) because workflow rewind targets it
            # directly; see workflow_revision.rewind().
            transition(project, ProjectState.BRIEF_READY)
            transition(project, ProjectState.SOURCES_COLLECTING)
            workspace.save_project(project)
            try:
                accounts.add_project_member(
                    project.project_id,
                    request.state.account.user_id,
                    role="owner",
                )
            except Exception:
                # Project metadata and membership live in independent stores.
                # If membership persistence fails, leaving the freshly-created
                # directory behind creates an invisible orphan and a retry
                # creates a duplicate. Roll back only this brand-new UUID.
                shutil.rmtree(workspace.project_dir(project.project_id), ignore_errors=True)
                raise
            emit(
                ProductEvent.PROJECT_CREATED,
                ProjectCreated(
                    topic_type=brief.topic_type.value
                    if hasattr(brief.topic_type, "value")
                    else str(brief.topic_type),
                    entry_mode="web",
                ),
                user_id=request.state.account.user_id,
                project_id=project.project_id,
            )
            emit(
                ProductEvent.GATE_BRIEF_CONFIRMED,
                GateBriefConfirmed(),
                user_id=request.state.account.user_id,
                project_id=project.project_id,
            )
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
                        "must_include": must_include,
                        "exclusions": exclusions,
                    },
                },
                status_code=422,
            )
        return RedirectResponse(
            f"/projects/{project.project_id}/sources",
            status_code=HTTP_303_SEE_OTHER,
        )

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    def project_overview(request: Request, project_id: UUID) -> Response:
        if redirect := _login_redirect(request):
            return redirect
        if redirect := _project_redirect(request, project_id):
            return redirect
        project = workspace.load_project(project_id)
        model = build_project_read_model(
            project,
            failure_action_url=failure_action_url(project),
        )
        schema_drift = any(
            result.reason == "schema"
            for result in project_readiness(
                project_id=project_id,
                workspace_root=workspace.root,
            )
        )
        return render(
            request,
            "projects/overview.html",
            {
                "project": project,
                "model": model,
                "schema_drift": schema_drift,
            },
        )

    @app.get("/projects/{project_id}/brief", response_class=HTMLResponse)
    def brief_page(request: Request, project_id: UUID) -> Response:
        if redirect := _login_redirect(request):
            return redirect
        if redirect := _project_redirect(request, project_id):
            return redirect
        project = workspace.load_project(project_id)
        return render(
            request,
            "projects/brief.html",
            {
                "project": project,
                "brief_locked": project.state not in _EDITABLE_BRIEF_STATES,
            },
        )

    @app.post("/projects/{project_id}/brief", response_class=HTMLResponse)
    def save_brief(
        request: Request,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
        central_question: Annotated[str, Form()] = "",
        must_include: Annotated[str, Form()] = "",
        exclusions: Annotated[str, Form()] = "",
        mode: Annotated[str, Form()] = "",
        action: Annotated[str, Form()] = "save",
    ) -> Response:
        if redirect := _login_redirect(request):
            return redirect
        if redirect := _project_redirect(request, project_id):
            return redirect
        project = workspace.load_project(project_id)
        values = {
            "central_question": central_question,
            "must_include": must_include,
            "exclusions": exclusions,
            "mode": mode,
        }
        try:
            _validate_csrf(request, csrf_token)
            if project.state not in _EDITABLE_BRIEF_STATES:
                raise ValueError(
                    "این برداشت اولیه وارد تحلیل منابع شده است و بدون بازگشت "
                    "به مرحلهٔ قبلی قابل ویرایش نیست."
                )
            if project.brief is None:
                raise ValueError("صورت‌بندی گفتار وجود ندارد.")
            project.brief.central_question = central_question.strip()
            project.brief.scope_inclusions = [
                item.strip() for item in must_include.splitlines() if item.strip()
            ]
            project.brief.scope_exclusions = [
                item.strip() for item in exclusions.splitlines() if item.strip()
            ]
            if mode:
                if mode not in _BRIEF_MODES:
                    raise ValueError("رویکرد گفتار معتبر نیست.")
                project.brief.modes = [mode]
            if not project.brief.central_question:
                raise ValueError("پرسش اصلی نمی‌تواند خالی باشد.")
            if action == "confirm" and project.state == ProjectState.BRIEF_READY:
                transition(project, ProjectState.SOURCES_COLLECTING)
            workspace.save_project(project)
            if action == "confirm":
                emit(
                    ProductEvent.GATE_BRIEF_CONFIRMED,
                    GateBriefConfirmed(),
                    user_id=request.state.account.user_id,
                    project_id=project_id,
                )
            else:
                emit(
                    ProductEvent.GATE_BRIEF_EDITED,
                    GateBriefEdited(),
                    user_id=request.state.account.user_id,
                    project_id=project_id,
                )
        except ValueError as error:
            current = workspace.load_project(project_id)
            return render(
                request,
                "projects/brief.html",
                {
                    "project": current,
                    "brief_locked": current.state not in _EDITABLE_BRIEF_STATES,
                    "error": str(error),
                    "values": values,
                },
                status_code=422,
            )
        destination = (
            f"/projects/{project_id}/sources"
            if action == "confirm"
            else f"/projects/{project_id}/brief?saved=1"
        )
        return RedirectResponse(destination, status_code=HTTP_303_SEE_OTHER)

    register_source_routes(
        app,
        settings=runtime,
        workspace=workspace,
        corpus_builder=corpus_builder,
        episode_planner=episode_planner,
        execute_corpus=execute_corpus,
        render=render,
        login_redirect=_login_redirect,
        project_redirect=_project_redirect,
        validate_csrf=_validate_csrf,
    )
    register_episode_routes(
        app,
        workspace=workspace,
        planner=episode_planner,
        execute=execute_episode,
        render=render,
        login_redirect=_login_redirect,
        project_redirect=_project_redirect,
        validate_csrf=_validate_csrf,
    )
    register_script_routes(
        app,
        workspace=workspace,
        builder=script_builder,
        execute=execute_script,
        render=render,
        login_redirect=_login_redirect,
        project_redirect=_project_redirect,
        validate_csrf=_validate_csrf,
        preflight=preflight,
    )
    register_audio_routes(
        app,
        workspace=workspace,
        builder=audio_builder,
        execute=execute_audio,
        render=render,
        login_redirect=_login_redirect,
        project_redirect=_project_redirect,
        validate_csrf=_validate_csrf,
        settings=runtime,
    )

    register_readiness_routes(
        app,
        workspace=workspace,
        render=render,
        login_redirect=_login_redirect,
        project_redirect=_project_redirect,
    )

    register_observability_routes(
        app,
        workspace=workspace,
        reporter=observability,
        ledger=observability_ledger,
        render=render,
        login_redirect=_login_redirect,
        validate_csrf=_validate_csrf,
    )

    @app.get("/metrics", response_class=HTMLResponse)
    def metrics_page(request: Request) -> Response:
        if redirect := _login_redirect(request):
            return redirect
        account = _current_account(request)
        if account is None or account.role != "operator":
            return RedirectResponse("/projects", status_code=HTTP_303_SEE_OTHER)
        if request.session.get("ui_mode", "simple") != "operator":
            return RedirectResponse("/projects", status_code=HTTP_303_SEE_OTHER)
        rollup = ProductMetricsRollup(
            ProductEventStore(runtime.resolved_observability_database_path)
        )
        rows = rollup.list_metrics(limit=500)
        by_key: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            by_key.setdefault(str(row["metric_key"]), []).append(row)
        return render(
            request,
            "metrics.html",
            {
                "north_star": by_key.get("trusted_episodes_weekly", []),
                "stage_conversion": by_key.get("stage_conversion", []),
                "gate_block_rate": by_key.get("gate_block_rate", []),
                "gate_resolution_rate": by_key.get("gate_resolution_rate", []),
                "gate_median_blocked": by_key.get("gate_median_blocked_seconds", []),
                "emit_failed": emit_failed_count(),
            },
        )

    return app


app = create_app()


def main() -> None:
    # Logging setup is a process-level concern -- done once here, for the
    # real server, rather than inside create_app() which tests call many
    # times per process and would otherwise repeatedly reconfigure the root
    # logger out from under each other.
    logging_setup.configure_logging(Settings())
    uvicorn.run(
        "thesisound.web.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_config=logging_setup.uvicorn_log_config(Settings()),
    )
