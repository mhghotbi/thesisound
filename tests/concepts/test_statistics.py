from datetime import UTC, datetime

import pytest

from thesisound.concepts import (
    ConceptCell,
    ConceptEdge,
    ConceptMapStatistics,
    SourceChapter,
    SourceConceptMap,
)
from thesisound.domain import DocumentMapSection
from thesisound.services.concept_map_builder import ConceptMapIntegrityError, compute_statistics


def _chapter(
    index: int,
    *,
    block_ids: list[str] | None = None,
    detection_agreement: str = "agreed",
    title: str = "",
) -> SourceChapter:
    return SourceChapter(
        chapter_index=index,
        title=title or f"فصل {index}",
        heading_path=[title or f"فصل {index}"],
        block_ids=block_ids or [f"b{index:04d}"],
        estimated_minutes=10.0,
        detected_from="heading",
        detection_agreement=detection_agreement,  # type: ignore[arg-type]
    )


def _section(
    section_id: str,
    *block_ids: str,
    function: str = "argument",
) -> DocumentMapSection:
    return DocumentMapSection(
        section_id=section_id,
        source_block_ids=list(block_ids) or ["b0001"],
        title=section_id,
        function=function,  # type: ignore[arg-type]
    )


def _cell(
    cell_key: str,
    *,
    section_ids: list[str] | None = None,
    block_ids: list[str] | None = None,
    tier: int = 2,
    label_source: str | None = None,
    estimated_minutes: float = 5.0,
    tier_promoted: bool = False,
    chapter_index: int | None = None,
) -> ConceptCell:
    number = int(cell_key.split("-c")[1])
    chapter = int(cell_key[2:4]) if chapter_index is None else chapter_index
    return ConceptCell(
        cell_key=cell_key,
        label_fa=f"مفهوم {number}",
        label_source=label_source,
        kind="definition",
        tier=tier,  # type: ignore[arg-type]
        tier_promoted=tier_promoted,
        chapter_index=chapter,
        section_ids=section_ids or [f"s{number:03d}"],
        block_ids=block_ids or [f"b{number:04d}"],
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=estimated_minutes,
    )


def _edge(
    source_key: str,
    target_key: str,
    *,
    type: str = "prerequisite",
    is_cross_chapter: bool = False,
) -> ConceptEdge:
    return ConceptEdge(
        source_key=source_key,
        target_key=target_key,
        type=type,  # type: ignore[arg-type]
        weight=0.8,
        confidence=0.9,
        rationale_fa="رابطه در منبع آمده است.",
        is_cross_chapter=is_cross_chapter,
    )


def _map(
    cells: list[ConceptCell],
    *,
    edges: list[ConceptEdge] | None = None,
    chapters: list[SourceChapter] | None = None,
) -> SourceConceptMap:
    if chapters is None:
        by_chapter: dict[int, list[str]] = {}
        for cell in cells:
            by_chapter.setdefault(cell.chapter_index, []).extend(cell.block_ids)
        chapters = [
            _chapter(index, block_ids=list(dict.fromkeys(block_ids)) or [f"b{index:04d}"])
            for index, block_ids in sorted(by_chapter.items())
        ]
        if not chapters:
            chapters = [_chapter(0)]
    return SourceConceptMap(
        source_fingerprint="fp-test",
        builder_version=1,
        chapters=chapters,
        cells=cells,
        edges=list(edges or []),
        statistics=ConceptMapStatistics(cell_count=len(cells)),
        created_at=datetime(2026, 8, 19, tzinfo=UTC),
    )


def test_counts_orphans_promotions_and_cross_chapter_edges() -> None:
    cells = [
        _cell("ch00-c001", tier=1, tier_promoted=True, section_ids=["s001"], block_ids=["b0001"]),
        _cell("ch00-c002", tier=2, section_ids=["s002"], block_ids=["b0002"]),
        _cell("ch01-c001", tier=3, section_ids=["s003"], block_ids=["b0003"]),
    ]
    edges = [
        _edge("ch00-c001", "ch00-c002"),
        _edge("ch00-c001", "ch01-c001", type="related", is_cross_chapter=True),
    ]
    stats = compute_statistics(
        _map(cells, edges=edges),
        sections=[
            _section("s001", "b0001"),
            _section("s002", "b0002"),
            _section("s003", "b0003"),
        ],
    )
    assert stats.cell_count == 3
    assert stats.cells_per_tier == {1: 1, 2: 1, 3: 1}
    assert stats.cells_per_chapter == {0: 2, 1: 1}
    assert stats.edges_per_type["prerequisite"] == 1
    assert stats.edges_per_type["related"] == 1
    assert stats.orphan_cell_keys == []
    assert stats.cross_chapter_edge_count == 1
    assert stats.promoted_cell_keys == ["ch00-c001"]


