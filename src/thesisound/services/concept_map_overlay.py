"""Per-project owner corrections layered on a cached concept map.

The AI map in the shared cache is never rewritten. Effective map = cache ⊕ overlay.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from thesisound.concepts import (
    ConceptCell,
    ConceptCellTier,
    ConceptEdge,
    ConceptMapOverlay,
    SourceConceptMap,
)
from thesisound.services.concept_map_builder import compute_statistics
from thesisound.services.source_artifact_store import SourceArtifactStore

_EDGE_KEY_SEP = "|"


def edge_overlay_key(edge: ConceptEdge) -> str:
    """Stable overlay identity: ``source_key|target_key|type`` (B1.3)."""

    return f"{edge.source_key}{_EDGE_KEY_SEP}{edge.target_key}{_EDGE_KEY_SEP}{edge.type}"


class ConceptMapOverlayService:
    """Load, apply, and record overlay edits under ``sources/<sid>/``."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()

    def path(self, project_id: UUID, source_id: UUID) -> Path:
        return (
            self.workspace_root
            / str(project_id)
            / "sources"
            / str(source_id)
            / "concept-map-overlay.json"
        )

    def load(self, project_id: UUID, source_id: UUID) -> ConceptMapOverlay | None:
        path = self.path(project_id, source_id)
        try:
            return ConceptMapOverlay.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def save(
        self,
        project_id: UUID,
        source_id: UUID,
        overlay: ConceptMapOverlay,
    ) -> Path:
        path = self.path(project_id, source_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(overlay.model_dump(mode="json"), ensure_ascii=False, indent=2)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(payload + "\n", encoding="utf-8")
        temporary.replace(path)
        return path

    def apply(
        self,
        concept_map: SourceConceptMap,
        overlay: ConceptMapOverlay,
    ) -> SourceConceptMap:
        """Return the effective map. Does not write the shared AI cache."""

        if overlay.source_fingerprint != concept_map.source_fingerprint:
            raise ValueError(
                "Overlay fingerprint does not match the concept map "
                f"({overlay.source_fingerprint} != {concept_map.source_fingerprint})."
            )
        removed_cells = set(overlay.removed_cell_keys)
        cells = [cell for cell in concept_map.cells if cell.cell_key not in removed_cells]
        present = {cell.cell_key for cell in cells}
        for cell in overlay.added_cells:
            user_cell = cell.model_copy(update={"created_by": "user"})
            if user_cell.cell_key in present:
                cells = [
                    user_cell if item.cell_key == user_cell.cell_key else item for item in cells
                ]
            else:
                cells.append(user_cell)
                present.add(user_cell.cell_key)
        for cell_key, tier in overlay.tier_overrides.items():
            cells = [
                (
                    cell.model_copy(update={"tier": tier, "tier_promoted": False})
                    if cell.cell_key == cell_key
                    else cell
                )
                for cell in cells
            ]
        known = {cell.cell_key for cell in cells}
        removed_edges = set(overlay.removed_edge_keys)
        added_edge_keys = {edge_overlay_key(edge) for edge in overlay.added_edges}
        edges: list[ConceptEdge] = []
        seen: set[str] = set()
        for edge in [*concept_map.edges, *overlay.added_edges]:
            key = edge_overlay_key(edge)
            if key in removed_edges or key in seen:
                continue
            if edge.source_key not in known or edge.target_key not in known:
                continue
            seen.add(key)
            if key in added_edge_keys:
                edges.append(edge.model_copy(update={"created_by": "user"}))
            else:
                edges.append(edge)
        updated = concept_map.model_copy(update={"cells": cells, "edges": edges})
        return updated.model_copy(update={"statistics": compute_statistics(updated)})

    def record_edit(
        self,
        project_id: UUID,
        source_id: UUID,
        *,
        source_fingerprint: str,
        add_cell: ConceptCell | None = None,
        remove_cell_key: str | None = None,
        add_edge: ConceptEdge | None = None,
        remove_edge_key: str | None = None,
        tier_override: tuple[str, ConceptCellTier] | None = None,
    ) -> ConceptMapOverlay:
        """Persist one owner edit. Rebuilds never read this file to write the AI map."""

        overlay = self.load(project_id, source_id)
        if overlay is None or overlay.source_fingerprint != source_fingerprint:
            overlay = ConceptMapOverlay(source_fingerprint=source_fingerprint, version=1)
        else:
            overlay = overlay.model_copy(update={"version": overlay.version + 1})

        added_cells = list(overlay.added_cells)
        removed_cell_keys = list(overlay.removed_cell_keys)
        added_edges = list(overlay.added_edges)
        removed_edge_keys = list(overlay.removed_edge_keys)
        tier_overrides = dict(overlay.tier_overrides)

        if add_cell is not None:
            cell = add_cell.model_copy(update={"created_by": "user"})
            added_cells = [item for item in added_cells if item.cell_key != cell.cell_key]
            added_cells.append(cell)
            removed_cell_keys = [key for key in removed_cell_keys if key != cell.cell_key]
        if remove_cell_key is not None:
            added_cells = [item for item in added_cells if item.cell_key != remove_cell_key]
            if remove_cell_key not in removed_cell_keys:
                removed_cell_keys.append(remove_cell_key)
            tier_overrides.pop(remove_cell_key, None)
        if add_edge is not None:
            edge = add_edge.model_copy(update={"created_by": "user"})
            key = edge_overlay_key(edge)
            added_edges = [item for item in added_edges if edge_overlay_key(item) != key]
            added_edges.append(edge)
            removed_edge_keys = [item for item in removed_edge_keys if item != key]
        if remove_edge_key is not None:
            added_edges = [
                item for item in added_edges if edge_overlay_key(item) != remove_edge_key
            ]
            if remove_edge_key not in removed_edge_keys:
                removed_edge_keys.append(remove_edge_key)
        if tier_override is not None:
            cell_key, tier = tier_override
            tier_overrides[cell_key] = tier

        overlay = overlay.model_copy(
            update={
                "added_cells": added_cells,
                "removed_cell_keys": removed_cell_keys,
                "added_edges": added_edges,
                "removed_edge_keys": removed_edge_keys,
                "tier_overrides": tier_overrides,
            }
        )
        self.save(project_id, source_id, overlay)
        return overlay


def effective_concept_map(
    store: SourceArtifactStore,
    project_id: UUID,
    source_id: UUID,
) -> SourceConceptMap | None:
    """The map every planner must reason about: cache ⊕ overlay, or ``None`` if unmapped.

    One definition on purpose. Extraction planning is now cell-seeded for
    ``source_coverage`` (``resolve_extraction_seeds``), so any caller that
    reconstructs a plan -- the real planner, the reuse check, the duration cost
    predictor -- has to see the same map, including the owner's edits. A caller
    that skipped the overlay, or the map entirely, would compute a different plan
    from the stored one and mistake that for a reason to re-extract.
    """

    concept_map = store.load_concept_map_optional(project_id, source_id)
    if concept_map is None:
        return None
    overlay_service = ConceptMapOverlayService(store.workspace_root)
    overlay = overlay_service.load(project_id, source_id)
    if overlay is None:
        return concept_map
    return overlay_service.apply(concept_map, overlay)
