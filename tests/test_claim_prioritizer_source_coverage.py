"""Conditional point 2 (`10c` P3 Step 10): `ClaimPrioritizer.prioritize` × `lesson_intent`."""

from __future__ import annotations

from uuid import uuid4

from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    LessonIntent,
    Project,
    ProjectState,
    ResearchBrief,
    SupportStatus,
    TopicType,
)
from thesisound.episode import CoverageReport
from thesisound.services.claim_prioritizer import ClaimPrioritizer

_PROJECT_ID = uuid4()


def _brief(duration: int = 10) -> ResearchBrief:
    return ResearchBrief(
        normalized_topic="موضوع",
        topic_type=TopicType.CONCEPT,
        central_question="سؤال؟",
        target_duration_minutes=duration,
    )


def _project(intent: LessonIntent) -> Project:
    return Project(raw_input="متن", state=ProjectState.CORPUS_BUILDING, lesson_intent=intent)


def _coverage() -> CoverageReport:
    return CoverageReport(
        project_id=_PROJECT_ID,
        central_question_status="well_covered",
        central_question_claim_ids=[],
        max_supported_minutes=10,
        recommendation="continue",
        recommendation_reason="کافی است.",
        can_plan_episode=True,
        model_run_id=uuid4(),
    )


def _claim(claim_id: str) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        claim=f"ادعای {claim_id}",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=["ev-1"],
        support_status=SupportStatus.STRONG,
    )


def test_without_a_project_duration_cut_lines_apply_as_before() -> None:
    claims = [_claim("clm-1"), _claim("clm-2"), _claim("clm-3")]
    report = ClaimPrioritizer().prioritize(
        project_id=_PROJECT_ID, brief=_brief(30), claims=claims, coverage=_coverage()
    )
    levels = {item.level for item in report.priorities}
    assert levels <= {"must_include", "supporting", "optional", "deferred"}
    assert "clm-1" in {item.claim_id for item in report.priorities if item.level == "must_include"}


def test_focused_question_project_keeps_duration_cut_lines() -> None:
    claims = [_claim("clm-1"), _claim("clm-2")]
    report = ClaimPrioritizer().prioritize(
        project_id=_PROJECT_ID,
        brief=_brief(30),
        claims=claims,
        coverage=_coverage(),
        project=_project(LessonIntent.FOCUSED_QUESTION),
        must_include_claim_ids=["clm-2"],  # ignored off this path
    )
    must_include = {item.claim_id for item in report.priorities if item.level == "must_include"}
    assert must_include == {"clm-1", "clm-2"}  # scored, not linkage-driven


def test_every_claim_type_has_a_score_and_does_not_crash() -> None:
    """Regression for a real crash at checkpoint C-D (2026-08-20): extraction
    2.0 (`10c` P2 Step 1) added `definition`/`distinction`/`example` claim
    types that `_BASE_TYPE_SCORE` never gained, so scoring any such claim
    raised `KeyError` and surfaced as the unreadable `run.last_error` string
    `"<ClaimType.DEFINITION: 'definition'>"`."""

    claims = [
        ClaimRecord(
            claim_id=f"clm-{claim_type.value}",
            claim=f"ادعای {claim_type.value}",
            claim_type=claim_type,
            evidence_ids=["ev-1"],
            support_status=SupportStatus.STRONG,
        )
        for claim_type in ClaimType
    ]
    report = ClaimPrioritizer().prioritize(
        project_id=_PROJECT_ID, brief=_brief(30), claims=claims, coverage=_coverage()
    )
    assert len(report.priorities) == len(claims)


def test_source_coverage_project_uses_cell_linkage_not_scoring() -> None:
    claims = [_claim("clm-1"), _claim("clm-2"), _claim("clm-3")]
    report = ClaimPrioritizer().prioritize(
        project_id=_PROJECT_ID,
        brief=_brief(120),  # a long duration would normally must-include everything
        claims=claims,
        coverage=_coverage(),
        project=_project(LessonIntent.SOURCE_COVERAGE),
        must_include_claim_ids=["clm-2"],
    )
    by_id = {item.claim_id: item.level for item in report.priorities}
    assert by_id == {"clm-1": "deferred", "clm-2": "must_include", "clm-3": "deferred"}
