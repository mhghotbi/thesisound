"""`EpisodePlannerService.plan`'s deterministic budget precondition.

Not one of the five named `10c` P3 Step 10 conditional points, but a gap
found while wiring the per-part loop: the precondition used the *whole*
`brief`/`budget`, which for `source_coverage` describe the whole scope, not
one part -- it would otherwise reject every part call even after the
whole-scope 80% gate (`episode_planning_run`, point 5) was made advisory.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from thesisound.domain import ClaimRecord, ClaimType, ResearchBrief, SupportStatus, TopicType
from thesisound.episode import (
    ClaimPriorityReport,
    CoverageReport,
    DisagreementGraph,
    EpisodeBudgetReport,
    EpisodePlanDraft,
    EpisodeSegmentDraft,
)
from thesisound.modeling import ModelExecution, ModelRunRecord
from thesisound.services.episode_planner import EpisodePlannerService

_PROJECT_ID = uuid4()


class _EchoRunner:
    def run(self, *, project_id, stage, variables, output_type, model, validator=None, **_):
        skeleton = variables["segment_skeleton"]
        segments = [
            EpisodeSegmentDraft(
                title=f"Segment {index}",
                purpose="Explain.",
                target_minutes=item["estimated_minutes"],
                claim_ids=item["claim_ids"],
                key_question="What does this establish?",
                speaker_dynamic=item["speaker_dynamic"],
            )
            for index, item in enumerate(skeleton, start=1)
        ] or [
            EpisodeSegmentDraft(
                title="Segment",
                purpose="Explain.",
                target_minutes=variables["research_brief"]["target_duration_minutes"],
                claim_ids=["clm-1"],
                key_question="What does this establish?",
                speaker_dynamic="explanation",
            )
        ]
        output = EpisodePlanDraft(title="Title", listener_outcome="Outcome", segments=segments)
        if validator is not None:
            validator(output)
        record = ModelRunRecord(
            project_id=project_id,
            stage=stage,
            prompt_id=stage,
            prompt_version="test",
            prompt_hash="test",
            input_hash="test",
            provider="fake",
            model=model,
            output_model=output_type.__name__,
            status="succeeded",
        )
        return ModelExecution(output=output, record=record)


def _brief(duration: int = 10) -> ResearchBrief:
    return ResearchBrief(
        normalized_topic="topic",
        topic_type=TopicType.CONCEPT,
        central_question="What is it?",
        target_duration_minutes=duration,
    )


def _claim(claim_id: str) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        claim="A grounded claim.",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=["ev-1"],
        support_status=SupportStatus.STRONG,
    )


def _coverage() -> CoverageReport:
    return CoverageReport(
        project_id=_PROJECT_ID,
        central_question_status="well_covered",
        max_supported_minutes=10,
        recommendation="continue",
        recommendation_reason="ok",
        can_plan_episode=True,
        model_run_id=uuid4(),
    )


def _budget(*, target: int, effective: float) -> EpisodeBudgetReport:
    return EpisodeBudgetReport(
        project_id=_PROJECT_ID,
        target_duration_minutes=target,
        words_per_minute=130,
        available_claim_seconds=1_200,
        original_evidence_tokens=2_000,
        estimated_supported_minutes=effective,
        model_reported_supported_minutes=int(effective),
        effective_supported_minutes=effective,
        calibration_status="fixture_calibrated",
    )


def _priorities(*claim_ids: str) -> ClaimPriorityReport:
    from thesisound.episode import ClaimPriorityRecord

    return ClaimPriorityReport(
        project_id=_PROJECT_ID,
        target_duration_minutes=10,
        priorities=[
            ClaimPriorityRecord(
                claim_id=claim_id,
                level="must_include",
                score=90,
                estimated_explanation_seconds=60,
            )
            for claim_id in claim_ids
        ],
        available_content_seconds=600,
        estimated_selected_seconds=600,
    )


def _disagreement_graph() -> DisagreementGraph:
    return DisagreementGraph(project_id=_PROJECT_ID)


def test_low_whole_scope_budget_still_blocks_free_planning() -> None:
    service = EpisodePlannerService(_EchoRunner())
    with pytest.raises(ValueError, match="Deterministic budget is insufficient"):
        service.plan(
            project_id=_PROJECT_ID,
            brief=_brief(10),
            claims=[_claim("clm-1")],
            coverage=_coverage(),
            budget=_budget(target=10, effective=1),  # 1 < 10 * 0.8
            priorities=_priorities("clm-1"),
            disagreement_graph=_disagreement_graph(),
            extraction_plans=[],
            definitions=[],
            distinctions=[],
            examples=[],
            objections=[],
            responses=[],
            model="fake",
        )


def test_low_whole_scope_budget_does_not_block_a_part_call() -> None:
    service = EpisodePlannerService(_EchoRunner())
    plan, *_ = service.plan(
        project_id=_PROJECT_ID,
        brief=_brief(10),  # whole-scope brief: 10 minutes
        claims=[_claim("clm-1")],
        coverage=_coverage(),
        budget=_budget(target=10, effective=1),  # 1 < 10 * 0.8, would block free planning
        priorities=_priorities("clm-1"),
        disagreement_graph=_disagreement_graph(),
        extraction_plans=[],
        definitions=[],
        distinctions=[],
        examples=[],
        objections=[],
        responses=[],
        model="fake",
        part={"part_index": 1, "part_count": 1, "part_target_minutes": 2, "cell_labels": []},
        segment_skeleton=[
            {"claim_ids": ["clm-1"], "speaker_dynamic": "explanation", "estimated_minutes": 2}
        ],
    )
    assert plan.segments[0].claim_ids == ["clm-1"]
