from __future__ import annotations

import math
import re

from thesisound.domain import DocumentMap, ResearchBrief
from thesisound.source_analysis import (
    AnalysisProfile,
    EvidenceExtractionPlan,
    SourceDocumentBlock,
)

_WORD = re.compile(r"\w+", re.UNICODE)
_FUNCTION_WEIGHT = {
    "definition": 80,
    "argument": 75,
    "conclusion": 70,
    "response": 55,
    "objection": 50,
    "example": 30,
    "other": 25,
    "transition": 10,
    "front_matter": 0,
}


def build_analysis_profile(brief: ResearchBrief) -> AnalysisProfile:
    duration = brief.target_duration_minutes
    if duration <= 10:
        depth = "brief"
        coverage = 0.35
        max_claims = 2
        neighbors = 0
    elif duration <= 25:
        depth = "standard"
        coverage = 0.60
        max_claims = 3
        neighbors = 0
    elif duration <= 45:
        depth = "deep"
        coverage = 0.85
        max_claims = 5
        neighbors = 1
    else:
        depth = "extended"
        coverage = 1.0
        max_claims = 7
        neighbors = 2

    critical_mode = bool({"critical", "debate"} & set(brief.modes))
    if critical_mode:
        coverage = min(1.0, coverage + 0.10)
    if brief.prior_knowledge == "advanced":
        max_claims = min(12, max_claims + 1)
        neighbors = min(2, neighbors + 1)

    token_budget = max(12_000, min(180_000, duration * 1_800))
    rationale = [
        f"Duration {duration} minutes maps to the {depth} analysis tier.",
        "Block construction and document mapping remain output-independent.",
        "Evidence breadth and per-block depth are output-dependent.",
    ]
    if critical_mode:
        rationale.append("Critical/debate mode increases objection-response coverage.")
    if brief.prior_knowledge == "advanced":
        rationale.append("Advanced prior knowledge increases claim and context depth.")

    return AnalysisProfile(
        depth=depth,
        target_duration_minutes=duration,
        block_coverage_target=coverage,
        evidence_input_token_budget=token_budget,
        max_claims_per_block=max_claims,
        neighbor_context_blocks=neighbors,
        include_examples=depth != "brief",
        include_objections_and_responses=critical_mode or depth in {"deep", "extended"},
        second_pass_for_core_sections=depth == "extended",
        rationale=rationale,
    )


def plan_evidence_extraction(
    brief: ResearchBrief,
    document_map: DocumentMap,
    blocks: list[SourceDocumentBlock],
) -> EvidenceExtractionPlan:
    profile = build_analysis_profile(brief)
    content_blocks = [block for block in blocks if block.block_type != "front_matter"]
    if not content_blocks:
        return EvidenceExtractionPlan(
            source_id=document_map.source_id,
            profile=profile,
            selected_block_ids=[],
            deferred_block_ids=[],
            selected_source_tokens=0,
            total_source_tokens=0,
            achieved_token_coverage=1.0,
        )

    block_by_id = {block.block_id: block for block in content_blocks}
    index_by_id = {block.block_id: index for index, block in enumerate(content_blocks)}
    section_by_block = {
        block_id: section
        for section in document_map.sections
        for block_id in section.source_block_ids
        if block_id in block_by_id
    }
    total_tokens = sum(block.estimated_token_count for block in content_blocks)
    coverage_tokens = math.ceil(total_tokens * profile.block_coverage_target)
    target_tokens = min(total_tokens, coverage_tokens, profile.evidence_input_token_budget)

    selected: set[str] = set()
    required_sections = [
        section
        for section in document_map.sections
        if section.required_for_global_understanding
    ]
    for section in required_sections:
        first = next(
            (block_id for block_id in section.source_block_ids if block_id in block_by_id),
            None,
        )
        if first is not None:
            selected.add(first)

    ranked = sorted(
        content_blocks,
        key=lambda block: (
            -_block_score(block.block_id, section_by_block, brief),
            index_by_id[block.block_id],
        ),
    )
    selected_tokens = sum(block_by_id[block_id].estimated_token_count for block_id in selected)
    for block in ranked:
        if selected_tokens >= target_tokens and selected:
            break
        if block.block_id in selected:
            continue
        selected.add(block.block_id)
        selected_tokens += block.estimated_token_count

    selected_ids = [block.block_id for block in content_blocks if block.block_id in selected]
    deferred_ids = [block.block_id for block in content_blocks if block.block_id not in selected]
    achieved = selected_tokens / total_tokens if total_tokens else 1.0
    return EvidenceExtractionPlan(
        source_id=document_map.source_id,
        profile=profile,
        selected_block_ids=selected_ids,
        deferred_block_ids=deferred_ids,
        selected_source_tokens=selected_tokens,
        total_source_tokens=total_tokens,
        achieved_token_coverage=min(1.0, achieved),
    )


def _block_score(block_id: str, section_by_block: dict, brief: ResearchBrief) -> int:
    section = section_by_block.get(block_id)
    if section is None:
        return 0
    score = _FUNCTION_WEIGHT.get(section.function, 20)
    if section.required_for_global_understanding:
        score += 100
    if section.function in {"objection", "response"} and (
        {"critical", "debate"} & set(brief.modes)
    ):
        score += 35
    intent = " ".join(
        [
            brief.normalized_topic,
            brief.central_question,
            *brief.subquestions,
            *brief.scope_inclusions,
        ]
    )
    section_text = " ".join([section.title, *section.key_concepts])
    score += min(30, 5 * len(_terms(intent) & _terms(section_text)))
    return score


def _terms(text: str) -> set[str]:
    return {token.casefold() for token in _WORD.findall(text) if len(token) > 2}
