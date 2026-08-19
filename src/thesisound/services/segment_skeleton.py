"""Deterministic segment skeleton for one `LessonPart` (`10b` B1.6; `10c` P3 Step 7)."""

from __future__ import annotations

from collections.abc import Sequence

from thesisound.concepts import ConceptCell, ConceptEdge, LessonPart, SegmentSkeleton
from thesisound.domain import ClaimRecord, EvidenceItem
from thesisound.services.claim_cell_linkage import link_claims_to_cells

_ORDERING_EDGE_TYPES = frozenset({"prerequisite", "depends_on"})
_SPEAKER_DYNAMIC_BY_KIND: dict[str, str] = {
    "definition": "explanation",
    "argument": "explanation",
    "position": "explanation",
    "thread": "explanation",
    "distinction": "comparison",
    "objection": "critique",
    "response": "critique",
    "example": "questioning",
}
_RECAP_TITLE_FA = "مرور"
_RECAP_MINUTES = 1.5


def build(
    part: LessonPart,
    cells: Sequence[ConceptCell],
    claims: Sequence[ClaimRecord],
    evidence_items: Sequence[EvidenceItem],
    edges: Sequence[ConceptEdge],
) -> list[SegmentSkeleton]:
    """One segment per in-scope cell of ``part``, in packer order, plus a recap.

    A cell with no linked claim cannot form a valid segment (the writer needs
    at least one grounded claim) and is silently skipped here; it surfaces
    instead as "not covered: no claim" in the completion report (`10c` P3
    Step 11). ``claim_ids`` per cell follow block order within that cell;
    ``prerequisite_claim_ids`` are the claim_ids of this cell's
    `prerequisite`/`depends_on` cells that appear earlier in the same part. A
    trailing editorial recap segment (no claims) is appended once the part has
    three or more real segments.
    """

    cells_by_key = {cell.cell_key: cell for cell in cells if cell.cell_key in part.cell_keys}
    part_cells = [cells_by_key[key] for key in part.cell_keys]
    claim_to_cells = link_claims_to_cells(claims, evidence_items, part_cells)
    claims_by_id = {claim.claim_id: claim for claim in claims}
    block_id_by_evidence = {item.evidence_id: item.block_id for item in evidence_items}

    claim_ids_by_cell: dict[str, list[str]] = {key: [] for key in part.cell_keys}
    for claim_id, cell_keys in claim_to_cells.items():
        if cell_keys:
            claim_ids_by_cell[cell_keys[0]].append(claim_id)

    for key in part.cell_keys:
        block_position = {
            block_id: index for index, block_id in enumerate(cells_by_key[key].block_ids)
        }

        def _position(claim_id: str, block_position: dict[str, int] = block_position) -> int:
            claim = claims_by_id[claim_id]
            positions = [
                block_position[block_id_by_evidence[evidence_id]]
                for evidence_id in claim.evidence_ids
                if evidence_id in block_id_by_evidence
                and block_id_by_evidence[evidence_id] in block_position
            ]
            return min(positions) if positions else 0

        claim_ids_by_cell[key].sort(key=lambda claim_id: (_position(claim_id), claim_id))

    prerequisites_by_cell = _prerequisite_index(edges)

    segments: list[SegmentSkeleton] = []
    for index, key in enumerate(part.cell_keys, start=1):
        cell_claim_ids = claim_ids_by_cell.get(key, [])
        if not cell_claim_ids:
            continue
        cell = cells_by_key[key]
        earlier = set(part.cell_keys[: index - 1])
        prereq_keys = sorted(
            (p for p in prerequisites_by_cell.get(key, ()) if p in earlier),
            key=part.cell_keys.index,
        )
        prerequisite_claim_ids: list[str] = []
        for prereq_key in prereq_keys:
            for claim_id in claim_ids_by_cell.get(prereq_key, ()):
                if claim_id not in prerequisite_claim_ids:
                    prerequisite_claim_ids.append(claim_id)
        segments.append(
            SegmentSkeleton(
                segment_index=len(segments) + 1,
                cell_key=key,
                title_fa=cell.label_fa,
                claim_ids=cell_claim_ids,
                estimated_minutes=cell.estimated_minutes,
                speaker_dynamic=_SPEAKER_DYNAMIC_BY_KIND[cell.kind],
                prerequisite_claim_ids=prerequisite_claim_ids,
            )
        )

    if len(segments) >= 3:
        segments.append(
            SegmentSkeleton(
                segment_index=len(segments) + 1,
                cell_key=None,
                title_fa=_RECAP_TITLE_FA,
                claim_ids=[],
                estimated_minutes=_RECAP_MINUTES,
                speaker_dynamic="recap",
                prerequisite_claim_ids=[],
            )
        )
    return segments


def _prerequisite_index(edges: Sequence[ConceptEdge]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for edge in edges:
        if edge.type not in _ORDERING_EDGE_TYPES:
            continue
        index.setdefault(edge.target_key, []).append(edge.source_key)
    return index
