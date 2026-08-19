from __future__ import annotations

from uuid import uuid4

import pytest

from thesisound.domain import Locator
from thesisound.modeling import DeterministicValidationError
from thesisound.prompt_loader import PromptLoader
from thesisound.services.document_mapper import _validate_map_draft
from thesisound.source_analysis import (
    DocumentMapDraft,
    DocumentMapDraftSection,
    SourceDocumentBlock,
)


def _block(text: str, block_id: str = "block-1") -> SourceDocumentBlock:
    return SourceDocumentBlock(
        block_id=block_id,
        source_id=uuid4(),
        locator=Locator(page_start=1, page_end=1),
        heading_path=["Section"],
        block_type="argument",
        text=text,
        estimated_token_count=20,
        source_block_keys=["p1"],
    )


def _draft(*concepts: str, block_id: str = "block-1") -> DocumentMapDraft:
    return DocumentMapDraft(
        working_thesis="A thesis.",
        sections=[
            DocumentMapDraftSection(
                section_id="sec-001",
                source_block_ids=[block_id],
                title="Section",
                function="argument",
                key_concepts=list(concepts),
            )
        ],
    )


def test_latest_document_map_prompt_is_1_1_0_and_mentions_verbatim_key_concepts() -> None:
    loader = PromptLoader()
    contract = loader.load_contract("document_map")
    assert contract.version == "1.1.0"
    bundle = loader.load_bundle(
        "document_map",
        {"source_id": "src", "blocks": []},
    )
    assert "key_concepts entry must be a term or phrase that appears" in bundle.system_prompt


def test_key_concepts_present_in_blocks_pass() -> None:
    blocks = [_block("Action occurs directly between persons.")]
    draft = _draft("Action")
    _validate_map_draft(
        draft,
        known_ids={blocks[0].block_id},
        content_ids={blocks[0].block_id},
        blocks=blocks,
        attempt=1,
        max_attempts=3,
    )
    assert draft.sections[0].key_concepts == ["Action"]


def test_key_concepts_absent_from_blocks_rejected_before_final_attempt() -> None:
    blocks = [_block("Action occurs directly between persons.")]
    draft = _draft("plurality")
    with pytest.raises(DeterministicValidationError, match="key_concepts"):
        _validate_map_draft(
            draft,
            known_ids={blocks[0].block_id},
            content_ids={blocks[0].block_id},
            blocks=blocks,
            attempt=1,
            max_attempts=3,
        )


def test_key_concepts_absent_from_blocks_dropped_on_final_attempt() -> None:
    blocks = [_block("Action occurs directly between persons.")]
    draft = _draft("Action", "plurality")
    _validate_map_draft(
        draft,
        known_ids={blocks[0].block_id},
        content_ids={blocks[0].block_id},
        blocks=blocks,
        attempt=3,
        max_attempts=3,
    )
    assert draft.sections[0].key_concepts == ["Action"]
    assert any("Dropped key_concepts" in warning for warning in draft.warnings)
