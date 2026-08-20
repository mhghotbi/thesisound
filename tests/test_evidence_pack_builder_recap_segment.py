"""`EvidencePackBuilder` must build a pack for a claimless recap segment.

Regression for a real crash at checkpoint C-D (2026-08-20): the deterministic
`source_coverage` skeleton (`10b` B1.6) appends a trailing editorial recap
segment with `claim_ids=[]`; `EvidencePackBuilder.build` always builds one
pack per segment (`write_script` requires every segment to have one), but
`SegmentEvidencePack` required at least one claim/evidence/block, so building
a plan with a recap segment always raised a pydantic `ValidationError`.
"""

from __future__ import annotations

from uuid import uuid4

from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    EpisodePlan,
    EpisodeSegment,
    EvidenceItem,
    Locator,
    SupportStatus,
)
from thesisound.services.evidence_pack_builder import EvidencePackBuilder
from thesisound.source_analysis import AnalysisProfile, EvidenceExtractionPlan, SourceDocumentBlock

_SOURCE_ID = uuid4()


def test_a_recap_segment_with_no_claims_still_gets_a_valid_empty_pack() -> None:
    claim = ClaimRecord(
        claim_id="clm-1",
        claim="مدعا",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=["ev-1"],
        support_status=SupportStatus.STRONG,
    )
    evidence = EvidenceItem(
        evidence_id="ev-1",
        source_id=_SOURCE_ID,
        block_id="block-1",
        claim="مدعا",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt="نقل قول",
        locator=Locator(page_start=1, page_end=1),
        support_kind="direct",
        confidence=0.9,
    )
    block = SourceDocumentBlock(
        block_id="block-1",
        source_id=_SOURCE_ID,
        locator=Locator(page_start=1, page_end=1),
        heading_path=[],
        block_type="other",
        text="متن بلوک.",
        estimated_token_count=20,
        source_block_keys=["p1"],
    )
    plan = EpisodePlan(
        title="عنوان",
        listener_outcome="فهم",
        estimated_duration_minutes=5.5,
        segments=[
            EpisodeSegment(
                segment_id="seg-001",
                title="بخش",
                purpose="شرح",
                estimated_minutes=4.0,
                claim_ids=["clm-1"],
                key_question="چرا؟",
                speaker_dynamic="explanation",
            ),
            EpisodeSegment(
                segment_id="seg-002",
                title="مرور",
                purpose="مرور نکات",
                estimated_minutes=1.5,
                claim_ids=[],
                key_question="مرور",
                speaker_dynamic="recap",
            ),
        ],
    )
    extraction_plan = EvidenceExtractionPlan(
        source_id=_SOURCE_ID,
        profile=AnalysisProfile(
            depth="standard",
            target_duration_minutes=10,
            block_coverage_target=0.6,
            evidence_input_token_budget=18_000,
            max_claims_per_block=3,
            neighbor_context_blocks=0,
            include_examples=True,
            second_pass_for_core_sections=False,
        ),
        selected_block_ids=["block-1"],
        selected_source_tokens=20,
        total_source_tokens=20,
        achieved_token_coverage=1.0,
    )

    packs = EvidencePackBuilder().build(
        episode_plan=plan,
        claims=[claim],
        evidence_items=[evidence],
        blocks=[block],
        extraction_plans=[extraction_plan],
    )

    assert len(packs) == 2
    recap_pack = packs[1]
    assert recap_pack.segment_id == "seg-002"
    assert recap_pack.claim_ids == []
    assert recap_pack.evidence_items == []
    assert recap_pack.original_blocks == []
    assert recap_pack.actual_tokens == 0
