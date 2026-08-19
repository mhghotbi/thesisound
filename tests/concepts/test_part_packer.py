from collections.abc import Sequence

from thesisound.concepts import ConceptCell, ConceptEdge, LessonPart
from thesisound.services.part_packer import FILL_MAX, FILL_MIN, pack_parts


def _cell(
    cell_key: str,
    *,
    minutes: float = 4.0,
    chapter_index: int | None = None,
    section_ids: list[str] | None = None,
    label: str | None = None,
) -> ConceptCell:
    number = int(cell_key.split("-c")[1])
    chapter = int(cell_key[2:4]) if chapter_index is None else chapter_index
    return ConceptCell(
        cell_key=cell_key,
        label_fa=label or f"مفهوم {number}",
        kind="definition",
        tier=1,
        chapter_index=chapter,
        section_ids=section_ids or [f"s{chapter:02d}-{number:03d}"],
        block_ids=[f"b{number:04d}"],
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=minutes,
    )


def _edge(
    source_key: str,
    target_key: str,
    edge_type: str = "related",
) -> ConceptEdge:
    return ConceptEdge(
        source_key=source_key,
        target_key=target_key,
        type=edge_type,  # type: ignore[arg-type]
        weight=0.9,
        confidence=0.9,
        rationale_fa="رابطه در منبع آمده است.",
    )


def _minutes(cells: Sequence[ConceptCell]) -> dict[str, float]:
    return {cell.cell_key: cell.estimated_minutes for cell in cells}


def _pack(
    cells: Sequence[ConceptCell],
    *,
    target: float = 10.0,
    edges: Sequence[ConceptEdge] | None = None,
    minutes: dict[str, float] | None = None,
) -> list[LessonPart]:
    return pack_parts(cells, edges or [], target, minutes or _minutes(cells))


def _non_last_minutes(parts: Sequence[LessonPart]) -> list[float]:
    return [part.estimated_minutes for part in parts[:-1]]


def test_fill_rule_keeps_non_last_parts_in_window() -> None:
    cells = [
        _cell(f"ch00-c{index:03d}", minutes=4.0, section_ids=["s000"]) for index in range(1, 9)
    ]
    parts = _pack(cells, target=10.0)
    assert parts
    for part in parts[:-1]:
        assert FILL_MIN * 10.0 <= part.estimated_minutes <= FILL_MAX * 10.0
        assert "short_last_part" not in part.flags
    assert all(part.estimated_minutes <= FILL_MAX * 10.0 for part in parts)


def test_non_last_part_never_shorter_than_fill_min() -> None:
    cells = [
        _cell(f"ch00-c{index:03d}", minutes=4.0, section_ids=["s000"]) for index in range(1, 11)
    ]
    parts = _pack(cells, target=10.0)
    assert len(parts) >= 2
    assert all(minutes >= FILL_MIN * 10.0 for minutes in _non_last_minutes(parts))


def test_fill_rule_guard_does_not_leave_a_short_non_last_part() -> None:
    cells = [
        _cell("ch00-c001", minutes=6.0, section_ids=["s000"]),
        _cell("ch00-c002", minutes=8.0, section_ids=["s000"]),
    ]
    parts = _pack(cells, target=10.0)
    assert [part.cell_keys for part in parts] == [["ch00-c001", "ch00-c002"]]
    assert parts[0].estimated_minutes == 14.0
    assert "oversize_cell" in parts[0].flags
    assert "short_last_part" not in parts[0].flags


def test_boundary_prefers_chapter_change_once_floor_is_met() -> None:
    cells = [
        _cell("ch00-c001", minutes=8.0, chapter_index=0, section_ids=["s000"]),
        _cell("ch01-c001", minutes=2.0, chapter_index=1, section_ids=["s100"]),
    ]
    parts = _pack(
        cells,
        target=10.0,
        edges=[_edge("ch00-c001", "ch01-c001", "related")],
    )
    assert [part.cell_keys for part in parts] == [["ch00-c001"], ["ch01-c001"]]
    assert parts[0].estimated_minutes == 8.0
    assert "short_last_part" in parts[1].flags


def test_boundary_prefers_section_change_once_floor_is_met() -> None:
    cells = [
        _cell("ch00-c001", minutes=8.0, section_ids=["s-a"]),
        _cell("ch00-c002", minutes=2.0, section_ids=["s-b"]),
    ]
    parts = _pack(cells, target=10.0)
    assert [part.cell_keys for part in parts] == [["ch00-c001"], ["ch00-c002"]]


def test_last_part_may_be_shorter_than_fill_min() -> None:
    cells = [
        _cell("ch00-c001", minutes=4.0, section_ids=["s000"]),
        _cell("ch00-c002", minutes=4.0, section_ids=["s000"]),
        _cell("ch00-c003", minutes=3.0, section_ids=["s000"]),
    ]
    parts = _pack(cells, target=10.0)
    assert [part.cell_keys for part in parts] == [["ch00-c001", "ch00-c002"], ["ch00-c003"]]
    assert parts[0].estimated_minutes == 8.0
    assert parts[1].estimated_minutes == 3.0
    assert parts[1].flags == ["short_last_part"]


