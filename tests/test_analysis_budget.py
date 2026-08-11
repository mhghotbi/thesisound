from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from thesisound.domain import (
    DocumentMap,
    DocumentMapSection,
    Locator,
    ResearchBrief,
)
from thesisound.services.analysis_profile import (
    build_second_pass_profile,
    plan_evidence_extraction,
    required_section_block_ids,
)
from thesisound.source_analysis import SourceDocumentBlock

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "analysis_profile" / "real_run_selection.json"
_SOURCE_ID = UUID("98863830-8395-447c-a1ac-a3b85560cd98")


def _real_run_inputs() -> tuple[ResearchBrief, DocumentMap, list[SourceDocumentBlock]]:
    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    blocks = [
        SourceDocumentBlock(
            block_id=item["block_id"],
            source_id=_SOURCE_ID,
            locator=Locator(page_start=index + 1, page_end=index + 1),
            heading_path=["Notes"] if item["note_like"] else ["Body"],
            block_type=item["block_type"],
            text=("1. Note.\n" * 9) if item["note_like"] else "Semantic content.",
            estimated_token_count=item["estimated_token_count"],
            source_block_keys=[item["block_id"]],
        )
        for index, item in enumerate(fixture["blocks"])
    ]
    document_map = DocumentMap(
        source_id=_SOURCE_ID,
        scope_locator=Locator(page_start=1, page_end=len(blocks)),
        working_thesis="Fixture thesis.",
        sections=[DocumentMapSection(**section) for section in fixture["sections"]],
    )
    return ResearchBrief.model_validate(fixture["brief"]), document_map, blocks


def test_real_run_selection_respects_the_binding_analysis_budget() -> None:
    brief, document_map, blocks = _real_run_inputs()

    plan = plan_evidence_extraction(brief, document_map, blocks)
    budget = plan.profile.evidence_input_token_budget
    largest = max(
        block.estimated_token_count
        for block in blocks
        if block.block_id in set(plan.selected_block_ids)
    )

    assert plan.total_source_tokens == 258_194
    assert plan.target_source_tokens == budget
    assert plan.required_section_count == 40
    assert plan.selected_source_tokens - largest <= budget
    # `_REQUIRED_SEED_BUDGET_SHARE = 0.60` intentionally fixes these replay values.
    assert len(plan.selected_block_ids) == 13
    assert plan.selected_source_tokens == 18_307
    assert plan.seeded_block_count == 8


def test_real_run_selection_keeps_all_seeds_for_a_long_profile() -> None:
    brief, document_map, blocks = _real_run_inputs()
    long_brief = brief.model_copy(update={"target_duration_minutes": 60})

    first = plan_evidence_extraction(long_brief, document_map, blocks)
    second = plan_evidence_extraction(long_brief, document_map, blocks)

    assert first.target_source_tokens == 108_000
    assert first.seeded_block_count == 40
    assert first.selected_block_ids == second.selected_block_ids


def test_required_section_block_ids_returns_only_required_sections_blocks() -> None:
    document_map = DocumentMap(
        source_id=_SOURCE_ID,
        scope_locator=Locator(page_start=1, page_end=2),
        sections=[
            DocumentMapSection(
                section_id="sec-required",
                source_block_ids=["block-1"],
                title="Required",
                function="argument",
                required_for_global_understanding=True,
            ),
            DocumentMapSection(
                section_id="sec-optional",
                source_block_ids=["block-2"],
                title="Optional",
                function="example",
                required_for_global_understanding=False,
            ),
        ],
    )

    assert required_section_block_ids(document_map, ["block-1", "block-2"]) == {"block-1"}
    # A required block outside the passed-in scope is not returned.
    assert required_section_block_ids(document_map, ["block-2"]) == set()
    assert required_section_block_ids(document_map, []) == set()


def test_build_second_pass_profile_raises_levers_to_the_ceiling() -> None:
    brief, document_map, blocks = _real_run_inputs()
    profile = plan_evidence_extraction(brief, document_map, blocks).profile
    # The fixture brief resolves to the brief tier: neither lever starts at the ceiling.
    assert profile.neighbor_context_blocks == 0
    assert profile.max_claims_per_block == 2

    deepened = build_second_pass_profile(profile)

    assert deepened.depth == profile.depth
    assert deepened.neighbor_context_blocks == 2
    assert deepened.max_claims_per_block == 12
    assert deepened.include_examples is True
    assert deepened.include_objections_and_responses is True
    assert deepened.rationale[-1].startswith("Second pass:")
    # model_copy leaves the original untouched.
    assert profile.neighbor_context_blocks == 0
