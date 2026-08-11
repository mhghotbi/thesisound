from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from thesisound.domain import GlossaryTerm, Script, VerificationIssue


class GlossaryTermDraft(BaseModel):
    source_term: str = Field(min_length=1)
    preferred_persian: str = Field(min_length=1)
    first_use_form: str = Field(min_length=1)
    subsequent_use_form: str = Field(min_length=1)
    pronunciation_hint: str | None = None
    translation_status: Literal[
        "standard",
        "contextual",
        "contested",
        "transliteration_only",
    ]
    must_not_confuse_with: list[str] = Field(default_factory=list)


class GlossaryDraft(BaseModel):
    terms: list[GlossaryTermDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Glossary(BaseModel):
    project_id: UUID
    terms: list[GlossaryTerm] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model_run_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def require_unique_source_terms(self) -> Glossary:
        keys = [term.source_term.casefold() for term in self.terms]
        if len(keys) != len(set(keys)):
            raise ValueError("Glossary contains duplicate source terms.")
        return self


class ScriptTurnDraft(BaseModel):
    speaker: Literal["A", "B"]
    spoken_text_fa: str = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    editorial_only: bool = False

    @model_validator(mode="after")
    def require_grounding(self) -> ScriptTurnDraft:
        if not self.editorial_only and not self.claim_ids:
            raise ValueError("Substantive draft turns require claim IDs.")
        if not self.editorial_only and not self.evidence_ids:
            raise ValueError("Substantive draft turns require evidence IDs.")
        return self


class SegmentScriptDraft(BaseModel):
    turns: list[ScriptTurnDraft] = Field(min_length=1)


class ScriptCheckIssue(BaseModel):
    turn_id: str | None = None
    segment_id: str | None = None
    severity: Literal["low", "medium", "high", "blocking"]
    issue_type: Literal[
        "unknown_claim",
        "unknown_evidence",
        "claim_outside_segment",
        "evidence_outside_pack",
        "missing_grounding",
        "evidence_unlinked_to_claim",
        "duration_mismatch",
        "repetition",
        "glossary_inconsistency",
        "prompt_leakage",
        "speaker_pattern",
        "speaker_balance",
        "restatement",
        "other",
    ]
    explanation: str = Field(min_length=1)


class ScriptCheckReport(BaseModel):
    project_id: UUID
    verdict: Literal["pass", "revise", "reject"]
    issues: list[ScriptCheckIssue] = Field(default_factory=list)
    word_count: int = Field(ge=0)
    estimated_minutes: float = Field(ge=0)
    substantive_turn_count: int = Field(ge=0)
    # Defaulted so reports written before R10 still load.
    editorial_word_ratio: float = Field(default=0.0, ge=0, le=1)
    speaker_a_word_count: int = Field(default=0, ge=0)
    speaker_b_word_count: int = Field(default=0, ge=0)
    speaker_b_substantive_turn_count: int = Field(default=0, ge=0)
    claims_per_segment_minute: float = Field(default=0.0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


_QUALITY_WEIGHTS: dict[str, float] = {
    "evidence_fidelity": 0.30,
    "qualification_preservation": 0.25,
    "stance_and_disagreement": 0.20,
    "terminology_consistency": 0.15,
    "listenability": 0.10,
}


class ScriptQualityScore(BaseModel):
    evidence_fidelity: float = Field(ge=0, le=1)
    qualification_preservation: float = Field(ge=0, le=1)
    stance_and_disagreement: float = Field(ge=0, le=1)
    terminology_consistency: float = Field(ge=0, le=1)
    listenability: float = Field(ge=0, le=1)
    actionable_feedback: str = ""

    @property
    def overall(self) -> float:
        return round(
            sum(getattr(self, name) * weight for name, weight in _QUALITY_WEIGHTS.items()),
            4,
        )


class VerificationDraft(BaseModel):
    verdict: Literal["pass", "revise", "reject"]
    issues: list[VerificationIssue] = Field(default_factory=list)
    unsupported_claim_ratio: float = Field(ge=0, le=1)
    quality: ScriptQualityScore | None = None


class RevisionDecision(BaseModel):
    project_id: UUID
    accepted: bool
    reason: str
    original_verdict: str
    revised_verdict: str | None
    original_overall: float | None
    revised_overall: float | None
    delta: float | None
    original_issue_count: int
    revised_issue_count: int | None
    changed_turn_count: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RevisedTurnDraft(BaseModel):
    turn_id: str = Field(min_length=1)
    speaker: Literal["A", "B"]
    spoken_text_fa: str = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    editorial_only: bool = False


class TargetedRevisionDraft(BaseModel):
    revised_turns: list[RevisedTurnDraft] = Field(default_factory=list)


class ScriptPipelineManifest(BaseModel):
    project_id: UUID
    status: Literal[
        "glossary_ready",
        "draft_ready",
        "checks_ready",
        "verification_ready",
        "revision_ready",
        "verified",
        "review_required",
        "failed",
    ]
    segment_count: int = Field(default=0, ge=0)
    turn_count: int = Field(default=0, ge=0)
    revision_count: int = Field(default=0, ge=0)
    model_run_ids: list[UUID] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_error: str | None = None


class ScriptReviewDecision(BaseModel):
    project_id: UUID
    decision: Literal["accepted", "sent_back"]
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2_000)
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks_verdict: str
    verification_verdict: str
    unsupported_claim_ratio: float
    quality_overall: float | None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ScriptPipelineResult(BaseModel):
    glossary: Glossary
    script: Script
    checks: ScriptCheckReport
    verification: VerificationDraft
