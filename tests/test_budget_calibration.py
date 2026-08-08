from pathlib import Path
from uuid import uuid4

from thesisound.domain import (
    ClaimType,
    EpisodePlan,
    EpisodeSegment,
    EvidenceItem,
    Locator,
)
from thesisound.episode import SegmentEvidencePack
from thesisound.script import ScriptCheckReport, VerificationDraft
from thesisound.services.budget_calibration import BudgetCalibrationRecorder
from thesisound.source_analysis import SourceDocumentBlock


def test_calibration_requires_three_passing_samples_for_review(tmp_path: Path) -> None:
    recorder = BudgetCalibrationRecorder(tmp_path)
    for duration in (5, 15, 30):
        project_id = uuid4()
        source_id = uuid4()
        locator = Locator(page_start=1, page_end=1)
        block = SourceDocumentBlock(
            block_id="block-1",
            source_id=source_id,
            locator=locator,
            heading_path=[],
            block_type="argument",
            text="Grounded evidence.",
            estimated_token_count=duration * 100,
            source_block_keys=["p1"],
        )
        evidence = EvidenceItem(
            evidence_id="ev-1",
            source_id=source_id,
            block_id=block.block_id,
            claim="Grounded claim.",
            claim_type=ClaimType.AUTHOR_POSITION,
            supporting_excerpt="Grounded evidence",
            locator=locator,
            support_kind="direct",
            confidence=1,
        )
        plan = EpisodePlan(
            title="Test",
            listener_outcome="Test",
            estimated_duration_minutes=duration,
            segments=[
                EpisodeSegment(
                    segment_id="seg-001",
                    title="Test",
                    purpose="Test",
                    estimated_minutes=duration,
                    claim_ids=["clm-1"],
                    key_question="Test?",
                    speaker_dynamic="explanation",
                )
            ],
        )
        report = recorder.record(
            project_id=project_id,
            target_duration_minutes=duration,
            episode_plan=plan,
            evidence_packs=[
                SegmentEvidencePack(
                    segment_id="seg-001",
                    claim_ids=["clm-1"],
                    evidence_items=[evidence],
                    original_blocks=[block],
                    token_budget=max(1_800, duration * 100),
                    actual_tokens=duration * 100,
                )
            ],
            checks=ScriptCheckReport(
                project_id=project_id,
                verdict="pass",
                word_count=duration * 130,
                estimated_minutes=duration,
                substantive_turn_count=1,
            ),
            verification=VerificationDraft(
                verdict="pass",
                issues=[],
                unsupported_claim_ratio=0,
            ),
        )

    assert report.status == "ready_for_review"
    assert report.passing_sample_count == 3
    assert report.median_duration_ratio == 1
    assert report.median_evidence_tokens_per_script_minute == 100
