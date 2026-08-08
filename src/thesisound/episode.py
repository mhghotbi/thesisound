from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from thesisound.domain import EvidenceItem
from thesisound.source_analysis import SourceDocumentBlock

CoverageStatus = Literal["well_covered", "partially_covered", "not_covered"]
CoverageRecommendation = Literal["continue", "narrow_scope", "more_evidence"]
ClaimPriorityLevel = Literal["must_include", "supporting", "optional", "deferred"]
SpeakerDynamic = Literal[
    "explanation",
    "questioning",
    "critique",
    "comparison",
    "recap",
]


class ObjectiveCoverageDraft(BaseModel):
    objective: str = Field(min_length=1)
    status: CoverageStatus
    claim_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)


class CoverageAuditDraft(BaseModel):
    central_question_status: CoverageStatus
    central_question_claim_ids: list[str] = Field(default_factory=list)
    objective_coverage: list[ObjectiveCoverageDraft] = Field(default_factory=list)
    material_gaps: list[str] = Field(default_factory=list)
    max_supported_minutes: int = Field(ge=0, le=120)
    recommendation: CoverageRecommendation
    recommendation_reason: str = Field(min_length=1)


class CoverageReport(BaseModel):
    project_id: UUID
    central_question_status: CoverageStatus
    central_question_claim_ids: list[str] = Field(default_factory=list)
    objective_coverage: list[ObjectiveCoverageDraft] = Field(default_factory=list)
    material_gaps: list[str] = Field(default_factory=list)
    max_supported_minutes: int = Field(ge=0, le=120)
    recommendation: CoverageRecommendation
    recommendation_reason: str
    can_plan_episode: bool
    model_run_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ClaimPriorityRecord(BaseModel):
    claim_id: str = Field(min_length=1)
    level: ClaimPriorityLevel
    score: int = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    estimated_explanation_seconds: int = Field(ge=15, le=600)


class ClaimPriorityReport(BaseModel):
    project_id: UUID
    target_duration_minutes: int = Field(ge=5, le=120)
    priorities: list[ClaimPriorityRecord] = Field(default_factory=list)
    available_content_seconds: int = Field(ge=0)
    estimated_selected_seconds: int = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def require_unique_claim_ids(self) -> ClaimPriorityReport:
        claim_ids = [item.claim_id for item in self.priorities]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("Claim priority report contains duplicate claim IDs.")
        return self


class EpisodeSegmentDraft(BaseModel):
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    target_minutes: float = Field(gt=0)
    claim_ids: list[str] = Field(min_length=1)
    prerequisite_claim_ids: list[str] = Field(default_factory=list)
    key_question: str = Field(min_length=1)
    speaker_dynamic: SpeakerDynamic


class EpisodePlanDraft(BaseModel):
    title: str = Field(min_length=1)
    listener_outcome: str = Field(min_length=1)
    segments: list[EpisodeSegmentDraft] = Field(min_length=1)
    deliberately_omitted_claims: dict[str, str] = Field(default_factory=dict)
    follow_up_topics: list[str] = Field(default_factory=list)


class SegmentEvidencePack(BaseModel):
    segment_id: str = Field(min_length=1)
    claim_ids: list[str] = Field(min_length=1)
    evidence_items: list[EvidenceItem] = Field(min_length=1)
    original_blocks: list[SourceDocumentBlock] = Field(min_length=1)
    context_blocks: list[SourceDocumentBlock] = Field(default_factory=list)
    token_budget: int = Field(ge=1)
    actual_tokens: int = Field(ge=1)
    warnings: list[str] = Field(default_factory=list)


class EpisodePreparationManifest(BaseModel):
    project_id: UUID
    status: Literal[
        "coverage_ready",
        "priorities_ready",
        "plan_ready",
        "evidence_packs_ready",
        "failed",
    ]
    source_ids: list[UUID] = Field(default_factory=list)
    coverage_recommendation: CoverageRecommendation | None = None
    segment_count: int = Field(default=0, ge=0)
    evidence_pack_count: int = Field(default=0, ge=0)
    model_run_ids: list[UUID] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_error: str | None = None
