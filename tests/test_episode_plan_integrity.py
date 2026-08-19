from __future__ import annotations

import pytest

from thesisound.domain import ResearchBrief, TopicType
from thesisound.episode import ClaimPriorityRecord, EpisodePlanDraft, EpisodeSegmentDraft
from thesisound.modeling import DeterministicValidationError
from thesisound.prompt_loader import PromptLoader, PromptRenderError
from thesisound.services.episode_planner import _validate_draft


def _brief(minutes: int = 10) -> ResearchBrief:
    return ResearchBrief(
        normalized_topic="topic",
        topic_type=TopicType.CONCEPT,
        central_question="What is it?",
        learning_objectives=["Understand A", "Understand B"],
        target_duration_minutes=minutes,
    )


def _draft(
    *,
    claim_ids: list[str] | None = None,
    omitted: list[tuple[str, str]] | None = None,
    minutes: float = 10,
    speaker_dynamic: str = "explanation",
    extra_segments: list[EpisodeSegmentDraft] | None = None,
) -> EpisodePlanDraft:
    segments = [
        EpisodeSegmentDraft(
            title="Seg",
            purpose="Purpose",
            target_minutes=minutes,
            claim_ids=claim_ids or ["clm-must"],
            prerequisite_claim_ids=[],
            key_question="Why?",
            speaker_dynamic=speaker_dynamic,  # type: ignore[arg-type]
        )
    ]
    if extra_segments:
        segments.extend(extra_segments)
    return EpisodePlanDraft(
        title="Title",
        listener_outcome="Outcome",
        segments=segments,
        deliberately_omitted_claims=[
            {"claim_id": claim_id, "reason": reason} for claim_id, reason in (omitted or [])
        ],
        follow_up_topics=[],
    )


def _priorities(*pairs: tuple[str, str]) -> dict[str, ClaimPriorityRecord]:
    return {
        claim_id: ClaimPriorityRecord(
            claim_id=claim_id,
            level=level,  # type: ignore[arg-type]
            score=90,
            estimated_explanation_seconds=60,
        )
        for claim_id, level in pairs
    }


def test_latest_episode_plan_prompt_is_1_3_0_and_renders_part_and_skeleton() -> None:
    loader = PromptLoader()
    contract = loader.load_contract("episode_plan")
    assert contract.version == "1.3.0"
    bundle = loader.load_bundle(
        "episode_plan",
        {
            "research_brief": {},
            "part": {
                "part_index": 1,
                "part_count": 1,
                "part_target_minutes": 10,
                "cell_labels": [],
            },
            "segment_skeleton": [],
            "coverage_report": {},
            "budget_report": {},
            "disagreement_graph": {},
            "claim_priorities": {},
            "claims": [],
            "known_concepts": [],
        },
    )
    assert "<PART_JSON>" in bundle.user_prompt
    assert "<SEGMENT_SKELETON_JSON>" in bundle.user_prompt
    assert "<KNOWN_CONCEPTS>" in bundle.user_prompt
    assert "must_not_be_lost" in bundle.system_prompt
    assert "SEGMENT_SKELETON_JSON" in bundle.system_prompt
    assert "{{" not in bundle.system_prompt + bundle.user_prompt


def test_episode_plan_1_3_0_missing_part_variable_fails_loudly() -> None:
    with pytest.raises(PromptRenderError, match="part"):
        PromptLoader().load_bundle(
            "episode_plan",
            {
                "research_brief": {},
                "segment_skeleton": [],
                "coverage_report": {},
                "budget_report": {},
                "disagreement_graph": {},
                "claim_priorities": {},
                "claims": [],
                "known_concepts": [],
            },
        )


def test_must_not_be_lost_dropped_without_reason_is_integrity_breach() -> None:
    draft = _draft(claim_ids=["clm-must"])
    with pytest.raises(DeterministicValidationError, match="must-not-be-lost") as exc_info:
        _validate_draft(
            draft,
            brief=_brief(10),
            known_claim_ids={"clm-must", "clm-lost"},
            priority_by_id=_priorities(("clm-must", "must_include")),
            must_not_be_lost_ids={"clm-lost"},
        )
    assert exc_info.value.stop_reason == "integrity_breach"


