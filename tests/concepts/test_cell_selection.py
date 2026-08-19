from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from thesisound.concepts import (
    ConceptCell,
    ConceptEdge,
    ConceptMapStatistics,
    SourceChapter,
    SourceConceptMap,
)
from thesisound.domain import (
    MAX_PART_MINUTES,
    Compression,
    DeliveryMode,
    LessonIntent,
    Project,
    ProjectScope,
    ResearchBrief,
    TopicType,
)
from thesisound.services.cell_selection import (
    TIER_IN_SCOPE_REASON,
    closure_reason,
    select_cells,
)


def _chapter(index: int, title: str = "") -> SourceChapter:
    return SourceChapter(
        chapter_index=index,
        title=title or f"فصل {index}",
        heading_path=[title or f"فصل {index}"],
        block_ids=[f"b{index:04d}"],
        estimated_minutes=10.0,
        detected_from="heading",
        detection_agreement="agreed",
    )


def _cell(
    cell_key: str,
    *,
    tier: int = 1,
    kind: str = "definition",
    minutes: float = 4.0,
    label: str | None = None,
) -> ConceptCell:
    number = int(cell_key.split("-c")[1])
    return ConceptCell(
        cell_key=cell_key,
        label_fa=label or f"مفهوم {number}",
        kind=kind,  # type: ignore[arg-type]
        tier=tier,  # type: ignore[arg-type]
        chapter_index=int(cell_key[2:4]),
        section_ids=[f"s{number:03d}"],
        block_ids=[f"b{number:04d}"],
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=minutes,
    )


def _prereq(source_key: str, target_key: str) -> ConceptEdge:
    return ConceptEdge(
        source_key=source_key,
        target_key=target_key,
        type="prerequisite",
        weight=0.9,
        confidence=0.9,
        rationale_fa="هدف بدون مبدأ فهمیده نمی‌شود.",
    )


def _map(
    cells: list[ConceptCell],
    edges: list[ConceptEdge] | None = None,
    chapters: list[SourceChapter] | None = None,
) -> SourceConceptMap:
    chapter_indexes = sorted({cell.chapter_index for cell in cells})
    return SourceConceptMap(
        source_fingerprint="f" * 64,
        builder_version=1,
        chapters=chapters or [_chapter(index) for index in chapter_indexes],
        cells=cells,
        edges=edges or [],
        statistics=ConceptMapStatistics(cell_count=len(cells)),
        created_at=datetime.now(UTC),
    )


def test_concise_keeps_tier_1_and_closes_prerequisites() -> None:
    concept_map = _map(
        [
            _cell("ch00-c001", tier=1, label="استدلال اصلی"),
            _cell("ch00-c002", tier=3, label="تمایز پشتیبان"),
            _cell("ch00-c003", tier=3, label="مثال کنارگذاشته"),
        ],
        [_prereq("ch00-c002", "ch00-c001")],
    )
    in_scope, omitted = select_cells(concept_map, None, Compression.CONCISE)
    reasons = {item.cell.cell_key: item.in_scope_reason for item in in_scope}
    assert reasons == {
        "ch00-c001": TIER_IN_SCOPE_REASON,
        "ch00-c002": closure_reason("ch00-c001"),
    }
    assert [cell.cell_key for cell in omitted] == ["ch00-c003"]


def test_standard_keeps_tier_1_and_2() -> None:
    concept_map = _map(
        [
            _cell("ch00-c001", tier=1),
            _cell("ch00-c002", tier=2),
            _cell("ch00-c003", tier=3),
        ]
    )
    in_scope, omitted = select_cells(concept_map, None, "standard")
    assert [item.cell.cell_key for item in in_scope] == ["ch00-c001", "ch00-c002"]
    assert [cell.cell_key for cell in omitted] == ["ch00-c003"]


def test_full_closure_is_identity() -> None:
    concept_map = _map(
        [
            _cell("ch00-c001", tier=1),
            _cell("ch00-c002", tier=3),
        ],
        [_prereq("ch00-c002", "ch00-c001")],
    )
    in_scope, omitted = select_cells(concept_map, None, Compression.FULL)
    assert [item.cell.cell_key for item in in_scope] == ["ch00-c001", "ch00-c002"]
    assert all(item.in_scope_reason == TIER_IN_SCOPE_REASON for item in in_scope)
    assert omitted == []


def test_cycle_is_safe_and_includes_each_cell_once() -> None:
    concept_map = _map(
        [
            _cell("ch00-c001", tier=1),
            _cell("ch00-c002", tier=3),
        ],
        [_prereq("ch00-c002", "ch00-c001"), _prereq("ch00-c001", "ch00-c002")],
    )
    in_scope, omitted = select_cells(concept_map, None, Compression.CONCISE)
    assert [item.cell.cell_key for item in in_scope] == ["ch00-c001", "ch00-c002"]
    assert omitted == []
    assert in_scope[1].in_scope_reason == closure_reason("ch00-c001")