def test_orphan_is_reported_not_raised() -> None:
    cells = [
        _cell("ch00-c001", section_ids=["s001"], block_ids=["b0001"]),
        _cell("ch00-c002", section_ids=["s002"], block_ids=["b0002"]),
        _cell("ch00-c003", section_ids=["s003"], block_ids=["b0003"]),
    ]
    stats = compute_statistics(
        _map(cells, edges=[_edge("ch00-c001", "ch00-c002")]),
        sections=[
            _section("s001", "b0001"),
            _section("s002", "b0002"),
            _section("s003", "b0003"),
        ],
    )
    assert stats.orphan_cell_keys == ["ch00-c003"]


def test_needs_review_for_label_overlap_ratio_single_tier_oversize_and_disagreement() -> None:
    cells = [
        _cell(
            "ch00-c001",
            section_ids=["s001"],
            block_ids=["b0001"],
            tier=2,
            label_source="Wertform",
            estimated_minutes=30.0,
        ),
        _cell(
            "ch00-c002",
            section_ids=["s002"],
            block_ids=["b0002"],
            tier=2,
        ),
    ]
    concept_map = _map(
        cells,
        chapters=[
            _chapter(
                0,
                block_ids=["b0001", "b0002"],
                detection_agreement="disagreed",
                title="سرمایه",
            )
        ],
    )
    stats = compute_statistics(
        concept_map,
        sections=[_section("s001", "b0001"), _section("s002", "b0002")],
        block_texts={
            "b0001": "the author discusses labour in general",
            "b0002": "a later paragraph",
        },
    )
    joined = " | ".join(stats.needs_review)
    assert "chapter detection disagreed" in joined
    assert "سرمایه" in joined
    assert "single-tier chapter 0" in joined
    assert "ch00-c001 is oversize" in joined
    assert "ch00-c001 label_source 'Wertform'" in joined
    # two cells / two sections = 1.0, inside [0.5, 3]; no ratio flag
    assert "cells/sections ratio" not in joined


def test_cells_sections_ratio_is_flagged_when_too_high() -> None:
    cells = [
        _cell(f"ch00-c{n:03d}", section_ids=["s001"], block_ids=["b0001"], tier=n)
        for n in (1, 2, 3)
    ]
    extra = [
        _cell("ch00-c004", section_ids=["s001"], block_ids=["b0001"], tier=2),
        _cell("ch00-c005", section_ids=["s001"], block_ids=["b0001"], tier=3),
        _cell("ch00-c006", section_ids=["s001"], block_ids=["b0001"], tier=2),
        _cell("ch00-c007", section_ids=["s001"], block_ids=["b0001"], tier=1),
    ]
    stats = compute_statistics(
        _map(cells + extra, chapters=[_chapter(0, block_ids=["b0001"])]),
        sections=[_section("s001", "b0001")],
    )
    assert any(
        "cells/sections ratio" in flag and "chapter 0" in flag
        for flag in stats.needs_review
    )


def test_uncovered_section_is_critical() -> None:
    cells = [_cell("ch00-c001", section_ids=["s001"], block_ids=["b0001"])]
    with pytest.raises(ConceptMapIntegrityError, match="no cell after consolidation"):
        compute_statistics(
            _map(cells, chapters=[_chapter(0, block_ids=["b0001", "b0002"])]),
            sections=[_section("s001", "b0001"), _section("s002", "b0002")],
        )


def test_unknown_block_id_is_critical() -> None:
    cells = [_cell("ch00-c001", section_ids=["s001"], block_ids=["b0999"])]
    with pytest.raises(ConceptMapIntegrityError, match="Unknown IDs"):
        compute_statistics(
            _map(cells, chapters=[_chapter(0, block_ids=["b0001"])]),
            sections=[_section("s001", "b0001")],
        )


def test_cell_without_block_is_critical() -> None:
    cell = _cell("ch00-c001", section_ids=["s001"], block_ids=["b0001"])
    broken = ConceptCell.model_construct(**{**cell.model_dump(), "block_ids": []})
    with pytest.raises(ConceptMapIntegrityError, match="no source block"):
        compute_statistics(
            _map([broken], chapters=[_chapter(0, block_ids=["b0001"])]),
            sections=[_section("s001", "b0001")],
        )