def test_must_not_be_lost_explicitly_omitted_is_accepted() -> None:
    draft = _draft(
        claim_ids=["clm-must"],
        omitted=[("clm-lost", "Does not fit the part window without dropping the thesis.")],
    )
    _validate_draft(
        draft,
        brief=_brief(10),
        known_claim_ids={"clm-must", "clm-lost"},
        priority_by_id=_priorities(("clm-must", "must_include")),
        must_not_be_lost_ids={"clm-lost"},
    )
    assert [item.claim_id for item in draft.deliberately_omitted_claims] == ["clm-lost"]


def test_skeleton_deviation_in_claim_ids_is_integrity_breach() -> None:
    draft = _draft(claim_ids=["clm-must"], minutes=10)
    skeleton = [
        {
            "segment_index": 1,
            "claim_ids": ["clm-must", "clm-other"],
            "speaker_dynamic": "explanation",
            "estimated_minutes": 10,
        }
    ]
    with pytest.raises(DeterministicValidationError, match="claim_ids") as exc_info:
        _validate_draft(
            draft,
            brief=_brief(10),
            known_claim_ids={"clm-must", "clm-other"},
            priority_by_id=_priorities(("clm-must", "must_include")),
            segment_skeleton=skeleton,
        )
    assert exc_info.value.stop_reason == "integrity_breach"


def test_skeleton_deviation_in_order_minutes_or_dynamic_is_rejected() -> None:
    first = EpisodeSegmentDraft(
        title="A",
        purpose="Purpose A",
        target_minutes=6,
        claim_ids=["clm-a"],
        key_question="A?",
        speaker_dynamic="explanation",
    )
    second = EpisodeSegmentDraft(
        title="B",
        purpose="Purpose B",
        target_minutes=6,
        claim_ids=["clm-b"],
        key_question="B?",
        speaker_dynamic="critique",
    )
    draft = EpisodePlanDraft(
        title="Title",
        listener_outcome="Outcome",
        segments=[first, second],
    )
    skeleton = [
        {
            "claim_ids": ["clm-b"],
            "speaker_dynamic": "critique",
            "estimated_minutes": 6,
        },
        {
            "claim_ids": ["clm-a"],
            "speaker_dynamic": "explanation",
            "estimated_minutes": 6,
        },
    ]
    with pytest.raises(DeterministicValidationError, match="claim_ids") as exc_info:
        _validate_draft(
            draft,
            brief=_brief(10),
            known_claim_ids={"clm-a", "clm-b"},
            priority_by_id=_priorities(("clm-a", "must_include"), ("clm-b", "must_include")),
            part={
                "part_index": 1,
                "part_count": 1,
                "part_target_minutes": 10,
                "cell_labels": [],
            },
            segment_skeleton=skeleton,
        )
    assert exc_info.value.stop_reason == "integrity_breach"


def test_matching_skeleton_allows_duration_outside_ten_percent_window() -> None:
    first = EpisodeSegmentDraft(
        title="A",
        purpose="Purpose A",
        target_minutes=6,
        claim_ids=["clm-a"],
        key_question="A?",
        speaker_dynamic="explanation",
    )
    second = EpisodeSegmentDraft(
        title="B",
        purpose="Purpose B",
        target_minutes=6,
        claim_ids=["clm-b"],
        key_question="B?",
        speaker_dynamic="critique",
    )
    draft = EpisodePlanDraft(
        title="Title",
        listener_outcome="Outcome",
        segments=[first, second],
    )
    skeleton = [
        {
            "claim_ids": ["clm-a"],
            "speaker_dynamic": "explanation",
            "estimated_minutes": 6,
        },
        {
            "claim_ids": ["clm-b"],
            "speaker_dynamic": "critique",
            "estimated_minutes": 6,
        },
    ]
    _validate_draft(
        draft,
        brief=_brief(10),
        known_claim_ids={"clm-a", "clm-b"},
        priority_by_id=_priorities(("clm-a", "must_include"), ("clm-b", "must_include")),
        part={
            "part_index": 1,
            "part_count": 1,
            "part_target_minutes": 10,
            "cell_labels": [],
        },
        segment_skeleton=skeleton,
    )


def test_empty_skeleton_still_enforces_ten_percent_window() -> None:
    draft = _draft(claim_ids=["clm-must"], minutes=12)
    with pytest.raises(DeterministicValidationError, match="outside the allowed range"):
        _validate_draft(
            draft,
            brief=_brief(10),
            known_claim_ids={"clm-must"},
            priority_by_id=_priorities(("clm-must", "must_include")),
            segment_skeleton=[],
        )
