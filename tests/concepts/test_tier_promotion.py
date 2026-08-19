from thesisound.concepts import ConceptCell, ConceptEdge
from thesisound.domain import DocumentMapSection
from thesisound.services.concept_map_builder import promote_tiers


def _section(
    section_id: str,
    *block_ids: str,
    required: bool = False,
) -> DocumentMapSection:
    return DocumentMapSection(
        section_id=section_id,
        source_block_ids=list(block_ids) or ["b0001"],
        title=section_id,
        function="argument",
        required_for_global_understanding=required,
    )


def _cell(
    cell_key: str,
    *,
    tier: int = 3,
    section_ids: list[str] | None = None,
) -> ConceptCell:
    number = int(cell_key.split("-c")[1])
    return ConceptCell(
        cell_key=cell_key,
        label_fa=f"مفهوم {number}",
        kind="definition",
        tier=tier,  # type: ignore[arg-type]
        chapter_index=int(cell_key[2:4]),
        section_ids=section_ids or [f"s{number:03d}"],
        block_ids=[f"b{number:04d}"],
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=5.0,
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


def test_required_section_raises_tier_3_to_tier_2() -> None:
    cells = [_cell("ch00-c001", tier=3, section_ids=["s001"])]
    promoted = promote_tiers(cells, [], [_section("s001", "b0001", required=True)])
    assert promoted[0].tier == 2
    assert promoted[0].tier_promoted is True


def test_required_section_does_not_demote_tier_1() -> None:
    cells = [_cell("ch00-c001", tier=1, section_ids=["s001"])]
    promoted = promote_tiers(cells, [], [_section("s001", "b0001", required=True)])
    assert promoted[0].tier == 1
    assert promoted[0].tier_promoted is False


def test_prerequisite_outdegree_2_raises_tier_3_to_tier_2() -> None:
    cells = [
        _cell("ch00-c001", tier=3),
        _cell("ch00-c002"),
        _cell("ch00-c003"),
    ]
    edges = [_prereq("ch00-c001", "ch00-c002"), _prereq("ch00-c001", "ch00-c003")]
    promoted = promote_tiers(cells, edges, [_section("s001"), _section("s002"), _section("s003")])
    by_key = {cell.cell_key: cell for cell in promoted}
    assert by_key["ch00-c001"].tier == 2
    assert by_key["ch00-c001"].tier_promoted is True
    assert by_key["ch00-c002"].tier == 3
    assert by_key["ch00-c002"].tier_promoted is False


def test_prerequisite_outdegree_4_raises_to_tier_1() -> None:
    cells = [_cell(f"ch00-c{n:03d}", tier=3 if n == 1 else 2) for n in range(1, 6)]
    edges = [_prereq("ch00-c001", f"ch00-c{n:03d}") for n in range(2, 6)]
    promoted = promote_tiers(cells, edges, [_section(f"s{n:03d}") for n in range(1, 6)])
    hub = next(cell for cell in promoted if cell.cell_key == "ch00-c001")
    assert hub.tier == 1
    assert hub.tier_promoted is True


def test_related_edges_do_not_promote() -> None:
    cells = [_cell("ch00-c001", tier=3), _cell("ch00-c002"), _cell("ch00-c003")]
    edges = [
        ConceptEdge(
            source_key="ch00-c001",
            target_key="ch00-c002",
            type="related",
            weight=0.5,
            confidence=0.8,
            rationale_fa="خانوادهٔ یکسان.",
        ),
        ConceptEdge(
            source_key="ch00-c001",
            target_key="ch00-c003",
            type="related",
            weight=0.5,
            confidence=0.8,
            rationale_fa="خانوادهٔ یکسان.",
        ),
    ]
    promoted = promote_tiers(cells, edges, [_section("s001"), _section("s002"), _section("s003")])
    assert promoted[0].tier == 3
    assert promoted[0].tier_promoted is False


def test_owner_override_wins_over_promotion() -> None:
    cells = [_cell("ch00-c001", tier=3, section_ids=["s001"])]
    promoted = promote_tiers(
        cells,
        [],
        [_section("s001", "b0001", required=True)],
        tier_overrides={"ch00-c001": 3},
    )
    assert promoted[0].tier == 3
    assert promoted[0].tier_promoted is False
