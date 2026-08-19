from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from tests.concepts.test_builder_resume import (
    _PARSED,
    _PROJECT_ID,
    _SOURCE_ID,
    FakeConceptMapModel,
    _builder,
    _document_map,
    _three_chapter_blocks,
)
from thesisound.services.concept_map_cache import ConceptMapCache
from thesisound.services.document_identity import block_sequence_key


def test_rebuild_skips_source_cache(tmp_path: Path) -> None:
    blocks = _three_chapter_blocks()
    document_map = _document_map(blocks)
    first = FakeConceptMapModel()
    built = _builder(tmp_path, first).build(
        _PROJECT_ID,
        _SOURCE_ID,
        blocks,
        document_map,
        _PARSED,
        model_fast="fake-fast",
    )
    assert built.statistics.cell_count == 6
    assert first.stages

    cached_hit = FakeConceptMapModel()
    _builder(tmp_path, cached_hit).build(
        _PROJECT_ID,
        _SOURCE_ID,
        blocks,
        document_map,
        _PARSED,
        model_fast="fake-fast",
    )
    assert cached_hit.stages == []

    rebuilt_model = FakeConceptMapModel()
    rebuilt = _builder(tmp_path, rebuilt_model).build(
        _PROJECT_ID,
        uuid4(),
        blocks,
        document_map,
        _PARSED,
        model_fast="fake-fast",
        rebuild=True,
    )
    assert rebuilt.statistics.cell_count == 6
    assert any(stage.startswith("concept_cells:") for stage in rebuilt_model.stages)


def test_chapter_indexes_does_not_write_source_cache(tmp_path: Path) -> None:
    blocks = _three_chapter_blocks()
    document_map = _document_map(blocks)
    model = FakeConceptMapModel()
    subset = _builder(tmp_path, model).build(
        _PROJECT_ID,
        _SOURCE_ID,
        blocks,
        document_map,
        _PARSED,
        model_fast="fake-fast",
        chapter_indexes=(0,),
    )
    assert [chapter.chapter_index for chapter in subset.chapters] == [0]
    assert subset.statistics.cell_count == 2
    cache = ConceptMapCache(tmp_path / "workspaces")
    assert cache.load_source(block_sequence_key(blocks)) is None
