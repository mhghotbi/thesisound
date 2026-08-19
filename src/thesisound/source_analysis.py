from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    EvidenceExtraction,
    ExtractedAuxiliaryPoint,
    ExtractedDefinition,
    ExtractedDistinction,
    Locator,
    MustNotBeLostPoint,
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
AnalysisDepth = Literal["brief", "standard", "deep", "extended"]


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


class AnalysisProfile(BaseModel):
    depth: AnalysisDepth
    target_duration_minutes: int = Field(ge=5, le=120)
    block_coverage_target: float = Field(ge=0, le=1)
    evidence_input_token_budget: int = Field(ge=1)
    max_claims_per_block: int = Field(ge=1, le=12)
    neighbor_context_blocks: int = Field(ge=0, le=2)
    include_examples: bool
    include_objections_and_responses: bool
    second_pass_for_core_sections: bool
    rationale: list[str] = Field(default_factory=list)


class EvidenceExtractionPlan(BaseModel):
    source_id: UUID
    profile: AnalysisProfile
    selected_block_ids: list[str] = Field(default_factory=list)
    deferred_block_ids: list[str] = Field(default_factory=list)
    selected_source_tokens: int = Field(ge=0)
    total_source_tokens: int = Field(ge=0)
    achieved_token_coverage: float = Field(ge=0, le=1)
    # Defaulted so plans written before R5 still load.
    target_source_tokens: int = Field(default=0, ge=0)
    required_section_count: int = Field(default=0, ge=0)
    seeded_block_count: int = Field(default=0, ge=0)
    # Extraction 2.0 (10c P2 Step 2): fraction of each block's characters covered
    # by located claim excerpts. Computed via `excerpt_char_coverage` in
    # `excerpt_matching.py`; not yet wired into any gate (P3 adds the
    # tier-1/thin_extraction reading for `lesson_intent == source_coverage`).
    excerpt_char_coverage: dict[str, float] = Field(default_factory=dict)
    # Cell-unit batches (10c P3 Step 4). Empty on duration-ranked plans; the
    # extractor then slices by ``batch_size`` as before. When populated, each
    # inner list is one ``evidence_extraction_batch`` call.
    cell_batch_units: list[list[str]] = Field(default_factory=list)
    # Blocks belonging to an in-scope cell of tier ≤ 2. The extractor runs
    # ``_second_pass_for_block`` when that block also sets ``more_claims_available``.
    dense_second_pass_block_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_disjoint_block_sets(self) -> EvidenceExtractionPlan:
        selected = set(self.selected_block_ids)
        deferred = set(self.deferred_block_ids)
        if selected & deferred:
            raise ValueError("Selected and deferred block IDs must be disjoint.")
        if self.seeded_block_count > len(selected):
            raise ValueError("Seeded blocks cannot outnumber selected blocks.")
        return self


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


class DocumentMapSectionUpdateDraft(BaseModel):
    section_id: str = Field(min_length=1)
    depends_on_section_ids: list[str] = Field(default_factory=list)
    unresolved_context: list[str] = Field(default_factory=list)


