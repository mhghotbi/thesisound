"""Pass 1 with chapter partitions (10c P1 Step 3).

`map_document(..., partitions=...)` lets the concept-map builder hand in
per-chapter partitions instead of the size-based split. The two paths must
still cover the source identically -- only the partition boundaries differ.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from thesisound.domain import Locator
from thesisound.modeling import ModelExecution, ModelRunRecord
from thesisound.services.document_mapper import DocumentMapperService
from thesisound.source_analysis import (
    DocumentMapDraft,
    DocumentMapDraftSection,
    DocumentMapMergeDraft,
    SourceDocumentBlock,
)


class _EchoRunner:
    """Maps every partition to one section that lists its own block IDs."""

    def __init__(self) -> None:
        self.partition_sizes: list[int] = []

    def run(
        self,
        *,
        project_id: UUID,
        stage: str,
        variables: dict[str, object],
        output_type,
        model: str,
        validator=None,
        **_: object,
    ):
        if output_type is DocumentMapDraft:
            blocks = variables["blocks"]
            block_ids = [str(item["block_id"]) for item in blocks]
            self.partition_sizes.append(len(block_ids))
            output = DocumentMapDraft(
                sections=[
                    DocumentMapDraftSection(
                        section_id=f"section-{len(self.partition_sizes)}",
                        source_block_ids=block_ids,
                        title="Mapped partition",
                        function="argument",
                    )
                ]
            )
        elif output_type is DocumentMapMergeDraft:
            output = DocumentMapMergeDraft()
        else:
            raise AssertionError(f"Unexpected output type: {output_type}")
        if validator is not None:
            validator(output)
        record = ModelRunRecord(
            project_id=project_id,
            stage=stage,
            prompt_id=stage,
            prompt_version="test",
            prompt_hash="test",
            input_hash="test",
            provider="fake",
            model=model,
            output_model=output_type.__name__,
            status="succeeded",
        )
        return ModelExecution(output=output, record=record)


def _blocks(source_id) -> list[SourceDocumentBlock]:
    return [
        SourceDocumentBlock(
            block_id=f"block-{index}",
            source_id=source_id,
            locator=Locator(page_start=index, page_end=index),
            heading_path=["Book"],
            block_type="argument",
            text="x" * 100,
            estimated_token_count=25,
            source_block_keys=[f"source-{index}"],
        )
        for index in range(1, 9)
    ]


def _mapped_block_ids(document_map) -> list[str]:
    return [
        block_id for section in document_map.sections for block_id in section.source_block_ids
    ]


def test_chapter_partitions_yield_the_same_block_coverage_as_size_based_partitioning() -> None:
    source_id = uuid4()
    blocks = _blocks(source_id)
    chapter_partitions = [blocks[:3], blocks[3:]]

    size_based_runner = _EchoRunner()
    size_based_mapper = DocumentMapperService(size_based_runner, maximum_input_characters=250)
    size_based_map, _ = size_based_mapper.map_document(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        model="fake",
    )

    chapter_runner = _EchoRunner()
    chapter_mapper = DocumentMapperService(chapter_runner, maximum_input_characters=250)
    chapter_map, _ = chapter_mapper.map_document(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        model="fake",
        partitions=chapter_partitions,
    )

    expected_ids = [block.block_id for block in blocks]
    assert _mapped_block_ids(size_based_map) == expected_ids
    assert _mapped_block_ids(chapter_map) == expected_ids

    # The two partitioning strategies must actually differ for this fixture,
    # otherwise the test would not exercise the new code path at all.
    assert size_based_runner.partition_sizes != chapter_runner.partition_sizes
    assert len(chapter_runner.partition_sizes) == 5
    assert len(size_based_runner.partition_sizes) == 4


def test_a_single_chapter_partition_is_returned_untouched_when_it_fits_the_budget() -> None:
    source_id = uuid4()
    blocks = _blocks(source_id)[:2]
    runner = _EchoRunner()
    mapper = DocumentMapperService(runner, maximum_input_characters=10_000)

    document_map, _ = mapper.map_document(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        model="fake",
        partitions=[blocks],
    )

    assert runner.partition_sizes == [2]
    assert _mapped_block_ids(document_map) == [block.block_id for block in blocks]


def test_map_document_without_partitions_argument_is_unaffected() -> None:
    source_id = uuid4()
    blocks = _blocks(source_id)
    runner = _EchoRunner()
    mapper = DocumentMapperService(runner, maximum_input_characters=250)

    document_map, _ = mapper.map_document(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        model="fake",
    )

    assert runner.partition_sizes == [2, 2, 2, 2]
    assert _mapped_block_ids(document_map) == [block.block_id for block in blocks]
