from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from thesisound.domain import ClaimRecord, EpisodePlan, EpisodeSegment, EvidenceItem
from thesisound.episode import RetrievalHit, SegmentEvidencePack
from thesisound.modeling import DeterministicValidationError
from thesisound.services.sqlite_block_retriever import SQLiteBlockRetriever
from thesisound.source_analysis import EvidenceExtractionPlan, SourceDocumentBlock


class EvidencePackBuilder:
    def __init__(self, retriever: SQLiteBlockRetriever | None = None) -> None:
        self.retriever = retriever

    def build(
        self,
        *,
        episode_plan: EpisodePlan,
        claims: list[ClaimRecord],
        evidence_items: list[EvidenceItem],
        blocks: list[SourceDocumentBlock],
        extraction_plans: list[EvidenceExtractionPlan],
    ) -> list[SegmentEvidencePack]:
        claim_by_id = {claim.claim_id: claim for claim in claims}
        evidence_by_id = {item.evidence_id: item for item in evidence_items}
        block_by_key = {(block.source_id, block.block_id): block for block in blocks}
        blocks_by_source: dict[UUID, dict[str, SourceDocumentBlock]] = defaultdict(dict)
        for block in blocks:
            blocks_by_source[block.source_id][block.block_id] = block
        neighbors_by_source = {
            plan.source_id: plan.profile.neighbor_context_blocks
            for plan in extraction_plans
        }
        if self.retriever is not None:
            self.retriever.rebuild(blocks)

        packs = [
            self._build_segment(
                segment=segment,
                claim_by_id=claim_by_id,
                evidence_by_id=evidence_by_id,
                block_by_key=block_by_key,
                blocks_by_source=blocks_by_source,
                neighbors_by_source=neighbors_by_source,
            )
            for segment in episode_plan.segments
        ]
        if len(packs) != len(episode_plan.segments):
            raise DeterministicValidationError(
                "Every episode segment must have exactly one evidence pack."
            )
        return packs

    def _build_segment(
        self,
        *,
        segment: EpisodeSegment,
        claim_by_id: dict[str, ClaimRecord],
        evidence_by_id: dict[str, EvidenceItem],
        block_by_key: dict[tuple[UUID, str], SourceDocumentBlock],
        blocks_by_source: dict[UUID, dict[str, SourceDocumentBlock]],
        neighbors_by_source: dict[UUID, int],
    ) -> SegmentEvidencePack:
        claims = []
        for claim_id in segment.claim_ids:
            claim = claim_by_id.get(claim_id)
            if claim is None:
                raise DeterministicValidationError(
                    f"Evidence pack requested unknown claim ID {claim_id}."
                )
            claims.append(claim)

        evidence: list[EvidenceItem] = []
        seen_evidence: set[str] = set()
        for claim in claims:
            for evidence_id in claim.evidence_ids:
                item = evidence_by_id.get(evidence_id)
                if item is None:
                    raise DeterministicValidationError(
                        f"Claim {claim.claim_id} references missing evidence {evidence_id}."
                    )
                if evidence_id not in seen_evidence:
                    evidence.append(item)
                    seen_evidence.add(evidence_id)

        originals: list[SourceDocumentBlock] = []
        seen_blocks: set[tuple[UUID, str]] = set()
        for item in evidence:
            key = (item.source_id, item.block_id)
            block = block_by_key.get(key)
            if block is None:
                raise DeterministicValidationError(
                    f"Evidence {item.evidence_id} references missing source block {item.block_id}."
                )
            if key not in seen_blocks:
                originals.append(block)
                seen_blocks.add(key)

        token_budget = max(1_800, min(18_000, round(segment.estimated_minutes * 1_400)))
        original_tokens = sum(block.estimated_token_count for block in originals)
        warnings: list[str] = []
        if original_tokens > token_budget:
            warnings.append(
                "Required evidence blocks exceed the nominal segment token budget; "
                "grounding was preserved and context was omitted."
            )

        context: list[SourceDocumentBlock] = []
        retrieval_hits: list[RetrievalHit] = []
        context_seen = set(seen_blocks)
        remaining = max(0, token_budget - original_tokens)
        candidates = self._context_candidates(
            originals,
            blocks_by_source=blocks_by_source,
            neighbors_by_source=neighbors_by_source,
        )
        for block in candidates:
            remaining = _append_context(block, context, context_seen, remaining)

        if self.retriever is not None and remaining > 0:
            query = " ".join(
                [
                    segment.title,
                    segment.purpose,
                    segment.key_question,
                    *(claim.claim for claim in claims),
                ]
            )
            source_ids = {item.source_id for item in evidence}
            for hit in self.retriever.search(query, limit=10, source_ids=source_ids):
                block = block_by_key.get((hit.source_id, hit.block_id))
                if block is None:
                    continue
                before = remaining
                remaining = _append_context(block, context, context_seen, remaining)
                if remaining < before:
                    retrieval_hits.append(hit)

        actual_tokens = original_tokens + sum(
            block.estimated_token_count for block in context
        )
        return SegmentEvidencePack(
            segment_id=segment.segment_id,
            claim_ids=segment.claim_ids,
            evidence_items=evidence,
            original_blocks=originals,
            context_blocks=context,
            retrieval_hits=retrieval_hits,
            token_budget=token_budget,
            actual_tokens=actual_tokens,
            warnings=warnings,
        )

    @staticmethod
    def _context_candidates(
        originals: list[SourceDocumentBlock],
        *,
        blocks_by_source: dict[UUID, dict[str, SourceDocumentBlock]],
        neighbors_by_source: dict[UUID, int],
    ) -> list[SourceDocumentBlock]:
        candidates: list[SourceDocumentBlock] = []
        for original in originals:
            source_blocks = blocks_by_source[original.source_id]
            distance = neighbors_by_source.get(original.source_id, 0)
            previous_id = original.previous_block_id
            next_id = original.next_block_id
            for _ in range(distance):
                if previous_id is not None:
                    previous = source_blocks.get(previous_id)
                    if previous is not None:
                        candidates.insert(0, previous)
                        previous_id = previous.previous_block_id
                    else:
                        previous_id = None
                if next_id is not None:
                    following = source_blocks.get(next_id)
                    if following is not None:
                        candidates.append(following)
                        next_id = following.next_block_id
                    else:
                        next_id = None
        return candidates


def _append_context(
    block: SourceDocumentBlock,
    context: list[SourceDocumentBlock],
    seen: set[tuple[UUID, str]],
    remaining: int,
) -> int:
    key = (block.source_id, block.block_id)
    if key in seen or block.estimated_token_count > remaining:
        return remaining
    context.append(block)
    seen.add(key)
    return remaining - block.estimated_token_count
