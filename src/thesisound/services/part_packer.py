"""Deterministic packing of in-scope cells into `LessonPart`s (`10c` P3 Step 6)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import median

from thesisound.concepts import ConceptCell, ConceptEdge, ConceptEdgeType, LessonPart

# Tuning copied from KMS/AQT session-planner (server-mono
# `session-planner.service.ts`). Recalibrate FILL_* and the pull/push weights
# from real `source_coverage` runs in P6 — not from intuition. Missing
# `minutes_by_cell` entries use the cell's `estimated_minutes`; if that is also
# unusable, the median of known minutes (KMS rule). The packer never needs the
# graph to make progress: book order is the prior, `graph_backed` is an honesty
# flag.
SAME_PART_PULL: dict[ConceptEdgeType, float] = {
    "related": 1.0,
    "contrasts": 1.0,
    "objects_to": 1.0,
    "responds_to": 1.0,
    "instance_of": 0.8,
    "prerequisite": 0.35,
    "depends_on": 0.35,
}
NEXT_PART_PUSH: dict[ConceptEdgeType, float] = {"extends": -0.5}
SIBLING_PULL = 0.7
ADJACENCY_PULL = 0.5
ADJACENCY_WINDOW = 3
FILL_MIN = 0.8
FILL_MAX = 1.0
BOUNDARY_BONUS_CHAPTER = 0.3
BOUNDARY_BONUS_SECTION = 0.15

_ORDERING_EDGE_TYPES = frozenset({"prerequisite", "depends_on"})
_OVERSIZE_FLAG = "oversize_cell"
_SHORT_LAST_FLAG = "short_last_part"


def pack_parts(
    cells: Sequence[ConceptCell],
    edges: Sequence[ConceptEdge],
    target_minutes: float,
    minutes_by_cell: Mapping[str, float],
) -> list[LessonPart]:
    """Pack in-scope cells into parts of about ``target_minutes``.

    Each non-last part is filled to ``[FILL_MIN, FILL_MAX] × T``, preferring a
    chapter/section boundary once the floor is met. Only the last part may be
    shorter. Readiness follows ``prerequisite`` / ``depends_on``; book order is
    the tie-break and the fallback when the graph cannot sequence.
    """

    if target_minutes <= 0:
        raise ValueError("target_minutes must be > 0.")
    if not cells:
        return []

    ordered = sorted(cells, key=lambda cell: cell.cell_key)
    in_scope = {cell.cell_key for cell in ordered}
    book_index = {cell.cell_key: index for index, cell in enumerate(ordered)}
    minutes = _resolve_minutes(ordered, minutes_by_cell)
    ordering_prereqs = _ordering_prereqs(edges)
    affinity_edges = _affinity_index(edges, in_scope)

    placed: set[str] = set()
    packed: list[list[ConceptCell]] = []
    part_flags: list[list[str]] = []
    part_graph_backed: list[bool] = []

    while len(placed) < len(ordered):
        part: list[ConceptCell] = []
        part_minutes = 0.0
        flags: list[str] = []
        skipped_for_readiness = False
        while True:
            remaining = [cell for cell in ordered if cell.cell_key not in placed]
            if not remaining:
                break
            ready = _ready_cells(ordered, placed, in_scope, ordering_prereqs)
            if not ready:
                ready = remaining
            fitting = [
                cell
                for cell in ready
                if part_minutes + minutes[cell.cell_key] <= FILL_MAX * target_minutes
            ]
            if not fitting:
                if not part or part_minutes < FILL_MIN * target_minutes:
                    chosen = _min_minutes_cell(ready, minutes, book_index)
                    skipped_for_readiness = skipped_for_readiness or _skipped_for_readiness(
                        chosen, ready, placed, book_index
                    )
                    part.append(chosen)
                    part_minutes += minutes[chosen.cell_key]
                    flags.append(_OVERSIZE_FLAG)
                    placed.add(chosen.cell_key)
                break
            best = _best_fitting(part, fitting, affinity_edges, book_index)
            if part and part_minutes >= FILL_MIN * target_minutes and _crosses_boundary(part, best):
                break
            skipped_for_readiness = skipped_for_readiness or _skipped_for_readiness(
                best, ready, placed, book_index
            )
            part.append(best)
            part_minutes += minutes[best.cell_key]
            placed.add(best.cell_key)
        packed.append(part)
        part_flags.append(flags)
        part_graph_backed.append(skipped_for_readiness or _has_internal_edge(part, affinity_edges))

    parts: list[LessonPart] = []
    for index, part in enumerate(packed, start=1):
        flags = list(part_flags[index - 1])
        estimated = sum(minutes[cell.cell_key] for cell in part)
        if index == len(packed) and estimated < FILL_MIN * target_minutes:
            flags.append(_SHORT_LAST_FLAG)
        parts.append(
            LessonPart(
                part_index=index,
                title_fa=part[0].label_fa,
                cell_keys=[cell.cell_key for cell in part],
                claim_ids=[],
                estimated_minutes=estimated,
                graph_backed=part_graph_backed[index - 1],
                flags=flags,
            )
        )
    return parts


def _resolve_minutes(
    cells: Sequence[ConceptCell],
    minutes_by_cell: Mapping[str, float],
) -> dict[str, float]:
    known = [minutes_by_cell[cell.cell_key] for cell in cells if cell.cell_key in minutes_by_cell]
    fallback = median(known) if known else 0.0
    resolved: dict[str, float] = {}
    for cell in cells:
        if cell.cell_key in minutes_by_cell:
            resolved[cell.cell_key] = minutes_by_cell[cell.cell_key]
        elif cell.estimated_minutes > 0:
            resolved[cell.cell_key] = cell.estimated_minutes
        else:
            resolved[cell.cell_key] = fallback
    return resolved


def _ordering_prereqs(edges: Sequence[ConceptEdge]) -> dict[str, frozenset[str]]:
    prereqs: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge.type not in _ORDERING_EDGE_TYPES:
            continue
        prereqs[edge.target_key].add(edge.source_key)
    return {key: frozenset(values) for key, values in prereqs.items()}


def _affinity_index(
    edges: Sequence[ConceptEdge],
    in_scope: set[str],
) -> dict[frozenset[str], list[ConceptEdge]]:
    index: dict[frozenset[str], list[ConceptEdge]] = defaultdict(list)
    for edge in edges:
        if edge.source_key not in in_scope or edge.target_key not in in_scope:
            continue
        if edge.source_key == edge.target_key:
            continue
        index[frozenset({edge.source_key, edge.target_key})].append(edge)
    return index


def _ready_cells(
    ordered: Sequence[ConceptCell],
    placed: set[str],
    in_scope: set[str],
    ordering_prereqs: Mapping[str, frozenset[str]],
) -> list[ConceptCell]:
    ready: list[ConceptCell] = []
    for cell in ordered:
        if cell.cell_key in placed:
            continue
        prereqs = ordering_prereqs.get(cell.cell_key, frozenset())
        if all(key in placed or key not in in_scope for key in prereqs):
            ready.append(cell)
    return ready


def _min_minutes_cell(
    ready: Sequence[ConceptCell],
    minutes: Mapping[str, float],
    book_index: Mapping[str, int],
) -> ConceptCell:
    return min(ready, key=lambda cell: (minutes[cell.cell_key], book_index[cell.cell_key]))


def _best_fitting(
    part: Sequence[ConceptCell],
    fitting: Sequence[ConceptCell],
    affinity_edges: Mapping[frozenset[str], Sequence[ConceptEdge]],
    book_index: Mapping[str, int],
) -> ConceptCell:
    best: ConceptCell | None = None
    best_score = float("-inf")
    for cell in fitting:
        score = _score(part, cell, affinity_edges, book_index)
        if best is None or score > best_score:
            best = cell
            best_score = score
    assert best is not None
    return best


def _score(
    part: Sequence[ConceptCell],
    candidate: ConceptCell,
    affinity_edges: Mapping[frozenset[str], Sequence[ConceptEdge]],
    book_index: Mapping[str, int],
) -> float:
    if not part:
        return 0.0
    affinity = sum(_affinity(placed, candidate, affinity_edges) for placed in part)
    return affinity + _adjacency(part, candidate, book_index) + _sibling(part, candidate)


def _affinity(
    placed: ConceptCell,
    candidate: ConceptCell,
    affinity_edges: Mapping[frozenset[str], Sequence[ConceptEdge]],
) -> float:
    score = 0.0
    for edge in affinity_edges.get(frozenset({placed.cell_key, candidate.cell_key}), ()):
        score += SAME_PART_PULL.get(edge.type, 0.0)
        score += NEXT_PART_PUSH.get(edge.type, 0.0)
    return score


def _adjacency(
    part: Sequence[ConceptCell],
    candidate: ConceptCell,
    book_index: Mapping[str, int],
) -> float:
    candidate_index = book_index[candidate.cell_key]
    for cell in part:
        if abs(candidate_index - book_index[cell.cell_key]) <= ADJACENCY_WINDOW:
            return ADJACENCY_PULL
    return 0.0


def _sibling(part: Sequence[ConceptCell], candidate: ConceptCell) -> float:
    candidate_sections = set(candidate.section_ids)
    for cell in part:
        if candidate_sections.intersection(cell.section_ids):
            return SIBLING_PULL
    return 0.0


def _crosses_boundary(part: Sequence[ConceptCell], candidate: ConceptCell) -> bool:
    return _boundary_strength(part, candidate) > 0


def _boundary_strength(part: Sequence[ConceptCell], candidate: ConceptCell) -> float:
    last = part[-1]
    if candidate.chapter_index != last.chapter_index:
        return BOUNDARY_BONUS_CHAPTER
    if set(candidate.section_ids).isdisjoint(last.section_ids):
        return BOUNDARY_BONUS_SECTION
    return 0.0


def _skipped_for_readiness(
    chosen: ConceptCell,
    ready: Sequence[ConceptCell],
    placed: set[str],
    book_index: Mapping[str, int],
) -> bool:
    ready_keys = {cell.cell_key for cell in ready}
    chosen_index = book_index[chosen.cell_key]
    for key, index in book_index.items():
        if key in placed or key == chosen.cell_key:
            continue
        if index < chosen_index and key not in ready_keys:
            return True
    return False


def _has_internal_edge(
    part: Sequence[ConceptCell],
    affinity_edges: Mapping[frozenset[str], Sequence[ConceptEdge]],
) -> bool:
    keys = [cell.cell_key for cell in part]
    return any(
        affinity_edges.get(frozenset({keys[left], keys[right]}))
        for left in range(len(keys))
        for right in range(left + 1, len(keys))
    )
