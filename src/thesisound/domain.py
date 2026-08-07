from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, model_validator


class ProjectState(StrEnum):
    DRAFT = "draft"
    BRIEF_READY = "brief_ready"
    SOURCES_COLLECTING = "sources_collecting"
    SOURCE_SELECTION_REQUIRED = "source_selection_required"
    CORPUS_BUILDING = "corpus_building"
    CORPUS_READY = "corpus_ready"
    EPISODE_PLANNING = "episode_planning"
    EPISODE_PLANNED = "episode_planned"
    SCRIPT_DRAFTING = "script_drafting"
    SCRIPT_READY = "script_ready"
    SCRIPT_VERIFYING = "script_verifying"
    SCRIPT_VERIFIED = "script_verified"
    AUDIO_GENERATING = "audio_generating"
    AUDIO_READY = "audio_ready"
    AUDIO_VERIFYING = "audio_verifying"
    COMPLETE = "complete"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"


class TopicType(StrEnum):
    PERSON = "person"
    WORK = "work"
    CONCEPT = "concept"
    EVENT = "event"
    DEBATE = "debate"
    COMPARISON = "comparison"
    QUESTION = "question"
    MIXED = "mixed"


class SourceRole(StrEnum):
    PRIMARY = "primary"
    REFERENCE = "reference"
    SCHOLARLY_SECONDARY = "scholarly_secondary"
    CRITICAL = "critical"
    HISTORICAL_CONTEXT = "historical_context"
    RECENT_RESEARCH = "recent_research"
    USER_CONTEXT = "user_context"


class SourceAccess(StrEnum):
    FULL_TEXT = "full_text"
    PARTIAL_TEXT = "partial_text"
    ABSTRACT_ONLY = "abstract_only"
    METADATA_ONLY = "metadata_only"
    INACCESSIBLE = "inaccessible"


class SourceDecision(StrEnum):
    PENDING = "pending"
    INCLUDE = "include"
    EXCLUDE = "exclude"
    BACKGROUND_ONLY = "background_only"
    RECOMMENDED_READING_ONLY = "recommended_reading_only"


class ClaimType(StrEnum):
    AUTHOR_POSITION = "author_position"
    SCHOLARLY_INTERPRETATION = "scholarly_interpretation"
    HISTORICAL_CONTEXT = "historical_context"
    CRITICISM = "criticism"
    COUNTERARGUMENT = "counterargument"
    EDITORIAL_EXPLANATION = "editorial_explanation"


class SupportStatus(StrEnum):
    STRONG = "strong"
    MODERATE = "moderate"
    CONTESTED = "contested"
    UNCERTAIN = "uncertain"


class ResearchBrief(BaseModel):
    normalized_topic: str
    topic_type: TopicType
    central_question: str
    audience: str = "educated general listener"
    prior_knowledge: Literal["none", "introductory", "intermediate", "advanced"] = "introductory"
    target_duration_minutes: int = Field(default=30, ge=5, le=120)
    output_language: str = "fa"
    modes: list[Literal["explanatory", "critical", "comparative", "debate"]] = [
        "explanatory"
    ]
    learning_objectives: list[str] = []
    subquestions: list[str] = []
    scope_inclusions: list[str] = []
    scope_exclusions: list[str] = []
    ambiguities: list[str] = []


class SearchQuery(BaseModel):
    query: str
    provider: Literal[
        "openalex",
        "semantic_scholar",
        "crossref",
        "google_books",
        "open_library",
        "web",
    ]
    source_role: SourceRole
    language: str
    purpose: str
    priority: int = Field(ge=1, le=5)
    exact_phrases: list[str] = []
    include_domains: list[str] = []
    exclude_domains: list[str] = []
    year_from: int | None = None
    year_to: int | None = None


