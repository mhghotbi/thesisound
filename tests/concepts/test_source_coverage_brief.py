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
    LessonIntent,
    Project,
    ProjectScope,
    SourceCandidate,
    SourceRole,
    TopicType,
)
from thesisound.services.cell_selection import select_cells
from thesisound.services.source_coverage_brief import build_source_coverage_brief


def _chapter(index: int, title: str) -> SourceChapter:
    return SourceChapter(
        chapter_index=index,
        title=title,
        heading_path=[title],
        block_ids=[f"b{index:04d}a", f"b{index:04d}b"],
        estimated_minutes=12.0,
        detected_from="heading",
        detection_agreement="agreed",
    )


def _cell(
    cell_key: str,
    *,
    kind: str,
    label: str,
    minutes: float = 4.0,
    tier: int = 1,
) -> ConceptCell:
    number = int(cell_key.split("-c")[1])
    return ConceptCell(
        cell_key=cell_key,
        label_fa=label,
        kind=kind,  # type: ignore[arg-type]
        tier=tier,  # type: ignore[arg-type]
        chapter_index=int(cell_key[2:4]),
        section_ids=[f"s{number:03d}"],
        block_ids=[f"b{number:04d}"],
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=minutes,
    )


def _map(cells: list[ConceptCell], chapters: list[SourceChapter]) -> SourceConceptMap:
    return SourceConceptMap(
        source_fingerprint="a" * 64,
        builder_version=1,
        chapters=chapters,
        cells=cells,
        edges=[],
        statistics=ConceptMapStatistics(cell_count=len(cells)),
        created_at=datetime.now(UTC),
    )


def _project(source_id, *, chapter_indexes=None) -> Project:
    return Project(
        raw_input="عنوان خام",
        lesson_intent=LessonIntent.SOURCE_COVERAGE,
        compression=Compression.STANDARD,
        scope=ProjectScope(source_id=source_id, chapter_indexes=chapter_indexes),
        sources=[
            SourceCandidate(
                source_id=source_id,
                title="وضع بشر",
                role=SourceRole.PRIMARY,
                source_type="book",
                origin="upload",
            )
        ],
    )


def test_derived_brief_uses_source_title_and_persian_question() -> None:
    source_id = uuid4()
    cells = [
        _cell("ch00-c001", kind="definition", label="کنش"),
        _cell("ch00-c002", kind="distinction", label="کار و عمل"),
    ]
    concept_map = _map(cells, [_chapter(0, "فصل یکم")])
    brief = build_source_coverage_brief(_project(source_id), concept_map, cells)
    assert brief.topic_type == TopicType.WORK
    assert brief.normalized_topic == "وضع بشر"
    assert brief.central_question == ("وضع بشر در کل اثر چه استدلال می‌کند و چه تمایزهایی می‌گذارد؟")
    assert brief.modes == ["explanatory", "critical"]
    assert brief.cell_keys == ["ch00-c001", "ch00-c002"]
    assert brief.target_duration_minutes == 8
    assert brief.learning_objectives == [
        "فصل یکم — تعریف: کنش",
        "فصل یکم — تمایز: کار و عمل",
    ]


def test_scoped_chapters_appear_in_topic_and_question() -> None:
    source_id = uuid4()
    cells = [_cell("ch01-c001", kind="argument", label="آزادی")]
    concept_map = _map(
        cells + [_cell("ch00-c001", kind="definition", label="قدرت")],
        [_chapter(0, "فصل صفر"), _chapter(1, "فصل یکم")],
    )
    project = _project(source_id, chapter_indexes=[1])
    in_scope, _omitted = select_cells(concept_map, project.scope, project.compression)
    brief = build_source_coverage_brief(project, concept_map, in_scope)
    assert brief.normalized_topic == "وضع بشر — فصل یکم"
    assert "فصل یکم" in brief.central_question
    assert "کل اثر" not in brief.central_question
    assert brief.cell_keys == ["ch01-c001"]
    assert brief.scope_inclusions == ["فصل یکم"]


def test_duration_clamps_to_brief_schema() -> None:
    source_id = uuid4()
    short = [_cell("ch00-c001", kind="definition", label="الف", minutes=1.2)]
    long_cells = [
        _cell(f"ch00-c{i:03d}", kind="argument", label=f"مفهوم {i}", minutes=30.0)
        for i in range(1, 8)
    ]
    concept_map = _map(long_cells, [_chapter(0, "فصل")])
    short_brief = build_source_coverage_brief(
        _project(source_id), _map(short, [_chapter(0, "فصل")]), short
    )
    long_brief = build_source_coverage_brief(_project(source_id), concept_map, long_cells)
    assert short_brief.target_duration_minutes == 5
    assert long_brief.target_duration_minutes == 120


def test_learning_objectives_cap_at_five_grouped_by_chapter_then_kind() -> None:
    source_id = uuid4()
    cells = [
        _cell("ch00-c001", kind="definition", label="د۱"),
        _cell("ch00-c002", kind="distinction", label="ت۱"),
        _cell("ch00-c003", kind="argument", label="ا۱"),
        _cell("ch01-c001", kind="position", label="م۱"),
        _cell("ch01-c002", kind="objection", label="ع۱"),
        _cell("ch01-c003", kind="example", label="مثال نباید در پنج‌تای اول باشد"),
    ]
    concept_map = _map(cells, [_chapter(0, "فصل الف"), _chapter(1, "فصل ب")])
    brief = build_source_coverage_brief(_project(source_id), concept_map, cells)
    assert len(brief.learning_objectives) == 5
    assert brief.learning_objectives[0].startswith("فصل الف — تعریف")
    assert brief.learning_objectives[3].startswith("فصل ب — موضع")
    assert all("نباید" not in item for item in brief.learning_objectives)
