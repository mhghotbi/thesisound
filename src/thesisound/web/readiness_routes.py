from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from thesisound.pipeline import WorkspaceStore
from thesisound.services.readiness import project_readiness
from thesisound.web.readiness_views import build_readiness_view

Render = Callable[..., HTMLResponse]
LoginRedirect = Callable[[Request], RedirectResponse | None]
ProjectRedirect = Callable[[Request, UUID], RedirectResponse | None]


def register_readiness_routes(
    app: FastAPI,
    *,
    workspace: WorkspaceStore,
    render: Render,
    login_redirect: LoginRedirect,
    project_redirect: ProjectRedirect,
) -> None:
    @app.get("/projects/{project_id}/readiness", response_class=HTMLResponse)
    def readiness_page(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        project = workspace.load_project(project_id)
        gate_results = project_readiness(
            project_id=project_id,
            workspace_root=workspace.root,
        )
        brief = getattr(project, "brief", None)
        return render(
            request,
            "projects/readiness.html",
            {
                "project": project,
                "gate_results": gate_results,
                "readiness": build_readiness_view(
                    gate_results,
                    project_id=project_id,
                    target_duration_minutes=getattr(brief, "target_duration_minutes", None),
                    workspace_root=workspace.root,
                ),
            },
        )
