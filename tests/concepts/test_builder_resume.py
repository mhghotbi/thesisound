from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

import pytest

from thesisound.concepts import (
    ConceptCellDraft,
    ConceptCellsDraft,
    ConceptEdgeDraft,
    ConceptEdgesDraft,
)
from thesisound.domain import DocumentMap, DocumentMapSection, Locator
from thesisound.modeling import ModelUsage, StructuredModelResponse
from thesisound.ports import ParsedDocument
from thesisound.prompt_loader import PromptLoader
from thesisound.services.concept_map_builder import ConceptMapBuilder
from thesisound.services.concept_map_cache import CONCEPT_MAP_BUILDER_VERSION, ConceptMapCache
from thesisound.services.document_identity import block_sequence_key
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner
from thesisound.source_analysis import SourceDocumentBlock

_SOURCE_ID = uuid4()
_PROJECT_ID = uuid4()
_PARSED = ParsedDocument(parser_name="fake", parser_version="0", blocks=[])
_CHAPTER_STAGE = re.compile(r"concept_cells:ch(\d+)")
_INTRA_STAGE = re.compile(r"\Aconcept_edges:ch(\d+)\Z")
_CROSS_STAGE = re.compile(r"\Aconcept_edges:ch(\d+)-ch(\d+)\Z")


def _block(index: int, heading_path: list[str]) -> SourceDocumentBlock:
    return SourceDocumentBlock(
        block_id=f"b{index:04d}",
        source_id=_SOURCE_ID,
        locator=Locator(),
        heading_path=heading_path,
        block_type="other",
        text=f"block {index} about a distinct concept in this chapter.",
        estimated_token_count=30,
        source_block_keys=[f"raw-{index}"],
    )


def _three_chapter_blocks() -> list[SourceDocumentBlock]:
    heading_paths: list[list[str]] = [[], []]
    for title in ("Chapter One", "Chapter Two", "Chapter Three"):
        heading_paths.extend([[title]] * 10)
    return [_block(index, path) for index, path in enumerate(heading_paths)]


def _document_map(blocks: list[SourceDocumentBlock]) -> DocumentMap:
    # Front matter (b0000, b0001) joins chapter 0; content starts at b0002.
    ranges = ((0, "s000", 2, 12), (1, "s001", 12, 22), (2, "s002", 22, 32))
    sections = [
        DocumentMapSection(
            section_id=section_id,
            source_block_ids=[blocks[index].block_id for index in range(start, end)],
            title=f"Section {chapter_index}",
            function="argument",
        )
        for chapter_index, section_id, start, end in ranges
    ]
    return DocumentMap(
        source_id=_SOURCE_ID,
        scope_locator=Locator(),
        sections=sections,
    )


def _response(output: ConceptCellsDraft | ConceptEdgesDraft) -> StructuredModelResponse:
    return StructuredModelResponse(
        output=output,
        provider="fake",
        model="fake-fast",
        usage=ModelUsage(),
        latency_ms=1,
        finish_reason="STOP",
    )


