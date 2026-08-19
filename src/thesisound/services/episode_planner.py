from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from thesisound.domain import (
    ClaimRecord,
    DeliberatelyOmittedClaim,
    EpisodePlan,
    EpisodeSegment,
    ExtractedAuxiliaryPoint,
    ExtractedDefinition,
    ExtractedDistinction,
    ResearchBrief,
)
from thesisound.episode import (
    ClaimPriorityReport,
    CoverageReport,
    DisagreementGraph,
    EpisodeBudgetReport,
    EpisodePlanDraft,
)
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.script import QualityNote
from thesisound.services.model_runner import ModelRunner
from thesisound.services.quality_notes import make_quality_note
from thesisound.source_analysis import EvidenceExtractionPlan

_SKELETON_MINUTE_TOLERANCE = 1e-6


def default_part_payload(brief: ResearchBrief) -> dict[str, Any]:
    return {
        "part_index": 1,
        "part_count": 1,
        "part_target_minutes": brief.target_duration_minutes,
        "cell_labels": [],
    }


class EpisodePlannerService:
    def __init__(self, model_runner: ModelRunner) -> None:
        self.model_runner = model_runner

    def plan(
        self,
        *,
        project_id: UUID,
        brief: ResearchBrief,
        claims: list[ClaimRecord],
        coverage: CoverageReport,
        budget: EpisodeBudgetReport,
        priorities: ClaimPriorityReport,
        disagreement_graph: DisagreementGraph,
        extraction_plans: list[EvidenceExtractionPlan],
        definitions: list[ExtractedDefinition],
        distinctions: list[ExtractedDistinction],
        examples: list[ExtractedAuxiliaryPoint],
        objections: list[ExtractedAuxiliaryPoint],
        responses: list[ExtractedAuxiliaryPoint],
        model: str,
        prompt_version: str | None = None,
        part: Mapping[str, Any] | None = None,
        segment_skeleton: Sequence[Mapping[str, Any]] | None = None,
        known_concepts: Sequence[Any] | None = None,
    ) -> tuple[EpisodePlan, EpisodePlanDraft, ModelRunRecord, list[QualityNote]]:
        # Structural: needs the user to narrow scope or add sources (information_asymmetry).
        if not coverage.can_plan_episode:
            raise ValueError(
                "Coverage is insufficient for the requested duration; narrow scope or add evidence."
            )
        # Structural: same — user must change duration or evidence (information_asymmetry).
        if budget.effective_supported_minutes < brief.target_duration_minutes * 0.8:
            raise ValueError("Deterministic budget is insufficient for episode planning.")
        claim_ids = {claim.claim_id for claim in claims}
        must_not_be_lost_ids = {
            claim.claim_id for claim in claims if claim.must_not_be_lost
        }
        priority_by_id = {item.claim_id: item for item in priorities.priorities}
        notes: list[QualityNote] = []
        part_payload = dict(part) if part is not None else default_part_payload(brief)
        skeleton = [dict(item) for item in segment_skeleton] if segment_skeleton is not None else []
        known = list(known_concepts) if known_concepts is not None else []
        # Grounding material, not claim inventory: no claim_ids, not must-include/
        # deferred-scored, and not subject to _validate_draft's used-or-omitted gate.
        # The prompt is instructed to draw on this instead of inventing examples,
        # objections, responses, definitions, and distinctions from claims alone.
        execution = self.model_runner.run(
            project_id=project_id,
            stage="episode_plan",
            prompt_name="episode_plan",
            variables={
                "research_brief": brief.model_dump(mode="json"),
                "part": part_payload,
                "segment_skeleton": skeleton,
                "known_concepts": known,
                "coverage_report": coverage.model_dump(mode="json"),
                "budget_report": budget.model_dump(mode="json"),
                "disagreement_graph": disagreement_graph.model_dump(mode="json"),
                "claim_priorities": priorities.model_dump(mode="json"),
                "claims": [claim.model_dump(mode="json") for claim in claims],
                "extraction_plans": [
                    plan.model_dump(mode="json") for plan in extraction_plans
                ],
                "definitions": [item.model_dump(mode="json") for item in definitions],
                "distinctions": [item.model_dump(mode="json") for item in distinctions],
                "examples": [item.model_dump(mode="json") for item in examples],
                "objections": [item.model_dump(mode="json") for item in objections],
                "responses": [item.model_dump(mode="json") for item in responses],
            },
            output_type=EpisodePlanDraft,
            model=model,
            prompt_version=prompt_version,
            validator=lambda draft: _validate_draft(
                draft,
                brief=brief,
                known_claim_ids=claim_ids,
                priority_by_id=priority_by_id,
                notes=notes,
                must_not_be_lost_ids=must_not_be_lost_ids,
                part=part_payload,
                segment_skeleton=skeleton,
            ),
        )
        draft = execution.output
        part_index = int(part_payload.get("part_index", 1))
        segments = [
            EpisodeSegment(
                segment_id=f"seg-{index:03d}",
                title=segment.title,
                purpose=segment.purpose,
                estimated_minutes=segment.target_minutes,
                claim_ids=segment.claim_ids,
                prerequisite_claim_ids=segment.prerequisite_claim_ids,
                key_question=segment.key_question,
                speaker_dynamic=segment.speaker_dynamic,
                part_index=part_index,
            )
            for index, segment in enumerate(draft.segments, start=1)
        ]
        plan = EpisodePlan(
            title=draft.title,
            listener_outcome=draft.listener_outcome,
            estimated_duration_minutes=sum(item.estimated_minutes for item in segments),
            segments=segments,
            deliberately_omitted_claims=draft.deliberately_omitted_claims,
            follow_up_topics=draft.follow_up_topics,
        )
        return plan, draft, execution.record, notes


