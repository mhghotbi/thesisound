from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    Locator,
    SupportStatus,
)

BlockType = Literal[
    "front_matter",
    "definition",
    "argument",
    "example",
    "objection",
    "response",
    "transition",
    "conclusion",
    "table",
    "formula",
    "code",
    "other",
]


class SourceDocumentBlock(BaseModel):
    block_id: str = Field(min_length=1)
    source_id: UUID
    locator: Locator
    heading_path: list[str] = Field(default_factory=list)
    block_type: BlockType = "other"
    text: str = Field(min_length=1)
    estimated_token_count: int = Field(ge=1)
    source_block_keys: list[str] = Field(min_length=1)
    previous_block_id: str | None = None
    next_block_id: str | None = None


class BlockBuildReport(BaseModel):
    source_id: UUID
    input_block_count: int = Field(ge=0)
    output_block_count: int = Field(ge=0)
    removed_margin_block_keys: list[str] = Field(default_factory=list)
    split_source_block_keys: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DocumentMapDraftSection(BaseModel):
    section_id: str = Field(min_length=1)
    source_block_ids: list[str] = Field(min_length=1)
    title: str = Field(min_length=1)
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


class CrossSectionThreadDraft(BaseModel):
    label: str = Field(min_length=1)
    section_ids: list[str] = Field(min_length=1)
    description: str = Field(min_length=1)


class DocumentMapDraft(BaseModel):
    working_thesis: str | None = None
    sections: list[DocumentMapDraftSection] = Field(min_length=1)
    cross_section_threads: list[CrossSectionThreadDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EvidenceClaimDraft(BaseModel):
    claim: str = Field(min_length=1)
    claim_type: ClaimType
    supporting_excerpt: str = Field(min_length=1)
    support_kind: Literal["direct", "inferential"]
    qualifications: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class DefinitionDraft(BaseModel):
    term: str = Field(min_length=1)
    definition: str = Field(min_length=1)


class DistinctionDraft(BaseModel):
    item_a: str = Field(min_length=1)
    item_b: str = Field(min_length=1)
    distinction: str = Field(min_length=1)


class EvidenceExtractionDraft(BaseModel):
    segment_function: str = Field(min_length=1)
    claims: list[EvidenceClaimDraft] = Field(default_factory=list)
    definitions: list[DefinitionDraft] = Field(default_factory=list)
    distinctions: list[DistinctionDraft] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    responses: list[str] = Field(default_factory=list)
    references_to_other_sections: list[str] = Field(default_factory=list)
    unresolved_context: list[str] = Field(default_factory=list)
    must_not_be_lost: list[str] = Field(default_factory=list)


class ClaimDraft(BaseModel):
    claim: str = Field(min_length=1)
    claim_type: ClaimType
    evidence_ids: list[str] = Field(min_length=1)
    support_status: SupportStatus
    qualifications: list[str] = Field(default_factory=list)


class ClaimReconciliationDraft(BaseModel):
    claims: list[ClaimDraft] = Field(default_factory=list)
    unresolved_evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ClaimLedger(BaseModel):
    source_id: UUID
    claims: list[ClaimRecord] = Field(default_factory=list)
    unresolved_evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_unique_claim_ids(self) -> ClaimLedger:
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("Claim ledger contains duplicate claim IDs.")
        return self


class SourceAnalysisManifest(BaseModel):
    project_id: UUID
    source_id: UUID
    source_sha256: str
    status: Literal[
        "blocks_ready",
        "document_mapped",
        "evidence_ready",
        "claims_ready",
        "failed",
    ]
    block_count: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    claim_count: int = Field(default=0, ge=0)
    model_run_ids: list[UUID] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_error: str | None = None
