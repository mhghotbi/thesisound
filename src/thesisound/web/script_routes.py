from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.status import HTTP_303_SEE_OTHER

from thesisound.domain import Locator, Project, ProjectState, Script
from thesisound.pipeline import WorkspaceStore, transition
from thesisound.script import ScriptReviewDecision
from thesisound.services.plan_approval import (
    EpisodePlanApprovalStore,
    episode_plan_hash,
)
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_run import ScriptBuildRunService
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.web.error_messages import user_facing_error

Render = Callable[..., HTMLResponse]
LoginRedirect = Callable[[Request], RedirectResponse | None]
ProjectRedirect = Callable[[Request, UUID], RedirectResponse | None]
ValidateCsrf = Callable[[Request, str], None]


def register_script_routes(
    app: FastAPI,
    *,
    workspace: WorkspaceStore,
    builder: ScriptBuildRunService,
    execute: Callable[[UUID], None],
    render: Render,
    login_redirect: LoginRedirect,
    project_redirect: ProjectRedirect,
    validate_csrf: ValidateCsrf,
) -> None:
    script_store = ScriptArtifactStore(workspace.root)
    approval_store = EpisodePlanApprovalStore(workspace.root)
    source_store = SourceArtifactStore(workspace.root)

    @app.get("/projects/{project_id}/script", response_class=HTMLResponse)
    def script_page(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        return _render_script_page(
            request,
            project_id,
            workspace=workspace,
            builder=builder,
            script_store=script_store,
            approval_store=approval_store,
            source_store=source_store,
            render=render,
        )

    @app.get("/projects/{project_id}/script/live", response_class=HTMLResponse)
    def script_live(request: Request, project_id: UUID) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        response = _render_script_page(
            request,
            project_id,
            workspace=workspace,
            builder=builder,
            script_store=script_store,
            approval_store=approval_store,
            source_store=source_store,
            render=render,
            template_name="projects/_script_live.html",
        )
        run = builder.run_store.load_optional(project_id)
        if not (run and run.status in {"queued", "running"}):
            response.headers["HX-Refresh"] = "true"
        return response

    @app.post("/projects/{project_id}/script/approve")
    def approve_script(
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
            actor = request.state.account.label
            builder.approve_and_queue(project_id, approved_by=actor)
            background_tasks.add_task(execute, project_id)
        except (OSError, RuntimeError, ValueError) as error:
            return _render_script_page(
                request,
                project_id,
                workspace=workspace,
                builder=builder,
                script_store=script_store,
                approval_store=approval_store,
                source_store=source_store,
                render=render,
                error=user_facing_error(error, action="script"),
                status_code=422,
            )
        return _script_redirect(project_id)

    @app.post("/projects/{project_id}/script/review")
    def review_script(
        request: Request,
        background_tasks: BackgroundTasks,
        project_id: UUID,
        csrf_token: Annotated[str, Form()],
        decision: Annotated[str, Form()],
        reason: Annotated[str, Form()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        try:
            validate_csrf(request, csrf_token)
            project = workspace.load_project(project_id)
            if project.state != ProjectState.SCRIPT_REVIEW_REQUIRED:
                raise ValueError("This script is not awaiting a review decision.")
            clean_reason = reason.strip()
            if not clean_reason:
                raise ValueError("A review reason is required.")
            if decision not in {"accept", "send_back"}:
                raise ValueError("Unknown script review decision.")
            plan_hash = episode_plan_hash(project.episode_plan) if project.episode_plan else ""
            checks = script_store.load_latest_checks(project_id)
            verification = script_store.load_latest_verification(project_id)
            review = ScriptReviewDecision(
                project_id=project_id,
                decision="accepted" if decision == "accept" else "sent_back",
                reviewer=request.state.account.label,
                reason=clean_reason,
                plan_hash=plan_hash,
                checks_verdict=checks.verdict,
                verification_verdict=verification.verdict,
                unsupported_claim_ratio=verification.unsupported_claim_ratio,
                quality_overall=(
                    verification.quality.overall if verification.quality is not None else None
                ),
            )
            script_store.save_review_decision(review)
            manifest = script_store.load_manifest(project_id)
            if decision == "accept":
                transition(project, ProjectState.SCRIPT_VERIFIED)
                manifest.status = "verified"
                manifest.last_error = None
            else:
                transition(project, ProjectState.SCRIPT_DRAFTING)
                manifest.last_error = clean_reason
            workspace.save_project(project)
            script_store.save_manifest(manifest)
            if decision == "send_back":
                builder.send_back(project_id)
                background_tasks.add_task(execute, project_id)
        except (OSError, RuntimeError, ValueError) as error:
            return _render_script_page(
                request,
                project_id,
                workspace=workspace,
                builder=builder,
                script_store=script_store,
                approval_store=approval_store,
                source_store=source_store,
                render=render,
                error=user_facing_error(error, action="script"),
                status_code=422,
            )
        return _script_redirect(project_id)

    @app.post("/projects/{project_id}/script/retry")
    def retry_script(
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
            builder.retry(project_id)
            background_tasks.add_task(execute, project_id)
        except (OSError, RuntimeError, ValueError) as error:
            return _render_script_page(
                request,
                project_id,
                workspace=workspace,
                builder=builder,
                script_store=script_store,
                approval_store=approval_store,
                source_store=source_store,
                render=render,
                error=user_facing_error(error, action="script"),
                status_code=422,
            )
        return _script_redirect(project_id)


def _render_script_page(
    request: Request,
    project_id: UUID,
    *,
    workspace: WorkspaceStore,
    builder: ScriptBuildRunService,
    script_store: ScriptArtifactStore,
    approval_store: EpisodePlanApprovalStore,
    source_store: SourceArtifactStore,
    render: Render,
    error: str | None = None,
    status_code: int = 200,
    template_name: str = "projects/script.html",
) -> HTMLResponse:
    project = workspace.load_project(project_id)
    current_plan_hash = (
        episode_plan_hash(project.episode_plan) if project.episode_plan is not None else None
    )
    stored_run = builder.run_store.load_optional(project_id)
    stored_approval = approval_store.load_optional(project_id)
    run = (
        stored_run
        if stored_run is not None and stored_run.approved_plan_hash == current_plan_hash
        else None
    )
    approval = (
        stored_approval
        if stored_approval is not None and stored_approval.plan_hash == current_plan_hash
        else None
    )
    artifacts_current = bool(
        current_plan_hash and script_store.artifacts_match_plan(project_id, current_plan_hash)
    )
    script = (
        _load_optional(script_store.load_latest_script, project_id) if artifacts_current else None
    )
    checks = (
        _load_optional(script_store.load_latest_checks, project_id) if artifacts_current else None
    )
    verification = (
        _load_optional(script_store.load_latest_verification, project_id)
        if artifacts_current
        else None
    )
    manifest = script_store.load_manifest_optional(project_id) if artifacts_current else None
    return render(
        request,
        template_name,
        {
            "project": project,
            "script_run": run,
            "script_active": bool(run and run.status in {"queued", "running"}),
            "script_attempt": len(builder.run_store.load_history(project_id)),
            "approval": approval,
            "script": script,
            "checks": checks,
            "verification": verification,
            "revision_decision": (
                script_store.load_revision_decision_optional(project_id)
                if artifacts_current
                else None
            ),
            "review_decision": (
                script_store.load_review_decision_optional(project_id)
                if artifacts_current
                else None
            ),
            "outcome_reason": manifest.last_error if manifest else None,
            "manifest": manifest,
            "used_revision": bool(
                artifacts_current and script_store.has_revised_script(project_id)
            ),
            "segment_views": _segment_views(project, script, source_store),
            "can_approve": project.state == ProjectState.EPISODE_PLANNED,
            "can_retry": bool(
                run
                and run.status == "failed"
                and project.state in {ProjectState.EPISODE_PLANNED, ProjectState.FAILED_RETRYABLE}
            ),
            "error": error,
        },
        status_code=status_code,
    )


def _segment_views(
    project: Project,
    script: Script | None,
    source_store: SourceArtifactStore,
) -> list[dict[str, object]]:
    if script is None or project.episode_plan is None:
        return []
    source_titles = {source.source_id: source.title for source in project.sources}
    source_ids = [source.source_id for source in project.sources if source.usable_as_evidence]
    if not project.sources:
        source_ids = source_store.list_claim_ready_source_ids(project.project_id)
    evidence_by_id: dict[str, dict[str, object]] = {}
    for source_id in source_ids:
        try:
            evidence_items = source_store.load_evidence_items(project.project_id, source_id)
        except FileNotFoundError:
            continue
        for item in evidence_items:
            evidence_by_id[item.evidence_id] = {
                "evidence_id": item.evidence_id,
                "source_id": str(source_id),
                "source_title": source_titles.get(source_id, str(source_id)),
                "locator": _locator_label(item.locator),
                "excerpt": item.supporting_excerpt,
            }

    turns_by_segment: dict[str, list[dict[str, object]]] = {}
    for turn in script.turns:
        references = [
            evidence_by_id[evidence_id]
            for evidence_id in turn.evidence_ids
            if evidence_id in evidence_by_id
        ]
        turns_by_segment.setdefault(turn.segment_id, []).append(
            {
                "turn": turn,
                "references": references,
            }
        )
    return [
        {
            "segment": segment,
            "turns": turns_by_segment.get(segment.segment_id, []),
        }
        for segment in project.episode_plan.segments
    ]


def _locator_label(locator: Locator) -> str:
    parts: list[str] = []
    if locator.page_start is not None:
        page = str(locator.page_start)
        if locator.page_end is not None and locator.page_end != locator.page_start:
            page += f"–{locator.page_end}"
        parts.append(f"صفحه {page}")
    if locator.chapter:
        parts.append(f"فصل {locator.chapter}")
    if locator.section:
        parts.append(f"بخش {locator.section}")
    if locator.paragraph_start is not None:
        paragraph = str(locator.paragraph_start)
        if locator.paragraph_end is not None and locator.paragraph_end != locator.paragraph_start:
            paragraph += f"–{locator.paragraph_end}"
        parts.append(f"بند {paragraph}")
    return "، ".join(parts) if parts else "نشانی در منبع مشخص نیست"


def _load_optional(loader: Callable[[UUID], object], project_id: UUID) -> object | None:
    try:
        return loader(project_id)
    except FileNotFoundError:
        return None


def _script_redirect(project_id: UUID) -> RedirectResponse:
    return RedirectResponse(
        f"/projects/{project_id}/script",
        status_code=HTTP_303_SEE_OTHER,
    )
