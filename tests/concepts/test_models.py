import pytest
from pydantic import ValidationError

from thesisound.concepts import (
    ConceptCell,
    ConceptEdge,
    ConceptMapOverlay,
    ConceptMapStatistics,
    ConsolidateActionDraft,
    LessonPart,
    SourceChapter,
    SourceConceptMap,
)


def _chapter(**overrides: object) -> SourceChapter:
    defaults: dict[object, object] = dict(
        chapter_index=1,
        title="فصل یکم",
        heading_path=["فصل یکم"],
        block_ids=["b0001", "b0002"],
        estimated_minutes=12.5,
        detected_from="heading",
        detection_agreement="agreed",
    )
    defaults.update(overrides)
    return SourceChapter(**defaults)


def _cell(**overrides: object) -> ConceptCell:
    defaults: dict[object, object] = dict(
        cell_key="ch01-c001",
        label_fa="تعریف مفهوم",
        label_source=None,
        kind="definition",
        tier=1,
        chapter_index=1,
        section_ids=["s001"],
        block_ids=["b0001"],
        granularity_rationale="یک تعریف مستقل و قابل ردیابی است.",
        estimated_minutes=4.0,
    )
    defaults.update(overrides)
    return ConceptCell(**defaults)


def _edge(**overrides: object) -> ConceptEdge:
    defaults: dict[object, object] = dict(
        source_key="ch01-c001",
        target_key="ch01-c002",
        type="prerequisite",
        weight=0.8,
        confidence=0.9,
        rationale_fa="سلول دوم به فهم سلول اول نیاز دارد.",
    )
    defaults.update(overrides)
    return ConceptEdge(**defaults)


def _statistics(**overrides: object) -> ConceptMapStatistics:
    defaults: dict[object, object] = dict(
        cell_count=2,
        cells_per_tier={1: 1, 2: 1},
        cells_per_chapter={1: 2},
        edges_per_type={"prerequisite": 1},
        orphan_cell_keys=[],
        cross_chapter_edge_count=0,
        promoted_cell_keys=[],
        needs_review=[],
    )
    defaults.update(overrides)
    return ConceptMapStatistics(**defaults)


class TestRoundTrip:
    def test_source_chapter_round_trip(self) -> None:
        chapter = _chapter()
        reloaded = SourceChapter.model_validate_json(chapter.model_dump_json())
        assert reloaded == chapter

    def test_concept_cell_round_trip(self) -> None:
        cell = _cell(label_source="Begriff", evidence_ids=["e001"], tier_promoted=True)
        reloaded = ConceptCell.model_validate_json(cell.model_dump_json())
        assert reloaded == cell

    def test_concept_edge_round_trip(self) -> None:
        edge = _edge(is_cross_chapter=True, created_by="user")
        reloaded = ConceptEdge.model_validate_json(edge.model_dump_json())
        assert reloaded == edge

    def test_statistics_round_trip(self) -> None:
        stats = _statistics(needs_review=["chapter detection disagreed: ch03"])
        reloaded = ConceptMapStatistics.model_validate_json(stats.model_dump_json())
        assert reloaded == stats

    def test_source_concept_map_round_trip(self) -> None:
        concept_map = SourceConceptMap(
            source_fingerprint="a" * 64,
            builder_version=1,
            chapters=[_chapter()],
            cells=[_cell(), _cell(cell_key="ch01-c002", tier=2)],
            edges=[_edge()],
            statistics=_statistics(),
            warnings=["one chapter used the single detector"],
        )
        reloaded = SourceConceptMap.model_validate_json(concept_map.model_dump_json())
        assert reloaded == concept_map

    def test_concept_map_overlay_round_trip(self) -> None:
        overlay = ConceptMapOverlay(
            source_fingerprint="a" * 64,
            version=1,
            added_cells=[_cell(created_by="user")],
            removed_cell_keys=["ch01-c009"],
            added_edges=[_edge(created_by="user")],
            removed_edge_keys=["ch01-c001|ch01-c002|prerequisite"],
            tier_overrides={"ch01-c003": 2},
        )
        reloaded = ConceptMapOverlay.model_validate_json(overlay.model_dump_json())
        assert reloaded == overlay

    def test_lesson_part_round_trip(self) -> None:
        part = LessonPart(
            part_index=1,
            title_fa="بخش یکم",
            cell_keys=["ch01-c001"],
            claim_ids=["c-1"],
            estimated_minutes=20.0,
            graph_backed=True,
            flags=["oversize_cell"],
        )
        reloaded = LessonPart.model_validate_json(part.model_dump_json())
        assert reloaded == part


