from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


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
    SCRIPT_REVIEW_REQUIRED = "script_review_required"
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


class AuthorityClass(StrEnum):
    PRIMARY_TEXT = "primary_text"
    PEER_REVIEWED_OR_UNIVERSITY_PRESS = "peer_reviewed_or_university_press"
    ACADEMIC_REFERENCE = "academic_reference"
    REPUTABLE_INSTITUTION = "reputable_institution"
    GENERAL_WEB = "general_web"
    UNKNOWN = "unknown"


class ClaimType(StrEnum):
    AUTHOR_POSITION = "author_position"
    SCHOLARLY_INTERPRETATION = "scholarly_interpretation"
    HISTORICAL_CONTEXT = "historical_context"
    CRITICISM = "criticism"
    COUNTERARGUMENT = "counterargument"
    EDITORIAL_EXPLANATION = "editorial_explanation"
    # Extraction 2.0 (10c P2 Step 1): the former aux lists (definitions,
    # distinctions, examples, objections, responses) are now claims with one
    # of these types, so every extracted item lives in one audited inventory.
    DEFINITION = "definition"
    DISTINCTION = "distinction"
    EXAMPLE = "example"
    OBJECTION = "objection"
    RESPONSE = "response"


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
    modes: list[Literal["explanatory", "critical", "comparative", "debate"]] = Field(
        default_factory=lambda: ["explanatory"]
    )
    learning_objectives: list[str] = Field(default_factory=list)
    subquestions: list[str] = Field(default_factory=list)
    scope_inclusions: list[str] = Field(default_factory=list)
    scope_exclusions: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)


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
    exact_phrases: list[str] = Field(default_factory=list)
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    year_from: int | None = None
    year_to: int | None = None


class SourceAssessment(BaseModel):
    recommended_role: SourceRole
    relevance_reasons: list[str] = Field(default_factory=list)
    perspective: str | None = None
    recommended_authority_class: AuthorityClass = AuthorityClass.UNKNOWN
    can_support: list[str] = Field(default_factory=list)
    cannot_support: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    distinct_value: str | None = None
    inclusion_recommendation: Literal["strong_include", "optional", "background_only", "reject"]
    recommendation_reason: str
    requires_full_text_before_use: bool


class SourceCandidate(BaseModel):
    source_id: UUID = Field(default_factory=uuid4)
    title: str
    authors: list[str] = Field(default_factory=list)
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
    relevance_reasons: list[str] = Field(default_factory=list)
    authority_class: AuthorityClass = AuthorityClass.UNKNOWN
    limitations: list[str] = Field(default_factory=list)
    duplicate_of: UUID | None = None

    @property
    def usable_as_evidence(self) -> bool:
        return (
            self.access == SourceAccess.FULL_TEXT and self.user_decision == SourceDecision.INCLUDE
        )


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
    heading_path: list[str] = Field(default_factory=list)
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


class DocumentMapSection(BaseModel):
    section_id: str
    source_block_ids: list[str]
    title: str
    function: Literal[
        "front_matter",
        "definition",
        "argument",
        "example",
        "objection",
        "response",
        "transition",
        "conclusion",
        "other",
    ]
    key_concepts: list[str] = Field(default_factory=list)
    depends_on_section_ids: list[str] = Field(default_factory=list)
    required_for_global_understanding: bool = False
    unresolved_context: list[str] = Field(default_factory=list)


class CrossSectionThread(BaseModel):
    label: str
    section_ids: list[str]
    description: str


class DocumentMap(BaseModel):
    source_id: UUID
    scope_locator: Locator
    working_thesis: str | None = None
    sections: list[DocumentMapSection]
    cross_section_threads: list[CrossSectionThread] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExtractedDefinition(BaseModel):
    term: str
    definition: str
    source_id: UUID
    block_id: str
    locator: Locator


class ExtractedDistinction(BaseModel):
    item_a: str
    item_b: str
    distinction: str
    source_id: UUID
    block_id: str
    locator: Locator


class ExtractedAuxiliaryPoint(BaseModel):
    """A grounded example, objection, or response from one block.

    One shape for all three categories: the field they live under on
    ``EvidenceExtraction`` already carries the semantic distinction.
    """

    text: str
    source_id: UUID
    block_id: str
    locator: Locator


class MustNotBeLostPoint(BaseModel):
    """Block-level content flagged important but not turned into a claim.

    A safety-net flag, not a proposition. Kept distinct from
    ``ExtractedAuxiliaryPoint`` so the must-not-be-lost review artifact stays
    self-documenting.
    """

    text: str
    source_id: UUID
    block_id: str
    locator: Locator


class EvidenceItem(BaseModel):
    evidence_id: str
    source_id: UUID
    block_id: str
    claim: str
    claim_type: ClaimType
    supporting_excerpt: str
    locator: Locator
    support_kind: Literal["direct", "inferential"]
    qualifications: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    # Extraction 2.0 claim-level fields (10c P2 Step 1).
    must_not_be_lost: bool = False
    term: str | None = None
    contrast: tuple[str, str] | None = None


