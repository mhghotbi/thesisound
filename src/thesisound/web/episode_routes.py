from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.status import HTTP_303_SEE_OTHER

from thesisound.domain import ProjectState
from thesisound.pipeline import WorkspaceStore
from thesisound.product_metrics import ProductEvent, emit
from thesisound.product_metrics.events import PlanOmittedListOpened, PlanReviewed
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.episode_duration_cost import (
    duration_cost_hint,
    reextraction_required_for_duration,
)
from thesisound.services.episode_planning_run import EpisodePlanningRunService
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.web.error_messages import user_facing_error
from thesisound.web.evidence_views import (
    load_claim_index,
    load_evidence_index,
    must_not_be_lost_review_views,
    omitted_claim_views,
)

Render = Callable[..., HTMLResponse]
LoginRedirect = Callable[[Request], RedirectResponse | None]
ProjectRedirect = Callable[[Request, UUID], RedirectResponse | None]
ValidateCsrf = Callable[[Request, str], None]


def register_episode_routes(
    app: FastAPI,
    *,
    workspace: WorkspaceStore,
    planner: EpisodePlanningRunService,
    execute: Callable[[UUID], None],
    render: Render,
    login_redirect: LoginRedirect,
    project_redirect: ProjectRedirect,
    validate_csrf: ValidateCsrf,
) -> None:
    episode_store = EpisodeArtifactStore(workspace.root)
    source_store = SourceArtifactStore(workspace.root)

    def episode_context(project_id: UUID) -> dict[str, object]:
        project = workspace.load_project(project_id)
        run = planner.run_store.load_optional(project_id)
        episode_plan = _load_optional(episode_store.load_plan, project_id) or project.episode_plan
        omitted_views: list[dict[str, object]] = []
        mnbl_views: list[dict[str, object]] = []
        unused_mnbl_views: list[dict[str, object]] = []
        mnbl_unused_count: int | None = None
        claims: dict = {}
        evidence_by_id: dict = {}
        needs_claim_index = bool(
            episode_plan is not None
            and (
                episode_plan.deliberately_omitted_claims
                or project.state == ProjectState.EPISODE_PLANNED
            )
        )
        if needs_claim_index:
            claims = load_claim_index(project, source_store)
            evidence_by_id = load_evidence_index(project, source_store)
        if episode_plan is not None and episode_plan.deliberately_omitted_claims:
            omitted_views = omitted_claim_views(
                episode_plan.deliberately_omitted_claims,
                claims=claims,
                evidence_by_id=evidence_by_id,
            )
        review = _load_optional(episode_store.load_must_not_be_lost_review, project_id)
        if review is not None:
            if not claims:
                claims = load_claim_index(project, source_store)
                evidence_by_id = load_evidence_index(project, source_store)
            mnbl_views = must_not_be_lost_review_views(
                review,
                claims=claims,
                evidence_by_id=evidence_by_id,
            )
            unused_mnbl_views = [row for row in mnbl_views if not row["used_in_plan"]]
            mnbl_unused_count = getattr(review, "unused_count", None)

        default_duration = None
        if run is not None and run.supported_duration_minutes is not None:
            if run.status == "blocked":
                candidate = int(run.supported_duration_minutes)
                if candidate >= 5:
                    default_duration = candidate
            elif (
                run.status == "succeeded"
                and project.state == ProjectState.EPISODE_PLANNED
                and project.brief is not None
            ):
                default_duration = project.brief.target_duration_minutes
        duration_reextraction = False
        if default_duration is not None and project.brief is not None:
            duration_reextraction = reextraction_required_for_duration(
                project, source_store, default_duration
            )

        return {
            "project": project,
            "planning_run": run,
            "planning_active": bool(run and run.status in {"queued", "running"}),
            "planning_attempt": len(planner.run_store.load_history(project_id)),
            "coverage": _load_optional(episode_store.load_coverage, project_id),
            "budget": _load_optional(episode_store.load_budget, project_id),
            "episode_plan": episode_plan,
            "omitted_claim_views": omitted_views,
            "must_not_be_lost_review_views": mnbl_views,
            "unused_must_not_be_lost_views": unused_mnbl_views,
            "must_not_be_lost_unused_count": mnbl_unused_count,
            "duration_reextraction_required": duration_reextraction,
            "can_start": project.state == ProjectState.CORPUS_READY,
            "can_retry": bool(
                run and run.status == "failed" and project.state == ProjectState.FAILED_RETRYABLE
            ),
        }

    @app.get("/projects/{project_id}/episode", response_class=HTMLResponse)
    def episode_page(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        context = episode_context(project_id)
        project = context["project"]
        if getattr(project, "state", None) == ProjectState.EPISODE_PLANNED:
            emit(
                ProductEvent.PLAN_REVIEWED,
                PlanReviewed(
                    has_omitted=bool(context["omitted_claim_views"]),
                    has_unused_must_not_be_lost=bool(context["unused_must_not_be_lost_views"]),
                ),
                user_id=getattr(request.state.account, "user_id", None),
                project_id=project_id,
            )
        return render(request, "projects/episode.html", context)

    @app.get("/projects/{project_id}/episode/live", response_class=HTMLResponse)
    def episode_live(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        context = episode_context(project_id)
        response = render(request, "projects/_episode_live.html", context)
        if not context["planning_active"]:
            response.headers["HX-Refresh"] = "true"
        return response

    @app.get("/projects/{project_id}/episode/duration-cost", response_class=HTMLResponse)
    def duration_cost(
        request: Request,
        project_id: UUID,
        minutes: Annotated[int, Query(ge=5, le=120)],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        project = workspace.load_project(project_id)
        run = planner.run_store.load_optional(project_id)
        blocked = bool(run and run.status == "blocked")
        required = False
        if project.brief is not None:
            required = reextraction_required_for_duration(project, source_store, minutes)
        hint = duration_cost_hint(reextraction_required=required, blocked=blocked)
        return HTMLResponse(hint)

    @app.post("/projects/{project_id}/episode/list-opened")
    def list_opened(
        request: Request,
        project_id: UUID,
        csrf_token: Annotated[str, Form()] = "",
        origin: Annotated[Literal["omitted", "must_not_be_lost"], Form()] = "omitted",
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        if csrf_token:
            try:
                validate_csrf(request, csrf_token)
            except ValueError:
                return Response(status_code=403)
        emit(
            ProductEvent.PLAN_OMITTED_LIST_OPENED,
            PlanOmittedListOpened(origin=origin),
            user_id=getattr(request.state.account, "user_id", None),
            project_id=project_id,
        )
        return Response(status_code=204)

    @app.post("/projects/{project_id}/episode/prepare")
    def prepare_episode(
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
            planner.queue(project_id)
            background_tasks.add_task(execute, project_id)
        except ValueError as error:
            return _episode_error(
                request,
                project_id,
                user_facing_error(error, action="planning"),
                workspace=workspace,
                planner=planner,
                episode_store=episode_store,
                render=render,
            )
        return _episode_redirect(project_id)

    @app.post("/projects/{project_id}/episode/retry")
    def retry_episode(
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
            planner.retry(project_id)
            background_tasks.add_task(execute, project_id)
        except ValueError as error:
            return _episode_error(
                request,
                project_id,
                user_facing_error(error, action="planning"),
                workspace=workspace,
                planner=planner,
                episode_store=episode_store,
                render=render,
            )
        return _episode_redirect(project_id)

    @app.post("/projects/{project_id}/episode/duration")
    def set_duration(
        request: Request,
        background_tasks: BackgroundTasks,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
        duration_minutes: Annotated[int, Form()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        try:
            validate_csrf(request, csrf_token)
            planner.requeue_with_duration(project_id, duration_minutes)
            background_tasks.add_task(execute, project_id)
        except ValueError as error:
            return _episode_error(
                request,
                project_id,
                user_facing_error(error, action="planning"),
                workspace=workspace,
                planner=planner,
                episode_store=episode_store,
                render=render,
            )
        return _episode_redirect(project_id)

    @app.post("/projects/{project_id}/episode/reopen-inputs")
    def reopen_inputs(
        request: Request,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
        action: Annotated[str, Form()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        destination = f"/projects/{project_id}/sources"
        try:
            validate_csrf(request, csrf_token)
            if action == "add-source":
                reason = "Coverage review requested additional sources."
            elif action == "change-focus":
                reason = "Coverage review requested a narrower or revised research focus."
                destination = f"/projects/{project_id}/brief"
            else:
                raise ValueError("Action is not supported.")
            planner.reopen_inputs(project_id, reason=reason)
        except ValueError as error:
            return _episode_error(
                request,
                project_id,
                user_facing_error(error, action="planning"),
                workspace=workspace,
                planner=planner,
                episode_store=episode_store,
                render=render,
            )
        return RedirectResponse(destination, status_code=HTTP_303_SEE_OTHER)


def _episode_error(
    request: Request,
    project_id: UUID,
    message: str,
    *,
    workspace: WorkspaceStore,
    planner: EpisodePlanningRunService,
    episode_store: EpisodeArtifactStore,
    render: Render,
) -> HTMLResponse:
    project = workspace.load_project(project_id)
    run = planner.run_store.load_optional(project_id)
    plan = _load_optional(episode_store.load_plan, project_id) or project.episode_plan
    return render(
        request,
        "projects/episode.html",
        {
            "project": project,
            "planning_run": run,
            "planning_active": bool(run and run.status in {"queued", "running"}),
            "planning_attempt": len(planner.run_store.load_history(project_id)),
            "coverage": _load_optional(episode_store.load_coverage, project_id),
            "budget": _load_optional(episode_store.load_budget, project_id),
            "episode_plan": plan,
            "omitted_claim_views": [],
            "must_not_be_lost_review_views": [],
            "unused_must_not_be_lost_views": [],
            "must_not_be_lost_unused_count": None,
            "duration_reextraction_required": False,
            "can_start": project.state == ProjectState.CORPUS_READY,
            "can_retry": bool(
                run
                and run.status == "failed"
                and project.state == ProjectState.FAILED_RETRYABLE
            ),
            "error": message,
        },
        status_code=422,
    )


def _load_optional(loader: Callable[[UUID], object], project_id: UUID) -> object | None:
    try:
        return loader(project_id)
    except (FileNotFoundError, OSError, ValueError):
        return None


def _episode_redirect(project_id: UUID) -> RedirectResponse:
    return RedirectResponse(
        f"/projects/{project_id}/episode",
        status_code=HTTP_303_SEE_OTHER,
    )
