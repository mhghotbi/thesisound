from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from thesisound import tracing
from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    LessonIntent,
    Project,
    ResearchBrief,
    SupportStatus,
)
from thesisound.episode import ClaimPriorityRecord, ClaimPriorityReport, CoverageReport

_SUPPORT_SCORE = {
    SupportStatus.STRONG: 40,
    SupportStatus.MODERATE: 28,
    SupportStatus.CONTESTED: 20,
    SupportStatus.UNCERTAIN: 8,
}
_BASE_TYPE_SCORE = {
    ClaimType.AUTHOR_POSITION: 20,
    ClaimType.SCHOLARLY_INTERPRETATION: 14,
    ClaimType.CRITICISM: 10,
    ClaimType.COUNTERARGUMENT: 10,
    ClaimType.HISTORICAL_CONTEXT: 7,
    ClaimType.EDITORIAL_EXPLANATION: 0,
    # Extraction 2.0 (10c P2 Step 1) claim types, missing here since that
    # step shipped -- every claim of one of these types crashed `_score`
    # with a KeyError (found for real at checkpoint C-D, 2026-08-20: any
    # extracted `definition` claim reached this lookup and failed).
    # Definitions/distinctions are prerequisite scaffolding a segment often
    # cannot be understood without; examples are illustrative and expendable.
    ClaimType.DEFINITION: 16,
    ClaimType.DISTINCTION: 16,
    ClaimType.EXAMPLE: 6,
}


class ClaimPrioritizer:
    def prioritize(
        self,
        *,
        project_id: UUID,
        brief: ResearchBrief,
        claims: list[ClaimRecord],
        coverage: CoverageReport,
        project: Project | None = None,
        must_include_claim_ids: Sequence[str] | None = None,
    ) -> ClaimPriorityReport:
        with tracing.span(
            "episode.prioritize_claims", component="episode", project_id=project_id
        ) as span:
            if not claims:
                raise ValueError("Claim prioritization requires at least one claim.")
            central = set(coverage.central_question_claim_ids)
            objective_hits: dict[str, int] = {}
            for item in coverage.objective_coverage:
                for claim_id in item.claim_ids:
                    objective_hits[claim_id] = objective_hits.get(claim_id, 0) + 1

            if project is not None and project.lesson_intent == LessonIntent.SOURCE_COVERAGE:
                # Cut-lines are cell linkage, not a duration ranking (`10c` P3
                # Step 8): a claim linked to this part's cells is must_include,
                # everything else passed in is deferred.
                must_include = set(must_include_claim_ids or ())
                priorities = [
                    ClaimPriorityRecord(
                        claim_id=claim.claim_id,
                        level="must_include" if claim.claim_id in must_include else "deferred",
                        score=self._score(claim, brief, central, objective_hits),
                        reasons=self._reasons(
                            claim, central=central, objective_hits=objective_hits, brief=brief
                        ),
                        estimated_explanation_seconds=self._estimate_seconds(claim),
                    )
                    for claim in claims
                ]
                selected_seconds = sum(
                    item.estimated_explanation_seconds
                    for item in priorities
                    if item.level == "must_include"
                )
                span.measure(claim_count=len(claims), must_include_count=len(must_include))
                return ClaimPriorityReport(
                    project_id=project_id,
                    target_duration_minutes=brief.target_duration_minutes,
                    priorities=priorities,
                    available_content_seconds=coverage.max_supported_minutes * 60,
                    estimated_selected_seconds=selected_seconds,
                )

            scored = [
                (
                    claim,
                    self._score(claim, brief, central, objective_hits),
                    self._estimate_seconds(claim),
                )
                for claim in claims
            ]
            scored.sort(key=lambda item: (-item[1], item[0].claim_id))

            must_count = max(1, min(len(scored), round(brief.target_duration_minutes / 3)))
            supporting_count = max(
                1,
                min(len(scored) - must_count, round(brief.target_duration_minutes / 2)),
            )
            optional_count = max(
                0,
                min(
                    len(scored) - must_count - supporting_count,
                    round(brief.target_duration_minutes / 4),
                ),
            )

            priorities: list[ClaimPriorityRecord] = []
            for index, (claim, score, seconds) in enumerate(scored):
                if index < must_count:
                    level = "must_include"
                elif index < must_count + supporting_count:
                    level = "supporting"
                elif index < must_count + supporting_count + optional_count:
                    level = "optional"
                else:
                    level = "deferred"
                priorities.append(
                    ClaimPriorityRecord(
                        claim_id=claim.claim_id,
                        level=level,
                        score=score,
                        reasons=self._reasons(
                            claim,
                            central=central,
                            objective_hits=objective_hits,
                            brief=brief,
                        ),
                        estimated_explanation_seconds=seconds,
                    )
                )

            selected_seconds = sum(
                item.estimated_explanation_seconds
                for item in priorities
                if item.level in {"must_include", "supporting"}
            )
            span.measure(claim_count=len(claims), must_include_count=must_count)
            return ClaimPriorityReport(
                project_id=project_id,
                target_duration_minutes=brief.target_duration_minutes,
                priorities=priorities,
                available_content_seconds=coverage.max_supported_minutes * 60,
                estimated_selected_seconds=selected_seconds,
            )

    @staticmethod
    def _score(
        claim: ClaimRecord,
        brief: ResearchBrief,
        central: set[str],
        objective_hits: dict[str, int],
    ) -> int:
        score = _SUPPORT_SCORE[claim.support_status] + _BASE_TYPE_SCORE[claim.claim_type]
        if claim.claim_id in central:
            score += 25
        score += min(20, objective_hits.get(claim.claim_id, 0) * 10)
        score += min(8, len(claim.evidence_ids) * 2)
        score += min(5, len(claim.qualifications))
        if (
            claim.claim_type in {ClaimType.CRITICISM, ClaimType.COUNTERARGUMENT}
            and {"critical", "debate"} & set(brief.modes)
        ):
            score += 15
        if claim.claim_type == ClaimType.HISTORICAL_CONTEXT and brief.target_duration_minutes <= 10:
            score -= 8
        return max(0, min(100, score))

    @staticmethod
    def _estimate_seconds(claim: ClaimRecord) -> int:
        seconds = 45
        if claim.claim_type in {
            ClaimType.SCHOLARLY_INTERPRETATION,
            ClaimType.CRITICISM,
            ClaimType.COUNTERARGUMENT,
        }:
            seconds += 25
        seconds += min(60, len(claim.qualifications) * 15)
        seconds += min(45, max(0, len(claim.evidence_ids) - 1) * 15)
        return min(600, seconds)

    @staticmethod
    def _reasons(
        claim: ClaimRecord,
        *,
        central: set[str],
        objective_hits: dict[str, int],
        brief: ResearchBrief,
    ) -> list[str]:
        reasons = [f"Support status: {claim.support_status.value}."]
        if claim.claim_id in central:
            reasons.append("Directly supports the central question.")
        hit_count = objective_hits.get(claim.claim_id, 0)
        if hit_count:
            reasons.append(f"Supports {hit_count} learning objective(s).")
        if claim.claim_type in {ClaimType.CRITICISM, ClaimType.COUNTERARGUMENT} and (
            {"critical", "debate"} & set(brief.modes)
        ):
            reasons.append("Critical/debate mode raises this claim's importance.")
        if claim.qualifications:
            reasons.append("Carries material qualifications that should not be lost.")
        return reasons
