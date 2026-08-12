from __future__ import annotations

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
from thesisound.services.model_runner import ModelRunner
from thesisound.source_analysis import EvidenceExtractionPlan


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
    ) -> tuple[EpisodePlan, EpisodePlanDraft, ModelRunRecord]:
        if not coverage.can_plan_episode:
            raise ValueError(
                "Coverage is insufficient for the requested duration; narrow scope or add evidence."
            )
        if budget.effective_supported_minutes < brief.target_duration_minutes * 0.8:
            raise ValueError("Deterministic budget is insufficient for episode planning.")
        claim_ids = {claim.claim_id for claim in claims}
        priority_by_id = {item.claim_id: item for item in priorities.priorities}
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
            ),
        )
        draft = execution.output
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
        return plan, draft, execution.record


def _validate_draft(
    draft: EpisodePlanDraft,
    *,
    brief: ResearchBrief,
    known_claim_ids: set[str],
    priority_by_id: dict,
) -> None:
    total_minutes = sum(segment.target_minutes for segment in draft.segments)
    lower = brief.target_duration_minutes * 0.9
    upper = brief.target_duration_minutes * 1.1
    if not lower <= total_minutes <= upper:
        raise DeterministicValidationError(
            f"Episode duration {total_minutes:.1f} is outside the allowed range "
            f"{lower:.1f}-{upper:.1f}."
        )

    used_claims: list[str] = []
    seen_before: set[str] = set()
    for index, segment in enumerate(draft.segments, start=1):
        unknown = sorted(set(segment.claim_ids) - known_claim_ids)
        if unknown:
            raise DeterministicValidationError(
                f"Segment {index} references unknown claim IDs: {', '.join(unknown)}"
            )
        prerequisites = set(segment.prerequisite_claim_ids)
        unknown_prerequisites = sorted(prerequisites - known_claim_ids)
        if unknown_prerequisites:
            raise DeterministicValidationError(
                "Episode plan references unknown prerequisite claim IDs: "
                + ", ".join(unknown_prerequisites)
            )
        missing_prerequisites = sorted(prerequisites - seen_before)
        if missing_prerequisites:
            raise DeterministicValidationError(
                f"Segment {index} uses prerequisites before they are introduced: "
                + ", ".join(missing_prerequisites)
            )
        duplicate_within = len(segment.claim_ids) != len(set(segment.claim_ids))
        if duplicate_within:
            raise DeterministicValidationError(
                f"Segment {index} contains duplicate claim IDs."
            )
        used_claims.extend(segment.claim_ids)
        seen_before.update(segment.claim_ids)

    duplicate_across = sorted(
        claim_id for claim_id in set(used_claims) if used_claims.count(claim_id) > 1
    )
    if duplicate_across:
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
        raise DeterministicValidationError(
            "Episode plan omitted must-include claims: " + ", ".join(missing_must)
        )

    omitted_ids = [item.claim_id for item in draft.deliberately_omitted_claims]
    if len(omitted_ids) != len(set(omitted_ids)):
        raise DeterministicValidationError(
            "Episode plan lists duplicate deliberately omitted claim IDs."
        )
    omitted = set(omitted_ids)
    unknown_omitted = sorted(omitted - known_claim_ids)
    if unknown_omitted:
        raise DeterministicValidationError(
            "Episode plan listed unknown omitted claim IDs: " + ", ".join(unknown_omitted)
        )
    overlap = sorted(omitted & set(used_claims))
    if overlap:
        raise DeterministicValidationError(
            "Claims cannot be both used and deliberately omitted: " + ", ".join(overlap)
        )

    expected_accounted = {
        claim_id
        for claim_id, priority in priority_by_id.items()
        if priority.level in {"must_include", "supporting", "optional"}
    }
    unaccounted = sorted(expected_accounted - set(used_claims) - omitted)
    if unaccounted:
        # Auto-close as omitted rather than reject the plan: an omission is
        # already a first-class, expected outcome (not every supporting/
        # optional claim fits the runtime), so silently dropping one is not a
        # correctness defect the way an unknown or duplicated ID is -- the
        # model just forgot to label the drop. Those still raise above.
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
