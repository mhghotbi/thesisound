from __future__ import annotations

from typing import Protocol

from thesisound.domain import ClaimRecord, ClaimType, EvidenceItem
from thesisound.source_analysis import AnalysisProfile


class _HasBlockId(Protocol):
    block_id: str


def extraction_profiles_compatible(
    stored: AnalysisProfile,
    current: AnalysisProfile,
) -> bool:
    """Whether prior block extractions remain valid under the current profile.

    Selection budget and coverage targets can change without invalidating a block's
    extraction contract. Depth, claim caps, neighbor context, and category flags do
    change what the extractor is asked to produce, so those must match.
    """

    return (
        stored.depth == current.depth
        and stored.max_claims_per_block == current.max_claims_per_block
        and stored.neighbor_context_blocks == current.neighbor_context_blocks
        and stored.include_examples == current.include_examples
        and stored.include_objections_and_responses
        == current.include_objections_and_responses
        and stored.second_pass_for_core_sections == current.second_pass_for_core_sections
    )


def scope_claims_and_evidence(
    claims: list[ClaimRecord],
    evidence_items: list[EvidenceItem],
    selected_block_ids: set[str] | list[str],
) -> tuple[list[ClaimRecord], list[EvidenceItem]]:
    """Keep only evidence and claims that belong to the current selected blocks.

    A claim stays when every evidence_id it cites is in-scope. Claims that depend on
    deferred-block evidence are dropped. Editorial claims with no evidence_ids remain.
    """

    selected = set(selected_block_ids)
    scoped_evidence = [item for item in evidence_items if item.block_id in selected]
    in_scope_ids = {item.evidence_id for item in scoped_evidence}
    scoped_claims: list[ClaimRecord] = []
    for claim in claims:
        if not claim.evidence_ids:
            if claim.claim_type == ClaimType.EDITORIAL_EXPLANATION:
                scoped_claims.append(claim)
            continue
        if all(evidence_id in in_scope_ids for evidence_id in claim.evidence_ids):
            scoped_claims.append(claim)
    return scoped_claims, scoped_evidence


def scope_by_block[T: _HasBlockId](
    items: list[T],
    selected_block_ids: set[str] | list[str],
) -> list[T]:
    """Keep only items whose block_id is in the current selection.

    Generic over the six auxiliary-evidence types on ``ClaimLedger`` (definitions,
    distinctions, examples, objections, responses, must_not_be_lost) -- all share a
    ``block_id`` attribute, so one scoping function replaces six near-identical ones.
    """

    selected = set(selected_block_ids)
    return [item for item in items if item.block_id in selected]
