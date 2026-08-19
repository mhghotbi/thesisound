from thesisound.concepts import ConceptCell
from thesisound.services.concept_map_builder import normalise_cells


def _cell(
    cell_key: str,
    label_fa: str,
    *,
    chapter_index: int = 0,
    section_ids: list[str] | None = None,
    block_ids: list[str] | None = None,
    label_source: str | None = None,
) -> ConceptCell:
    number = int(cell_key.split("-c")[1])
    return ConceptCell(
        cell_key=cell_key,
        label_fa=label_fa,
        label_source=label_source,
        kind="definition",
        tier=2,
        chapter_index=chapter_index,
        section_ids=section_ids or [f"s{number:03d}"],
        block_ids=block_ids or [f"b{number:04d}"],
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=5.0,
    )


def test_merges_near_duplicates_keeping_earliest_key() -> None:
    cells = [
        _cell("ch00-c001", "تعریف ارزش مبادله", block_ids=["b0001"], section_ids=["s001"]),
        _cell("ch00-c002", "تعریف ارزش مبادله", block_ids=["b0002"], section_ids=["s002"]),
        _cell("ch00-c003", "موضع نویسنده درباره دولت", block_ids=["b0003"], section_ids=["s003"]),
    ]
    result = normalise_cells(cells)
    assert [cell.cell_key for cell in result.cells] == ["ch00-c001", "ch00-c003"]
    kept = result.cells[0]
    assert set(kept.block_ids) == {"b0001", "b0002"}
    assert set(kept.section_ids) == {"s001", "s002"}
    assert any("ch00-c002" in warning and "ch00-c001" in warning for warning in result.warnings)
    assert result.related_candidates == ()


def test_does_not_merge_distinct_labels() -> None:
    cells = [
        _cell("ch00-c001", "تمایز کنش و ساخت"),
        _cell("ch00-c002", "اعتراض به نظریه دولت"),
    ]
    result = normalise_cells(cells)
    assert [cell.cell_key for cell in result.cells] == ["ch00-c001", "ch00-c002"]
    assert result.warnings == ()


def test_same_label_across_chapters_is_related_not_merged() -> None:
    cells = [
        _cell("ch00-c001", "تعریف ارزش", chapter_index=0),
        _cell("ch01-c001", "تعریف ارزش", chapter_index=1),
    ]
    result = normalise_cells(cells)
    assert [cell.cell_key for cell in result.cells] == ["ch00-c001", "ch01-c001"]
    assert result.related_candidates == (("ch00-c001", "ch01-c001"),)
    assert any("Not merged across chapters" in warning for warning in result.warnings)


def test_prior_cells_register_cross_chapter_matches() -> None:
    prior = [_cell("ch00-c001", "تمایز امر عمومی و خصوصی", chapter_index=0)]
    current = [_cell("ch02-c001", "تمایز امر عمومی و خصوصی", chapter_index=2)]
    result = normalise_cells(current, prior_cells=prior)
    assert [cell.cell_key for cell in result.cells] == ["ch02-c001"]
    assert result.related_candidates == (("ch00-c001", "ch02-c001"),)


def test_matching_source_language_term_is_a_related_candidate() -> None:
    cells = [
        _cell(
            "ch00-c001",
            "مفهوم کنش",
            chapter_index=0,
            label_source="praxis",
        ),
        _cell(
            "ch01-c001",
            "کنش در فصل بعد",
            chapter_index=1,
            label_source="Praxis",
        ),
    ]
    result = normalise_cells(cells)
    assert result.related_candidates == (("ch00-c001", "ch01-c001"),)
