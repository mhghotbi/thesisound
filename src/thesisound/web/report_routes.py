"""The `source_coverage` completion report page (`10c` P3 Step 11/12)."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from thesisound.observability import ObservabilityLedger
from thesisound.pipeline import WorkspaceStore
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.lesson_report import LessonReportBuilder
from thesisound.services.source_artifact_store import SourceArtifactStore

Render = Callable[..., HTMLResponse]
LoginRedirect = Callable[[Request], RedirectResponse | None]
ProjectRedirect = Callable[[Request, UUID], RedirectResponse | None]


def register_report_routes(
    app: FastAPI,
    *,
    workspace: WorkspaceStore,
    render: Render,
    login_redirect: LoginRedirect,
    project_redirect: ProjectRedirect,
    ledger: ObservabilityLedger | None = None,
) -> None:
    source_store = SourceArtifactStore(workspace.root)
    episode_store = EpisodeArtifactStore(workspace.root)
    builder = LessonReportBuilder(
        source_store=source_store, episode_store=episode_store, ledger=ledger
    )

    @app.get("/projects/{project_id}/report", response_class=HTMLResponse)
    def report_page(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        project = workspace.load_project(project_id)
        error: str | None = None
        report = None
        try:
            report = builder.build(project_id, project)
        except (FileNotFoundError, OSError, ValueError) as exc:
            error = str(exc)
        return render(
            request,
            "projects/report.html",
            {"project": project, "report": report, "error": error},
        )