class SourceCandidate(BaseModel):
    source_id: UUID = Field(default_factory=uuid4)
    title: str
    authors: list[str] = []
    role: SourceRole
    source_type: str
    origin: str
    language: str | None = None
    publication_year: int | None = None
    publisher_or_venue: str | None = None
    doi: str | None = None
    canonical_url: HttpUrl | None = None
    access: SourceAccess = SourceAccess.METADATA_ONLY
    user_decision: SourceDecision = SourceDecision.PENDING
    relevance_reasons: list[str] = []
    authority_class: Literal[
        "primary_text",
        "peer_reviewed_or_university_press",
        "academic_reference",
        "reputable_institution",
        "general_web",
        "unknown",
    ] = "unknown"
    limitations: list[str] = []
    duplicate_of: UUID | None = None

    @property
    def usable_as_evidence(self) -> bool:
        return self.access == SourceAccess.FULL_TEXT and self.user_decision == SourceDecision.INCLUDE


class Locator(BaseModel):
    page_start: int | None = None
    page_end: int | None = None
    chapter: str | None = None
    section: str | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    epub_cfi: str | None = None


class DocumentBlock(BaseModel):
    block_id: str
    source_id: UUID
    locator: Locator
    heading_path: list[str] = []
    block_type: Literal[
        "front_matter",
        "definition",
        "argument",
        "example",
        "objection",
        "response",
        "transition",
        "conclusion",
        "other",
    ] = "other"
    text: str
    token_count: int = Field(ge=1)
    previous_block_id: str | None = None
    next_block_id: str | None = None


class EvidenceItem(BaseModel):
    evidence_id: str
    source_id: UUID
    block_id: str
    claim: str
    claim_type: ClaimType
    supporting_excerpt: str
    locator: Locator
    support_kind: Literal["direct", "inferential"]
    qualifications: list[str] = []
    confidence: float = Field(ge=0, le=1)


class ClaimRecord(BaseModel):
    claim_id: str
    claim: str
    claim_type: ClaimType
    evidence_ids: list[str]
    support_status: SupportStatus
    qualifications: list[str] = []
    agreeing_source_ids: list[UUID] = []
    disagreeing_source_ids: list[UUID] = []

    @model_validator(mode="after")
    def require_evidence_for_non_editorial_claim(self) -> ClaimRecord:
        if self.claim_type != ClaimType.EDITORIAL_EXPLANATION and not self.evidence_ids:
            raise ValueError("Non-editorial claims require at least one evidence_id")
        return self


class EpisodeSegment(BaseModel):
    segment_id: str
    title: str
    purpose: str
    estimated_minutes: float = Field(gt=0)
    claim_ids: list[str]
    key_question: str
    speaker_dynamic: Literal[
        "explanation",
        "questioning",
        "critique",
        "comparison",
        "recap",
    ]


class EpisodePlan(BaseModel):
    title: str
    listener_outcome: str
    estimated_duration_minutes: float = Field(gt=0)
    segments: list[EpisodeSegment]
    deliberately_omitted_claims: dict[str, str] = {}
    follow_up_topics: list[str] = []


class ScriptTurn(BaseModel):
    turn_id: str
    segment_id: str
    speaker: Literal["A", "B"]
    spoken_text_fa: str
    claim_ids: list[str] = []
    editorial_only: bool = False

    @model_validator(mode="after")
    def enforce_grounding(self) -> ScriptTurn:
        if not self.editorial_only and not self.claim_ids:
            raise ValueError("Substantive turns require claim_ids")
        return self


class Script(BaseModel):
    title: str
    turns: list[ScriptTurn]
    glossary_terms_used: list[str] = []


class VerificationIssue(BaseModel):
    turn_id: str
    severity: Literal["low", "medium", "high", "blocking"]
    issue_type: Literal[
        "unsupported_claim",
        "overstated_certainty",
        "lost_qualification",
        "wrong_attribution",
        "collapsed_disagreement",
        "invented_example",
        "terminology_error",
        "translation_shift",
        "other",
    ]
    explanation: str
    required_revision: str


class VerificationReport(BaseModel):
    verdict: Literal["pass", "revise", "reject"]
    issues: list[VerificationIssue] = []
    unsupported_claim_ratio: float = Field(ge=0, le=1)


class Project(BaseModel):
    project_id: UUID = Field(default_factory=uuid4)
    raw_input: str
    state: ProjectState = ProjectState.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    brief: ResearchBrief | None = None
    sources: list[SourceCandidate] = []
    episode_plan: EpisodePlan | None = None
    script: Script | None = None
    last_error: str | None = None
