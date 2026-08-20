"""The `delivery in {text, both}` written-lesson reading page (`10c` P4)."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from thesisound.domain import DeliveryMode, Project, Script
from thesisound.pipeline import WorkspaceStore
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.web.evidence_views import (
    claim_groups_for_ids,
    load_claim_index,
    load_evidence_index,
)

Render = Callable[..., HTMLResponse]
LoginRedirect = Callable[[Request], RedirectResponse | None]
ProjectRedirect = Callable[[Request, UUID], RedirectResponse | None]


def register_lesson_routes(
    app: FastAPI,
    *,
    workspace: WorkspaceStore,
    render: Render,
    login_redirect: LoginRedirect,
    project_redirect: ProjectRedirect,
) -> None:
    script_store = ScriptArtifactStore(workspace.root)
    source_store = SourceArtifactStore(workspace.root)

    @app.get("/projects/{project_id}/lesson/{part_index}", response_class=HTMLResponse)
    def lesson_page(request: Request, project_id: UUID, part_index: int) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        project = workspace.load_project(project_id)
        script, part_count, error = _load_part_lesson(project, script_store, part_index)
        paragraphs = _paragraph_views(project, script, source_store) if script else []
        return render(
            request,
            "projects/lesson.html",
            {
                "project": project,
                "part_index": part_index,
                "part_count": part_count,
                "script": script,
                "paragraphs": paragraphs,
                "error": error,
            },
        )

    @app.get("/projects/{project_id}/lesson/{part_index}/export.md")
    def lesson_export(request: Request, project_id: UUID, part_index: int) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        project = workspace.load_project(project_id)
        script, _part_count, error = _load_part_lesson(project, script_store, part_index)
        if error or script is None:
            return PlainTextResponse(error or "این گفتار هنوز آماده نیست.", status_code=404)
        markdown = _render_markdown(project, script, source_store, part_index)
        return Response(
            content=markdown,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="lesson-part-{part_index}.md"',
            },
        )


def _load_part_lesson(
    project: Project,
    script_store: ScriptArtifactStore,
    part_index: int,
) -> tuple[Script | None, int, str | None]:
    if project.delivery not in {DeliveryMode.TEXT, DeliveryMode.BOTH}:
        return None, 0, "این گفتار نسخهٔ نوشتاری ندارد."
    parts = project.episode_plan.parts if project.episode_plan else []
    part_count = len(parts) or 1
    if part_index < 1 or part_index > part_count:
        return None, part_count, "این شمارهٔ گفتار وجود ندارد."
    try:
        if project.delivery == DeliveryMode.TEXT:
            script = (
                script_store.load_part_script(project.project_id, part_index)
                if parts
                else script_store.load_script(project.project_id)
            )
        else:
            script = (
                script_store.load_part_prose_script_optional(project.project_id, part_index)
                if parts
                else script_store.load_prose_script_optional(project.project_id)
            )
    except FileNotFoundError:
        script = None
    if script is None:
        return None, part_count, "متن نوشتاری این گفتار هنوز آماده نشده است."
    return script, part_count, None


def _paragraph_views(
    project: Project,
    script: Script,
    source_store: SourceArtifactStore,
) -> list[dict[str, object]]:
    evidence_by_id = load_evidence_index(project, source_store)
    claims = load_claim_index(project, source_store)
    views = []
    for turn in script.turns:
        groups = claim_groups_for_ids(
            list(turn.claim_ids),
            turn_evidence_ids=list(turn.evidence_ids),
            claims=claims,
            evidence_by_id=evidence_by_id,
        )
        views.append({"turn": turn, "claim_groups": groups})
    return views


def _render_markdown(
    project: Project,
    script: Script,
    source_store: SourceArtifactStore,
    part_index: int,
) -> str:
    evidence_by_id = load_evidence_index(project, source_store)
    claims = load_claim_index(project, source_store)
    footnote_number_by_evidence_id: dict[str, int] = {}
    footnotes: list[str] = []
    lines = [f"# {script.title}", ""]
    for turn in script.turns:
        prefix = "#" * (turn.heading_level + 2) if turn.heading_level else ""
        numbers: list[int] = []
        groups = claim_groups_for_ids(
            list(turn.claim_ids),
            turn_evidence_ids=list(turn.evidence_ids),
            claims=claims,
            evidence_by_id=evidence_by_id,
        )
        for group in groups:
            for reference in group["evidence"]:
                evidence_id = reference["evidence_id"]
                if reference.get("availability") != "ok" or not reference.get("source_title"):
                    continue
                number = footnote_number_by_evidence_id.get(evidence_id)
                if number is None:
                    number = len(footnotes) + 1
                    footnote_number_by_evidence_id[evidence_id] = number
                    locator = reference.get("locator_label") or reference.get("locator") or ""
                    footnotes.append(f"{reference['source_title']} — {locator}")
                numbers.append(number)
        marker = "".join(f"[^{number}]" for number in sorted(set(numbers)))
        text = f"{turn.spoken_text_fa}{marker}"
        lines.append(f"{prefix} {text}".strip() if prefix else text)
        lines.append("")
    if footnotes:
        lines.append("---")
        lines.append("")
        for number, footnote in enumerate(footnotes, start=1):
            lines.append(f"[^{number}]: {footnote}")
        lines.append("")
    return "\n".join(lines)
