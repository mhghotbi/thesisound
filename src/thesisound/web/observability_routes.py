from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.status import HTTP_303_SEE_OTHER

from thesisound.observability import ObservabilityLedger
from thesisound.pipeline import WorkspaceStore
from thesisound.services.observability_reporting import ObservabilityReporter

Render = Callable[..., HTMLResponse]
LoginRedirect = Callable[[Request], RedirectResponse | None]
ValidateCsrf = Callable[[Request, str], None]


def register_observability_routes(
    app: FastAPI,
    *,
    workspace: WorkspaceStore,
    reporter: ObservabilityReporter,
    ledger: ObservabilityLedger,
    render: Render,
    login_redirect: LoginRedirect,
    validate_csrf: ValidateCsrf,
) -> None:
    """Register the operator-only, read-only observability surface.

    Authorization is based on the authenticated account role, never the UI
    preference stored in ``session['ui_mode']``. The latter only controls how
    much technical information normal workflow pages choose to render.

    ``validate_csrf`` is accepted intentionally to match the route-module
    composition signature. No route mutates state, so it is never called and
    this module adds no CSRF surface.
    """

    del validate_csrf

    def authenticated_operator(request: Request) -> bool:
        account = getattr(request.state, "account", None)
        return account is not None and getattr(account, "role", None) == "operator"

    def operator_mode(request: Request) -> bool:
        return request.session.get("ui_mode", "simple") == "operator"

    def require_operator(request: Request, project_id: UUID) -> Response | None:
        if redirect := login_redirect(request):
            return redirect
        if not authenticated_operator(request) or not operator_mode(request):
            return RedirectResponse(f"/projects/{project_id}", status_code=HTTP_303_SEE_OTHER)
        return None

    @app.get("/projects/{project_id}/observability", response_class=HTMLResponse)
    def observability_page(
        request: Request,
        project_id: UUID,
        trace_id: UUID | None = None,
        call_id: UUID | None = None,
        trace_page: int = Query(default=1, ge=1),
        event_page: int = Query(default=1, ge=1),
        depth: int = Query(default=6, ge=1, le=12),
    ) -> Response:
        if response := require_operator(request, project_id):
            return response
        try:
            project = workspace.load_project(project_id)
            overview = reporter.project_overview(
                project_id,
                trace_id=trace_id,
                trace_page=trace_page,
                event_page=event_page,
                depth=depth,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        selected_call = None
        if call_id is not None:
            try:
                detail = ledger.get_call(call_id)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            if detail.call.project_id != project_id:
                raise HTTPException(status_code=404, detail="Model call not found for project.")
            selected_call = detail

        return render(
            request,
            "projects/observability.html",
            {
                "project": project,
                "selected_call": selected_call,
                **overview,
            },
        )

    @app.get("/projects/{project_id}/observability/live", response_class=HTMLResponse)
    def observability_live(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if not authenticated_operator(request) or not operator_mode(request):
            return HTMLResponse("", status_code=403)
        try:
            workspace.load_project(project_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return render(
            request,
            "projects/_observability_live.html",
            {
                "project_id": project_id,
                **reporter.live_status(project_id),
            },
        )
