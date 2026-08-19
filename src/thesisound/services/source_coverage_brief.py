"""Deterministic ResearchBrief for a `source_coverage` project (`10c` P3 Step 1)."""

from __future__ import annotations

from collections.abc import Sequence

from thesisound.concepts import ConceptCell, ConceptCellKind, SourceConceptMap
from thesisound.domain import (
    BRIEF_DURATION_MINUTES_MAX,
    BRIEF_DURATION_MINUTES_MIN,
    Project,
    ResearchBrief,
    TopicType,
)
from thesisound.services.cell_selection import SelectedCell

_KIND_ORDER: tuple[ConceptCellKind, ...] = (
    "definition",
    "distinction",
    "argument",
    "position",
    "objection",
    "response",
    "example",
    "thread",
)
_KIND_FA: dict[str, str] = {
    "definition": "تعریف",
    "distinction": "تمایز",
    "argument": "استدلال",
    "position": "موضع",
    "objection": "اعتراض",
    "response": "پاسخ",
    "example": "مثال",
    "thread": "رشته",
}
_MAX_OBJECTIVES = 5


def build_source_coverage_brief(
    project: Project,
    concept_map: SourceConceptMap,
    in_scope_cells: Sequence[ConceptCell | SelectedCell],
) -> ResearchBrief:
    """Build the derived brief. No model call."""

    cells = [_as_cell(item) for item in in_scope_cells]
    cells = sorted(cells, key=lambda cell: cell.cell_key)
    source_title = _source_title(project)
    chapter_titles = _scoped_chapter_titles(project, concept_map)
    if chapter_titles:
        normalized_topic = f"{source_title} — {'، '.join(chapter_titles)}"
        scope_phrase = " و ".join(chapter_titles)
    else:
        normalized_topic = source_title
        scope_phrase = "کل اثر"
    duration = _clamp_brief_minutes(sum(cell.estimated_minutes for cell in cells))
    return ResearchBrief(
        normalized_topic=normalized_topic,
        topic_type=TopicType.WORK,
        central_question=(
            f"{source_title} در {scope_phrase} چه استدلال می‌کند و چه تمایزهایی می‌گذارد؟"
        ),
        target_duration_minutes=duration,
        modes=["explanatory", "critical"],
        learning_objectives=_learning_objectives(concept_map, cells),
        cell_keys=[cell.cell_key for cell in cells],
        scope_inclusions=list(chapter_titles),
    )


def _as_cell(item: ConceptCell | SelectedCell) -> ConceptCell:
    return item.cell if isinstance(item, SelectedCell) else item


def _source_title(project: Project) -> str:
    source_id = project.scope.source_id if project.scope is not None else None
    if source_id is not None:
        for source in project.sources:
            if source.source_id == source_id:
                return source.title
    if len(project.sources) == 1:
        return project.sources[0].title
    return project.raw_input


def _scoped_chapter_titles(project: Project, concept_map: SourceConceptMap) -> list[str]:
    if project.scope is None or project.scope.chapter_indexes is None:
        return []
    wanted = list(dict.fromkeys(project.scope.chapter_indexes))
    by_index = {chapter.chapter_index: chapter for chapter in concept_map.chapters}
    titles: list[str] = []
    for index in wanted:
        chapter = by_index.get(index)
        titles.append(chapter.title if chapter is not None else f"فصل {index}")
    return titles


def _clamp_brief_minutes(total_minutes: float) -> int:
    return min(
        BRIEF_DURATION_MINUTES_MAX,
        max(BRIEF_DURATION_MINUTES_MIN, round(total_minutes)),
    )


def _learning_objectives(
    concept_map: SourceConceptMap,
    cells: Sequence[ConceptCell],
) -> list[str]:
    if not cells:
        return []
    chapters_by_index = {chapter.chapter_index: chapter for chapter in concept_map.chapters}
    chapter_order = list(dict.fromkeys(cell.chapter_index for cell in cells))
    grouped: dict[tuple[int, str], list[str]] = {}
    for cell in cells:
        grouped.setdefault((cell.chapter_index, cell.kind), []).append(cell.label_fa)
    objectives: list[str] = []
    for chapter_index in chapter_order:
        chapter = chapters_by_index.get(chapter_index)
        title = chapter.title if chapter is not None else f"فصل {chapter_index}"
        for kind in _KIND_ORDER:
            labels = grouped.get((chapter_index, kind))
            if not labels:
                continue
            kind_fa = _KIND_FA[kind]
            objectives.append(f"{title} — {kind_fa}: {'، '.join(labels)}")
            if len(objectives) >= _MAX_OBJECTIVES:
                return objectives
    return objectives