class EvidenceExtraction(BaseModel):
    segment_function: str
    claims: list[EvidenceItem] = Field(default_factory=list)
    definitions: list[ExtractedDefinition] = Field(default_factory=list)
    distinctions: list[ExtractedDistinction] = Field(default_factory=list)
    examples: list[ExtractedAuxiliaryPoint] = Field(default_factory=list)
    objections: list[ExtractedAuxiliaryPoint] = Field(default_factory=list)
    responses: list[ExtractedAuxiliaryPoint] = Field(default_factory=list)
    must_not_be_lost: list[MustNotBeLostPoint] = Field(default_factory=list)


class ClaimRecord(BaseModel):
    claim_id: str
    claim: str
    claim_type: ClaimType
    evidence_ids: list[str]
    support_status: SupportStatus
    qualifications: list[str] = Field(default_factory=list)
    agreeing_source_ids: list[UUID] = Field(default_factory=list)
    disagreeing_source_ids: list[UUID] = Field(default_factory=list)
    # Extraction 2.0 claim-level fields (10c P2 Step 1).
    must_not_be_lost: bool = False
    term: str | None = None
    contrast: tuple[str, str] | None = None

    @model_validator(mode="after")
    def require_evidence_for_non_editorial_claim(self) -> ClaimRecord:
        if self.claim_type != ClaimType.EDITORIAL_EXPLANATION and not self.evidence_ids:
            raise ValueError("Non-editorial claims require at least one evidence_id")
        return self


class CoverageItem(BaseModel):
    subquestion: str
    status: Literal["well_covered", "partially_covered", "not_covered"]
    claim_ids: list[str] = Field(default_factory=list)
    missing_source_roles: list[SourceRole] = Field(default_factory=list)
    risk_if_ignored: str | None = None


class CoverageReport(BaseModel):
    coverage: list[CoverageItem]
    requires_more_research: bool = False
    material_gaps: list[str] = Field(default_factory=list)


class EpisodeSegment(BaseModel):
    segment_id: str
    title: str
    purpose: str
    estimated_minutes: float = Field(gt=0)
    claim_ids: list[str]
    prerequisite_claim_ids: list[str] = Field(default_factory=list)
    key_question: str
    speaker_dynamic: Literal[
        "explanation",
        "questioning",
        "critique",
        "comparison",
        "recap",
    ]
    part_index: int = Field(default=1, ge=1)


class DeliberatelyOmittedClaim(BaseModel):
    """Gemini-safe omitted-claim record (no free-form object maps)."""

    claim_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


def coerce_deliberately_omitted_claims(value: object) -> object:
    """Accept legacy `{claim_id: reason}` maps as well as list records."""
    if isinstance(value, dict):
        return [
            {"claim_id": str(claim_id), "reason": str(reason)} for claim_id, reason in value.items()
        ]
    return value


class EpisodePlan(BaseModel):
    title: str
    listener_outcome: str
    estimated_duration_minutes: float = Field(gt=0)
    segments: list[EpisodeSegment]
    deliberately_omitted_claims: list[DeliberatelyOmittedClaim] = Field(default_factory=list)
    follow_up_topics: list[str] = Field(default_factory=list)

    @field_validator("deliberately_omitted_claims", mode="before")
    @classmethod
    def _coerce_omitted_claims(cls, value: object) -> object:
        return coerce_deliberately_omitted_claims(value)


class GlossaryTerm(BaseModel):
    source_term: str
    preferred_persian: str
    first_use_form: str
    subsequent_use_form: str
    pronunciation_hint: str | None = None
    translation_status: Literal["standard", "contextual", "contested", "transliteration_only"]
    must_not_confuse_with: list[str] = Field(default_factory=list)


class ScriptTurn(BaseModel):
    turn_id: str
    segment_id: str
    speaker: Literal["A", "B"]
    spoken_text_fa: str
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    editorial_only: bool = False

    @model_validator(mode="after")
    def enforce_grounding(self) -> ScriptTurn:
        if not self.editorial_only and not self.claim_ids:
            raise ValueError("Substantive turns require claim_ids")
        if not self.editorial_only and not self.evidence_ids:
            raise ValueError("Substantive turns require evidence_ids")
        return self


class Script(BaseModel):
    title: str
    turns: list[ScriptTurn]
    glossary_terms_used: list[str] = Field(default_factory=list)


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
        "duration_or_pacing",
        "prompt_leakage",
        "other",
    ]
    explanation: str
    required_revision: str


class VerificationReport(BaseModel):
    verdict: Literal["pass", "revise", "reject"]
    issues: list[VerificationIssue] = Field(default_factory=list)
    unsupported_claim_ratio: float = Field(ge=0, le=1)


class AudioQaReport(BaseModel):
    verdict: Literal["pass", "regenerate", "manual_review"]
    missing_content: list[str] = Field(default_factory=list)
    repeated_content: list[str] = Field(default_factory=list)
    truncated: bool = False
    speaker_errors: list[str] = Field(default_factory=list)
    prompt_leakage: list[str] = Field(default_factory=list)
    name_number_date_errors: list[str] = Field(default_factory=list)
    semantic_changes: list[str] = Field(default_factory=list)
    pronunciation_review: list[str] = Field(default_factory=list)
    regeneration_instructions: list[str] = Field(default_factory=list)


class Project(BaseModel):
    project_id: UUID = Field(default_factory=uuid4)
    raw_input: str
    state: ProjectState = ProjectState.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    brief: ResearchBrief | None = None
    sources: list[SourceCandidate] = Field(default_factory=list)
    episode_plan: EpisodePlan | None = None
    script: Script | None = None
    last_error: str | None = None
