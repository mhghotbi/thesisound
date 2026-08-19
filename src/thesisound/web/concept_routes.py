from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, get_args
from uuid import UUID

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from starlette.status import HTTP_303_SEE_OTHER

from thesisound.concepts import (
    CELL_KEY_PATTERN,
    ConceptCell,
    ConceptCellKind,
    ConceptEdge,
    ConceptEdgeType,
    SourceConceptMap,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.services.concept_map_overlay import ConceptMapOverlayService, edge_overlay_key
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.web.source_manifest import UiSourceManifestStore

Render = Callable[..., HTMLResponse]
LoginRedirect = Callable[[Request], RedirectResponse | None]
ProjectRedirect = Callable[[Request, UUID], RedirectResponse | None]
ValidateCsrf = Callable[[Request, str], None]

_KIND_LABELS_FA: dict[str, str] = {
    "definition": "تعریف",
    "distinction": "تمایز",
    "argument": "استدلال",
    "position": "موضع",
    "objection": "اعتراض",
    "response": "پاسخ",
    "example": "مثال",
    "thread": "رشته",
}
_AGREEMENT_LABELS_FA: dict[str, str] = {
    "agreed": "دو روش هم‌خوان",
    "toc_only": "از فهرست مطالب",
    "heading_only": "از عنوان‌ها",
    "disagreed": "اختلاف در تشخیص فصل",
}
_EDGE_LABELS_FA: dict[str, str] = {
    "prerequisite": "پیش‌نیاز",
    "depends_on": "وابسته",
    "related": "مرتبط",
    "extends": "گسترش",
    "contrasts": "تمایز/تضاد",
    "objects_to": "اعتراض به",
    "responds_to": "پاسخ به",
    "instance_of": "نمونهٔ",
}


def register_concept_routes(
    app: FastAPI,
    *,
    workspace: WorkspaceStore,
    render: Render,
    login_redirect: LoginRedirect,
    project_redirect: ProjectRedirect,
    validate_csrf: ValidateCsrf,
) -> None:
    artifacts = SourceArtifactStore(workspace.root)
    overlays = ConceptMapOverlayService(workspace.root)

    def _page_url(project_id: UUID, source_id: UUID) -> str:
        return f"/projects/{project_id}/sources/{source_id}/concept-map"

    @app.get(
        "/projects/{project_id}/sources/{source_id}/concept-map",
        response_class=HTMLResponse,
    )
    def concept_map_page(
        request: Request,
        project_id: UUID,
        source_id: UUID,
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        project = workspace.load_project(project_id)
        context = _page_context(
            project_id,
            source_id,
            error=request.query_params.get("error"),
        )
        context["project"] = project
        return render(request, "concepts/concept_map.html", context)

    @app.post("/projects/{project_id}/sources/{source_id}/concept-map/cells")
    def add_cell(
        request: Request,
        project_id: UUID,
        source_id: UUID,
        csrf_token: Annotated[str, Form()],
        label_fa: Annotated[str, Form()],
        kind: Annotated[str, Form()],
        tier: Annotated[int, Form()],
        chapter_index: Annotated[int, Form()],
        block_ids: Annotated[str, Form()],
        section_ids: Annotated[str, Form()],
        estimated_minutes: Annotated[float, Form()] = 5.0,
        granularity_rationale: Annotated[str, Form()] = "افزوده‌شده توسط مالک.",
        cell_key: Annotated[str, Form()] = "",
        label_source: Annotated[str, Form()] = "",
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        try:
            validate_csrf(request, csrf_token)
            concept_map = _load_map(artifacts, project_id, source_id)
            if concept_map is None:
                raise ValueError("نقشهٔ مفهومی این منبع هنوز ساخته نشده است.")
            parsed_blocks = _split_ids(block_ids)
            parsed_sections = _split_ids(section_ids)
            if not parsed_blocks or not parsed_sections:
                raise ValueError("هر مفهوم باید دست‌کم به یک پاره‌متن و یک بخش وصل باشد.")
            key = cell_key.strip() or _next_cell_key(concept_map, chapter_index)
            cell = ConceptCell(
                cell_key=key,
                label_fa=label_fa.strip(),
                label_source=label_source.strip() or None,
                kind=kind,  # type: ignore[arg-type]
                tier=tier,  # type: ignore[arg-type]
                chapter_index=chapter_index,
                section_ids=parsed_sections,
                block_ids=parsed_blocks,
                granularity_rationale=granularity_rationale.strip() or "افزوده‌شده توسط مالک.",
                estimated_minutes=estimated_minutes,
                created_by="user",
            )
            overlays.record_edit(
                project_id,
                source_id,
                source_fingerprint=concept_map.source_fingerprint,
                add_cell=cell,
            )
        except (ValueError, TypeError, ValidationError) as error:
            return _error_page(
                request,
                project_id,
                source_id,
                str(error),
            )
        return RedirectResponse(_page_url(project_id, source_id), status_code=HTTP_303_SEE_OTHER)

    @app.post("/projects/{project_id}/sources/{source_id}/concept-map/cells/remove")
    def remove_cell(
        request: Request,
        project_id: UUID,
        source_id: UUID,
        csrf_token: Annotated[str, Form()],
        cell_key: Annotated[str, Form()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        try:
            validate_csrf(request, csrf_token)
            concept_map = _load_map(artifacts, project_id, source_id)
            if concept_map is None:
                raise ValueError("نقشهٔ مفهومی این منبع هنوز ساخته نشده است.")
            key = cell_key.strip()
            if not CELL_KEY_PATTERN.match(key):
                raise ValueError("شناسهٔ مفهوم معتبر نیست.")
            overlays.record_edit(
                project_id,
                source_id,
                source_fingerprint=concept_map.source_fingerprint,
                remove_cell_key=key,
            )
        except ValueError as error:
            return _error_page(request, project_id, source_id, str(error))
        return RedirectResponse(_page_url(project_id, source_id), status_code=HTTP_303_SEE_OTHER)

    @app.post("/projects/{project_id}/sources/{source_id}/concept-map/edges")
    def add_edge(
        request: Request,
        project_id: UUID,
        source_id: UUID,
        csrf_token: Annotated[str, Form()],
        source_key: Annotated[str, Form()],
        target_key: Annotated[str, Form()],
        edge_type: Annotated[str, Form()],
        rationale_fa: Annotated[str, Form()],
        weight: Annotated[float, Form()] = 0.8,
        confidence: Annotated[float, Form()] = 0.8,
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        try:
            validate_csrf(request, csrf_token)
            concept_map = _load_map(artifacts, project_id, source_id)
            if concept_map is None:
                raise ValueError("نقشهٔ مفهومی این منبع هنوز ساخته نشده است.")
            edge = ConceptEdge(
                source_key=source_key.strip(),
                target_key=target_key.strip(),
                type=edge_type,  # type: ignore[arg-type]
                weight=weight,
                confidence=confidence,
                rationale_fa=rationale_fa.strip() or "افزوده‌شده توسط مالک.",
                created_by="user",
                is_cross_chapter=_is_cross_chapter(
                    concept_map, source_key.strip(), target_key.strip()
                ),
            )
            overlays.record_edit(
                project_id,
                source_id,
                source_fingerprint=concept_map.source_fingerprint,
                add_edge=edge,
            )
        except (ValueError, TypeError, ValidationError) as error:
            return _error_page(request, project_id, source_id, str(error))
        return RedirectResponse(_page_url(project_id, source_id), status_code=HTTP_303_SEE_OTHER)

    @app.post("/projects/{project_id}/sources/{source_id}/concept-map/edges/remove")
    def remove_edge(
        request: Request,
        project_id: UUID,
        source_id: UUID,
        csrf_token: Annotated[str, Form()],
        edge_key: Annotated[str, Form()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        try:
            validate_csrf(request, csrf_token)
            concept_map = _load_map(artifacts, project_id, source_id)
            if concept_map is None:
                raise ValueError("نقشهٔ مفهومی این منبع هنوز ساخته نشده است.")
            key = edge_key.strip()
            if key.count("|") != 2:
                raise ValueError("شناسهٔ رابطه معتبر نیست.")
            overlays.record_edit(
                project_id,
                source_id,
                source_fingerprint=concept_map.source_fingerprint,
                remove_edge_key=key,
            )
        except ValueError as error:
            return _error_page(request, project_id, source_id, str(error))
        return RedirectResponse(_page_url(project_id, source_id), status_code=HTTP_303_SEE_OTHER)

    @app.post("/projects/{project_id}/sources/{source_id}/concept-map/tier")
    def override_tier(
        request: Request,
        project_id: UUID,
        source_id: UUID,
        csrf_token: Annotated[str, Form()],
        cell_key: Annotated[str, Form()],
        tier: Annotated[int, Form()],
    ) -> Response:
        if redirect := login_redirect(request):
            return redirect
        if redirect := project_redirect(request, project_id):
            return redirect
        try:
            validate_csrf(request, csrf_token)
            concept_map = _load_map(artifacts, project_id, source_id)
            if concept_map is None:
                raise ValueError("نقشهٔ مفهومی این منبع هنوز ساخته نشده است.")
            key = cell_key.strip()
            if not CELL_KEY_PATTERN.match(key):
                raise ValueError("شناسهٔ مفهوم معتبر نیست.")
            if tier not in (1, 2, 3):
                raise ValueError("سطح اهمیت باید ۱، ۲ یا ۳ باشد.")
            overlays.record_edit(
                project_id,
                source_id,
                source_fingerprint=concept_map.source_fingerprint,
                tier_override=(key, tier),  # type: ignore[arg-type]
            )
        except ValueError as error:
            return _error_page(request, project_id, source_id, str(error))
        return RedirectResponse(_page_url(project_id, source_id), status_code=HTTP_303_SEE_OTHER)

    def _error_page(
        request: Request,
        project_id: UUID,
        source_id: UUID,
        error: str,
    ) -> HTMLResponse:
        project = workspace.load_project(project_id)
        context = _page_context(project_id, source_id, error=error)
        context["project"] = project
        return render(request, "concepts/concept_map.html", context, status_code=422)

    def _page_context(
        project_id: UUID,
        source_id: UUID,
        *,
        error: str | None = None,
    ) -> dict[str, object]:
        concept_map = _load_map(artifacts, project_id, source_id)
        overlay = overlays.load(project_id, source_id)
        effective = concept_map
        overlay_applied = False
        if (
            concept_map is not None
            and overlay is not None
            and overlay.source_fingerprint == concept_map.source_fingerprint
        ):
            effective = overlays.apply(concept_map, overlay)
            overlay_applied = True
        block_texts = _block_texts(artifacts, project_id, source_id)
        source_title = _source_title(workspace, project_id, source_id)
        cells = list(effective.cells) if effective is not None else []
        edges = list(effective.edges) if effective is not None else []
        return {
            "source_id": source_id,
            "source_title": source_title,
            "concept_map": effective,
            "chapters": list(effective.chapters) if effective is not None else [],
            "cells": cells,
            "edges": edges,
            "statistics": effective.statistics if effective is not None else None,
            "needs_review": (
                list(effective.statistics.needs_review) if effective is not None else []
            ),
            "block_texts": block_texts,
            "kind_labels": _KIND_LABELS_FA,
            "agreement_labels": _AGREEMENT_LABELS_FA,
            "edge_labels": _EDGE_LABELS_FA,
            "kind_choices": list(get_args(ConceptCellKind)),
            "edge_choices": list(get_args(ConceptEdgeType)),
            "overlay_version": overlay.version if overlay_applied and overlay else None,
            "error": error or None,
            "cell_rows": [_cell_row(cell, block_texts) for cell in cells],
            "edge_rows": [_edge_row(edge) for edge in edges],
        }


def _load_map(
    artifacts: SourceArtifactStore,
    project_id: UUID,
    source_id: UUID,
) -> SourceConceptMap | None:
    try:
        return artifacts.load_concept_map(project_id, source_id)
    except (FileNotFoundError, ValueError, OSError):
        return None


def _block_texts(
    artifacts: SourceArtifactStore,
    project_id: UUID,
    source_id: UUID,
) -> dict[str, str]:
    try:
        blocks = artifacts.load_blocks(project_id, source_id)
    except (FileNotFoundError, ValueError, OSError):
        return {}
    return {block.block_id: block.text for block in blocks}


def _source_title(workspace: WorkspaceStore, project_id: UUID, source_id: UUID) -> str:
    try:
        manifest = UiSourceManifestStore(workspace.project_dir(project_id)).get(source_id)
    except (FileNotFoundError, ValueError, OSError, KeyError):
        return str(source_id)
    return manifest.title


def _split_ids(raw: str) -> list[str]:
    return [item.strip() for item in raw.replace("،", ",").split(",") if item.strip()]


def _next_cell_key(concept_map: SourceConceptMap, chapter_index: int) -> str:
    numbers = [
        int(cell.cell_key.split("-c")[1])
        for cell in concept_map.cells
        if cell.chapter_index == chapter_index
    ]
    next_number = max(numbers, default=0) + 1
    return f"ch{chapter_index:02d}-c{next_number:03d}"


def _is_cross_chapter(concept_map: SourceConceptMap, source_key: str, target_key: str) -> bool:
    by_key = {cell.cell_key: cell for cell in concept_map.cells}
    left = by_key.get(source_key)
    right = by_key.get(target_key)
    if left is None or right is None:
        return False
    return left.chapter_index != right.chapter_index


def _cell_row(cell: ConceptCell, block_texts: dict[str, str]) -> dict[str, object]:
    traces = []
    for block_id in cell.block_ids:
        text = block_texts.get(block_id, "")
        snippet = text.replace("\n", " ").strip()
        if len(snippet) > 120:
            snippet = snippet[:117] + "…"
        traces.append({"block_id": block_id, "snippet": snippet})
    return {
        "cell": cell,
        "kind_label": _KIND_LABELS_FA.get(cell.kind, cell.kind),
        "traces": traces,
    }


def _edge_row(edge: ConceptEdge) -> dict[str, object]:
    return {
        "edge": edge,
        "key": edge_overlay_key(edge),
        "type_label": _EDGE_LABELS_FA.get(edge.type, edge.type),
    }