def test_readiness_places_ordering_prerequisite_before_dependent() -> None:
    cells = [
        _cell("ch00-c001", minutes=4.0, section_ids=["s000"]),
        _cell("ch00-c002", minutes=4.0, section_ids=["s000"]),
    ]
    parts = _pack(cells, edges=[_edge("ch00-c002", "ch00-c001", "prerequisite")], target=10.0)
    assert parts[0].cell_keys == ["ch00-c002", "ch00-c001"]
    assert parts[0].graph_backed is True


def test_depends_on_is_an_ordering_prerequisite() -> None:
    cells = [
        _cell("ch00-c001", minutes=4.0, section_ids=["s000"]),
        _cell("ch00-c002", minutes=4.0, section_ids=["s000"]),
    ]
    parts = _pack(cells, edges=[_edge("ch00-c002", "ch00-c001", "depends_on")], target=10.0)
    assert parts[0].cell_keys == ["ch00-c002", "ch00-c001"]


def test_out_of_scope_prerequisite_does_not_block_readiness() -> None:
    cells = [_cell("ch00-c002", minutes=4.0, section_ids=["s000"])]
    parts = _pack(cells, edges=[_edge("ch00-c001", "ch00-c002", "prerequisite")], target=10.0)
    assert [part.cell_keys for part in parts] == [["ch00-c002"]]


def test_oversize_cell_is_placed_alone_and_flagged() -> None:
    cells = [_cell("ch00-c001", minutes=12.0, section_ids=["s000"])]
    parts = _pack(cells, target=10.0)
    assert [part.cell_keys for part in parts] == [["ch00-c001"]]
    assert parts[0].flags == ["oversize_cell"]
    assert parts[0].estimated_minutes == 12.0


def test_each_oversize_cell_becomes_its_own_part() -> None:
    cells = [
        _cell("ch00-c001", minutes=12.0, section_ids=["s000"]),
        _cell("ch00-c002", minutes=13.0, section_ids=["s000"]),
    ]
    parts = _pack(cells, target=10.0)
    assert [part.cell_keys for part in parts] == [["ch00-c001"], ["ch00-c002"]]
    assert all(part.flags == ["oversize_cell"] for part in parts)


def test_graph_backed_when_part_has_an_internal_edge() -> None:
    cells = [
        _cell("ch00-c001", minutes=4.0, section_ids=["s000"]),
        _cell("ch00-c002", minutes=4.0, section_ids=["s000"]),
    ]
    parts = _pack(cells, edges=[_edge("ch00-c001", "ch00-c002", "related")], target=10.0)
    assert len(parts) == 1
    assert parts[0].graph_backed is True


def test_graph_backed_false_for_book_order_without_edges() -> None:
    cells = [
        _cell("ch00-c001", minutes=4.0, section_ids=["s000"]),
        _cell("ch00-c002", minutes=4.0, section_ids=["s000"]),
        _cell("ch00-c003", minutes=4.0, section_ids=["s000"]),
    ]
    parts = _pack(cells, target=10.0)
    assert all(part.graph_backed is False for part in parts)


def test_pack_twice_is_deterministic_even_when_input_is_shuffled() -> None:
    cells = [
        _cell("ch01-c002", minutes=4.0, section_ids=["s-b"]),
        _cell("ch00-c001", minutes=4.0, section_ids=["s-a"]),
        _cell("ch00-c003", minutes=4.0, section_ids=["s-a"]),
        _cell("ch01-c001", minutes=4.0, section_ids=["s-b"]),
    ]
    edges = [
        _edge("ch00-c003", "ch01-c001", "related"),
        _edge("ch00-c001", "ch00-c003", "prerequisite"),
    ]
    first = pack_parts(list(reversed(cells)), list(reversed(edges)), 10.0, _minutes(cells))
    second = pack_parts(cells, edges, 10.0, _minutes(cells))
    assert first == second
    assert pack_parts(cells, edges, 10.0, _minutes(cells)) == first


def test_empty_input_returns_no_parts() -> None:
    assert pack_parts([], [], 20.0, {}) == []


def test_minutes_by_cell_overrides_estimated_minutes() -> None:
    cells = [
        _cell("ch00-c001", minutes=4.0, section_ids=["s000"]),
        _cell("ch00-c002", minutes=4.0, section_ids=["s000"]),
    ]
    parts = _pack(cells, target=10.0, minutes={"ch00-c001": 8.0, "ch00-c002": 2.0})
    assert [part.cell_keys for part in parts] == [["ch00-c001", "ch00-c002"]]
    assert parts[0].estimated_minutes == 10.0
