from __future__ import annotations

import math
import re
from collections.abc import Iterable

from thesisound import tracing
from thesisound.domain import DocumentMap, DocumentMapSection, ResearchBrief
from thesisound.source_analysis import (
    AnalysisProfile,
    EvidenceExtractionPlan,
    SourceDocumentBlock,
)

_WORD = re.compile(r"\w+", re.UNICODE)
_SELECTION_HEADROOM = 0.10
# Required sections seed the selection so a short episode still touches every part of
# the argument. Before R5 that seeding ran before any budget check and could not be
# stopped by one: a map marking 40 of 47 sections required produced 40 blocks /
# 55,913 tokens against an 18,000-token budget, and the ranking loop below broke on
# its first iteration. Seeds now compete for this share of target_tokens; the rest is
# left to the ranking, which is what lets the best sections get a second block.
_REQUIRED_SEED_BUDGET_SHARE = 0.60
_NOTE_HEADINGS = frozenset(
    {
        "notes",
        "endnotes",
        "footnotes",
        "references",
        "bibliography",
        "works cited",
        "further reading",
        "index",
        "acknowledgements",
        "acknowledgments",
        "یادداشت",
        "یادداشت‌ها",
        "پانویس",
        "پی‌نوشت",
        "منابع",
        "فهرست منابع",
        "کتابنامه",
        "کتاب‌نامه",
        "نمایه",
    }
)
_NOTE_LINE = re.compile(r"^\s*\[?\d{1,3}[\].)]\s", re.MULTILINE)
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
# Second-pass deepening pushes these two levers to the schema ceiling (AnalysisProfile
# caps max_claims_per_block at 12 and neighbor_context_blocks at 2). For today's only
# caller (depth == "extended") the other two levers -- include_examples and
# include_objections_and_responses -- are already forced on by build_analysis_profile,
# so claim capacity and neighbor context are the only levers with real headroom.
_SECOND_PASS_MAX_CLAIMS_PER_BLOCK = 12
_SECOND_PASS_NEIGHBOR_CONTEXT_BLOCKS = 2


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


def build_second_pass_profile(profile: AnalysisProfile) -> AnalysisProfile:
    """Deepen a profile for one re-extraction pass over required-section blocks.

    Ephemeral: the result is never persisted as a source's canonical profile, only
    passed to a single ``extract_source`` call. ``depth`` is left unchanged so the
    second pass stays identifiable as the same analysis tier with every extraction
    lever pushed to its ceiling, rather than a different tier.
    """

    return profile.model_copy(
        update={
            "neighbor_context_blocks": max(
                profile.neighbor_context_blocks, _SECOND_PASS_NEIGHBOR_CONTEXT_BLOCKS
            ),
            "max_claims_per_block": max(
                profile.max_claims_per_block, _SECOND_PASS_MAX_CLAIMS_PER_BLOCK
            ),
            "include_examples": True,
            "include_objections_and_responses": True,
            "rationale": [
                *profile.rationale,
                "Second pass: deepened extraction for a required_for_global_understanding section.",
            ],
        }
    )


