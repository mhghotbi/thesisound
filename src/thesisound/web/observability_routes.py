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

    Authorization requires the authenticated account role to be ``operator``.
    The existing ``session['ui_mode'] == 'operator'`` preference is an additional
    presentation gate; it never grants authorization by itself.

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
        include_synthetic: bool | None = Query(default=None),
    ) -> Response:
        if response := require_operator(request, project_id):
            return response
        # A runtime that stamps its own telemetry synthetic -- every non-production
        # setup does, see ``ledger_from_settings`` -- would otherwise render a page
        # that hides everything it just wrote, while the live banner above it keeps
        # naming the running stage. Follow the ledger unless the URL says otherwise.
        show_synthetic = ledger.is_synthetic if include_synthetic is None else include_synthetic
        try:
            project = workspace.load_project(project_id)
            overview = reporter.project_overview(
                project_id,
                trace_id=trace_id,
                trace_page=trace_page,
                event_page=event_page,
                depth=depth,
                include_synthetic=show_synthetic,
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
                "include_synthetic": show_synthetic,
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
