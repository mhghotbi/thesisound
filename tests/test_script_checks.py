from __future__ import annotations

from uuid import uuid4

from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    EpisodePlan,
    EpisodeSegment,
    EvidenceItem,
    Locator,
    Script,
    ScriptTurn,
    SupportStatus,
)
from thesisound.episode import SegmentEvidencePack
from thesisound.script import Glossary
from thesisound.services.script_checks import ScriptChecker
from thesisound.source_analysis import SourceDocumentBlock


def _plan() -> EpisodePlan:
    return EpisodePlan(
        title="طرح",
        listener_outcome="نتیجه",
        estimated_duration_minutes=1,
        segments=[
            EpisodeSegment(
                segment_id="seg-1",
                title="بخش",
                purpose="آزمون",
                estimated_minutes=1,
                claim_ids=["claim-1"],
                key_question="پرسش؟",
                speaker_dynamic="explanation",
            )
        ],
    )


def _block(source_id, text: str) -> SourceDocumentBlock:
    return SourceDocumentBlock(
        block_id="block-1",
        source_id=source_id,
        locator=Locator(page_start=1, page_end=1),
        heading_path=["Section"],
        block_type="argument",
        text=text,
        estimated_token_count=max(1, len(text.split())),
        source_block_keys=["p1"],
    )


def _evidence(source_id, excerpt: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev-1",
        source_id=source_id,
        block_id="block-1",
        claim="مدعا",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt=excerpt,
        locator=Locator(page_start=1, page_end=1),
        support_kind="direct",
        confidence=0.9,
    )


def _claim() -> ClaimRecord:
    return ClaimRecord(
        claim_id="claim-1",
        claim="مدعا",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=["ev-1"],
        support_status=SupportStatus.STRONG,
    )


def _pack(source_id, excerpt: str, *, block_text: str | None = None) -> SegmentEvidencePack:
    text = block_text if block_text is not None else excerpt
    return SegmentEvidencePack(
        segment_id="seg-1",
        claim_ids=["claim-1"],
        evidence_items=[_evidence(source_id, excerpt)],
        original_blocks=[_block(source_id, text)],
        token_budget=100,
        actual_tokens=max(1, len(excerpt.split())),
    )


def _check(*, spoken: str, excerpt: str, editorial_only: bool = False) -> object:
    source_id = uuid4()
    project_id = uuid4()
    turn = ScriptTurn(
        turn_id="t1",
        segment_id="seg-1",
        speaker="A",
        spoken_text_fa=spoken,
        claim_ids=[] if editorial_only else ["claim-1"],
        evidence_ids=[] if editorial_only else ["ev-1"],
        editorial_only=editorial_only,
    )
    return ScriptChecker(words_per_minute=130).check(
        project_id=project_id,
        script=Script(title="متن", turns=[turn]),
        episode_plan=_plan(),
        evidence_packs=[_pack(source_id, excerpt)],
        claims=[_claim()],
        glossary=Glossary(project_id=project_id, model_run_id=uuid4()),
    )


def _unsupported(report) -> list:
    return [issue for issue in report.issues if issue.issue_type == "unsupported_specifics"]


def test_unsupported_specifics_flags_year_absent_from_pack() -> None:
    report = _check(
        spoken="این استدلال در سال 1979 مطرح شد.",
        excerpt="عبارت شاهد بدون تاریخ مشخص.",
    )
    issues = _unsupported(report)
    assert len(issues) == 1
    assert issues[0].severity == "medium"
    assert issues[0].turn_id == "t1"
    assert "1979" in issues[0].explanation
    assert report.verdict == "revise"


def test_unsupported_specifics_accepts_number_present_in_excerpt() -> None:
    report = _check(
        spoken="متن منبع رقم 123 را ذکر می‌کند.",
        excerpt="متن شامل 123 است.",
    )
    assert _unsupported(report) == []


def test_unsupported_specifics_accepts_persian_digits_matching_ascii_excerpt() -> None:
    report = _check(
        spoken="متن منبع رقم ۱۲۳ را ذکر می‌کند.",
        excerpt="متن شامل 123 است.",
    )
    assert _unsupported(report) == []


def test_unsupported_specifics_skips_editorial_only_turns() -> None:
    report = _check(
        spoken="برای فهم بهتر، سال 1979 را در نظر بگیرید.",
        excerpt="عبارت شاهد بدون تاریخ مشخص.",
        editorial_only=True,
    )
    assert _unsupported(report) == []
