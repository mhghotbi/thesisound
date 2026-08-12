from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    EpisodePlan,
    EpisodeSegment,
    EvidenceItem,
    Locator,
    MustNotBeLostPoint,
    Script,
    ScriptTurn,
    SupportStatus,
)
from thesisound.episode import (
    MustNotBeLostReview,
    MustNotBeLostReviewItem,
    SegmentEvidencePack,
)
from thesisound.modeling import DeterministicValidationError
from thesisound.script import Glossary, ScriptTurnDraft, SegmentScriptDraft
from thesisound.services.persian_script_writer import (
    SpeakerBalancePolicy,
    _validate_segment_draft,
)
from thesisound.services.script_checks import ScriptChecker

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "script_dialogue_quality"
_SOURCE_ID = UUID("98863830-8395-447c-a1ac-a3b85560cd98")


def _segment(*claim_ids: str, segment_id: str = "seg-001") -> EpisodeSegment:
    return EpisodeSegment(
        segment_id=segment_id,
        title="بخش",
        purpose="آزمون",
        estimated_minutes=2,
        claim_ids=list(claim_ids or ("clm-1",)),
        key_question="پرسش چیست؟",
        speaker_dynamic="questioning",
    )


def _evidence(evidence_id: str = "ev-1") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source_id=_SOURCE_ID,
        block_id="blk-1",
        claim="مدعا",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt="عبارت شاهد",
        locator=Locator(page_start=1, page_end=1),
        support_kind="direct",
        confidence=0.9,
    )


def _claim(claim_id: str = "clm-1", *, evidence_id: str = "ev-1") -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        claim="مدعا",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=[evidence_id],
        support_status=SupportStatus.STRONG,
    )


def _check(
    script: Script,
    *,
    plan: EpisodePlan | None = None,
    claims: list[ClaimRecord] | None = None,
    packs: list[SegmentEvidencePack] | None = None,
    speaker_balance_violations: dict[str, list[str]] | None = None,
    must_not_be_lost_review: MustNotBeLostReview | None = None,
    words_per_minute: int = 130,
):
    project_id = uuid4()
    claim_ids = sorted(
        {claim_id for turn in script.turns for claim_id in turn.claim_ids} or {"clm-1"}
    )
    evidence_ids = sorted(
        {evidence_id for turn in script.turns for evidence_id in turn.evidence_ids} or {"ev-1"}
    )
    episode_plan = plan or EpisodePlan(
        title="عنوان",
        listener_outcome="نتیجه",
        estimated_duration_minutes=max(1, round(len(script.turns) * 0.5)),
        segments=[_segment(*claim_ids)],
    )
    if packs is None:
        packs = [
            SegmentEvidencePack.model_construct(
                segment_id=segment.segment_id,
                claim_ids=list(segment.claim_ids),
                evidence_items=[_evidence(evidence_id) for evidence_id in evidence_ids],
                original_blocks=[],
                token_budget=1,
                actual_tokens=0,
            )
            for segment in episode_plan.segments
        ]
    if claims is None:
        claims = []
        seen: set[str] = set()
        for turn in script.turns:
            for claim_id, evidence_id in zip(turn.claim_ids, turn.evidence_ids, strict=False):
                if claim_id not in seen:
                    claims.append(_claim(claim_id, evidence_id=evidence_id))
                    seen.add(claim_id)
        if not claims:
            claims = [_claim()]
    return ScriptChecker(words_per_minute=words_per_minute).check(
        project_id=project_id,
        script=script,
        episode_plan=episode_plan,
        evidence_packs=packs,
        claims=claims,
        glossary=Glossary(project_id=project_id, model_run_id=uuid4()),
        speaker_balance_violations=speaker_balance_violations,
        must_not_be_lost_review=must_not_be_lost_review,
    )


def _words(count: int, token: str = "متن") -> str:
    return " ".join([token] * count)


def test_speaker_balance_violation_is_recorded_but_does_not_block_verdict() -> None:
    """Style/format checks are recorded at low severity, not blocking (MVP policy, 2026-08-13).

    Content grounding matters more than dialogue polish for now; C1's
    high-severity promotion is deliberately reverted here.
    """

    script = Script(
        title="عنوان",
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa=_words(20, "مطلب"),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
            ScriptTurn(
                turn_id="t2",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa=_words(20, "پاسخ"),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
        ],
    )
    report = _check(
        script,
        speaker_balance_violations={"seg-001": ["F1 editorial words are 40%"]},
        words_per_minute=20,
    )
    assert report.verdict == "pass"
    assert any(
        issue.issue_type == "speaker_balance" and issue.severity == "low"
        for issue in report.issues
    )


