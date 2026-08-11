from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.status import HTTP_303_SEE_OTHER

from thesisound.domain import ProjectState
from thesisound.pipeline import WorkspaceStore, transition
from thesisound.product_metrics import ProductEvent, emit
from thesisound.product_metrics.events import (
    EpisodeSourceTraceOpened,
    GateScriptApproved,
    GateScriptReviewRequested,
)
from thesisound.script import ScriptReviewDecision
from thesisound.services.plan_approval import (
    EpisodePlanApprovalStore,
    episode_plan_hash,
)
from thesisound.services.lineage_events import emit_review_decision
from thesisound.services.runtime_preflight import RuntimePreflight
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_run import ScriptBuildRunService
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.web.error_messages import user_facing_error
from thesisound.web.evidence_views import segment_views as _segment_views

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
    preflight: RuntimePreflight,
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
            emit_review_decision(
                disposition="approved",
                subject_type="script",
                subject_id=str(project_id),
                reviewer=actor,
                reason_code="script_approve",
            )
            background_tasks.add_task(execute, project_id)
            emit(
                ProductEvent.GATE_SCRIPT_APPROVED,
                GateScriptApproved(),
                user_id=getattr(request.state.account, "user_id", None),
                project_id=project_id,
            )
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
            if decision == "send_back":
                # Queues a fresh build; /script/approve and /script/retry are
                # gated by the preflight middleware, this branch is not.
                # This must happen before persisting the review/state changes.
                preflight.require("script")
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
            emit_review_decision(
                disposition=review.decision,
                subject_type="script",
                subject_id=str(project_id),
                reviewer=review.reviewer,
                reason_code=clean_reason[:120],
                regenerated_stage="script" if decision == "send_back" else None,
            )
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
            emit(
                ProductEvent.GATE_SCRIPT_REVIEW_REQUESTED,
                GateScriptReviewRequested(decision=decision),  # type: ignore[arg-type]
                user_id=getattr(request.state.account, "user_id", None),
                project_id=project_id,
            )
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

    @app.post("/projects/{project_id}/script/source-trace")
    def source_trace_opened(
        request: Request,
        project_id: UUID,
        csrf_token: Annotated[str, Form()] = "",
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
            ProductEvent.EPISODE_SOURCE_TRACE_OPENED,
            EpisodeSourceTraceOpened(),
            user_id=getattr(request.state.account, "user_id", None),
            project_id=project_id,
        )
        return Response(status_code=204)

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
