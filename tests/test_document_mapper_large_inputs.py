from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from thesisound import tracing
from thesisound.domain import Locator
from thesisound.modeling import (
    DeterministicValidationError,
    ModelExecution,
    ModelRunRecord,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.services.block_builder import BlockBuilder
from thesisound.services.claim_reconciler import ClaimReconcilerService
from thesisound.services.document_identity import partition_block_key
from thesisound.services.document_map_part_cache import DocumentMapPartCache
from thesisound.services.document_mapper import DocumentMapperService
from thesisound.services.evidence_extractor import EvidenceExtractorService
from thesisound.services.source_analysis_service import SourceAnalysisService
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    BlockBuildReport,
    CrossSectionThreadDraft,
    DocumentMapDraft,
    DocumentMapDraftSection,
    DocumentMapMergeDraft,
    DocumentMapSectionUpdateDraft,
    SourceAnalysisManifest,
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
            for partition in partitions:
                assert "source_block_ids" not in partition["sections"][0]
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


class OmittingPartitionRunner(HierarchicalRunner):
    def run(self, **kwargs):
        output_type = kwargs["output_type"]
        if output_type is DocumentMapDraft:
            variables = kwargs["variables"]
            blocks = variables["blocks"]
            assert isinstance(blocks, list)
            output = DocumentMapDraft(
                sections=[
                    DocumentMapDraftSection(
                        section_id="section",
                        source_block_ids=[str(item["block_id"]) for item in blocks[:-1]],
                        title="Incomplete partition",
                        function="argument",
                    )
                ]
            )
            validator = kwargs.get("validator")
            if validator is not None:
                validator(output)
        return super().run(**kwargs)


class RecordingRunner(HierarchicalRunner):
    def __init__(self) -> None:
        super().__init__()
        self.merge_variables: dict[str, object] | None = None

    def run(self, **kwargs):
        if kwargs["output_type"] is DocumentMapMergeDraft:
            self.merge_variables = kwargs["variables"]
        return super().run(**kwargs)


class FailingMergeRunner(HierarchicalRunner):
    def run(self, **kwargs):
        if kwargs["output_type"] is DocumentMapMergeDraft:
            raise DeterministicValidationError("forced merge failure")
        return super().run(**kwargs)


class FailingLastPartitionRunner(HierarchicalRunner):
    def __init__(self, failing_part_number: int) -> None:
        super().__init__()
        self.failing_part_number = failing_part_number

    def run(self, **kwargs):
        if (
            kwargs["stage"] == "document_map_part"
            and kwargs["variables"]["part_number"] == self.failing_part_number
        ):
            self.stages.append("document_map_part")
            raise DeterministicValidationError("forced partition failure")
        return super().run(**kwargs)


class ThesislessMergeRunner(HierarchicalRunner):
    def run(self, **kwargs):
        execution = super().run(**kwargs)
        if kwargs["output_type"] is DocumentMapMergeDraft:
            execution.output.working_thesis = None
        return execution


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


def _map(
    mapper: DocumentMapperService,
    blocks: list[SourceDocumentBlock],
):
    return mapper.map_document(
        project_id=uuid4(),
        source_id=blocks[0].source_id,
        blocks=blocks,
        model="fake",
    )


def _document_map_signature(
    document_map,
) -> tuple[object, list[tuple[object, ...]], list[tuple[object, ...]]]:
    return (
        document_map.working_thesis,
        [
            (
                section.section_id,
                section.source_block_ids,
                section.title,
                section.function,
                section.key_concepts,
                section.depends_on_section_ids,
                section.required_for_global_understanding,
                section.unresolved_context,
            )
            for section in document_map.sections
        ],
        [
            (thread.label, thread.section_ids, thread.description)
            for thread in document_map.cross_section_threads
        ],
    )


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


class OverlappingPartitionRunner(HierarchicalRunner):
    def run(self, **kwargs):
        output_type = kwargs["output_type"]
        if output_type is DocumentMapDraft:
            variables = kwargs["variables"]
            blocks = variables["blocks"]
            assert isinstance(blocks, list)
            block_ids = [str(item["block_id"]) for item in blocks]
            mid = max(1, len(block_ids) // 2)
            output = DocumentMapDraft(
                sections=[
                    DocumentMapDraftSection(
                        section_id="sec-a",
                        source_block_ids=block_ids[: mid + 1],
                        title="First half with overlap",
                        function="argument",
                    ),
                    DocumentMapDraftSection(
                        section_id="sec-b",
                        source_block_ids=[
                            "blk-outside-partition",
                            *block_ids[mid:],
                        ],
                        title="Second half with invented ID",
                        function="argument",
                    ),
                ]
            )
            validator = kwargs.get("validator")
            if validator is not None:
                validator(output)
            record = ModelRunRecord(
                project_id=kwargs["project_id"],
                stage=kwargs["stage"],
                prompt_id=kwargs["stage"],
                prompt_version="test",
                prompt_hash="test",
                input_hash="test",
                provider="fake",
                model=kwargs["model"],
                output_model=output_type.__name__,
                status="succeeded",
            )
            return ModelExecution(output=output, record=record)
        return super().run(**kwargs)


def test_map_draft_normalizes_unknown_and_overlapping_blocks() -> None:
    blocks = _blocks()
    mapper = DocumentMapperService(
        OverlappingPartitionRunner(),
        maximum_input_characters=100_000,
    )

    document_map, _ = mapper.map_document(
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
    assert any("overlapping blocks" in warning for warning in document_map.warnings)
    assert any("unknown block IDs" in warning for warning in document_map.warnings)


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


def test_large_document_rejects_any_omitted_content_block() -> None:
    blocks = _blocks()
    mapper = DocumentMapperService(
        OmittingPartitionRunner(),
        maximum_input_characters=700,
    )

    with pytest.raises(
        DeterministicValidationError,
        match="required coverage is 100%",
    ):
        mapper.map_document(
            project_id=uuid4(),
            source_id=blocks[0].source_id,
            blocks=blocks,
            model="fake",
        )


def test_merge_variables_expose_the_trimmed_partition_payload() -> None:
    blocks = _blocks()
    runner = RecordingRunner()
    mapper = DocumentMapperService(runner, maximum_input_characters=500)

    document_map, _ = mapper.map_document(
        project_id=uuid4(),
        source_id=blocks[0].source_id,
        blocks=blocks,
        model="fake",
    )

    assert runner.merge_variables is not None
    variables = runner.merge_variables
    partitions = variables["partitions"]
    assert isinstance(partitions, list)
    assert len(partitions) == variables["partition_count"]
    payload_sections = [section for partition in partitions for section in partition["sections"]]
    assert {section["section_id"] for section in payload_sections} == {
        section.section_id for section in document_map.sections
    }
    expected_keys = {
        "section_id",
        "title",
        "function",
        "key_concepts",
        "depends_on_section_ids",
        "required_for_global_understanding",
        "unresolved_context",
        "block_count",
    }
    assert all(set(section) == expected_keys for section in payload_sections)
    assert all("source_block_ids" not in section for section in payload_sections)
    assert all(section["block_count"] >= 1 for section in payload_sections)


def test_merge_failure_degrades_to_partition_union_with_a_warning() -> None:
    blocks = _blocks()
    mapper = DocumentMapperService(FailingMergeRunner(), maximum_input_characters=500)

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
    assert any("Cross-partition merge failed" in warning for warning in document_map.warnings)
    assert run.stage == "document_map_part"


def test_global_thesis_falls_back_to_the_first_partition_with_a_warning() -> None:
    blocks = _blocks()
    mapper = DocumentMapperService(ThesislessMergeRunner(), maximum_input_characters=500)

    document_map, _ = mapper.map_document(
        project_id=uuid4(),
        source_id=blocks[0].source_id,
        blocks=blocks,
        model="fake",
    )

    assert document_map.working_thesis == "Thesis for partition 1"
    assert any("no global thesis" in warning for warning in document_map.warnings)


def test_oversized_merge_payload_skips_the_merge_without_discarding_partitions() -> None:
    blocks = _blocks()
    runner = HierarchicalRunner()
    mapper = DocumentMapperService(
        runner,
        maximum_input_characters=500,
        maximum_merge_payload_characters=100,
    )

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
    assert "document_map_merge" not in runner.stages
    assert run.stage == "document_map_part"
    assert any("Cross-partition merge was skipped" in warning for warning in document_map.warnings)


def test_merge_payload_budget_is_independent_of_the_partition_text_budget() -> None:
    """A smaller text budget makes more partitions, so it must not shrink the merge budget."""

    blocks = _blocks()
    runner = HierarchicalRunner()
    mapper = DocumentMapperService(runner, maximum_input_characters=500)

    document_map, run = mapper.map_document(
        project_id=uuid4(),
        source_id=blocks[0].source_id,
        blocks=blocks,
        model="fake",
    )

    assert runner.stages.count("document_map_part") == len(blocks)
    assert runner.stages[-1] == "document_map_merge"
    assert run.stage == "document_map_merge"
    assert not any("merge was skipped" in warning for warning in document_map.warnings)


def test_merge_payload_budget_must_be_positive() -> None:
    with pytest.raises(ValueError, match="maximum_merge_payload_characters"):
        DocumentMapperService(HierarchicalRunner(), maximum_merge_payload_characters=0)


def test_successful_partitions_are_not_remapped_after_a_later_partition_fails(
    tmp_path: Path,
) -> None:
    blocks = _blocks()
    cache = DocumentMapPartCache(tmp_path)
    first_runner = FailingLastPartitionRunner(failing_part_number=4)
    first_mapper = DocumentMapperService(
        first_runner,
        maximum_input_characters=900,
        part_cache=cache,
    )

    with pytest.raises(DeterministicValidationError, match="forced partition failure"):
        _map(first_mapper, blocks)

    second_runner = HierarchicalRunner()
    second_mapper = DocumentMapperService(
        second_runner,
        maximum_input_characters=900,
        part_cache=cache,
    )
    _map(second_mapper, blocks)

    assert second_runner.stages == ["document_map_part", "document_map_merge"]


def test_successful_partitions_are_persisted_but_the_failed_partition_is_not(
    tmp_path: Path,
) -> None:
    blocks = _blocks()
    cache = DocumentMapPartCache(tmp_path)
    mapper = DocumentMapperService(
        FailingLastPartitionRunner(failing_part_number=4),
        maximum_input_characters=900,
        part_cache=cache,
    )

    with pytest.raises(DeterministicValidationError, match="forced partition failure"):
        _map(mapper, blocks)

    assert len(list(cache.root.glob("*.json"))) == 3
    assert list(cache.root.glob("*.json.tmp")) == []


def test_cache_hit_document_map_matches_the_cache_miss_map_field_for_field(
    tmp_path: Path,
) -> None:
    blocks = _blocks()
    cache = DocumentMapPartCache(tmp_path)
    first_map, _ = _map(
        DocumentMapperService(
            HierarchicalRunner(),
            maximum_input_characters=900,
            part_cache=cache,
        ),
        blocks,
    )
    second_map, _ = _map(
        DocumentMapperService(
            HierarchicalRunner(),
            maximum_input_characters=900,
            part_cache=cache,
        ),
        blocks,
    )

    assert _document_map_signature(second_map) == _document_map_signature(first_map)


def test_partition_cache_reuses_content_across_sources_and_rebuilds_block_ids(
    tmp_path: Path,
) -> None:
    first_blocks = _blocks()
    second_source_id = uuid4()
    second_blocks = [
        block.model_copy(
            update={
                "block_id": f"rebuilt-{index}",
                "source_id": second_source_id,
                "source_block_keys": [f"rebuilt-source-{index}"],
            }
        )
        for index, block in enumerate(first_blocks, start=1)
    ]
    cache = DocumentMapPartCache(tmp_path)
    _map(
        DocumentMapperService(
            HierarchicalRunner(),
            maximum_input_characters=900,
            part_cache=cache,
        ),
        first_blocks,
    )
    second_runner = HierarchicalRunner()
    second_map, _ = _map(
        DocumentMapperService(
            second_runner,
            maximum_input_characters=900,
            part_cache=cache,
        ),
        second_blocks,
    )

    mapped_ids = [
        block_id for section in second_map.sections for block_id in section.source_block_ids
    ]
    assert "document_map_part" not in second_runner.stages
    assert mapped_ids == [block.block_id for block in second_blocks]
    assert not any(block_id.startswith("block-") for block_id in mapped_ids)


def test_changing_partition_budget_produces_no_cache_hits(tmp_path: Path) -> None:
    blocks = _blocks()
    cache = DocumentMapPartCache(tmp_path)
    _map(
        DocumentMapperService(
            HierarchicalRunner(),
            maximum_input_characters=500,
            part_cache=cache,
        ),
        blocks,
    )
    second_runner = HierarchicalRunner()
    second_map, _ = _map(
        DocumentMapperService(
            second_runner,
            maximum_input_characters=900,
            part_cache=cache,
        ),
        blocks,
    )

    mapped_ids = [
        block_id for section in second_map.sections for block_id in section.source_block_ids
    ]
    assert second_runner.stages.count("document_map_part") == 4
    assert mapped_ids == [block.block_id for block in blocks]


def test_partition_key_keeps_front_matter() -> None:
    blocks = _blocks()
    front_matter = blocks[0].model_copy(
        update={"block_type": "front_matter", "text": "Edition one front matter."}
    )
    revised_front_matter = front_matter.model_copy(update={"text": "Edition two front matter."})

    assert partition_block_key([front_matter, blocks[1]]) != partition_block_key(
        [revised_front_matter, blocks[1]]
    )


def test_partition_key_preserves_heading_boundaries() -> None:
    block = _blocks()[0]
    first = block.model_copy(update={"heading_path": ["A"], "text": "B C"})
    second = block.model_copy(update={"heading_path": ["A B"], "text": "C"})

    assert partition_block_key([first]) != partition_block_key([second])


def test_partition_cache_is_disabled_by_default(tmp_path: Path) -> None:
    blocks = _blocks()
    first_map, _ = _map(
        DocumentMapperService(HierarchicalRunner(), maximum_input_characters=500),
        blocks,
    )
    second_map, _ = _map(
        DocumentMapperService(HierarchicalRunner(), maximum_input_characters=500),
        blocks,
    )

    assert list(tmp_path.iterdir()) == []
    assert _document_map_signature(second_map) == _document_map_signature(first_map)


def test_all_cached_partitions_and_a_merge_failure_return_no_record_and_mark_the_source(
    tmp_path: Path,
) -> None:
    blocks = _blocks()
    project_id = uuid4()
    source_id = blocks[0].source_id
    root = tmp_path / "workspaces"
    cache = DocumentMapPartCache(root)
    _map(
        DocumentMapperService(
            HierarchicalRunner(),
            maximum_input_characters=900,
            part_cache=cache,
        ),
        blocks,
    )
    failing_mapper = DocumentMapperService(
        FailingMergeRunner(),
        maximum_input_characters=900,
        part_cache=cache,
    )

    document_map, run = _map(failing_mapper, blocks)

    assert run is None
    assert any("Cross-partition merge failed" in warning for warning in document_map.warnings)

    workspace = WorkspaceStore(root)
    artifact_store = SourceArtifactStore(root)
    artifact_store.save_blocks(
        project_id,
        source_id,
        blocks,
        BlockBuildReport(
            source_id=source_id,
            input_block_count=len(blocks),
            output_block_count=len(blocks),
        ),
    )
    artifact_store.save_manifest(
        SourceAnalysisManifest(
            project_id=project_id,
            source_id=source_id,
            source_sha256="test",
            status="blocks_ready",
            block_count=len(blocks),
        )
    )
    service = SourceAnalysisService(
        workspace_store=workspace,
        artifact_store=artifact_store,
        block_builder=BlockBuilder(),
        document_mapper=failing_mapper,
        evidence_extractor=EvidenceExtractorService(HierarchicalRunner()),
        claim_reconciler=ClaimReconcilerService(HierarchicalRunner()),
    )

    manifest = service.map_document(project_id, source_id, model="fake")

    assert manifest.status == "document_mapped"
    assert manifest.model_run_ids == []


def test_partition_cache_emits_hit_and_miss_events(
    tmp_path: Path,
    recording_tracer: tracing.Tracer,
) -> None:
    blocks = _blocks()
    cache = DocumentMapPartCache(tmp_path)
    mapper = DocumentMapperService(
        HierarchicalRunner(),
        maximum_input_characters=900,
        part_cache=cache,
    )
    _map(mapper, blocks)
    _map(mapper, blocks)

    cache_events = [
        event
        for event in recording_tracer.sink.events
        if event.name == "cache.lookup" and event.attributes.get("cache") == "document_map_part"
    ]
    assert [event.attributes["result"] for event in cache_events] == [
        "miss",
        "miss",
        "miss",
        "miss",
        "hit",
        "hit",
        "hit",
        "hit",
    ]
