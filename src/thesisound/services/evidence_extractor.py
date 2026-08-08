from __future__ import annotations

import hashlib
import re
from uuid import UUID

from thesisound.domain import (
    DocumentMap,
    EvidenceExtraction,
    EvidenceItem,
    ExtractedDefinition,
    ExtractedDistinction,
)
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.services.evidence_validator import validate_evidence_extraction
from thesisound.services.model_runner import ModelRunner
from thesisound.source_analysis import EvidenceExtractionDraft, SourceDocumentBlock

_WHITESPACE = re.compile(r"\s+")


class EvidenceExtractorService:
    def __init__(self, model_runner: ModelRunner) -> None:
        self.model_runner = model_runner

    def extract_source(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        blocks: list[SourceDocumentBlock],
        document_map: DocumentMap,
        model: str,
        prompt_version: str | None = None,
    ) -> tuple[list[EvidenceExtraction], list[ModelRunRecord]]:
        if document_map.source_id != source_id:
            raise ValueError("Document map belongs to a different source.")
        section_by_block = {
            block_id: section
            for section in document_map.sections
            for block_id in section.source_block_ids
        }
        extractions: list[EvidenceExtraction] = []
        runs: list[ModelRunRecord] = []

        for block in blocks:
            if block.block_type == "front_matter":
                continue
            section = section_by_block.get(block.block_id)
            variables = {
                "source_id": str(source_id),
                "block": block.model_dump(mode="json"),
                "section_context": (
                    section.model_dump(mode="json") if section is not None else None
                ),
                "working_thesis": document_map.working_thesis,
            }

            def validate(draft: EvidenceExtractionDraft) -> None:
                _validate_draft(draft, block)

            execution = self.model_runner.run(
                project_id=project_id,
                stage="evidence_extraction",
                prompt_name="evidence_extraction",
                variables=variables,
                output_type=EvidenceExtractionDraft,
                model=model,
                prompt_version=prompt_version,
                validator=validate,
            )
            extraction = _materialize_extraction(execution.output, block)
            validate_evidence_extraction(extraction, block)
            extractions.append(extraction)
            runs.append(execution.record)
        return extractions, runs


def _validate_draft(draft: EvidenceExtractionDraft, block: SourceDocumentBlock) -> None:
    normalized_source = _normalize(block.text)
    seen_claims: set[str] = set()
    for claim in draft.claims:
        normalized_claim = _normalize(claim.claim).casefold()
        if normalized_claim in seen_claims:
            raise DeterministicValidationError(
                f"Duplicate claim extracted from block {block.block_id}."
            )
        seen_claims.add(normalized_claim)
        excerpt = _normalize(claim.supporting_excerpt)
        if len(excerpt) < 12:
            raise DeterministicValidationError("supporting_excerpt is too short to audit.")
        if excerpt not in normalized_source:
            raise DeterministicValidationError(
                "supporting_excerpt must be copied from the supplied source block."
            )
        if claim.claim_type.value == "editorial_explanation":
            raise DeterministicValidationError(
                "Evidence extraction may not create editorial claims."
            )


def _materialize_extraction(
    draft: EvidenceExtractionDraft,
    block: SourceDocumentBlock,
) -> EvidenceExtraction:
    claims = [
        EvidenceItem(
            evidence_id=_evidence_id(block, claim.claim, claim.supporting_excerpt),
            source_id=block.source_id,
            block_id=block.block_id,
            claim=claim.claim.strip(),
            claim_type=claim.claim_type,
            supporting_excerpt=claim.supporting_excerpt.strip(),
            locator=block.locator.model_copy(deep=True),
            support_kind=claim.support_kind,
            qualifications=claim.qualifications,
            confidence=claim.confidence,
        )
        for claim in draft.claims
    ]
    return EvidenceExtraction(
        segment_function=draft.segment_function,
        claims=claims,
        definitions=[
            ExtractedDefinition(
                term=item.term,
                definition=item.definition,
                locator=block.locator.model_copy(deep=True),
            )
            for item in draft.definitions
        ],
        distinctions=[
            ExtractedDistinction(
                item_a=item.item_a,
                item_b=item.item_b,
                distinction=item.distinction,
                locator=block.locator.model_copy(deep=True),
            )
            for item in draft.distinctions
        ],
        examples=draft.examples,
        objections=draft.objections,
        responses=draft.responses,
        references_to_other_sections=draft.references_to_other_sections,
        unresolved_context=draft.unresolved_context,
        must_not_be_lost=draft.must_not_be_lost,
    )


def _evidence_id(block: SourceDocumentBlock, claim: str, excerpt: str) -> str:
    payload = "\x1f".join(
        [str(block.source_id), block.block_id, _normalize(claim), _normalize(excerpt)]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"ev-{digest}"


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()
