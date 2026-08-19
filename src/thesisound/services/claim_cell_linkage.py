"""Claim ↔ concept-cell linkage and per-cell coverage levels (`10c` P3 Step 5)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from thesisound.concepts import ConceptCell
from thesisound.domain import ClaimRecord, EpisodePlan, EvidenceItem, Script


@dataclass(frozen=True)
class CellCoverage:
    """Whether an in-scope cell has evidence, is in the plan, and was spoken."""

    cell_key: str
    extracted: bool
    planned: bool
    spoken: bool

    @property
    def level(self) -> str | None:
        if self.spoken:
            return "spoken"
        if self.planned:
            return "planned"
        if self.extracted:
            return "extracted"
        return None


def link_claims_to_cells(
    claims: Sequence[ClaimRecord],
    evidence_items: Sequence[EvidenceItem],
    cells: Sequence[ConceptCell],
) -> dict[str, list[str]]:
    """Map each claim to the cells that contain any of its evidence blocks.

    A claim whose evidence sits in several cells is listed against each of them.
    Keys are unique and sorted in book order; the first is the primary cell
    (earliest in the book). Claims with no matching cell map to ``[]``.
    """

    block_ids_by_evidence = {item.evidence_id: item.block_id for item in evidence_items}
    cells_by_block: dict[str, list[str]] = {}
    for cell in sorted(cells, key=lambda item: item.cell_key):
        for block_id in cell.block_ids:
            cells_by_block.setdefault(block_id, []).append(cell.cell_key)

    linked: dict[str, list[str]] = {}
    for claim in claims:
        keys: set[str] = set()
        for evidence_id in claim.evidence_ids:
            block_id = block_ids_by_evidence.get(evidence_id)
            if block_id is None:
                continue
            keys.update(cells_by_block.get(block_id, []))
        linked[claim.claim_id] = sorted(keys)
    return linked


def cell_coverage_levels(
    cells: Sequence[ConceptCell],
    claim_to_cells: Mapping[str, Sequence[str]],
    *,
    plan: EpisodePlan | None = None,
    script: Script | None = None,
) -> dict[str, CellCoverage]:
    """Pure coverage over ledger linkage + plan segments + script turns.

    ``extracted``: at least one claim linked to the cell.
    ``planned``: a linked claim appears in a plan segment.
    ``spoken``: a linked claim appears in a script turn.
    """

    extracted_keys = {key for keys in claim_to_cells.values() for key in keys}
    planned_claim_ids = {
        claim_id
        for segment in (plan.segments if plan is not None else [])
        for claim_id in segment.claim_ids
    }
    spoken_claim_ids = {
        claim_id
        for turn in (script.turns if script is not None else [])
        for claim_id in turn.claim_ids
    }
    planned_keys = {
        key
        for claim_id, keys in claim_to_cells.items()
        if claim_id in planned_claim_ids
        for key in keys
    }
    spoken_keys = {
        key
        for claim_id, keys in claim_to_cells.items()
        if claim_id in spoken_claim_ids
        for key in keys
    }
    return {
        cell.cell_key: CellCoverage(
            cell_key=cell.cell_key,
            extracted=cell.cell_key in extracted_keys,
            planned=cell.cell_key in planned_keys,
            spoken=cell.cell_key in spoken_keys,
        )
        for cell in cells
    }
