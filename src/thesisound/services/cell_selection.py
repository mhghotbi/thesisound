"""In-scope cell selection: tier filter plus prerequisite closure (`10c` P3 Step 2)."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from thesisound.concepts import ConceptCell, ConceptEdge, SourceConceptMap
from thesisound.domain import Compression, ProjectScope

TIER_IN_SCOPE_REASON = "tier"
PREREQUISITE_CLOSURE_HOP_CAP = 25

_TIERS_BY_COMPRESSION: dict[Compression, frozenset[int]] = {
    Compression.CONCISE: frozenset({1}),
    Compression.STANDARD: frozenset({1, 2}),
    Compression.FULL: frozenset({1, 2, 3}),
}


@dataclass(frozen=True)
class SelectedCell:
    """An in-scope cell plus why it survived the tier filter / closure."""

    cell: ConceptCell
    in_scope_reason: str


def closure_reason(cell_key: str) -> str:
    return f"prerequisite_of:{cell_key}"


def select_cells(
    concept_map: SourceConceptMap,
    scope: ProjectScope | None,
    compression: Compression | str,
) -> tuple[list[SelectedCell], list[ConceptCell]]:
    """Return ``(in_scope, omitted_by_compression)`` for a compressed lesson.

    The first argument is the effective map (cache ⊕ overlay). Closure walks
    ``prerequisite`` edges backwards (BFS, cap 25 hops, cycle-safe) and can
    pull cells from outside the chapter scope when a selected cell depends on
    them. Out-of-tier cells that closure does not pull, and that sit in the
    chapter scope, are ``omitted_by_compression``.
    """

    allowed_tiers = _TIERS_BY_COMPRESSION[Compression(compression)]
    cells_by_key = {cell.cell_key: cell for cell in concept_map.cells}
    chapter_scope = _chapter_scope(scope)
    scoped = [
        cell
        for cell in concept_map.cells
        if chapter_scope is None or cell.chapter_index in chapter_scope
    ]
    selected = [cell for cell in scoped if cell.tier in allowed_tiers]
    reasons = {cell.cell_key: TIER_IN_SCOPE_REASON for cell in selected}
    _apply_prerequisite_closure(
        selected_keys=list(reasons),
        reasons=reasons,
        cells_by_key=cells_by_key,
        edges=concept_map.edges,
    )
    in_scope_keys = set(reasons)
    in_scope = [
        SelectedCell(cell=cells_by_key[key], in_scope_reason=reasons[key])
        for key in _book_order(in_scope_keys)
        if key in cells_by_key
    ]
    omitted = [cell for cell in _book_ordered_cells(scoped) if cell.cell_key not in in_scope_keys]
    return in_scope, omitted


def _chapter_scope(scope: ProjectScope | None) -> frozenset[int] | None:
    if scope is None or scope.chapter_indexes is None:
        return None
    return frozenset(scope.chapter_indexes)


def _apply_prerequisite_closure(
    *,
    selected_keys: Sequence[str],
    reasons: dict[str, str],
    cells_by_key: dict[str, ConceptCell],
    edges: Sequence[ConceptEdge],
) -> None:
    prerequisites: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.type != "prerequisite":
            continue
        prerequisites[edge.target_key].append(edge.source_key)
    for key in prerequisites:
        prerequisites[key] = sorted(set(prerequisites[key]))

    visited = set(selected_keys)
    queue: deque[tuple[str, int, str]] = deque()
    for origin in _book_order(selected_keys):
        for source_key in prerequisites.get(origin, []):
            queue.append((source_key, 1, origin))

    while queue:
        key, hops, origin = queue.popleft()
        if hops > PREREQUISITE_CLOSURE_HOP_CAP:
            continue
        if key in visited or key not in cells_by_key:
            continue
        visited.add(key)
        reasons[key] = closure_reason(origin)
        for source_key in prerequisites.get(key, []):
            queue.append((source_key, hops + 1, origin))


def _book_order(keys: Iterable[str]) -> list[str]:
    return sorted(keys)


def _book_ordered_cells(cells: Sequence[ConceptCell]) -> list[ConceptCell]:
    return sorted(cells, key=lambda cell: cell.cell_key)