class DocumentMapMergeDraft(BaseModel):
    """Global relationships discovered after all complete partitions are mapped."""

    working_thesis: str | None = None
    section_updates: list[DocumentMapSectionUpdateDraft] = Field(default_factory=list)
    globally_required_section_ids: list[str] = Field(default_factory=list)
    cross_section_threads: list[CrossSectionThreadDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EvidenceClaimDraft(BaseModel):
    """One claim in the Extraction 2.0 audited inventory (10c P2 Step 1, App A.2).

    There are no separate lists for definitions, distinctions, examples,
    objections or responses: each is a claim carrying the matching
    ``claim_type`` plus the field(s) that type requires. See
    ``_validate_claim_type_fields`` for the per-type requirements.
    """

    claim: str = Field(min_length=1)
    claim_type: ClaimType
    supporting_excerpt: str = Field(min_length=1)
    support_kind: Literal["direct", "inferential"]
    qualifications: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    must_not_be_lost: bool = False
    term: str | None = None
    contrast: tuple[str, str] | None = None
    responds_to_excerpt: str | None = None


class EvidenceExtractionDraft(BaseModel):
    segment_function: str = Field(min_length=1)
    claims: list[EvidenceClaimDraft] = Field(default_factory=list)
    # True when the block supports more distinct claims than max_claims_per_block
    # allowed extracting; triggers `_second_pass_for_block` for source_coverage
    # blocks that belong to a tier ≤ 2 in-scope cell (P3 Step 19).
    more_claims_available: bool = False


class BatchEvidenceEntryDraft(BaseModel):
    """One block's extraction inside a batched call.

    ``block_index`` is 1-based and refers to this block's position in this call's
    TARGET_BLOCKS_JSON list. It is the only attribution channel: block IDs are not
    sent to the model, so reordered responses remain attributable safely.
    """

    block_index: int = Field(ge=1)
    extraction: EvidenceExtractionDraft


class BatchEvidenceExtractionDraft(BaseModel):
    entries: list[BatchEvidenceEntryDraft] = Field(default_factory=list)


class BlockEvidenceExtraction(BaseModel):
    """One block extraction outcome.

    ``rejected`` means the model answered but the answer remained unusable after
    retries. ``skipped`` means no usable answer was obtained at all, normally
    because a provider or safety failure prevented the model from answering.

    ``extraction_identity`` records model/prompt/extractor versions so reuse can
    refuse stale blocks after a semantic change (R6). Absent identity is a miss.

    ``schema_version`` defaults to 1 so payloads written before the provenance
    change still load; writers stamp the current version on save.
    """

    source_id: UUID
    block_id: str = Field(min_length=1)
    extraction: EvidenceExtraction
    status: Literal["extracted", "rejected", "skipped"] = "extracted"
    rejection_reason: str | None = None
    failure_kind: Literal["contract", "provider"] | None = None
    extraction_pass: int = Field(default=1, ge=1)
    extraction_identity: dict[str, Any] | None = None
    schema_version: int = 1
    # Extraction 2.0: copied from the draft. Default False so pre-2.0 artifacts
    # still load. Dense second pass (P3 Step 19) reads this together with
    # ``EvidenceExtractionPlan.dense_second_pass_block_ids``.
    more_claims_available: bool = False


class ClaimDraft(BaseModel):
    claim: str = Field(min_length=1)
    claim_type: ClaimType
    evidence_ids: list[str] = Field(min_length=1)
    support_status: SupportStatus
    qualifications: list[str] = Field(default_factory=list)
    must_not_be_lost: bool = False
    term: str | None = None
    contrast: tuple[str, str] | None = None


class ClaimReconciliationDraft(BaseModel):
    claims: list[ClaimDraft] = Field(default_factory=list)
    unresolved_evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ClaimMergeGroup(BaseModel):
    """Claim IDs from different reconciliation batches that express the same proposition."""

    claim_ids: list[str] = Field(min_length=2)
    # Empty on parse means "use the first listed member"; the validator fills it.
    canonical_claim_id: str = ""

    @model_validator(mode="after")
    def require_canonical_in_group(self) -> ClaimMergeGroup:
        if not self.canonical_claim_id:
            self.canonical_claim_id = self.claim_ids[0]
        elif self.canonical_claim_id not in self.claim_ids:
            raise ValueError(
                f"canonical_claim_id {self.canonical_claim_id!r} is not one of claim_ids."
            )
        return self


class ClaimMergeDraft(BaseModel):
    merge_groups: list[ClaimMergeGroup] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ClaimLedger(BaseModel):
    source_id: UUID
    claims: list[ClaimRecord] = Field(default_factory=list)
    unresolved_evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # Deduplicated deterministically from block extractions in claim_reconciler.py --
    # not model output, so they carry no separate reconciliation draft/prompt.
    definitions: list[ExtractedDefinition] = Field(default_factory=list)
    distinctions: list[ExtractedDistinction] = Field(default_factory=list)
    examples: list[ExtractedAuxiliaryPoint] = Field(default_factory=list)
    objections: list[ExtractedAuxiliaryPoint] = Field(default_factory=list)
    responses: list[ExtractedAuxiliaryPoint] = Field(default_factory=list)
    must_not_be_lost: list[MustNotBeLostPoint] = Field(default_factory=list)
    # Model/prompt/reconciler versions that produced this ledger (R6 reuse gate).
    reconciler_identity: dict[str, Any] | None = None

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
    selected_block_count: int = Field(default=0, ge=0)
    deferred_block_count: int = Field(default=0, ge=0)
    analysis_depth: AnalysisDepth | None = None
    evidence_token_coverage: float | None = Field(default=None, ge=0, le=1)
    evidence_count: int = Field(default=0, ge=0)
    skipped_block_count: int = Field(default=0, ge=0)
    claim_count: int = Field(default=0, ge=0)
    model_run_ids: list[UUID] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_error: str | None = None
