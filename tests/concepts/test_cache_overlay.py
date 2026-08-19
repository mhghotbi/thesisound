from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from thesisound.concepts import (
    ConceptCell,
    ConceptEdge,
    ConceptMapOverlay,
    ConceptMapStatistics,
    SourceChapter,
    SourceConceptMap,
)
from thesisound.config import Settings
from thesisound.domain import Locator
from thesisound.pipeline import WorkspaceStore
from thesisound.services.concept_map_builder import ConceptMapBuilder
from thesisound.services.concept_map_cache import (
    CONCEPT_MAP_BUILDER_VERSION,
    CachedChapterConceptMap,
    ConceptMapCache,
    chapter_hash,
)
from thesisound.services.concept_map_overlay import ConceptMapOverlayService, edge_overlay_key
from thesisound.services.source_analysis_service import SourceAnalysisService
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import SourceDocumentBlock

_FINGERPRINT = "a" * 64


def _chapter(index: int = 1, block_ids: list[str] | None = None) -> SourceChapter:
    return SourceChapter(
        chapter_index=index,
        title=f"فصل {index}",
        heading_path=[f"فصل {index}"],
        block_ids=block_ids or ["b0001", "b0002", "b0003"],
        estimated_minutes=10.0,
        detected_from="heading",
        detection_agreement="agreed",
    )


def _cell(cell_key: str, *, tier: int = 2, created_by: str = "ai") -> ConceptCell:
    number = int(cell_key.split("-c")[1])
    chapter = int(cell_key[2:4])
    return ConceptCell(
        cell_key=cell_key,
        label_fa=f"مفهوم {number}",
        kind="definition",
        tier=tier,  # type: ignore[arg-type]
        chapter_index=chapter,
        section_ids=[f"s{number:03d}"],
        block_ids=[f"b{number:04d}"],
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=5.0,
        created_by=created_by,  # type: ignore[arg-type]
    )


def _edge(source_key: str, target_key: str, *, created_by: str = "ai") -> ConceptEdge:
    return ConceptEdge(
        source_key=source_key,
        target_key=target_key,
        type="prerequisite",
        weight=0.8,
        confidence=0.9,
        rationale_fa="رابطه در منبع آمده است.",
        created_by=created_by,  # type: ignore[arg-type]
    )


def _map(
    *,
    cells: list[ConceptCell] | None = None,
    edges: list[ConceptEdge] | None = None,
) -> SourceConceptMap:
    cells = cells or [_cell("ch01-c001"), _cell("ch01-c002", tier=1)]
    edges = edges or [_edge("ch01-c001", "ch01-c002")]
    return SourceConceptMap(
        source_fingerprint=_FINGERPRINT,
        builder_version=CONCEPT_MAP_BUILDER_VERSION,
        chapters=[_chapter(1)],
        cells=cells,
        edges=edges,
        statistics=ConceptMapStatistics(cell_count=len(cells)),
        created_at=datetime(2026, 8, 19, tzinfo=UTC),
    )


def test_source_cache_round_trip(tmp_path: Path) -> None:
    cache = ConceptMapCache(tmp_path)
    concept_map = _map()
    saved = cache.save_source(concept_map)
    assert saved is not None
    loaded = cache.load_source(_FINGERPRINT)
    assert loaded is not None
    assert loaded.source_fingerprint == _FINGERPRINT
    assert [cell.cell_key for cell in loaded.cells] == [cell.cell_key for cell in concept_map.cells]
    assert [edge_overlay_key(edge) for edge in loaded.edges] == [
        edge_overlay_key(edge) for edge in concept_map.edges
    ]


def test_builder_version_invalidation_is_a_miss(tmp_path: Path) -> None:
    cache = ConceptMapCache(tmp_path)
    cache.save_source(_map())
    path = cache.source_path(_FINGERPRINT)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["builder_version"] = CONCEPT_MAP_BUILDER_VERSION + 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert cache.load_source(_FINGERPRINT) is None


def test_chapter_sub_entry_round_trip(tmp_path: Path) -> None:
    cache = ConceptMapCache(tmp_path)
    chapter = _chapter(0)
    blocks = [
        SourceDocumentBlock(
            block_id="b0000",
            source_id=uuid4(),
            locator=Locator(),
            heading_path=["فصل 0"],
            block_type="argument",
            text="first chapter body",
            estimated_token_count=20,
            source_block_keys=["k0"],
        ),
        SourceDocumentBlock(
            block_id="b0000x",
            source_id=uuid4(),
            locator=Locator(),
            heading_path=["فصل 0"],
            block_type="argument",
            text="more body",
            estimated_token_count=20,
            source_block_keys=["k1"],
        ),
    ]
    chapter_key = chapter_hash(chapter, blocks)
    entry = CachedChapterConceptMap(
        source_fingerprint=_FINGERPRINT,
        chapter_hash=chapter_key,
        builder_version=CONCEPT_MAP_BUILDER_VERSION,
        chapter=chapter,
        cells=[_cell("ch00-c001")],
        intra_edges=[],
        warnings=["ok"],
    )
    assert cache.save_chapter(entry) is not None
    loaded = cache.load_chapter(_FINGERPRINT, chapter_key)
    assert loaded is not None
    assert loaded.cells[0].cell_key == "ch00-c001"
    assert loaded.warnings == ["ok"]

    stale = json.loads(cache.chapter_path(_FINGERPRINT, chapter_key).read_text(encoding="utf-8"))
    stale["builder_version"] = CONCEPT_MAP_BUILDER_VERSION + 1
    cache.chapter_path(_FINGERPRINT, chapter_key).write_text(json.dumps(stale), encoding="utf-8")
    assert cache.load_chapter(_FINGERPRINT, chapter_key) is None