def plan_evidence_extraction(
    brief: ResearchBrief,
    document_map: DocumentMap,
    blocks: list[SourceDocumentBlock],
) -> EvidenceExtractionPlan:
    with tracing.span(
        "corpus.plan_extraction", component="corpus", subject_type="source",
        subject_id=str(document_map.source_id),
    ) as span:
        profile = build_analysis_profile(brief)
        content_blocks = [block for block in blocks if block.block_type != "front_matter"]
        if not content_blocks:
            span.measure(selected_count=0, deferred_count=0)
            return EvidenceExtractionPlan(
                source_id=document_map.source_id,
                profile=profile,
                selected_block_ids=[],
                deferred_block_ids=[],
                selected_source_tokens=0,
                total_source_tokens=0,
                achieved_token_coverage=1.0,
            )

        eligible = [block for block in content_blocks if not _is_note_like(block)]
        if not eligible:
            eligible = content_blocks  # never filter a source down to nothing

        block_by_id = {block.block_id: block for block in eligible}
        index_by_id = {block.block_id: index for index, block in enumerate(eligible)}
        section_by_block = {
            block_id: section
            for section in document_map.sections
            for block_id in section.source_block_ids
            if block_id in block_by_id
        }
        total_tokens = sum(block.estimated_token_count for block in eligible)
        coverage_tokens = math.ceil(
            total_tokens * profile.block_coverage_target * (1 + _SELECTION_HEADROOM)
        )
        target_tokens = min(total_tokens, coverage_tokens, profile.evidence_input_token_budget)

        required_sections = [
            section
            for section in document_map.sections
            if section.required_for_global_understanding
        ]
        seed_ids = _required_section_seeds(required_sections, block_by_id)
        seed_allowance = math.ceil(target_tokens * _REQUIRED_SEED_BUDGET_SHARE)

        selected: set[str] = set()
        selected_tokens = 0
        for block_id in sorted(
            seed_ids,
            key=lambda block_id: (
                -_block_score(block_id, section_by_block, brief),
                index_by_id[block_id],
            ),
        ):
            # Checked before the add, so the first seed always lands even when it alone
            # exceeds the allowance -- a required section is never silently dropped.
            if selected and selected_tokens >= seed_allowance:
                break
            selected.add(block_id)
            selected_tokens += block_by_id[block_id].estimated_token_count
        seeded_block_count = len(selected)

        ranked = sorted(
            eligible,
            key=lambda block: (
                -_block_score(block.block_id, section_by_block, brief),
                index_by_id[block.block_id],
            ),
        )
        for block in ranked:
            if selected_tokens >= target_tokens and selected:
                break
            if block.block_id in selected:
                continue
            selected.add(block.block_id)
            selected_tokens += block.estimated_token_count

        selected_ids = [
            block.block_id for block in content_blocks if block.block_id in selected
        ]
        deferred_ids = [
            block.block_id for block in content_blocks if block.block_id not in selected
        ]
        achieved = selected_tokens / total_tokens if total_tokens else 1.0
        largest_selected = max(
            (block_by_id[block_id].estimated_token_count for block_id in selected),
            default=0,
        )
        # Check-before-add lets exactly one block cross the line. Anything past that is
        # a real budget failure and must not be silent again.
        if selected_tokens - largest_selected > profile.evidence_input_token_budget:
            tracing.event(
                "corpus.plan_over_budget",
                component="corpus",
                level="warn",
                subject_type="source",
                subject_id=str(document_map.source_id),
                selected_source_tokens=selected_tokens,
                budget_source_tokens=profile.evidence_input_token_budget,
            )
        # The single most direct cost lever in the corpus stage: every block NOT
        # selected here is a model call that never happens.
        span.measure(
            selected_count=len(selected_ids),
            deferred_count=len(deferred_ids),
            achieved_token_coverage=round(min(1.0, achieved), 4),
            selected_source_tokens=selected_tokens,
            target_source_tokens=target_tokens,
            required_section_count=len(required_sections),
            seeded_block_count=seeded_block_count,
        )
        span.set(depth=profile.depth)
        return EvidenceExtractionPlan(
            source_id=document_map.source_id,
            profile=profile,
            selected_block_ids=selected_ids,
            deferred_block_ids=deferred_ids,
            selected_source_tokens=selected_tokens,
            total_source_tokens=total_tokens,
            achieved_token_coverage=min(1.0, achieved),
            target_source_tokens=target_tokens,
            required_section_count=len(required_sections),
            seeded_block_count=seeded_block_count,
        )


def required_section_block_ids(
    document_map: DocumentMap,
    block_ids: Iterable[str],
) -> set[str]:
    """Subset of ``block_ids`` whose document-map section is globally required.

    Reuses the same section-lookup construction as ``plan_evidence_extraction`` so a
    second extraction pass can target required-section blocks without a dedicated
    field on ``EvidenceExtractionPlan`` -- this is cheap to re-derive from the
    document map already in hand at the call site.
    """

    candidates = set(block_ids)
    section_by_block = {
        block_id: section
        for section in document_map.sections
        for block_id in section.source_block_ids
        if block_id in candidates
    }
    return {
        block_id
        for block_id, section in section_by_block.items()
        if section.required_for_global_understanding
    }


def _required_section_seeds(
    required_sections: list[DocumentMapSection],
    block_by_id: dict[str, SourceDocumentBlock],
) -> list[str]:
    """First eligible block of each globally required section, in document-map order.

    Deduplicated: two sections can share a first eligible block when one of them has no
    eligible block of its own, and a seed must not be paid for twice.
    """

    seeds: list[str] = []
    seen: set[str] = set()
    for section in required_sections:
        first = next(
            (block_id for block_id in section.source_block_ids if block_id in block_by_id),
            None,
        )
        if first is not None and first not in seen:
            seen.add(first)
            seeds.append(first)
    return seeds


def _is_note_like(block: SourceDocumentBlock) -> bool:
    for heading in block.heading_path:
        folded = heading.casefold().strip()
        if any(
            folded == token or folded.startswith(f"{token} ")
            for token in _NOTE_HEADINGS
        ):
            return True
    return len(_NOTE_LINE.findall(block.text)) >= 8


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