class FakeConceptMapModel:
    provider = "fake"

    def __init__(self, *, fail_on_stage: str | None = None) -> None:
        self.fail_on_stage = fail_on_stage
        self.stages: list[str] = []

    def generate_structured(self, **kwargs):
        stage = kwargs["metadata"].stage
        if self.fail_on_stage is not None and stage == self.fail_on_stage:
            raise RuntimeError(f"interrupted at {stage}")
        self.stages.append(stage)
        output_type = kwargs["output_type"]
        if output_type is ConceptCellsDraft:
            match = _CHAPTER_STAGE.search(stage)
            assert match is not None
            index = int(match.group(1))
            section = f"s{index:03d}"
            first = 2 + index * 10
            return _response(
                ConceptCellsDraft(
                    cells=[
                        ConceptCellDraft(
                            label_fa=f"مفهوم اصلی فصل {index} الف",
                            kind="definition",
                            tier=1,
                            section_ids=[section],
                            block_ids=[f"b{first:04d}"],
                            granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
                            estimated_minutes=5.0,
                        ),
                        ConceptCellDraft(
                            label_fa=f"مفهوم اصلی فصل {index} ب",
                            kind="argument",
                            tier=2,
                            section_ids=[section],
                            block_ids=[f"b{first + 1:04d}"],
                            granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
                            estimated_minutes=6.0,
                        ),
                    ]
                )
            )
        if output_type is ConceptEdgesDraft:
            intra = _INTRA_STAGE.match(stage)
            if intra:
                index = int(intra.group(1))
                left = f"ch{index:02d}-c001"
                right = f"ch{index:02d}-c002"
                return _response(
                    ConceptEdgesDraft(
                        edges=[
                            ConceptEdgeDraft(
                                source_key=left,
                                target_key=right,
                                type="related",
                                weight=0.7,
                                confidence=0.8,
                                rationale_fa="هر دو در یک فصل آمده‌اند.",
                            )
                        ]
                    )
                )
            cross = _CROSS_STAGE.match(stage)
            assert cross is not None
            left = f"ch{int(cross.group(1)):02d}-c001"
            right = f"ch{int(cross.group(2)):02d}-c001"
            return _response(
                ConceptEdgesDraft(
                    edges=[
                        ConceptEdgeDraft(
                            source_key=left,
                            target_key=right,
                            type="related",
                            weight=0.6,
                            confidence=0.7,
                            rationale_fa="ادامهٔ بحث در فصل بعد.",
                        )
                    ]
                )
            )
        raise AssertionError(f"unexpected output type {output_type}")


def _builder(tmp_path: Path, model: FakeConceptMapModel) -> ConceptMapBuilder:
    runner = ModelRunner(
        model,
        PromptLoader(),
        WorkspaceModelRunStore(tmp_path / "workspaces"),
        sleeper=lambda _: None,
    )
    return ConceptMapBuilder(runner, workspace_root=tmp_path / "workspaces")


def test_builder_resumes_after_interrupt_at_chapter_two(tmp_path: Path) -> None:
    blocks = _three_chapter_blocks()
    document_map = _document_map(blocks)
    failing = FakeConceptMapModel(fail_on_stage="concept_cells:ch02")
    builder = _builder(tmp_path, failing)
    with pytest.raises(RuntimeError, match="interrupted at concept_cells:ch02"):
        builder.build(
            _PROJECT_ID,
            _SOURCE_ID,
            blocks,
            document_map,
            _PARSED,
            model_fast="fake-fast",
        )

    partial_path = (
        tmp_path
        / "workspaces"
        / str(_PROJECT_ID)
        / "sources"
        / str(_SOURCE_ID)
        / "concept-map.partial.json"
    )
    assert partial_path.exists()
    assert json.loads(partial_path.read_text(encoding="utf-8"))["completed_chapter_indexes"] == [
        0,
        1,
    ]
    assert "concept_cells:ch00" in failing.stages
    assert "concept_cells:ch01" in failing.stages
    assert "concept_cells:ch02" not in failing.stages

    cache = ConceptMapCache(tmp_path / "workspaces")
    fingerprint = block_sequence_key(blocks)
    assert cache.load_source(fingerprint) is None

    resuming = FakeConceptMapModel()
    resumed = _builder(tmp_path, resuming)
    concept_map = resumed.build(
        _PROJECT_ID,
        _SOURCE_ID,
        blocks,
        document_map,
        _PARSED,
        model_fast="fake-fast",
    )

    assert not partial_path.exists()
    assert [chapter.chapter_index for chapter in concept_map.chapters] == [0, 1, 2]
    assert concept_map.builder_version == CONCEPT_MAP_BUILDER_VERSION
    assert concept_map.source_fingerprint == fingerprint
    assert concept_map.statistics.cell_count == 6
    assert "concept_cells:ch00" not in resuming.stages
    assert "concept_cells:ch01" not in resuming.stages
    assert "concept_cells:ch02" in resuming.stages
    cached = cache.load_source(fingerprint)
    assert cached is not None
    assert cached.statistics.cell_count == 6

    hit_model = FakeConceptMapModel()
    hit = _builder(tmp_path, hit_model).build(
        _PROJECT_ID,
        _SOURCE_ID,
        blocks,
        document_map,
        _PARSED,
        model_fast="fake-fast",
    )
    assert hit.statistics.cell_count == 6
    assert hit_model.stages == []