def test_writer_still_completes_on_final_attempt() -> None:
    draft = SegmentScriptDraft(
        turns=[
            ScriptTurnDraft(
                speaker="B",
                spoken_text_fa=_words(4),
                editorial_only=True,
            ),
            ScriptTurnDraft(
                speaker="A",
                spoken_text_fa=_words(1),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
        ]
    )
    recorded: list[str] = []
    _validate_segment_draft(
        draft,
        allowed_claim_ids={"clm-1"},
        allowed_evidence_ids={"ev-1"},
        segment=_segment("clm-1", "clm-2"),
        policy=SpeakerBalancePolicy(),
        is_opening=False,
        attempt={"n": 0},
        max_attempts=1,
        violations=recorded,
    )
    assert recorded
    assert all(item.startswith("F") for item in recorded)


def test_editorial_ratio_threshold() -> None:
    high = Script(
        title="عنوان",
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa=_words(314, "تحریر"),
                editorial_only=True,
            ),
            ScriptTurn(
                turn_id="t2",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa=_words(686, "مطلب"),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
        ],
    )
    low = Script(
        title="عنوان",
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa=_words(24, "تحریر"),
                editorial_only=True,
            ),
            ScriptTurn(
                turn_id="t2",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa=_words(76, "مطلب"),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
        ],
    )
    high_report = _check(high, words_per_minute=1000)
    low_report = _check(low, words_per_minute=100)
    assert any(issue.issue_type == "editorial_ratio" for issue in high_report.issues)
    assert not any(issue.issue_type == "editorial_ratio" for issue in low_report.issues)


def test_speaker_skew_threshold() -> None:
    skewed = Script(
        title="عنوان",
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa=_words(757, "مطلب"),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
            ScriptTurn(
                turn_id="t2",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa=_words(355, "مطلب"),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
        ],
    )
    balanced = Script(
        title="عنوان",
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa=_words(600, "مطلب"),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
            ScriptTurn(
                turn_id="t2",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa=_words(500, "مطلب"),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
        ],
    )
    skewed_report = _check(skewed, words_per_minute=2000)
    balanced_report = _check(balanced, words_per_minute=2000)
    assert any(issue.issue_type == "speaker_skew" for issue in skewed_report.issues)
    assert not any(issue.issue_type == "speaker_skew" for issue in balanced_report.issues)


def test_restatement_detects_both_speakers() -> None:
    script = Script(
        title="عنوان",
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa="دقیقاً این یک گذار است",
                editorial_only=True,
            ),
            ScriptTurn(
                turn_id="t2",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa="بله، دقیقاً پرسش بعدی چیست؟",
                editorial_only=True,
            ),
            ScriptTurn(
                turn_id="t3",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa=_words(40, "مطلب"),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
            ScriptTurn(
                turn_id="t4",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa=_words(40, "مطلب"),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
        ],
    )
    report = _check(script, words_per_minute=40)
    restatement_turns = {
        issue.turn_id
        for issue in report.issues
        if issue.issue_type == "restatement" and issue.turn_id
    }
    assert restatement_turns >= {"t1", "t2"}


def test_restatement_ignores_midsentence_filler_in_substantive_turn() -> None:
    script = Script(
        title="عنوان",
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa="مدعای اصلی این است که در واقع نتیجه روشن است و ادامه دارد",
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
            ScriptTurn(
                turn_id="t2",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa=_words(40, "مطلب"),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
        ],
    )
    report = _check(script, words_per_minute=40)
    assert not any(issue.issue_type == "restatement" for issue in report.issues)


def test_repetition_near_duplicate() -> None:
    base = "این مطلب مهم است چون دلیل اصلی روشن و قابل توضیح برای شنونده است"
    near = "این مطلب مهم است چون دلیل اصلی روشن و قابل بیان برای شنونده است"
    script = Script(
        title="عنوان",
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa=base,
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
            ScriptTurn(
                turn_id="t2",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa=near,
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
        ],
    )
    report = _check(script, words_per_minute=20)
    assert any(
        issue.issue_type == "repetition" and issue.severity == "high"
        for issue in report.issues
    )


def test_repetition_exact_duplicate_is_blocking() -> None:
    text = "این یک جمله تکراری بلند برای آزمون تکرار دقیق گفتار است"
    script = Script(
        title="عنوان",
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa=text,
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
            ScriptTurn(
                turn_id="t2",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa=text,
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
        ],
    )
    report = _check(script, words_per_minute=20)
    assert report.verdict == "reject"
    assert any(
        issue.issue_type == "repetition" and issue.severity == "blocking"
        for issue in report.issues
    )


def test_dropped_content_flags_unreached_point() -> None:
    project_id = uuid4()
    script = Script(
        title="عنوان",
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa=_words(40, "مطلب"),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
            ScriptTurn(
                turn_id="t2",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa=_words(40, "پاسخ"),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
        ],
    )
    review = MustNotBeLostReview(
        project_id=project_id,
        unused_count=1,
        items=[
            MustNotBeLostReviewItem(
                point=MustNotBeLostPoint(
                    text="نکته حیاتی که نباید از دست برود در گفتار",
                    source_id=_SOURCE_ID,
                    block_id="blk-9",
                    locator=Locator(),
                ),
                reflected_in_claims=["clm-missing"],
                used_in_plan=True,
            )
        ],
    )
    report = _check(script, must_not_be_lost_review=review, words_per_minute=40)
    assert any(
        issue.issue_type == "dropped_content" and issue.severity in {"medium", "high"}
        for issue in report.issues
    )


