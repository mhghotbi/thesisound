from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from thesisound.domain import ClaimRecord, ResearchBrief
from thesisound.episode import CoverageAuditDraft, CoverageReport
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.services.model_runner import ModelRunner
from thesisound.source_analysis import EvidenceExtractionPlan


class CoverageAuditorService:
    def __init__(self, model_runner: ModelRunner) -> None:
        self.model_runner = model_runner

    def audit(
        self,
        *,
        project_id: UUID,
        brief: ResearchBrief,
        claims: list[ClaimRecord],
        extraction_plans: list[EvidenceExtractionPlan],
        model: str,
        prompt_version: str | None = None,
    ) -> tuple[CoverageReport, ModelRunRecord]:
        if not claims:
            raise ValueError("Coverage audit requires at least one grounded claim.")
        claim_ids = {claim.claim_id for claim in claims}
        execution = self.model_runner.run(
            project_id=project_id,
            stage="coverage_audit",
            prompt_name="coverage_audit",
            variables={
                "research_brief": brief.model_dump(mode="json"),
                "claims": [claim.model_dump(mode="json") for claim in claims],
                "extraction_plans": [
                    plan.model_dump(mode="json") for plan in extraction_plans
                ],
            },
            output_type=CoverageAuditDraft,
            model=model,
            prompt_version=prompt_version,
            validator=lambda draft: _validate_draft(draft, brief, claim_ids),
        )
        draft = execution.output
        can_plan = (
            draft.recommendation == "continue"
            and draft.max_supported_minutes >= round(brief.target_duration_minutes * 0.8)
        )
        return (
            CoverageReport(
                project_id=project_id,
                central_question_status=draft.central_question_status,
                central_question_claim_ids=draft.central_question_claim_ids,
                objective_coverage=draft.objective_coverage,
                material_gaps=draft.material_gaps,
                max_supported_minutes=draft.max_supported_minutes,
                recommendation=draft.recommendation,
                recommendation_reason=draft.recommendation_reason,
                can_plan_episode=can_plan,
                model_run_id=execution.record.run_id,
            ),
            execution.record,
        )


def _validate_draft(
    draft: CoverageAuditDraft,
    brief: ResearchBrief,
    known_claim_ids: set[str],
) -> None:
    _require_known_claims(draft.central_question_claim_ids, known_claim_ids)
    expected_objectives = list(dict.fromkeys(brief.learning_objectives))
    returned_objectives = [item.objective for item in draft.objective_coverage]
    if returned_objectives != expected_objectives:
        raise DeterministicValidationError(
            "Coverage audit must return every learning objective once and in input order."
        )
    for item in draft.objective_coverage:
        _require_known_claims(item.claim_ids, known_claim_ids)
        if item.status == "well_covered" and not item.claim_ids:
            raise DeterministicValidationError(
                f"Well-covered objective has no claim IDs: {item.objective}"
            )
    if draft.central_question_status == "well_covered" and not (
        draft.central_question_claim_ids
    ):
        raise DeterministicValidationError(
            "A well-covered central question requires at least one claim ID."
        )
    if draft.recommendation == "continue" and draft.max_supported_minutes == 0:
        raise DeterministicValidationError(
            "Coverage audit cannot recommend continuing with zero supported minutes."
        )


def _require_known_claims(claim_ids: Iterable[str], known_claim_ids: set[str]) -> None:
    unknown = sorted(set(claim_ids) - known_claim_ids)
    if unknown:
        raise DeterministicValidationError(
            f"Coverage audit referenced unknown claim IDs: {', '.join(unknown)}"
        )