def test_overlay_apply_and_record_edit_round_trip(tmp_path: Path) -> None:
    service = ConceptMapOverlayService(tmp_path)
    project_id = uuid4()
    source_id = uuid4()
    concept_map = _map()
    overlay = service.record_edit(
        project_id,
        source_id,
        source_fingerprint=_FINGERPRINT,
        remove_cell_key="ch01-c002",
        add_cell=_cell("ch01-c003", created_by="user"),
        add_edge=_edge("ch01-c001", "ch01-c003", created_by="user"),
        remove_edge_key=edge_overlay_key(_edge("ch01-c001", "ch01-c002")),
        tier_override=("ch01-c001", 1),
    )
    reloaded = service.load(project_id, source_id)
    assert reloaded is not None
    assert reloaded.version == overlay.version == 1
    effective = service.apply(concept_map, reloaded)
    keys = [cell.cell_key for cell in effective.cells]
    assert "ch01-c002" not in keys
    assert "ch01-c003" in keys
    added = [cell for cell in effective.cells if cell.cell_key == "ch01-c003"]
    assert added and all(cell.created_by == "user" for cell in added)
    assert effective.cells[0].tier == 1
    assert effective.cells[0].tier_promoted is False
    assert [edge_overlay_key(edge) for edge in effective.edges] == [
        "ch01-c001|ch01-c003|prerequisite"
    ]
    # A later rebuild of the AI map does not touch the overlay file.
    overlay_path = service.path(project_id, source_id)
    before = overlay_path.read_text(encoding="utf-8")
    cache = ConceptMapCache(tmp_path)
    cache.save_source(concept_map)
    cache.load_source(_FINGERPRINT)
    assert overlay_path.read_text(encoding="utf-8") == before


def test_overlay_fingerprint_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="fingerprint"):
        ConceptMapOverlayService(Path("/tmp")).apply(
            _map(),
            ConceptMapOverlay(source_fingerprint="b" * 64, version=1),
        )


def test_concept_map_analysis_hook_is_off_by_default() -> None:
    assert Settings(_env_file=None).concept_map_on_analysis_enabled is False


def test_analysis_hook_does_not_build_when_disabled(tmp_path: Path) -> None:
    class ExplodingBuilder:
        def build(self, *args: object, **kwargs: object) -> SourceConceptMap:
            raise AssertionError("concept map must stay off until step 18")

    service = SourceAnalysisService(
        workspace_store=WorkspaceStore(tmp_path),
        artifact_store=SourceArtifactStore(tmp_path),
        block_builder=None,  # type: ignore[arg-type]
        document_mapper=None,  # type: ignore[arg-type]
        evidence_extractor=None,  # type: ignore[arg-type]
        claim_reconciler=None,  # type: ignore[arg-type]
        concept_map_builder=ExplodingBuilder(),  # type: ignore[arg-type]
        concept_map_enabled=False,
    )
    service._maybe_build_concept_map(uuid4(), uuid4(), model="fake")


def test_analysis_hook_requires_a_builder_when_enabled(tmp_path: Path) -> None:
    service = SourceAnalysisService(
        workspace_store=WorkspaceStore(tmp_path),
        artifact_store=SourceArtifactStore(tmp_path),
        block_builder=None,  # type: ignore[arg-type]
        document_mapper=None,  # type: ignore[arg-type]
        evidence_extractor=None,  # type: ignore[arg-type]
        claim_reconciler=None,  # type: ignore[arg-type]
        concept_map_enabled=True,
    )
    with pytest.raises(ValueError, match="no builder"):
        service._maybe_build_concept_map(uuid4(), uuid4(), model="fake")


def test_concept_map_builder_is_constructable_for_wiring(tmp_path: Path) -> None:
    from thesisound.prompt_loader import PromptLoader
    from thesisound.services.model_run_store import WorkspaceModelRunStore
    from thesisound.services.model_runner import ModelRunner

    class UnusedModel:
        provider = "fake"

        def generate_structured(self, **kwargs: object) -> None:
            raise AssertionError("unused")

    builder = ConceptMapBuilder(
        ModelRunner(
            UnusedModel(),  # type: ignore[arg-type]
            PromptLoader(),
            WorkspaceModelRunStore(tmp_path),
            sleeper=lambda _: None,
        ),
        workspace_root=tmp_path,
    )
    assert builder.cache.root == (tmp_path / "_shared" / "concept-maps").resolve()