def test_closure_hop_cap_stops_at_25() -> None:
    cells = [_cell("ch00-c001", tier=1)]
    edges: list[ConceptEdge] = []
    for hop in range(2, 28):
        key = f"ch00-c{hop:03d}"
        cells.append(_cell(key, tier=3))
        previous = f"ch00-c{hop - 1:03d}"
        edges.append(_prereq(key, previous))
    in_scope, omitted = select_cells(_map(cells, edges), None, Compression.CONCISE)
    keys = [item.cell.cell_key for item in in_scope]
    assert keys[0] == "ch00-c001"
    assert keys[-1] == "ch00-c026"
    assert len(keys) == 26
    assert [cell.cell_key for cell in omitted] == ["ch00-c027"]


def test_closure_reason_points_at_the_selected_cell() -> None:
    concept_map = _map(
        [
            _cell("ch00-c001", tier=1),
            _cell("ch00-c002", tier=3),
            _cell("ch00-c003", tier=3),
        ],
        [_prereq("ch00-c002", "ch00-c001"), _prereq("ch00-c003", "ch00-c002")],
    )
    in_scope, _omitted = select_cells(concept_map, None, Compression.CONCISE)
    reasons = {item.cell.cell_key: item.in_scope_reason for item in in_scope}
    assert reasons["ch00-c002"] == closure_reason("ch00-c001")
    assert reasons["ch00-c003"] == closure_reason("ch00-c001")


def test_chapter_scope_filters_then_closure_may_cross_chapters() -> None:
    source_id = uuid4()
    concept_map = _map(
        [
            _cell("ch00-c001", tier=3),
            _cell("ch01-c001", tier=1),
            _cell("ch01-c002", tier=3),
        ],
        [_prereq("ch00-c001", "ch01-c001")],
        chapters=[_chapter(0), _chapter(1)],
    )
    in_scope, omitted = select_cells(
        concept_map,
        ProjectScope(source_id=source_id, chapter_indexes=[1]),
        Compression.CONCISE,
    )
    assert [item.cell.cell_key for item in in_scope] == ["ch00-c001", "ch01-c001"]
    assert in_scope[0].in_scope_reason == closure_reason("ch01-c001")
    assert [cell.cell_key for cell in omitted] == ["ch01-c002"]


def test_non_prerequisite_edges_do_not_close() -> None:
    related = ConceptEdge(
        source_key="ch00-c002",
        target_key="ch00-c001",
        type="related",
        weight=0.5,
        confidence=0.5,
        rationale_fa="فقط مرتبط است.",
    )
    concept_map = _map(
        [_cell("ch00-c001", tier=1), _cell("ch00-c002", tier=3)],
        [related],
    )
    in_scope, omitted = select_cells(concept_map, None, Compression.CONCISE)
    assert [item.cell.cell_key for item in in_scope] == ["ch00-c001"]
    assert [cell.cell_key for cell in omitted] == ["ch00-c002"]


def test_project_fields_default_to_focused_question() -> None:
    project = Project(raw_input="پرسش")
    assert project.lesson_intent == LessonIntent.FOCUSED_QUESTION
    assert project.delivery == DeliveryMode.AUDIO
    assert project.compression == Compression.STANDARD
    assert project.episode_target_minutes == 20
    assert project.scope is None
    assert project.known_concepts == []


def test_legacy_project_json_loads_with_source_coverage_defaults() -> None:
    project = Project(raw_input="قدیمی")
    payload = project.model_dump(mode="json")
    for key in (
        "lesson_intent",
        "delivery",
        "compression",
        "episode_target_minutes",
        "scope",
        "known_concepts",
    ):
        payload.pop(key)
    reloaded = Project.model_validate(payload)
    assert reloaded.lesson_intent == LessonIntent.FOCUSED_QUESTION
    assert reloaded.episode_target_minutes == 20


def test_episode_target_minutes_respects_max_part() -> None:
    Project(raw_input="x", episode_target_minutes=5)
    Project(raw_input="x", episode_target_minutes=MAX_PART_MINUTES)
    with pytest.raises(ValidationError):
        Project(raw_input="x", episode_target_minutes=4)
    with pytest.raises(ValidationError):
        Project(raw_input="x", episode_target_minutes=MAX_PART_MINUTES + 1)


def test_research_brief_cell_keys_default_empty() -> None:
    brief = ResearchBrief(
        normalized_topic="موضوع",
        topic_type=TopicType.QUESTION,
        central_question="پرسش؟",
    )
    assert brief.cell_keys == []
    payload = brief.model_dump(mode="json")
    payload.pop("cell_keys")
    assert ResearchBrief.model_validate(payload).cell_keys == []
