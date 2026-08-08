from __future__ import annotations

import re

from thesisound.domain import EvidenceExtraction
from thesisound.modeling import DeterministicValidationError
from thesisound.source_analysis import SourceDocumentBlock

_WHITESPACE = re.compile(r"\s+")


def validate_evidence_extraction(
    extraction: EvidenceExtraction,
    block: SourceDocumentBlock,
) -> None:
    evidence_ids = [item.evidence_id for item in extraction.claims]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise DeterministicValidationError("Evidence IDs must be unique within a block.")

    normalized_source = _normalize(block.text)
    for item in extraction.claims:
        if item.source_id != block.source_id:
            raise DeterministicValidationError("Evidence source_id does not match its block.")
        if item.block_id != block.block_id:
            raise DeterministicValidationError("Evidence block_id does not match its block.")
        excerpt = _normalize(item.supporting_excerpt)
        if len(excerpt) < 12:
            raise DeterministicValidationError(
                f"Evidence excerpt {item.evidence_id} is too short to audit."
            )
        if excerpt not in normalized_source:
            raise DeterministicValidationError(
                f"Evidence excerpt {item.evidence_id} is not present in the source block."
            )
        _validate_locator(item.locator.page_start, item.locator.page_end, block)

    for definition in extraction.definitions:
        _validate_locator(
            definition.locator.page_start,
            definition.locator.page_end,
            block,
        )
    for distinction in extraction.distinctions:
        _validate_locator(
            distinction.locator.page_start,
            distinction.locator.page_end,
            block,
        )


def validate_evidence_collection(
    extractions: list[EvidenceExtraction],
    blocks: list[SourceDocumentBlock],
) -> None:
    block_by_id = {block.block_id: block for block in blocks}
    all_evidence_ids: list[str] = []
    for extraction in extractions:
        if not extraction.claims and not extraction.definitions and not extraction.distinctions:
            continue
        referenced_blocks = {item.block_id for item in extraction.claims}
        if len(referenced_blocks) > 1:
            raise DeterministicValidationError(
                "One EvidenceExtraction artifact may reference only one semantic block."
            )
        for item in extraction.claims:
            block = block_by_id.get(item.block_id)
            if block is None:
                raise DeterministicValidationError(
                    f"Evidence referenced unknown block {item.block_id}."
                )
            validate_evidence_extraction(extraction, block)
            all_evidence_ids.append(item.evidence_id)
    if len(all_evidence_ids) != len(set(all_evidence_ids)):
        raise DeterministicValidationError("Evidence IDs must be unique across the source.")


def _validate_locator(
    page_start: int | None,
    page_end: int | None,
    block: SourceDocumentBlock,
) -> None:
    if page_start is not None and block.locator.page_start is not None:
        if page_start < block.locator.page_start:
            raise DeterministicValidationError("Evidence locator starts before its source block.")
    if page_end is not None and block.locator.page_end is not None:
        if page_end > block.locator.page_end:
            raise DeterministicValidationError("Evidence locator ends after its source block.")
    if page_start is not None and page_end is not None and page_start > page_end:
        raise DeterministicValidationError("Evidence locator has an inverted page range.")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()
