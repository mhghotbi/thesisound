"""A concept map reused from the shared cache under a different source_id
must have its `block_ids` retargeted onto the new source's own blocks.

Real-run bug found at checkpoint C-D (2026-08-20): `block_id` embeds the
building source_id (`block_builder._block_id`), but the shared cache keys on
content only (`block_sequence_key`), so a cache hit under a fresh project/
source_id used to return cells pointing at blocks that did not exist in that
source -- cell-seeded extraction silently selected zero blocks and the whole
source_coverage run failed with "no claim-bearing evidence after retries."
"""

from __future__ import annotations

from uuid import uuid4

from thesisound.concepts import ConceptCell, ConceptMapStatistics, SourceChapter, SourceConceptMap
from thesisound.domain import Locator
from thesisound.services.block_builder import _block_id
from thesisound.services.concept_map_builder import _remap_block_ids
from thesisound.source_analysis import SourceDocumentBlock


def _block(source_id, index: int, text: str) -> SourceDocumentBlock:
    return SourceDocumentBlock(
        block_id=_block_id(source_id, index, text),
        source_id=source_id,
        locator=Locator(),
        heading_path=[],
        block_type="other",
        text=text,
        estimated_token_count=10,
        source_block_keys=[f"raw-{index}"],
    )


def test_cached_cell_and_chapter_block_ids_retarget_onto_the_new_source() -> None:
    old_source_id = uuid4()
    new_source_id = uuid4()
    texts = ["first block text.", "second block text."]
    old_blocks = [_block(old_source_id, index, text) for index, text in enumerate(texts)]
    new_blocks = [_block(new_source_id, index, text) for index, text in enumerate(texts)]
    assert old_blocks[0].block_id != new_blocks[0].block_id  # different source_id prefix

    cached_map = SourceConceptMap(
        source_fingerprint="f" * 64,
        builder_version=1,
        chapters=[
            SourceChapter(
                chapter_index=0,
                title="Chapter",
                heading_path=[],
                block_ids=[block.block_id for block in old_blocks],
                estimated_minutes=5.0,
                detected_from="single",
                detection_agreement="agreed",
            )
        ],
        cells=[
            ConceptCell(
                cell_key="ch00-c001",
                label_fa="برچسب",
                kind="argument",
                tier=1,
                chapter_index=0,
                section_ids=["s1"],
                block_ids=[old_blocks[0].block_id],
                granularity_rationale="r",
                estimated_minutes=4.0,
            )
        ],
        edges=[],
        statistics=ConceptMapStatistics(cell_count=1),
    )

    remapped = _remap_block_ids(cached_map, new_blocks)

    assert remapped.chapters[0].block_ids == [block.block_id for block in new_blocks]
    assert remapped.cells[0].block_ids == [new_blocks[0].block_id]
    # Untouched fields survive the round-trip.
    assert remapped.cells[0].cell_key == "ch00-c001"
    assert remapped.source_fingerprint == cached_map.source_fingerprint


def test_an_id_that_matches_nothing_in_the_new_blocks_is_left_alone() -> None:
    new_source_id = uuid4()
    new_blocks = [_block(new_source_id, 0, "only block.")]
    cached_map = SourceConceptMap(
        source_fingerprint="e" * 64,
        builder_version=1,
        chapters=[],
        cells=[
            ConceptCell(
                cell_key="ch00-c001",
                label_fa="برچسب",
                kind="argument",
                tier=1,
                chapter_index=0,
                section_ids=["s1"],
                block_ids=["not-a-real-block-id"],
                granularity_rationale="r",
                estimated_minutes=4.0,
            )
        ],
        edges=[],
        statistics=ConceptMapStatistics(cell_count=1),
    )

    remapped = _remap_block_ids(cached_map, new_blocks)

    assert remapped.cells[0].block_ids == ["not-a-real-block-id"]
