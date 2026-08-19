from datetime import UTC, datetime
from uuid import uuid4

from thesisound.concepts import (
    ConceptCell,
    ConceptMapStatistics,
    SourceChapter,
    SourceConceptMap,
)
from thesisound.domain import (
    Compression,
    DocumentMap,
    DocumentMapSection,
    LessonIntent,
    Locator,
    Project,
    ResearchBrief,
    TopicType,
)
from thesisound.services.analysis_profile import (
    group_selected_blocks_by_cell,
    plan_evidence_extraction,
    resolve_extraction_seeds,
)
from thesisound.source_analysis import SourceDocumentBlock


def _brief(duration: int = 10) -> ResearchBrief:
    return ResearchBrief(
        normalized_topic="Arendt and action",
        topic_type=TopicType.CONCEPT,
        central_question="What distinguishes action from fabrication?",
        target_duration_minutes=duration,
    )


def _cell(cell_key: str, block_ids: list[str], *, tier: int = 1) -> ConceptCell:
    return ConceptCell(
        cell_key=cell_key,
        label_fa="برچسب",
        kind="argument",
        tier=tier,  # type: ignore[arg-type]
        chapter_index=int(cell_key[2:4]),
        section_ids=["section-1"],
        block_ids=block_ids,
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=4.0,
    )


def _planning_fixture() -> tuple[list[SourceDocumentBlock], DocumentMap]:
    source_id = uuid4()
    blocks = [
        SourceDocumentBlock(
            block_id=f"block-{index}",
            source_id=source_id,
            locator=Locator(page_start=index, page_end=index),
            heading_path=[f"Section {index}"],
            block_type="other",
            text=f"Semantic content for block {index}." * 10,
            estimated_token_count=100,
            source_block_keys=[f"source-{index}"],
        )
        for index in range(1, 11)
    ]
    document_map = DocumentMap(
        source_id=source_id,
        scope_locator=Locator(page_start=1, page_end=10),
        working_thesis="Action differs from fabrication.",
        sections=[
            DocumentMapSection(
                section_id=f"section-{index}",
                source_block_ids=[f"block-{index * 2 - 1}", f"block-{index * 2}"],
                title=f"Section {index}",
                function="argument",
            )
            for index in range(1, 6)
        ],
    )
    return blocks, document_map


def _map(cells: list[ConceptCell]) -> SourceConceptMap:
    chapters = [
        SourceChapter(
            chapter_index=0,
            title="فصل ۰",
            heading_path=["فصل ۰"],
            block_ids=["block-1"],
            estimated_minutes=10.0,
            detected_from="heading",
            detection_agreement="agreed",
        )
    ]
    return SourceConceptMap(
        source_fingerprint="a" * 64,
        builder_version=1,
        chapters=chapters,
        cells=cells,
        edges=[],
        statistics=ConceptMapStatistics(cell_count=len(cells)),
        created_at=datetime.now(UTC),
    )


def test_seed_cells_select_only_those_blocks_and_defer_the_rest() -> None:
    blocks, document_map = _planning_fixture()
    seeds = [_cell("ch00-c001", ["block-1", "block-2"]), _cell("ch00-c002", ["block-4"])]

    plan = plan_evidence_extraction(
        _brief(5),
        document_map,
        blocks,
        seed_cells=seeds,
        force_depth="extended",
    )

    assert plan.selected_block_ids == ["block-1", "block-2", "block-4"]
    assert "block-3" in plan.deferred_block_ids
    assert plan.seeded_block_count == 3
    assert plan.profile.depth == "extended"
    assert plan.profile.second_pass_for_core_sections is False
    assert plan.cell_batch_units == [["block-1", "block-2"], ["block-4"]]
    assert plan.dense_second_pass_block_ids == ["block-1", "block-2", "block-4"]


def test_seed_cells_ignore_the_duration_token_budget() -> None:
    blocks, document_map = _planning_fixture()
    duration_plan = plan_evidence_extraction(_brief(5), document_map, blocks)
    seeds = [_cell("ch00-c001", [block.block_id for block in blocks])]

    seeded = plan_evidence_extraction(
        _brief(5),
        document_map,
        blocks,
        seed_cells=seeds,
        force_depth="extended",
    )

    assert len(duration_plan.selected_block_ids) < len(blocks)
    assert seeded.selected_block_ids == [block.block_id for block in blocks]
    assert seeded.deferred_block_ids == []


def test_force_depth_extended_does_not_change_focused_question_selection() -> None:
    """force_depth without seed_cells only deepens the profile, then ranks as usual."""

    blocks, document_map = _planning_fixture()
    plain = plan_evidence_extraction(_brief(20), document_map, blocks)
    forced = plan_evidence_extraction(
        _brief(20), document_map, blocks, force_depth="extended"
    )

    assert plain.profile.depth == "standard"
    assert forced.profile.depth == "extended"
    assert forced.cell_batch_units == []
    assert forced.dense_second_pass_block_ids == []
    assert len(forced.selected_block_ids) >= len(plain.selected_block_ids)


def test_tier_three_seed_blocks_are_not_dense_second_pass_targets() -> None:
    blocks, document_map = _planning_fixture()
    seeds = [
        _cell("ch00-c001", ["block-1"], tier=1),
        _cell("ch00-c002", ["block-2"], tier=3),
    ]

    plan = plan_evidence_extraction(
        _brief(10),
        document_map,
        blocks,
        seed_cells=seeds,
        force_depth="extended",
    )

    assert plan.selected_block_ids == ["block-1", "block-2"]
    assert plan.dense_second_pass_block_ids == ["block-1"]


def test_group_selected_blocks_by_cell_uses_the_earliest_cell_on_overlap() -> None:
    blocks, _document_map = _planning_fixture()
    # Later cell listed first; book order still attributes the shared block to ch00-c001.
    cells = [
        _cell("ch00-c002", ["block-2", "block-3"]),
        _cell("ch00-c001", ["block-1", "block-2"]),
    ]

    units = group_selected_blocks_by_cell(
        ["block-1", "block-2", "block-3"],
        blocks,
        cells,
        max_batch_tokens=10_000,
    )

    assert units == [["block-1", "block-2"], ["block-3"]]


def test_resolve_extraction_seeds_only_for_source_coverage_with_a_map() -> None:
    cells = [_cell("ch00-c001", ["block-1"])]
    concept_map = _map(cells)
    focused = Project(raw_input="پرسش", brief=_brief(), lesson_intent=LessonIntent.FOCUSED_QUESTION)
    coverage = Project(
        raw_input="منبع",
        brief=_brief(),
        lesson_intent=LessonIntent.SOURCE_COVERAGE,
        compression=Compression.STANDARD,
    )

    assert resolve_extraction_seeds(focused, concept_map) == (None, None)
    assert resolve_extraction_seeds(coverage, None) == (None, None)
    seeds, depth = resolve_extraction_seeds(coverage, concept_map)
    assert depth == "extended"
    assert seeds is not None
    assert [cell.cell_key for cell in seeds] == ["ch00-c001"]
