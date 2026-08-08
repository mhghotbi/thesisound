from __future__ import annotations

from uuid import UUID

from thesisound.episode import ClaimPriorityReport, CoverageReport, EpisodeBudgetReport
from thesisound.source_analysis import SourceDocumentBlock


class EpisodeBudgetEstimator:
    """Conservatively bound supported duration using auditable engineering assumptions."""

    def __init__(
        self,
        *,
        words_per_minute: int = 130,
        explanation_expansion_factor: float = 4.0,
        evidence_tokens_per_output_minute: float = 20.0,
        calibration_status: str = "fixture_calibrated",
    ) -> None:
        self.words_per_minute = words_per_minute
        self.explanation_expansion_factor = explanation_expansion_factor
        self.evidence_tokens_per_output_minute = evidence_tokens_per_output_minute
        self.calibration_status = calibration_status

    def estimate(
        self,
        *,
        project_id: UUID,
        target_duration_minutes: int,
        coverage: CoverageReport,
        priorities: ClaimPriorityReport,
        original_blocks: list[SourceDocumentBlock],
    ) -> EpisodeBudgetReport:
        available_claim_seconds = sum(
            item.estimated_explanation_seconds
            for item in priorities.priorities
            if item.level in {"must_include", "supporting", "optional"}
        )
        original_evidence_tokens = sum(
            block.estimated_token_count for block in original_blocks
        )
        claim_supported_minutes = (
            available_claim_seconds * self.explanation_expansion_factor / 60
        )
        evidence_supported_minutes = (
            original_evidence_tokens / self.evidence_tokens_per_output_minute
            if self.evidence_tokens_per_output_minute
            else 0
        )
        deterministic_supported = min(
            120.0,
            claim_supported_minutes,
            evidence_supported_minutes,
        )
        effective = min(
            float(coverage.max_supported_minutes),
            deterministic_supported,
        )
        return EpisodeBudgetReport(
            project_id=project_id,
            target_duration_minutes=target_duration_minutes,
            words_per_minute=self.words_per_minute,
            available_claim_seconds=available_claim_seconds,
            original_evidence_tokens=original_evidence_tokens,
            estimated_supported_minutes=round(deterministic_supported, 2),
            model_reported_supported_minutes=coverage.max_supported_minutes,
            effective_supported_minutes=round(effective, 2),
            calibration_status=self.calibration_status,
            assumptions=[
                f"Persian speech target: {self.words_per_minute} words per minute.",
                "Claim explanation seconds are expanded by "
                f"{self.explanation_expansion_factor:.2f} for examples, transitions, and dialogue.",
                "At least "
                f"{self.evidence_tokens_per_output_minute:.2f} original evidence tokens are required "
                "per output minute.",
                "The effective limit is the minimum of model and deterministic estimates.",
            ],
        )