def test_clean_script_still_passes() -> None:
    script = Script(
        title="عنوان",
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa=_words(40, "مطلب"),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
            ScriptTurn(
                turn_id="t2",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa=_words(40, "پاسخ"),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
            ScriptTurn(
                turn_id="t3",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa=_words(8, "گذار"),
                editorial_only=True,
            ),
            ScriptTurn(
                turn_id="t4",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa=_words(40, "ادامه"),
                claim_ids=["clm-2"],
                evidence_ids=["ev-2"],
            ),
        ],
    )
    project_id = uuid4()
    plan = EpisodePlan(
        title="عنوان",
        listener_outcome="نتیجه",
        estimated_duration_minutes=1,
        segments=[_segment("clm-1", "clm-2")],
    )
    pack = SegmentEvidencePack.model_construct(
        segment_id="seg-001",
        claim_ids=["clm-1", "clm-2"],
        evidence_items=[_evidence("ev-1"), _evidence("ev-2")],
        original_blocks=[],
        token_budget=1,
        actual_tokens=0,
    )
    review = MustNotBeLostReview(
        project_id=project_id,
        unused_count=0,
        items=[
            MustNotBeLostReviewItem(
                point=MustNotBeLostPoint(
                    text="نکته پوشش‌داده‌شده",
                    source_id=_SOURCE_ID,
                    block_id="blk-1",
                    locator=Locator(),
                ),
                reflected_in_claims=["clm-1"],
                used_in_plan=True,
            )
        ],
    )
    report = ScriptChecker(words_per_minute=128).check(
        project_id=project_id,
        script=script,
        episode_plan=plan,
        evidence_packs=[pack],
        claims=[_claim("clm-1", evidence_id="ev-1"), _claim("clm-2", evidence_id="ev-2")],
        glossary=Glossary(project_id=project_id, model_run_id=uuid4()),
        must_not_be_lost_review=review,
    )
    assert report.verdict == "pass", [issue.model_dump() for issue in report.issues]


def test_calibration_fixture_records_c1_c2_c3_at_low_severity() -> None:
    """C1/C2/C3 still measure and record on the known-bad script; they just no
    longer bind the verdict (MVP policy, 2026-08-13). The fixture's verdict
    stays non-"pass" here only because it also contains exact-duplicate turns
    (`repetition`, `blocking`), a content defect this policy did not touch.
    """

    script = Script.model_validate_json(
        (_FIXTURE_DIR / "calibration_script.json").read_text(encoding="utf-8")
    )
    violations = json.loads(
        (_FIXTURE_DIR / "speaker_balance_violations.json").read_text(encoding="utf-8")
    )
    plan = EpisodePlan(
        title="عنوان",
        listener_outcome="نتیجه",
        estimated_duration_minutes=9,
        segments=[_segment("clm-1")],
    )
    pack = SegmentEvidencePack.model_construct(
        segment_id="seg-001",
        claim_ids=["clm-1"],
        evidence_items=[_evidence("ev-1")],
        original_blocks=[],
        token_budget=1,
        actual_tokens=0,
    )
    report = ScriptChecker(words_per_minute=130).check(
        project_id=uuid4(),
        script=script,
        episode_plan=plan,
        evidence_packs=[pack],
        claims=[_claim()],
        glossary=Glossary(project_id=uuid4(), model_run_id=uuid4()),
        speaker_balance_violations={
            key: value for key, value in violations.items() if key == "seg-001"
        },
    )
    assert report.verdict != "pass"  # driven by blocking repetition, not style
    low_types = {issue.issue_type for issue in report.issues if issue.severity == "low"}
    assert "speaker_balance" in low_types  # C1
    assert low_types & {"editorial_ratio", "speaker_skew", "speaker_b_substantive"}  # C2
    assert "restatement" in low_types  # C3 rate high
    assert not any(
        issue.issue_type in {
            "speaker_balance",
            "editorial_ratio",
            "speaker_skew",
            "speaker_b_substantive",
            "restatement",
        }
        and issue.severity in {"medium", "high", "blocking"}
        for issue in report.issues
    )


def test_validate_raises_before_final_attempt() -> None:
    draft = SegmentScriptDraft(
        turns=[
            ScriptTurnDraft(speaker="B", spoken_text_fa=_words(4), editorial_only=True),
            ScriptTurnDraft(
                speaker="A",
                spoken_text_fa=_words(1),
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
        ]
    )
    with pytest.raises(DeterministicValidationError):
        _validate_segment_draft(
            draft,
            allowed_claim_ids={"clm-1"},
            allowed_evidence_ids={"ev-1"},
            segment=_segment("clm-1", "clm-2"),
            policy=SpeakerBalancePolicy(),
            is_opening=False,
            attempt={"n": 0},
            max_attempts=2,
            violations=[],
        )
