from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from thesisound.domain import EpisodePlan
from thesisound.episode import SegmentEvidencePack
from thesisound.script import ScriptCheckReport, VerificationDraft


class BudgetCalibrationPoint(BaseModel):
    project_id: UUID
    target_duration_minutes: float = Field(gt=0)
    planned_duration_minutes: float = Field(gt=0)
    estimated_script_minutes: float = Field(ge=0)
    script_word_count: int = Field(ge=0)
    evidence_tokens: int = Field(ge=0)
    claim_count: int = Field(ge=0)
    evidence_tokens_per_script_minute: float | None = Field(default=None, ge=0)
    check_verdict: Literal["pass", "revise", "reject"]
    verification_verdict: Literal["pass", "revise", "reject"]
    unsupported_claim_ratio: float = Field(ge=0, le=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BudgetCalibrationReport(BaseModel):
    points: list[BudgetCalibrationPoint] = Field(default_factory=list)
    status: Literal["insufficient_samples", "ready_for_review"]
    median_evidence_tokens_per_script_minute: float | None = Field(default=None, ge=0)
    median_duration_ratio: float | None = Field(default=None, ge=0)
    passing_sample_count: int = Field(ge=0)


class BudgetCalibrationRecorder:
    def __init__(self, workspace_root: Path) -> None:
        self.path = (
            workspace_root.expanduser().resolve()
            / "evaluations"
            / "budget-calibration.jsonl"
        )

    def record(
        self,
        *,
        project_id: UUID,
        target_duration_minutes: float,
        episode_plan: EpisodePlan,
        evidence_packs: list[SegmentEvidencePack],
        checks: ScriptCheckReport,
        verification: VerificationDraft,
    ) -> BudgetCalibrationReport:
        evidence_tokens = sum(pack.actual_tokens for pack in evidence_packs)
        claim_count = len(
            {
                claim_id
                for segment in episode_plan.segments
                for claim_id in segment.claim_ids
            }
        )
        tokens_per_minute = (
            evidence_tokens / checks.estimated_minutes
            if checks.estimated_minutes > 0
            else None
        )
        point = BudgetCalibrationPoint(
            project_id=project_id,
            target_duration_minutes=target_duration_minutes,
            planned_duration_minutes=episode_plan.estimated_duration_minutes,
            estimated_script_minutes=checks.estimated_minutes,
            script_word_count=checks.word_count,
            evidence_tokens=evidence_tokens,
            claim_count=claim_count,
            evidence_tokens_per_script_minute=tokens_per_minute,
            check_verdict=checks.verdict,
            verification_verdict=verification.verdict,
            unsupported_claim_ratio=verification.unsupported_claim_ratio,
        )
        points = self._read()
        points = [
            item
            for item in points
            if not (
                item.project_id == project_id
                and item.target_duration_minutes == target_duration_minutes
            )
        ]
        points.append(point)
        self._write(points)
        return _report(points)

    def report(self) -> BudgetCalibrationReport:
        return _report(self._read())

    def _read(self) -> list[BudgetCalibrationPoint]:
        if not self.path.exists():
            return []
        return [
            BudgetCalibrationPoint.model_validate_json(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def _write(self, points: list[BudgetCalibrationPoint]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".jsonl.tmp")
        temporary.write_text(
            "\n".join(
                json.dumps(point.model_dump(mode="json"), ensure_ascii=False)
                for point in points
            )
            + ("\n" if points else ""),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _report(points: list[BudgetCalibrationPoint]) -> BudgetCalibrationReport:
    passing = [
        point
        for point in points
        if point.check_verdict == "pass"
        and point.verification_verdict == "pass"
        and point.unsupported_claim_ratio == 0
        and point.estimated_script_minutes > 0
    ]
    token_rates = [
        point.evidence_tokens_per_script_minute
        for point in passing
        if point.evidence_tokens_per_script_minute is not None
    ]
    duration_ratios = [
        point.estimated_script_minutes / point.target_duration_minutes
        for point in passing
    ]
    return BudgetCalibrationReport(
        points=points,
        status="ready_for_review" if len(passing) >= 3 else "insufficient_samples",
        median_evidence_tokens_per_script_minute=(
            round(median(token_rates), 2) if token_rates else None
        ),
        median_duration_ratio=(
            round(median(duration_ratios), 3) if duration_ratios else None
        ),
        passing_sample_count=len(passing),
    )