class TestConceptCellConstraints:
    def test_cell_key_must_match_pattern(self) -> None:
        with pytest.raises(ValidationError):
            _cell(cell_key="chapter1-cell1")

    def test_cell_key_requires_zero_padded_digits(self) -> None:
        with pytest.raises(ValidationError):
            _cell(cell_key="ch1-c001")

    def test_tier_rejects_out_of_range_value(self) -> None:
        with pytest.raises(ValidationError):
            _cell(tier=4)

    def test_tier_rejects_zero(self) -> None:
        with pytest.raises(ValidationError):
            _cell(tier=0)

    def test_block_ids_require_at_least_one(self) -> None:
        with pytest.raises(ValidationError):
            _cell(block_ids=[])

    def test_section_ids_require_at_least_one(self) -> None:
        with pytest.raises(ValidationError):
            _cell(section_ids=[])

    def test_estimated_minutes_floor(self) -> None:
        with pytest.raises(ValidationError):
            _cell(estimated_minutes=0.1)

    def test_estimated_minutes_ceiling(self) -> None:
        with pytest.raises(ValidationError):
            _cell(estimated_minutes=31)


class TestConceptEdgeConstraints:
    def test_weight_rejects_above_one(self) -> None:
        with pytest.raises(ValidationError):
            _edge(weight=1.1)

    def test_weight_rejects_below_zero(self) -> None:
        with pytest.raises(ValidationError):
            _edge(weight=-0.1)

    def test_confidence_rejects_above_one(self) -> None:
        with pytest.raises(ValidationError):
            _edge(confidence=1.1)

    def test_confidence_rejects_below_zero(self) -> None:
        with pytest.raises(ValidationError):
            _edge(confidence=-0.1)

    def test_source_key_must_match_cell_key_pattern(self) -> None:
        with pytest.raises(ValidationError):
            _edge(source_key="not-a-cell-key")

    def test_target_key_must_match_cell_key_pattern(self) -> None:
        with pytest.raises(ValidationError):
            _edge(target_key="not-a-cell-key")


class TestSourceChapterConstraints:
    def test_block_ids_require_at_least_one(self) -> None:
        with pytest.raises(ValidationError):
            _chapter(block_ids=[])

    def test_chapter_index_rejects_negative(self) -> None:
        with pytest.raises(ValidationError):
            _chapter(chapter_index=-1)


class TestConsolidateActionDraft:
    def test_merge_into_none_is_valid_for_keep(self) -> None:
        action = ConsolidateActionDraft(
            cell_key="ch01-c001",
            action="keep",
            merge_into=None,
            reason="سلول مستقل و کافی است.",
        )
        assert action.merge_into is None

    def test_merge_into_accepts_valid_cell_key(self) -> None:
        action = ConsolidateActionDraft(
            cell_key="ch01-c002",
            action="merge",
            merge_into="ch01-c001",
            reason="با سلول دیگر هم‌پوشانی دارد.",
        )
        assert action.merge_into == "ch01-c001"

    def test_merge_into_rejects_invalid_cell_key(self) -> None:
        with pytest.raises(ValidationError):
            ConsolidateActionDraft(
                cell_key="ch01-c002",
                action="merge",
                merge_into="not-a-cell-key",
                reason="با سلول دیگر هم‌پوشانی دارد.",
            )


class TestConceptMapOverlayConstraints:
    def test_tier_override_rejects_invalid_tier(self) -> None:
        with pytest.raises(ValidationError):
            ConceptMapOverlay(
                source_fingerprint="a" * 64,
                version=1,
                tier_overrides={"ch01-c003": 4},
            )
