from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from thesisound.domain import Locator
from thesisound.modeling import ModelExecution, ModelRunRecord
from thesisound.services.document_mapper import DocumentMapperService
from thesisound.source_analysis import (
    CrossSectionThreadDraft,
    DocumentMapDraft,
    DocumentMapDraftSection,
    DocumentMapMergeDraft,
    DocumentMapSectionUpdateDraft,
    SourceDocumentBlock,
)


class HierarchicalRunner:
    def __init__(self) -> None:
        self.stages: list[str] = []

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
        self.stages.append(stage)
        if output_type is DocumentMapDraft:
            blocks = variables["blocks"]
            assert isinstance(blocks, list)
            output = DocumentMapDraft(
                working_thesis=f"Thesis for partition {variables.get('part_number')}",
                sections=[
                    DocumentMapDraftSection(
                        section_id="section",
                        source_block_ids=[str(item["block_id"]) for item in blocks],
                        title="Mapped partition",
                        function="argument",
                        key_concepts=["shared concept"],
                    )
                ],
            )
        elif output_type is DocumentMapMergeDraft:
            partitions = variables["partitions"]
            assert isinstance(partitions, list)
            section_ids = [str(partition["sections"][0]["section_id"]) for partition in partitions]
            output = DocumentMapMergeDraft(
                working_thesis="One thesis across the complete document.",
                section_updates=[
                    DocumentMapSectionUpdateDraft(
                        section_id=section_ids[index],
                        depends_on_section_ids=[section_ids[index - 1]],
                    )
                    for index in range(1, len(section_ids))
                ],
                globally_required_section_ids=[section_ids[0]],
                cross_section_threads=[
                    CrossSectionThreadDraft(
                        label="shared concept",
                        section_ids=section_ids,
                        description="The concept continues across all partitions.",
                    )
                ],
            )
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


def _blocks() -> list[SourceDocumentBlock]:
    source_id = uuid4()
    return [
        SourceDocumentBlock(
            block_id=f"block-{index}",
            source_id=source_id,
            locator=Locator(page_start=index, page_end=index),
            heading_path=[f"Chapter {(index - 1) // 2 + 1}"],
            block_type="argument",
            text=(f"Complete semantic content for block {index}. " * 8),
            estimated_token_count=80,
            source_block_keys=[f"source-{index}"],
        )
        for index in range(1, 9)
    ]


def test_large_document_is_mapped_without_omitting_or_duplicating_blocks() -> None:
    blocks = _blocks()
    runner = HierarchicalRunner()
    mapper = DocumentMapperService(runner, maximum_input_characters=500)

    document_map, run = mapper.map_document(
        project_id=uuid4(),
        source_id=blocks[0].source_id,
        blocks=blocks,
        model="fake",
    )

    mapped = [
        block_id for section in document_map.sections for block_id in section.source_block_ids
    ]
    assert mapped == [block.block_id for block in blocks]
    assert len(mapped) == len(set(mapped))
    assert runner.stages.count("document_map_part") > 1
    assert runner.stages[-1] == "document_map_merge"
    assert run.stage == "document_map_merge"
    assert document_map.sections[1].depends_on_section_ids == [document_map.sections[0].section_id]
    assert document_map.cross_section_threads[0].section_ids == [
        section.section_id for section in document_map.sections
    ]
    assert any("no blocks were omitted" in warning for warning in document_map.warnings)


def test_oversized_single_semantic_block_requests_blockbuilder_split() -> None:
    block = _blocks()[0].model_copy(update={"text": "x" * 501})
    mapper = DocumentMapperService(HierarchicalRunner(), maximum_input_characters=500)

    with pytest.raises(ValueError, match="BlockBuilder"):
        mapper.map_document(
            project_id=uuid4(),
            source_id=block.source_id,
            blocks=[block],
            model="fake",
        )
