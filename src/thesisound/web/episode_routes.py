from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.status import HTTP_303_SEE_OTHER

from thesisound.domain import ProjectState
from thesisound.pipeline import WorkspaceStore
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.episode_planning_run import EpisodePlanningRunService

Render = Callable[..., HTMLResponse]
LoginRedirect = Callable[[Request], RedirectResponse | None]
ValidateCsrf = Callable[[Request, str], None]


def register_episode_routes(
    app: FastAPI,
    *,
    workspace: WorkspaceStore,
    planner: EpisodePlanningRunService,
    execute: Callable[[UUID], None],
    render: Render,
    login_redirect: LoginRedirect,
    validate_csrf: ValidateCsrf,
) -> None:
    episode_store = EpisodeArtifactStore(workspace.root)

    @app.get("/projects/{project_id}/episode", response_class=HTMLResponse)
    def episode_page(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        project = workspace.load_project(project_id)
        run = planner.run_store.load_optional(project_id)
        coverage = _load_optional(episode_store.load_coverage, project_id)
        budget = _load_optional(episode_store.load_budget, project_id)
        plan = _load_optional(episode_store.load_plan, project_id) or project.episode_plan
        return render(
            request,
            "projects/episode.html",
            {
                "project": project,
                "planning_run": run,
                "planning_active": bool(run and run.status in {"queued", "running"}),
                "coverage": coverage,
                "budget": budget,
                "episode_plan": plan,
                "can_start": project.state == ProjectState.CORPUS_READY,
                "can_retry": bool(
                    run
                    and run.status == "failed"
                    and project.state == ProjectState.FAILED_RETRYABLE
                ),
            },
        )

    @app.post("/projects/{project_id}/episode/prepare")
    def prepare_episode(
        request: Request,
        background_tasks: BackgroundTasks,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        try:
            validate_csrf(request, csrf_token)
            planner.queue(project_id)
            background_tasks.add_task(execute, project_id)
        except ValueError as error:
            return _episode_error(
                request,
                project_id,
                str(error),
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
        try:
            validate_csrf(request, csrf_token)
            planner.retry(project_id)
            background_tasks.add_task(execute, project_id)
        except ValueError as error:
            return _episode_error(
                request,
                project_id,
                str(error),
                workspace=workspace,
                planner=planner,
                episode_store=episode_store,
                render=render,
            )
        return _episode_redirect(project_id)

    @app.post("/projects/{project_id}/episode/reduce-duration")
    def reduce_duration(
        request: Request,
        background_tasks: BackgroundTasks,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
        duration_minutes: Annotated[int, Form()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        try:
            validate_csrf(request, csrf_token)
            planner.requeue_with_duration(project_id, duration_minutes)
            background_tasks.add_task(execute, project_id)
        except ValueError as error:
            return _episode_error(
                request,
                project_id,
                str(error),
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
                str(error),
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
            "coverage": _load_optional(episode_store.load_coverage, project_id),
            "budget": _load_optional(episode_store.load_budget, project_id),
            "episode_plan": plan,
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
    except FileNotFoundError:
        return None


def _episode_redirect(project_id: UUID) -> RedirectResponse:
    return RedirectResponse(
        f"/projects/{project_id}/episode",
        status_code=HTTP_303_SEE_OTHER,
    )