def _validate_draft(
    draft: EpisodePlanDraft,
    *,
    brief: ResearchBrief,
    known_claim_ids: set[str],
    priority_by_id: dict,
    notes: list[QualityNote] | None = None,
    must_not_be_lost_ids: set[str] | None = None,
    part: Mapping[str, Any] | None = None,
    segment_skeleton: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    part_payload = dict(part) if part is not None else default_part_payload(brief)
    skeleton = list(segment_skeleton or ())
    target_minutes = float(part_payload.get("part_target_minutes", brief.target_duration_minutes))
    total_minutes = sum(segment.target_minutes for segment in draft.segments)
    if skeleton:
        upper = target_minutes * 1.25
        if total_minutes > upper + _SKELETON_MINUTE_TOLERANCE:
            raise DeterministicValidationError(
                f"Episode duration {total_minutes:.1f} exceeds the part budget "
                f"ceiling {upper:.1f}."
            )
        _assert_skeleton_identity(draft, skeleton)
    else:
        lower = brief.target_duration_minutes * 0.9
        upper = brief.target_duration_minutes * 1.1
        if not lower <= total_minutes <= upper:
            # Structural: model must hit the duration window; repair can fix this.
            raise DeterministicValidationError(
                f"Episode duration {total_minutes:.1f} is outside the allowed range "
                f"{lower:.1f}-{upper:.1f}."
            )

    used_claims: list[str] = []
    seen_before: set[str] = set()
    for index, segment in enumerate(draft.segments, start=1):
        unknown = sorted(set(segment.claim_ids) - known_claim_ids)
        if unknown:
            # Structural: no grounded artifact remains for unknown claim IDs.
            raise DeterministicValidationError(
                "One section referenced points that are not in the evidence set.",
                stop_reason="integrity_breach",
            )
        prerequisites = set(segment.prerequisite_claim_ids)
        unknown_prerequisites = sorted(prerequisites - known_claim_ids)
        if unknown_prerequisites:
            # Structural: unknown prerequisite IDs leave no grounded plan.
            raise DeterministicValidationError(
                "One section referenced prerequisite points that are not in the evidence set.",
                stop_reason="integrity_breach",
            )
        missing_prerequisites = sorted(prerequisites - seen_before)
        if missing_prerequisites:
            # Structural: ordering defect the model must repair.
            raise DeterministicValidationError(
                f"Segment {index} uses prerequisites before they are introduced: "
                + ", ".join(missing_prerequisites)
            )
        duplicate_within = len(segment.claim_ids) != len(set(segment.claim_ids))
        if duplicate_within:
            # Structural: duplicate IDs within a segment need model repair.
            raise DeterministicValidationError(
                f"Segment {index} contains duplicate claim IDs."
            )
        used_claims.extend(segment.claim_ids)
        seen_before.update(segment.claim_ids)

    duplicate_across = sorted(
        claim_id for claim_id in set(used_claims) if used_claims.count(claim_id) > 1
    )
    if duplicate_across:
        # Structural: cross-segment repeats need model repair.
        raise DeterministicValidationError(
            "Claims may not be repeated across segments without a separate recap artifact: "
            + ", ".join(duplicate_across)
        )

    must_include = {
        claim_id
        for claim_id, priority in priority_by_id.items()
        if priority.level == "must_include"
    }
    missing_must = sorted(must_include - set(used_claims))
    if missing_must:
        # Structural: silently dropping must-include defeats prioritisation.
        raise DeterministicValidationError(
            "One or more required points were left out of the episode plan. "
            "Add a section that covers them, or shorten the episode.",
            stop_reason="integrity_breach",
        )

    omitted_ids = [item.claim_id for item in draft.deliberately_omitted_claims]
    if len(omitted_ids) != len(set(omitted_ids)):
        # Structural: duplicate omitted IDs need model repair.
        raise DeterministicValidationError(
            "Episode plan lists duplicate deliberately omitted claim IDs."
        )
    omitted = set(omitted_ids)
    unknown_omitted = sorted(omitted - known_claim_ids)
    if unknown_omitted:
        # Structural: unknown omitted IDs leave no grounded inventory.
        raise DeterministicValidationError(
            "The plan set aside points that are not in the evidence set.",
            stop_reason="integrity_breach",
        )
    overlap = sorted(omitted & set(used_claims))
    if overlap:
        # Structural: used∩omitted is a contract contradiction.
        raise DeterministicValidationError(
            "Claims cannot be both used and deliberately omitted: " + ", ".join(overlap)
        )

    flagged = must_not_be_lost_ids or set()
    silent_lost = sorted(flagged - set(used_claims) - omitted)
    if silent_lost:
        raise DeterministicValidationError(
            "One or more must-not-be-lost points were dropped from the plan without a reason.",
            stop_reason="integrity_breach",
        )

    expected_accounted = {
        claim_id
        for claim_id, priority in priority_by_id.items()
        if priority.level in {"must_include", "supporting", "optional"}
    }
    unaccounted = sorted(expected_accounted - set(used_claims) - omitted)
    if unaccounted:
        # Recoverable: auto-close as omitted rather than reject the plan — an
        # omission is already a first-class, expected outcome (not every
        # supporting/optional claim fits the runtime). Unknown/duplicated IDs
        # still raise above. must_not_be_lost claims are never auto-omitted.
        draft.deliberately_omitted_claims = [
            *draft.deliberately_omitted_claims,
            *(
                DeliberatelyOmittedClaim(
                    claim_id=claim_id,
                    reason="Not referenced by any segment; auto-omitted at validation.",
                )
                for claim_id in unaccounted
            ),
        ]
        if notes is not None:
            notes.extend(
                make_quality_note(
                    stage="episode_plan",
                    kind="claim_omitted",
                    subject=claim_id,
                )
                for claim_id in unaccounted
            )


def _assert_skeleton_identity(
    draft: EpisodePlanDraft,
    skeleton: Sequence[Mapping[str, Any]],
) -> None:
    if len(skeleton) != len(draft.segments):
        raise DeterministicValidationError(
            "The plan changed the number of segments supplied by the skeleton.",
            stop_reason="integrity_breach",
        )
    for index, (expected, actual) in enumerate(zip(skeleton, draft.segments, strict=True), start=1):
        expected_ids = [str(item) for item in expected.get("claim_ids", [])]
        if expected_ids != list(actual.claim_ids):
            raise DeterministicValidationError(
                f"Segment {index} claim_ids deviate from the skeleton.",
                stop_reason="integrity_breach",
            )
        expected_dynamic = expected.get("speaker_dynamic")
        if expected_dynamic != actual.speaker_dynamic:
            raise DeterministicValidationError(
                f"Segment {index} speaker_dynamic deviates from the skeleton.",
                stop_reason="integrity_breach",
            )
        expected_minutes = _skeleton_minutes(expected)
        if abs(expected_minutes - actual.target_minutes) > _SKELETON_MINUTE_TOLERANCE:
            raise DeterministicValidationError(
                f"Segment {index} minutes deviate from the skeleton.",
                stop_reason="integrity_breach",
            )


def _skeleton_minutes(item: Mapping[str, Any]) -> float:
    if "estimated_minutes" in item:
        return float(item["estimated_minutes"])
    return float(item["target_minutes"])
