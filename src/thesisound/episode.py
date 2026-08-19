from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from thesisound.domain import (
    ClaimRecord,
    DeliberatelyOmittedClaim,
    EvidenceItem,
    MustNotBeLostPoint,
    coerce_deliberately_omitted_claims,
)
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
SourceStance = Literal["supports", "disputes", "qualifies", "unclear"]


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
    deliberately_omitted_claims: list[DeliberatelyOmittedClaim] = Field(default_factory=list)
    follow_up_topics: list[str] = Field(default_factory=list)

    @field_validator("deliberately_omitted_claims", mode="before")
    @classmethod
    def _coerce_omitted_claims(cls, value: object) -> object:
        return coerce_deliberately_omitted_claims(value)


class RetrievalHit(BaseModel):
    block_id: str = Field(min_length=1)
    source_id: UUID
    score: float
    query: str = Field(min_length=1)


class SegmentEvidencePack(BaseModel):
    segment_id: str = Field(min_length=1)
    claim_ids: list[str] = Field(min_length=1)
    claims: list[ClaimRecord] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(min_length=1)
    original_blocks: list[SourceDocumentBlock] = Field(min_length=1)
    context_blocks: list[SourceDocumentBlock] = Field(default_factory=list)
    retrieval_hits: list[RetrievalHit] = Field(default_factory=list)
    token_budget: int = Field(ge=1)
    actual_tokens: int = Field(ge=1)
    warnings: list[str] = Field(default_factory=list)


class DisagreementSourcePosition(BaseModel):
    source_id: UUID
    stance: SourceStance
    evidence_ids: list[str] = Field(default_factory=list)


class DisagreementNode(BaseModel):
    claim_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    positions: list[DisagreementSourcePosition] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)


class DisagreementEdge(BaseModel):
    from_claim_id: str = Field(min_length=1)
    to_claim_id: str = Field(min_length=1)
    relation: Literal["contradicts", "qualifies", "responds_to"]
    rationale: str = Field(min_length=1)


class DisagreementGraph(BaseModel):
    project_id: UUID
    nodes: list[DisagreementNode] = Field(default_factory=list)
    edges: list[DisagreementEdge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EpisodeBudgetReport(BaseModel):
    project_id: UUID
    target_duration_minutes: int = Field(ge=5, le=120)
    words_per_minute: int = Field(ge=80, le=220)
    available_claim_seconds: int = Field(ge=0)
    original_evidence_tokens: int = Field(ge=0)
    estimated_supported_minutes: float = Field(ge=0, le=120)
    model_reported_supported_minutes: int = Field(ge=0, le=120)
    effective_supported_minutes: float = Field(ge=0, le=120)
    calibration_status: Literal["uncalibrated", "fixture_calibrated", "corpus_calibrated"]
    assumptions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EpisodeStageInputs(BaseModel):
    """Input keys the stored coverage report and episode plan were produced from.

    A stage is reusable only while its key still matches the current inputs. Writing a
    fresh coverage report clears `plan`, because everything downstream of coverage was
    planned against the answer that just changed.

    ``coverage_semantic`` / ``plan_semantic`` retain the model/prompt/version payload
    used to build each key so cache misses can report a field-level invalidation reason.
    """

    coverage: str | None = None
    plan: str | None = None
    coverage_semantic: dict[str, object] | None = None
    plan_semantic: dict[str, object] | None = None


class EpisodePreparationManifest(BaseModel):
    project_id: UUID
    status: Literal[
        "coverage_ready",
        "budget_ready",
        "priorities_ready",
        "disagreement_ready",
        "plan_ready",
        "evidence_packs_ready",
        "failed",
    ]
    source_ids: list[UUID] = Field(default_factory=list)
    coverage_recommendation: CoverageRecommendation | None = None
    segment_count: int = Field(default=0, ge=0)
    evidence_pack_count: int = Field(default=0, ge=0)
    disagreement_count: int = Field(default=0, ge=0)
    model_run_ids: list[UUID] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_error: str | None = None


class MustNotBeLostReviewItem(BaseModel):
    point: MustNotBeLostPoint
    reflected_in_claims: list[str] = Field(default_factory=list)
    used_in_plan: bool = False


class MustNotBeLostReview(BaseModel):
    """Deterministic cross-reference: did each safety-net flag survive into the plan?

    Non-blocking by construction -- this is a human-review surface, not a gate. A
    flagged item with no reflected claim, or one whose claim was deliberately
    omitted, is surfaced here rather than silently dropped.
    """

    project_id: UUID
    items: list[MustNotBeLostReviewItem] = Field(default_factory=list)
    unused_count: int = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
