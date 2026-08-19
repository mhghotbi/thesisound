"""Concept-map pipeline: Pass 0 (chapters), Pass 2–5 (cells, edges, stats).

Pass 0 (`detect_chapters`) is deterministic. Pass 2 calls `concept_cells/1.0.0`
through `ModelRunner` with `_validate_cells_draft`; Pass 2.5 (`normalise_cells`)
is pure. Pass 3 calls `concept_cells_consolidate/1.0.0` only when a chapter's
cell count exceeds its budget; applying keep/merge/remove is deterministic.
Pass 4 calls `concept_edges/1.0.0` per chapter and per chapter pair within
window 2; `_validate_edges` repairs cycles on the last attempt. Pass 4.5
(`promote_tiers`) and Pass 5 (`compute_statistics`) are pure.
`ConceptMapBuilder.build` loops chapters with a project checkpoint, shared
cache, and per-chapter sub-entries.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from thesisound.concepts import (
    ConceptCell,
    ConceptCellDraft,
    ConceptCellsConsolidateDraft,
    ConceptCellsDraft,
    ConceptCellTier,
    ConceptEdge,
    ConceptEdgeDraft,
    ConceptEdgesDraft,
    ConceptMapStatistics,
    ConsolidateActionDraft,
    DetectedFrom,
    DetectionAgreement,
    SourceChapter,
    SourceConceptMap,
    cell_label_jaccard,
    cell_label_tokens,
    is_banned_or_smell_label,
    normalise_cell_label,
)
from thesisound.domain import DocumentMap, DocumentMapSection
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.ports import ParsedDocument
from thesisound.services.concept_map_cache import (
    CONCEPT_MAP_BUILDER_VERSION,
    CachedChapterConceptMap,
    ConceptMapCache,
    chapter_hash,
)
from thesisound.services.document_identity import block_sequence_key
from thesisound.services.lineage_events import emit_cache_lookup
from thesisound.services.model_runner import ModelRunner
from thesisound.source_analysis import SourceDocumentBlock

_MIN_CHAPTER_GROUPS = 2
_MIN_MEDIAN_CHAPTER_BLOCKS = 8
_MAX_CHAPTER_SHARE = 0.6
_MAX_DISAGREEING_BLOCK_SHARE = 0.2
_MAX_SINGLE_CHAPTER_SHARE = 0.4
_MIN_SINGLE_CHAPTER_SHARE = 0.02
_MINUTES_PER_TOKEN = 300
_UNSTRUCTURED_SOURCE_TITLE = "Whole source (no chapter structure detected)"

_Run = tuple[str, int, int]  # (heading text at the run's depth, start index, end index exclusive)


def detect_chapters(
    blocks: list[SourceDocumentBlock],
    parsed_document: ParsedDocument,
) -> list[SourceChapter]:
    """Split ``blocks`` into chapters with two independent detectors, reconciled.

    ``parsed_document`` is part of the signature for compatibility with `10b`
    B2 Pass 0, which lets Detector T read an explicit outline (Docling/MinerU
    headings list, EPUB nav). Today's parser output (`ports.ParsedDocument` /
    `ParsedBlock`) carries no such outline -- only per-block ``heading_path``.
    So Detector T here treats the document's own top-level headings
    (``heading_path[0]``) as the table of contents: every point where that
    value changes is a TOC entry, matched to the block that starts it. This is
    the fallback the runbook names for this exact gap. It is currently unused
    directly; if ``ParsedDocument`` grows a real outline field, Detector T
    should read that instead of re-deriving it from ``blocks``.

    Detector H (headings): for depth 0, then depth 1, group ``blocks`` into
    contiguous runs of ``heading_path[depth]``. A depth is accepted when its
    runs number >= 2, have a median size >= 8 blocks, and no run covers more
    than 60% of all blocks.

    Detector T (TOC): the depth-0 contiguous runs, accepted whenever there are
    >= 2 of them -- no size heuristic, matching an explicit TOC being trusted
    as given.

    In both detectors, a run with no heading value at that depth (front matter
    before the first heading, or a stretch with no deeper heading) is folded
    into the chapter before it, or into the first real chapter if it leads the
    document (`10c` P1 Step 2 point 4).

    Reconciliation:
    - Both found, and per-block chapter position agrees between the two
      (<= 20% of blocks land in a different ordinal chapter) and no Detector H
      chapter spans > 40% or < 2% of all blocks -> use H, ``agreed``.
    - Both found but disagree by either measure above -> use T, every chapter
      marked ``disagreed``. (The human-readable `needs_review` entry that
      names this is assembled later, in Pass 5 `compute_statistics` -- P1 step
      9 -- from this flag; it is not built here.)
    - Only one found -> use it (``heading_only`` / ``toc_only``).
    - Neither found -> one ``single`` chapter for the whole source.
    """
    if not blocks:
        raise ValueError("Cannot detect chapters without blocks.")

    depth0_runs = _absorb_unheaded_runs(_contiguous_runs(blocks, 0))
    depth1_runs = _absorb_unheaded_runs(_contiguous_runs(blocks, 1))

    heading_runs, heading_depth = _select_heading_detector(blocks, depth0_runs, depth1_runs)
    toc_runs = depth0_runs if len(depth0_runs) >= _MIN_CHAPTER_GROUPS else None

    if heading_runs is not None and toc_runs is not None:
        if _detectors_agree(blocks, heading_runs, toc_runs):
            return _build_chapters(blocks, heading_runs, heading_depth, "heading", "agreed")
        return _build_chapters(blocks, toc_runs, 0, "toc", "disagreed")
    if heading_runs is not None:
        return _build_chapters(blocks, heading_runs, heading_depth, "heading", "heading_only")
    if toc_runs is not None:
        return _build_chapters(blocks, toc_runs, 0, "toc", "toc_only")
    return _build_single_chapter(blocks)


def _contiguous_runs(blocks: list[SourceDocumentBlock], depth: int) -> list[_Run]:
    """Group ``blocks`` into contiguous runs of equal ``heading_path[depth]``.

    A block shorter than ``depth + 1`` contributes ``None`` as its key.
    """
    runs: list[list[object]] = []
    for index, block in enumerate(blocks):
        key = block.heading_path[depth] if len(block.heading_path) > depth else None
        if runs and runs[-1][0] == key:
            runs[-1][2] = index + 1
        else:
            runs.append([key, index, index + 1])
    return [(key, start, end) for key, start, end in runs]


def _absorb_unheaded_runs(runs: list[_Run]) -> list[_Run]:
    """Fold ``None``-key runs into a neighbouring chapter (see module docstring)."""
    if not any(key is not None for key, _start, _end in runs):
        return []
    named: list[list[object]] = []
    leading_start: int | None = None
    for key, start, end in runs:
        if key is None:
            if named:
                named[-1][2] = end
            else:
                leading_start = start
        elif named:
            named.append([key, start, end])
        else:
            named.append([key, leading_start if leading_start is not None else start, end])
    return [(key, start, end) for key, start, end in named]


def _passes_heading_heuristic(runs: list[_Run], total_blocks: int) -> bool:
    if len(runs) < _MIN_CHAPTER_GROUPS:
        return False
    sizes = [end - start for _key, start, end in runs]
    if median(sizes) < _MIN_MEDIAN_CHAPTER_BLOCKS:
        return False
    return max(sizes) / total_blocks <= _MAX_CHAPTER_SHARE


def _select_heading_detector(
    blocks: list[SourceDocumentBlock],
    depth0_runs: list[_Run],
    depth1_runs: list[_Run],
) -> tuple[list[_Run] | None, int]:
    for depth, runs in ((0, depth0_runs), (1, depth1_runs)):
        if _passes_heading_heuristic(runs, len(blocks)):
            return runs, depth
    return None, -1


def _detectors_agree(
    blocks: list[SourceDocumentBlock],
    heading_runs: list[_Run],
    toc_runs: list[_Run],
) -> bool:
    total = len(blocks)
    heading_starts = [start for _key, start, _end in heading_runs]
    toc_starts = [start for _key, start, _end in toc_runs]
    differing = sum(
        1
        for index in range(total)
        if bisect_right(heading_starts, index) != bisect_right(toc_starts, index)
    )
    if differing / total > _MAX_DISAGREEING_BLOCK_SHARE:
        return False
    shares = [(end - start) / total for _key, start, end in heading_runs]
    return all(_MIN_SINGLE_CHAPTER_SHARE <= share <= _MAX_SINGLE_CHAPTER_SHARE for share in shares)


def _heading_path_for(
    blocks: list[SourceDocumentBlock], start: int, end: int, depth: int, key: str
) -> list[str]:
    for block in blocks[start:end]:
        if len(block.heading_path) > depth and block.heading_path[depth] == key:
            return list(block.heading_path[: depth + 1])
    return [key]  # Defensive only: construction guarantees a match exists.


def _build_chapters(
    blocks: list[SourceDocumentBlock],
    runs: list[_Run],
    depth: int,
    detected_from: DetectedFrom,
    detection_agreement: DetectionAgreement,
) -> list[SourceChapter]:
    chapters: list[SourceChapter] = []
    for chapter_index, (key, start, end) in enumerate(runs):
        chapter_blocks = blocks[start:end]
        heading_path = _heading_path_for(blocks, start, end, depth, key)
        token_total = sum(block.estimated_token_count for block in chapter_blocks)
        chapters.append(
            SourceChapter(
                chapter_index=chapter_index,
                title=heading_path[-1],
                heading_path=heading_path,
                block_ids=[block.block_id for block in chapter_blocks],
                estimated_minutes=token_total / _MINUTES_PER_TOKEN,
                detected_from=detected_from,
                detection_agreement=detection_agreement,
            )
        )
    return chapters


def _build_single_chapter(blocks: list[SourceDocumentBlock]) -> list[SourceChapter]:
    token_total = sum(block.estimated_token_count for block in blocks)
    return [
        SourceChapter(
            chapter_index=0,
            title=_UNSTRUCTURED_SOURCE_TITLE,
            heading_path=[],
            block_ids=[block.block_id for block in blocks],
            estimated_minutes=token_total / _MINUTES_PER_TOKEN,
            detected_from="single",
            detection_agreement="agreed",
        )
    ]


# --- Pass 2 / 2.5: concept cells ------------------------------------------------

_PROMPT_NAME = "concept_cells"
_PROMPT_VERSION = "1.0.0"
_CONSOLIDATE_PROMPT_NAME = "concept_cells_consolidate"
_CONSOLIDATE_PROMPT_VERSION = "1.0.0"
_EDGES_PROMPT_NAME = "concept_edges"
_EDGES_PROMPT_VERSION = "1.0.0"
_MODE = "extraction"
_MIN_CHAPTER_BUDGET = 6
_MAX_CHAPTER_BUDGET = 40
_BUDGET_PER_SECTION = 1.5
_COUNT_CAP_FACTOR = 1.5
_JACCARD_DUPLICATE = 0.85
_TIER_DISTRIBUTION_MIN_CELLS = 6
_TIER1_SHARE_MIN = 0.15
_TIER1_SHARE_MAX = 0.45
_TIER3_SHARE_MIN = 0.10
_SECTIONS_EXEMPT_FROM_COVERAGE = frozenset({"front_matter", "transition"})
_NEEDS_REVIEW_PREFIX = "needs_review: "
_EDGE_TYPES = frozenset(
    {
        "prerequisite",
        "depends_on",
        "related",
        "extends",
        "contrasts",
        "objects_to",
        "responds_to",
        "instance_of",
    }
)
_CYCLE_EDGE_TYPES = frozenset({"prerequisite", "depends_on", "extends"})
_INTRA_EDGE_CAP_PER_CELL = 2
_INTRA_EDGE_CAP_MAX = 60
_DEFAULT_CROSS_CHAPTER_CAP = 10
_CROSS_CHAPTER_WINDOW = 2
_PREREQ_OUTDEGREE_TIER2 = 2
_PREREQ_OUTDEGREE_TIER1 = 4
_LABEL_BLOCK_OVERLAP_MIN = 0.15
_CELLS_PER_SECTION_RATIO_MAX = 3.0
_CELLS_PER_SECTION_RATIO_MIN = 0.5
_OVERSIZE_CELL_MINUTES = 30.0
_INTRA_RETURN_INSTRUCTION = "Return the edges between these cells."
_CROSS_RETURN_INSTRUCTION = (
    "Return only edges that cross the two chapters; edges inside one chapter "
    "are already recorded. Usually there are few (2–10). Prefer quality over quantity."
)


@dataclass(frozen=True)
class NormaliseCellsResult:
    """Pass 2.5 output: merged cells, warnings, and cross-chapter `related` hints."""

    cells: tuple[ConceptCell, ...]
    warnings: tuple[str, ...]
    related_candidates: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ChapterCellsResult:
    """One chapter after Pass 2 validation, key assignment, and Pass 2.5."""

    cells: tuple[ConceptCell, ...]
    warnings: tuple[str, ...]
    related_candidates: tuple[tuple[str, str], ...]
    record: ModelRunRecord


@dataclass(frozen=True)
class ConsolidateChapterResult:
    """Pass 3 output: cells at or under budget, with a run record when the model ran."""

    cells: tuple[ConceptCell, ...]
    skipped: bool
    warnings: tuple[str, ...]
    record: ModelRunRecord | None


@dataclass(frozen=True)
class ChapterEdgesResult:
    """Pass 4 output: validated edges for one chapter or one chapter pair."""

    edges: tuple[ConceptEdge, ...]
    warnings: tuple[str, ...]
    record: ModelRunRecord | None
    skipped: bool = False


class ConceptMapIntegrityError(ValueError):
    """Pass 5 critical failure: the map cannot be used as a teaching graph."""


class ConceptMapPartial(BaseModel):
    """Project-local checkpoint written after each finished chapter."""

    source_fingerprint: str
    builder_version: int = CONCEPT_MAP_BUILDER_VERSION
    chapters: list[SourceChapter] = Field(default_factory=list)
    completed_chapter_indexes: list[int] = Field(default_factory=list)
    cells: list[ConceptCell] = Field(default_factory=list)
    intra_edges: list[ConceptEdge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ConceptMapBuilder:
    """Run Pass 0–5 with shared cache, per-chapter sub-entries, and resume."""

    def __init__(
        self,
        model_runner: ModelRunner,
        *,
        workspace_root: Path,
        cache: ConceptMapCache | None = None,
    ) -> None:
        self.model_runner = model_runner
        self.workspace_root = workspace_root.expanduser().resolve()
        self.cache = cache or ConceptMapCache(self.workspace_root)

    def build(
        self,
        project_id: UUID,
        source_id: UUID,
        blocks: list[SourceDocumentBlock],
        document_map: DocumentMap,
        parsed_document: ParsedDocument,
        *,
        model_fast: str,
    ) -> SourceConceptMap:
        fingerprint = block_sequence_key(blocks)
        cached = self.cache.load_source(fingerprint)
        emit_cache_lookup(
            cache="shared_concept_map",
            result="hit" if cached is not None else "miss",
            project_id=project_id,
            subject_type="source",
            subject_id=str(source_id),
            lookup_key=fingerprint[:16],
            artifact_hash=fingerprint[:16] if cached is not None else None,
            avoided_calls=1 if cached is not None else None,
        )
        if cached is not None:
            self._clear_partial(project_id, source_id)
            return cached

        chapters = detect_chapters(blocks, parsed_document)
        partial = self._load_matching_partial(project_id, source_id, fingerprint)
        completed_indexes = set(partial.completed_chapter_indexes) if partial else set()
        cells = list(partial.cells) if partial else []
        intra_edges = list(partial.intra_edges) if partial else []
        warnings = list(partial.warnings) if partial else []
        if partial is not None:
            chapters = partial.chapters or chapters

        section_titles = {section.section_id: section.title for section in document_map.sections}
        for chapter in chapters:
            if chapter.chapter_index in completed_indexes:
                continue
            chapter_cells, chapter_edges, chapter_warnings = self._build_or_load_chapter(
                project_id=project_id,
                source_id=source_id,
                fingerprint=fingerprint,
                chapter=chapter,
                blocks=blocks,
                document_map=document_map,
                section_titles=section_titles,
                prior_cells=cells,
                model_fast=model_fast,
            )
            minutes = sum(cell.estimated_minutes for cell in chapter_cells)
            chapter.estimated_minutes = minutes
            cells.extend(chapter_cells)
            intra_edges.extend(chapter_edges)
            warnings.extend(chapter_warnings)
            completed_indexes.add(chapter.chapter_index)
            self._write_partial(
                project_id,
                source_id,
                ConceptMapPartial(
                    source_fingerprint=fingerprint,
                    builder_version=CONCEPT_MAP_BUILDER_VERSION,
                    chapters=chapters,
                    completed_chapter_indexes=sorted(completed_indexes),
                    cells=cells,
                    intra_edges=intra_edges,
                    warnings=warnings,
                ),
            )

        cells_by_chapter: dict[int, list[ConceptCell]] = {}
        for cell in cells:
            cells_by_chapter.setdefault(cell.chapter_index, []).append(cell)
        cross_edges: list[ConceptEdge] = []
        for left, right in iter_chapter_pairs_within_window(chapters):
            pair = build_cross_chapter_edges(
                cells_by_chapter.get(left.chapter_index, ()),
                cells_by_chapter.get(right.chapter_index, ()),
                default_cross_chapter_cap(
                    len(cells_by_chapter.get(left.chapter_index, ())),
                    len(cells_by_chapter.get(right.chapter_index, ())),
                ),
                model_runner=self.model_runner,
                project_id=project_id,
                model=model_fast,
                chapter_a_index=left.chapter_index,
                chapter_b_index=right.chapter_index,
                section_titles=section_titles,
            )
            cross_edges.extend(pair.edges)
            warnings.extend(pair.warnings)

        promoted = promote_tiers(cells, [*intra_edges, *cross_edges], document_map.sections)
        concept_map = SourceConceptMap(
            source_fingerprint=fingerprint,
            builder_version=CONCEPT_MAP_BUILDER_VERSION,
            chapters=chapters,
            cells=promoted,
            edges=[*intra_edges, *cross_edges],
            statistics=ConceptMapStatistics(cell_count=0),
            warnings=warnings,
        )
        block_texts = {block.block_id: block.text for block in blocks}
        concept_map = concept_map.model_copy(
            update={
                "statistics": compute_statistics(
                    concept_map,
                    sections=document_map.sections,
                    block_texts=block_texts,
                )
            }
        )
        self.cache.save_source(concept_map)
        emit_cache_lookup(
            cache="shared_concept_map",
            result="store",
            project_id=project_id,
            subject_type="source",
            subject_id=str(source_id),
            lookup_key=fingerprint[:16],
            artifact_hash=fingerprint[:16],
        )
        self._clear_partial(project_id, source_id)
        return concept_map

    def _build_or_load_chapter(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        fingerprint: str,
        chapter: SourceChapter,
        blocks: Sequence[SourceDocumentBlock],
        document_map: DocumentMap,
        section_titles: Mapping[str, str],
        prior_cells: Sequence[ConceptCell],
        model_fast: str,
    ) -> tuple[list[ConceptCell], list[ConceptEdge], list[str]]:
        chapter_key = chapter_hash(chapter, blocks)
        cached = self.cache.load_chapter(fingerprint, chapter_key)
        emit_cache_lookup(
            cache="shared_concept_map_chapter",
            result="hit" if cached is not None else "miss",
            project_id=project_id,
            subject_type="chapter",
            subject_id=str(chapter.chapter_index),
            lookup_key=chapter_key[:16],
            artifact_hash=chapter_key[:16] if cached is not None else None,
            avoided_calls=1 if cached is not None else None,
        )
        if cached is not None:
            return list(cached.cells), list(cached.intra_edges), list(cached.warnings)

        chapter_sections = _sections_for_chapter(chapter, document_map.sections)
        extracted = extract_chapter_cells(
            self.model_runner,
            project_id=project_id,
            source_id=source_id,
            chapter=chapter,
            sections=chapter_sections,
            blocks=blocks,
            model=model_fast,
            prior_cells=prior_cells,
        )
        budget = chapter_budget(chapter_sections)
        consolidated = consolidate_chapter(
            extracted.cells,
            budget,
            model_runner=self.model_runner,
            project_id=project_id,
            model=model_fast,
            chapter_title=chapter.title,
            section_titles=section_titles,
        )
        intra = build_edges_for_chapter(
            consolidated.cells,
            model_runner=self.model_runner,
            project_id=project_id,
            model=model_fast,
            chapter_title=chapter.title,
            section_titles=section_titles,
        )
        warnings = [
            *extracted.warnings,
            *consolidated.warnings,
            *intra.warnings,
        ]
        self.cache.save_chapter(
            CachedChapterConceptMap(
                source_fingerprint=fingerprint,
                chapter_hash=chapter_key,
                builder_version=CONCEPT_MAP_BUILDER_VERSION,
                chapter=chapter,
                cells=list(consolidated.cells),
                intra_edges=list(intra.edges),
                warnings=warnings,
            )
        )
        return list(consolidated.cells), list(intra.edges), warnings

    def _partial_path(self, project_id: UUID, source_id: UUID) -> Path:
        return (
            self.workspace_root
            / str(project_id)
            / "sources"
            / str(source_id)
            / "concept-map.partial.json"
        )

    def _load_matching_partial(
        self,
        project_id: UUID,
        source_id: UUID,
        fingerprint: str,
    ) -> ConceptMapPartial | None:
        path = self._partial_path(project_id, source_id)
        try:
            partial = ConceptMapPartial.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if partial.source_fingerprint != fingerprint:
            return None
        if partial.builder_version != CONCEPT_MAP_BUILDER_VERSION:
            return None
        return partial

    def _write_partial(
        self,
        project_id: UUID,
        source_id: UUID,
        partial: ConceptMapPartial,
    ) -> None:
        path = self._partial_path(project_id, source_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(partial.model_dump(mode="json"), ensure_ascii=False, indent=2)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(payload + "\n", encoding="utf-8")
        temporary.replace(path)

    def _clear_partial(self, project_id: UUID, source_id: UUID) -> None:
        self._partial_path(project_id, source_id).unlink(missing_ok=True)


def chapter_budget(sections: Sequence[DocumentMapSection]) -> int:
    """Soft cell target for a chapter: clamp(ceil(non-front-matter sections × 1.5), 6, 40)."""

    countable = sum(1 for section in sections if section.function != "front_matter")
    raw = math.ceil(countable * _BUDGET_PER_SECTION)
    return min(_MAX_CHAPTER_BUDGET, max(_MIN_CHAPTER_BUDGET, raw))


def build_chapter_awareness(
    accepted_cells: Sequence[ConceptCell | ConceptCellDraft],
    remaining_budget: int,
) -> dict[str, Any]:
    """Prompt payload listing cells already accepted for this chapter and the remaining budget."""

    return {
        "accepted_cell_count": len(accepted_cells),
        "accepted_labels": [
            {"label_fa": cell.label_fa, "kind": cell.kind, "tier": cell.tier}
            for cell in accepted_cells
        ],
        "remaining_budget": remaining_budget,
        "instruction": (
            "Do not recreate a concept already listed. If the budget is nearly exhausted, "
            "create only genuinely new concepts."
            if accepted_cells
            else "No cells accepted yet for this chapter."
        ),
    }


def _validate_cells_draft(
    draft: ConceptCellsDraft,
    *,
    known_block_ids: set[str],
    known_section_ids: set[str],
    sections: Sequence[DocumentMapSection],
    budget: int,
    attempt: int,
    max_attempts: int,
    accepted_cells: Sequence[ConceptCell] = (),
) -> None:
    """Deterministic Pass 2 gate. Last attempt auto-merges duplicates and flags distribution."""

    _reject_unknown_ids(draft, known_block_ids, known_section_ids)
    _reject_cells_without_blocks(draft)
    _reject_banned_labels(draft)
    _reject_uncovered_sections(draft, sections, accepted_cells)

    last_attempt = attempt >= max_attempts
    if _duplicate_groups([cell.label_fa for cell in draft.cells]):
        if last_attempt:
            kept = _merge_draft_duplicates(draft.cells)
            dropped = len(draft.cells) - len(kept)
            draft.cells[:] = kept
            draft.warnings.append(
                f"Auto-merged {dropped} near-duplicate cell(s) on the final attempt "
                f"(Jaccard ≥ {_JACCARD_DUPLICATE})."
            )
        else:
            pairs = _duplicate_label_pairs(draft.cells)
            raise DeterministicValidationError(
                f"Duplicate cell labels (Jaccard ≥ {_JACCARD_DUPLICATE}) on attempt {attempt}: "
                f"{pairs}. Rewrite so each cell names a distinct concept."
            )

    cap = budget * _COUNT_CAP_FACTOR
    total = len(accepted_cells) + len(draft.cells)
    if total > cap:
        raise DeterministicValidationError(
            f"Cell count {total} exceeds the chapter cap of {cap:.1f} (budget {budget} × "
            f"{_COUNT_CAP_FACTOR}). Reduce overlapping cells."
        )

    distribution = _tier_distribution_failure(draft.cells, accepted_cells)
    if distribution is None:
        return
    if last_attempt:
        draft.warnings.append(f"{_NEEDS_REVIEW_PREFIX}{distribution}")
        return
    raise DeterministicValidationError(f"{distribution} (attempt {attempt}). Redistribute tiers.")


def assign_cell_keys(
    drafts: Sequence[ConceptCellDraft],
    *,
    chapter_index: int,
    block_ids_in_order: Sequence[str],
) -> list[ConceptCell]:
    """Assign stable cell keys after validation, in first-block order."""

    order = {block_id: index for index, block_id in enumerate(block_ids_in_order)}

    def sort_key(draft: ConceptCellDraft) -> tuple[int, str]:
        positions = [order.get(block_id, len(order)) for block_id in draft.block_ids]
        return (min(positions, default=len(order)), draft.label_fa)

    cells: list[ConceptCell] = []
    for number, draft in enumerate(sorted(drafts, key=sort_key), start=1):
        cells.append(
            ConceptCell(
                cell_key=f"ch{chapter_index:02d}-c{number:03d}",
                label_fa=draft.label_fa,
                label_source=draft.label_source,
                kind=draft.kind,
                tier=draft.tier,
                tier_promoted=False,
                chapter_index=chapter_index,
                section_ids=list(draft.section_ids),
                block_ids=list(draft.block_ids),
                evidence_ids=[],
                granularity_rationale=draft.granularity_rationale,
                estimated_minutes=draft.estimated_minutes,
                created_by="ai",
            )
        )
    return cells


def normalise_cells(
    cells: Sequence[ConceptCell],
    *,
    prior_cells: Sequence[ConceptCell] = (),
) -> NormaliseCellsResult:
    """Pass 2.5: merge near-duplicates within a chapter; flag the same label across chapters."""

    warnings: list[str] = []
    merged: list[ConceptCell] = []
    by_chapter: dict[int, list[ConceptCell]] = {}
    for cell in cells:
        by_chapter.setdefault(cell.chapter_index, []).append(cell)

    for chapter_index in sorted(by_chapter):
        chapter_cells = by_chapter[chapter_index]
        groups = _duplicate_groups([cell.label_fa for cell in chapter_cells])
        if not groups:
            merged.extend(chapter_cells)
            continue
        chapter_merged, chapter_warnings = _merge_keyed_duplicates(chapter_cells, groups)
        merged.extend(chapter_merged)
        warnings.extend(chapter_warnings)

    related = _related_candidates(merged, prior_cells)
    for source_key, target_key in related:
        warnings.append(
            f"Same label in two chapters ({source_key} ~ {target_key}); recorded as a "
            "related-edge candidate. Not merged across chapters."
        )
    return NormaliseCellsResult(
        cells=tuple(merged),
        warnings=tuple(warnings),
        related_candidates=related,
    )


def extract_chapter_cells(
    model_runner: ModelRunner,
    *,
    project_id: UUID,
    source_id: str | UUID,
    chapter: SourceChapter,
    sections: Sequence[DocumentMapSection],
    blocks: Sequence[SourceDocumentBlock],
    model: str,
    accepted_cells: Sequence[ConceptCell] = (),
    prior_cells: Sequence[ConceptCell] = (),
    prompt_version: str | None = None,
) -> ChapterCellsResult:
    """Run Pass 2 for one chapter, assign keys, then Pass 2.5."""

    chapter_blocks = _blocks_for_chapter(chapter, blocks)
    chapter_sections = _sections_for_chapter(chapter, sections)
    budget = chapter_budget(chapter_sections)
    remaining = max(0, budget - len(accepted_cells))
    known_block_ids = set(chapter.block_ids)
    known_section_ids = {section.section_id for section in chapter_sections}
    attempt = {"n": 0}
    max_attempts = _cells_max_attempts(model_runner, prompt_version)

    def validate(draft: ConceptCellsDraft) -> None:
        attempt["n"] += 1
        _validate_cells_draft(
            draft,
            known_block_ids=known_block_ids,
            known_section_ids=known_section_ids,
            sections=chapter_sections,
            budget=budget,
            attempt=attempt["n"],
            max_attempts=max_attempts,
            accepted_cells=accepted_cells,
        )

    execution = model_runner.run(
        project_id=project_id,
        stage=f"concept_cells:ch{chapter.chapter_index:02d}",
        prompt_name=_PROMPT_NAME,
        prompt_version=prompt_version or _PROMPT_VERSION,
        variables={
            "source_id": str(source_id),
            "chapter": chapter.model_dump(mode="json"),
            "sections": [_section_payload(section) for section in chapter_sections],
            "blocks": [_block_payload(block) for block in chapter_blocks],
            "chapter_awareness": build_chapter_awareness(accepted_cells, remaining),
            "budget": budget,
            "mode": _MODE,
        },
        output_type=ConceptCellsDraft,
        model=model,
        validator=validate,
    )
    keyed = assign_cell_keys(
        execution.output.cells,
        chapter_index=chapter.chapter_index,
        block_ids_in_order=chapter.block_ids,
    )
    normalised = normalise_cells(keyed, prior_cells=prior_cells)
    warnings = tuple(execution.output.warnings) + normalised.warnings
    return ChapterCellsResult(
        cells=normalised.cells,
        warnings=warnings,
        related_candidates=normalised.related_candidates,
        record=execution.record,
    )


def consolidate_chapter(
    cells: Sequence[ConceptCell],
    budget: int,
    *,
    model_runner: ModelRunner,
    project_id: UUID,
    model: str,
    chapter_title: str,
    section_titles: Mapping[str, str] | None = None,
    prompt_version: str | None = None,
) -> ConsolidateChapterResult:
    """Pass 3: shrink a chapter to ``budget`` cells. No model call when already at or under."""

    if len(cells) <= budget:
        return ConsolidateChapterResult(
            cells=tuple(cells),
            skipped=True,
            warnings=(),
            record=None,
        )

    titles = dict(section_titles or {})
    attempt = {"n": 0}
    max_attempts = _consolidate_max_attempts(model_runner, prompt_version)

    def validate(draft: ConceptCellsConsolidateDraft) -> None:
        attempt["n"] += 1
        _validate_consolidate_draft(
            draft,
            cells,
            budget,
            attempt=attempt["n"],
            max_attempts=max_attempts,
        )

    chapter_index = cells[0].chapter_index if cells else 0
    execution = model_runner.run(
        project_id=project_id,
        stage=f"concept_cells_consolidate:ch{chapter_index:02d}",
        prompt_name=_CONSOLIDATE_PROMPT_NAME,
        prompt_version=prompt_version or _CONSOLIDATE_PROMPT_VERSION,
        variables={
            "chapter_title": chapter_title,
            "target_count": budget,
            "cells": [_cell_consolidate_payload(cell, titles) for cell in cells],
        },
        output_type=ConceptCellsConsolidateDraft,
        model=model,
        validator=validate,
    )
    applied = _apply_consolidate_actions(cells, execution.output)
    return ConsolidateChapterResult(
        cells=tuple(applied),
        skipped=False,
        warnings=_consolidate_action_warnings(execution.output),
        record=execution.record,
    )


def chapter_edge_cap(cell_count: int) -> int:
    """Intra-chapter edge cap: min(2 × N_cells, 60)."""

    return min(_INTRA_EDGE_CAP_MAX, _INTRA_EDGE_CAP_PER_CELL * max(0, cell_count))


def default_cross_chapter_cap(cell_count_a: int, cell_count_b: int) -> int:
    """Supplied cap for a chapter pair: usually 2–10, never above 10."""

    _ = cell_count_a, cell_count_b
    return _DEFAULT_CROSS_CHAPTER_CAP


def iter_chapter_pairs_within_window(
    chapters: Sequence[SourceChapter],
    *,
    window: int = _CROSS_CHAPTER_WINDOW,
) -> list[tuple[SourceChapter, SourceChapter]]:
    """Consecutive chapter pairs whose index distance is 1..``window`` (always built)."""

    ordered = sorted(chapters, key=lambda chapter: chapter.chapter_index)
    pairs: list[tuple[SourceChapter, SourceChapter]] = []
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 : index + 1 + window]:
            pairs.append((left, right))
    return pairs


def build_edges_for_chapter(
    cells: Sequence[ConceptCell],
    *,
    model_runner: ModelRunner,
    project_id: UUID,
    model: str,
    chapter_title: str,
    section_titles: Mapping[str, str] | None = None,
    prompt_version: str | None = None,
) -> ChapterEdgesResult:
    """Pass 4 intra-chapter: always called; skipped only when fewer than two cells."""

    cap = chapter_edge_cap(len(cells))
    if len(cells) < 2:
        return ChapterEdgesResult(edges=(), warnings=(), record=None, skipped=True)
    chapter_index = cells[0].chapter_index
    return _run_edges_prompt(
        cells,
        cap=cap,
        scope=f"chapter {chapter_index}: {chapter_title}",
        return_instruction=_INTRA_RETURN_INSTRUCTION,
        stage=f"concept_edges:ch{chapter_index:02d}",
        require_cross_chapter=False,
        model_runner=model_runner,
        project_id=project_id,
        model=model,
        section_titles=section_titles,
        prompt_version=prompt_version,
    )


def build_cross_chapter_edges(
    cells_a: Sequence[ConceptCell],
    cells_b: Sequence[ConceptCell],
    cap: int,
    *,
    model_runner: ModelRunner,
    project_id: UUID,
    model: str,
    chapter_a_index: int | None = None,
    chapter_b_index: int | None = None,
    section_titles: Mapping[str, str] | None = None,
    prompt_version: str | None = None,
) -> ChapterEdgesResult:
    """Pass 4 cross-chapter for one pair inside window 2. Always invoked by the builder."""

    if not cells_a or not cells_b:
        return ChapterEdgesResult(edges=(), warnings=(), record=None, skipped=True)
    index_a = chapter_a_index if chapter_a_index is not None else cells_a[0].chapter_index
    index_b = chapter_b_index if chapter_b_index is not None else cells_b[0].chapter_index
    cells = [*cells_a, *cells_b]
    return _run_edges_prompt(
        cells,
        cap=max(0, cap),
        scope=f"chapters {index_a} and {index_b}",
        return_instruction=_CROSS_RETURN_INSTRUCTION,
        stage=f"concept_edges:ch{index_a:02d}-ch{index_b:02d}",
        require_cross_chapter=True,
        model_runner=model_runner,
        project_id=project_id,
        model=model,
        section_titles=section_titles,
        prompt_version=prompt_version,
    )


def _run_edges_prompt(
    cells: Sequence[ConceptCell],
    *,
    cap: int,
    scope: str,
    return_instruction: str,
    stage: str,
    require_cross_chapter: bool,
    model_runner: ModelRunner,
    project_id: UUID,
    model: str,
    section_titles: Mapping[str, str] | None,
    prompt_version: str | None,
) -> ChapterEdgesResult:
    titles = dict(section_titles or {})
    known_keys = {cell.cell_key for cell in cells}
    chapter_by_key = {cell.cell_key: cell.chapter_index for cell in cells}
    attempt = {"n": 0}
    max_attempts = _edges_max_attempts(model_runner, prompt_version)

    def validate(draft: ConceptEdgesDraft) -> None:
        attempt["n"] += 1
        _validate_edges(
            draft,
            known_keys=known_keys,
            cap=cap,
            attempt=attempt["n"],
            max_attempts=max_attempts,
            chapter_by_key=chapter_by_key,
            require_cross_chapter=require_cross_chapter,
        )

    execution = model_runner.run(
        project_id=project_id,
        stage=stage,
        prompt_name=_EDGES_PROMPT_NAME,
        prompt_version=prompt_version or _EDGES_PROMPT_VERSION,
        variables={
            "scope": scope,
            "cells": [_cell_edge_payload(cell, titles) for cell in cells],
            "edge_cap": cap,
            "return_instruction": return_instruction,
        },
        output_type=ConceptEdgesDraft,
        model=model,
        validator=validate,
    )
    edges = _edges_from_draft(execution.output, chapter_by_key)
    return ChapterEdgesResult(
        edges=tuple(edges),
        warnings=tuple(execution.output.warnings),
        record=execution.record,
        skipped=False,
    )


def _validate_edges(
    draft: ConceptEdgesDraft,
    *,
    known_keys: set[str],
    cap: int,
    attempt: int,
    max_attempts: int,
    chapter_by_key: Mapping[str, int] | None = None,
    require_cross_chapter: bool = False,
) -> None:
    """Deterministic Pass 4 gate. Last attempt drops the weakest edge of each cycle."""

    unknown: list[str] = []
    invalid_types: list[str] = []
    self_loops: list[str] = []
    for edge in draft.edges:
        if edge.source_key not in known_keys:
            unknown.append(edge.source_key)
        if edge.target_key not in known_keys:
            unknown.append(edge.target_key)
        if edge.type not in _EDGE_TYPES:
            invalid_types.append(str(edge.type))
        if edge.source_key == edge.target_key:
            self_loops.append(edge.source_key)
        edge.weight = min(1.0, max(0.0, edge.weight))
        edge.confidence = min(1.0, max(0.0, edge.confidence))
    if unknown:
        raise DeterministicValidationError(
            "Unknown cell keys in edges: " + ", ".join(_unique(unknown))
        )
    if invalid_types:
        raise DeterministicValidationError(
            "Invalid edge type(s): " + ", ".join(_unique(invalid_types))
        )
    if self_loops:
        raise DeterministicValidationError(
            "Self-loop edges are not allowed: " + ", ".join(_unique(self_loops))
        )

    if require_cross_chapter and chapter_by_key is not None:
        kept_cross: list[ConceptEdgeDraft] = []
        dropped_intra = 0
        for edge in draft.edges:
            if chapter_by_key.get(edge.source_key) != chapter_by_key.get(edge.target_key):
                kept_cross.append(edge)
            else:
                dropped_intra += 1
        if dropped_intra:
            draft.warnings.append(
                f"Dropped {dropped_intra} intra-chapter edge(s) from a cross-chapter call."
            )
        draft.edges[:] = kept_cross

    _dedup_edges(draft)

    last_attempt = attempt >= max_attempts
    while True:
        cycle = _find_cycle_edge_indices(draft.edges)
        if cycle is None:
            break
        path = _cycle_path(draft.edges, cycle)
        if not last_attempt:
            raise DeterministicValidationError(
                "Cycle among prerequisite/depends_on/extends on attempt "
                f"{attempt}: {path}. Remove or reverse one of those edges."
            )
        drop_at = _lowest_weight_index(draft.edges, cycle)
        dropped = draft.edges.pop(drop_at)
        draft.warnings.append(
            f"Dropped {dropped.source_key}→{dropped.target_key} ({dropped.type}, "
            f"weight={dropped.weight}) to break cycle {path}."
        )

    if len(draft.edges) > cap:
        ranked = sorted(
            range(len(draft.edges)),
            key=lambda index: (
                -draft.edges[index].weight,
                -draft.edges[index].confidence,
                draft.edges[index].source_key,
                draft.edges[index].target_key,
                draft.edges[index].type,
            ),
        )
        keep = set(ranked[:cap])
        dropped_count = len(draft.edges) - cap
        draft.edges[:] = [edge for index, edge in enumerate(draft.edges) if index in keep]
        draft.warnings.append(
            f"Dropped {dropped_count} edge(s) to meet cap {cap} (kept highest weight)."
        )


def promote_tiers(
    cells: Sequence[ConceptCell],
    edges: Sequence[ConceptEdge],
    sections: Sequence[DocumentMapSection],
    *,
    tier_overrides: Mapping[str, ConceptCellTier] | None = None,
) -> list[ConceptCell]:
    """Pass 4.5: raise cells that others depend on, or that sit in a required section."""

    required_sections = {
        section.section_id
        for section in sections
        if section.required_for_global_understanding
    }
    prereq_out: dict[str, int] = {}
    for edge in edges:
        if edge.type == "prerequisite":
            prereq_out[edge.source_key] = prereq_out.get(edge.source_key, 0) + 1
    overrides = dict(tier_overrides or {})
    promoted: list[ConceptCell] = []
    for cell in cells:
        out_degree = prereq_out.get(cell.cell_key, 0)
        required = any(section_id in required_sections for section_id in cell.section_ids)
        new_tier = _promoted_tier(cell.tier, required=required, prereq_out=out_degree)
        auto_promoted = new_tier < cell.tier
        if cell.cell_key in overrides:
            new_tier = overrides[cell.cell_key]
            auto_promoted = False
        if new_tier == cell.tier and auto_promoted == cell.tier_promoted:
            promoted.append(cell)
            continue
        promoted.append(
            cell.model_copy(update={"tier": new_tier, "tier_promoted": auto_promoted})
        )
    return promoted


def compute_statistics(
    concept_map: SourceConceptMap,
    *,
    sections: Sequence[DocumentMapSection] = (),
    block_texts: Mapping[str, str] | None = None,
) -> ConceptMapStatistics:
    """Pass 5: counts, orphans, needs_review. Critical gaps raise ConceptMapIntegrityError."""

    cells = list(concept_map.cells)
    edges = list(concept_map.edges)
    chapters = list(concept_map.chapters)
    _reject_map_integrity(cells, edges, chapters, sections)

    texts = dict(block_texts or {})
    incident = {edge.source_key for edge in edges} | {edge.target_key for edge in edges}
    orphans = [cell.cell_key for cell in cells if cell.cell_key not in incident]
    cells_per_tier = {1: 0, 2: 0, 3: 0}
    cells_per_chapter = {chapter.chapter_index: 0 for chapter in chapters}
    for cell in cells:
        cells_per_tier[cell.tier] = cells_per_tier.get(cell.tier, 0) + 1
        cells_per_chapter[cell.chapter_index] = cells_per_chapter.get(cell.chapter_index, 0) + 1
    edges_per_type = {edge_type: 0 for edge_type in sorted(_EDGE_TYPES)}
    for edge in edges:
        edges_per_type[edge.type] = edges_per_type.get(edge.type, 0) + 1
    promoted_keys = [cell.cell_key for cell in cells if cell.tier_promoted]
    needs_review = _needs_review_flags(concept_map, sections, texts)
    return ConceptMapStatistics(
        cell_count=len(cells),
        cells_per_tier=cells_per_tier,
        cells_per_chapter=cells_per_chapter,
        edges_per_type=edges_per_type,
        orphan_cell_keys=orphans,
        cross_chapter_edge_count=sum(1 for edge in edges if edge.is_cross_chapter),
        promoted_cell_keys=promoted_keys,
        needs_review=needs_review,
    )


def _validate_consolidate_draft(
    draft: ConceptCellsConsolidateDraft,
    cells: Sequence[ConceptCell],
    budget: int,
    *,
    attempt: int = 1,
    max_attempts: int = 2,
) -> None:
    """Deterministic Pass 3 gate. Attempts are recorded for the retry loop; rules stay strict."""

    _ = attempt, max_attempts
    known_keys = [cell.cell_key for cell in cells]
    known_set = set(known_keys)
    if len(known_set) != len(known_keys):
        raise DeterministicValidationError(
            "Input cells have duplicate keys; cannot consolidate."
        )

    actions_by_key: dict[str, ConsolidateActionDraft] = {}
    duplicates: list[str] = []
    for action in draft.actions:
        if action.cell_key in actions_by_key:
            duplicates.append(action.cell_key)
        actions_by_key[action.cell_key] = action
    if duplicates:
        raise DeterministicValidationError(
            "Duplicate actions for cell key(s): " + ", ".join(_unique(duplicates))
        )

    unknown = sorted(set(actions_by_key) - known_set)
    if unknown:
        raise DeterministicValidationError(
            "Unknown cell_key values in consolidate actions: " + ", ".join(unknown)
        )
    missing = sorted(known_set - set(actions_by_key))
    if missing:
        raise DeterministicValidationError(
            "Every cell needs one action; missing: " + ", ".join(missing)
        )

    keep_keys = {
        action.cell_key for action in draft.actions if action.action == "keep"
    }
    for action in draft.actions:
        if action.action == "merge":
            if not action.merge_into:
                raise DeterministicValidationError(
                    f"{action.cell_key} action=merge requires merge_into."
                )
            if action.merge_into == action.cell_key:
                raise DeterministicValidationError(
                    f"{action.cell_key} cannot merge into itself."
                )
            if action.merge_into not in known_set:
                raise DeterministicValidationError(
                    f"{action.cell_key} merge_into {action.merge_into} "
                    "is not a cell in this chapter."
                )
            if action.merge_into not in keep_keys:
                raise DeterministicValidationError(
                    f"{action.cell_key} merge_into {action.merge_into} must be a keep action."
                )
        elif action.merge_into is not None:
            raise DeterministicValidationError(
                f"{action.cell_key} action={action.action} must not set merge_into."
            )

    surviving = _apply_consolidate_actions(cells, draft)
    if len(surviving) > budget:
        raise DeterministicValidationError(
            f"After consolidate, {len(surviving)} cells remain (budget {budget}). "
            "Merge or remove more overlapping cells."
        )

    original_sections = {section_id for cell in cells for section_id in cell.section_ids}
    surviving_sections = {section_id for cell in surviving for section_id in cell.section_ids}
    uncovered = sorted(original_sections - surviving_sections)
    if uncovered:
        raise DeterministicValidationError(
            "A section would lose its last cell: " + ", ".join(uncovered)
        )


def _apply_consolidate_actions(
    cells: Sequence[ConceptCell],
    draft: ConceptCellsConsolidateDraft,
) -> list[ConceptCell]:
    """Apply keep/merge/remove: union blocks/sections onto each keep, keep the lower tier."""

    updated = {cell.cell_key: cell for cell in cells}
    keep_keys = {action.cell_key for action in draft.actions if action.action == "keep"}
    for action in draft.actions:
        if action.action != "merge" or action.merge_into is None:
            continue
        source = updated[action.cell_key]
        target = updated[action.merge_into]
        updated[action.merge_into] = target.model_copy(
            update={
                "block_ids": _unique([*target.block_ids, *source.block_ids]),
                "section_ids": _unique([*target.section_ids, *source.section_ids]),
                "evidence_ids": _unique([*target.evidence_ids, *source.evidence_ids]),
                "tier": target.tier if target.tier <= source.tier else source.tier,
            }
        )
    return [updated[cell.cell_key] for cell in cells if cell.cell_key in keep_keys]


def _cell_consolidate_payload(
    cell: ConceptCell,
    section_titles: Mapping[str, str],
) -> dict[str, Any]:
    """Metadata-only payload: no block text (Pass 3 is labels and structure)."""

    return {
        "cell_key": cell.cell_key,
        "label_fa": cell.label_fa,
        "label_source": cell.label_source,
        "kind": cell.kind,
        "tier": cell.tier,
        "section_ids": list(cell.section_ids),
        "section_titles": [
            section_titles.get(section_id, section_id) for section_id in cell.section_ids
        ],
        "granularity_rationale": cell.granularity_rationale,
        "estimated_minutes": cell.estimated_minutes,
    }


def _consolidate_action_warnings(draft: ConceptCellsConsolidateDraft) -> tuple[str, ...]:
    warnings: list[str] = []
    for action in draft.actions:
        if action.action == "keep":
            continue
        if action.action == "merge":
            warnings.append(
                f"Merged {action.cell_key} into {action.merge_into}: {action.reason}"
            )
        else:
            warnings.append(f"Removed {action.cell_key}: {action.reason}")
    return tuple(warnings)


def _consolidate_max_attempts(model_runner: ModelRunner, prompt_version: str | None) -> int:
    loader = getattr(model_runner, "prompt_loader", None)
    if loader is None:
        return 2
    version = prompt_version or _CONSOLIDATE_PROMPT_VERSION
    return loader.load_contract(_CONSOLIDATE_PROMPT_NAME, version=version).max_attempts


def _cells_max_attempts(model_runner: ModelRunner, prompt_version: str | None) -> int:
    loader = getattr(model_runner, "prompt_loader", None)
    if loader is None:
        return 3
    version = prompt_version or _PROMPT_VERSION
    return loader.load_contract(_PROMPT_NAME, version=version).max_attempts


def _blocks_for_chapter(
    chapter: SourceChapter,
    blocks: Sequence[SourceDocumentBlock],
) -> list[SourceDocumentBlock]:
    by_id = {block.block_id: block for block in blocks}
    missing = [block_id for block_id in chapter.block_ids if block_id not in by_id]
    if missing:
        raise ValueError(f"Chapter {chapter.chapter_index} references unknown blocks: {missing}")
    return [by_id[block_id] for block_id in chapter.block_ids]


def _sections_for_chapter(
    chapter: SourceChapter,
    sections: Sequence[DocumentMapSection],
) -> list[DocumentMapSection]:
    chapter_blocks = set(chapter.block_ids)
    return [
        section
        for section in sections
        if chapter_blocks.intersection(section.source_block_ids)
    ]


def _section_payload(section: DocumentMapSection) -> dict[str, Any]:
    return {
        "section_id": section.section_id,
        "title": section.title,
        "function": section.function,
        "key_concepts": section.key_concepts,
        "required_for_global_understanding": section.required_for_global_understanding,
        "source_block_ids": section.source_block_ids,
    }


def _block_payload(block: SourceDocumentBlock) -> dict[str, Any]:
    return {
        "block_id": block.block_id,
        "heading_path": block.heading_path,
        "block_type": block.block_type,
        "text": block.text,
    }


def _reject_unknown_ids(
    draft: ConceptCellsDraft,
    known_block_ids: set[str],
    known_section_ids: set[str],
) -> None:
    unknown_blocks = sorted(
        {
            block_id
            for cell in draft.cells
            for block_id in cell.block_ids
            if block_id not in known_block_ids
        }
    )
    if unknown_blocks:
        raise DeterministicValidationError(
            f"Unknown block_id values: {', '.join(unknown_blocks)}"
        )
    unknown_sections = sorted(
        {
            section_id
            for cell in draft.cells
            for section_id in cell.section_ids
            if section_id not in known_section_ids
        }
    )
    if unknown_sections:
        raise DeterministicValidationError(
            f"Unknown section_id values: {', '.join(unknown_sections)}"
        )


def _reject_cells_without_blocks(draft: ConceptCellsDraft) -> None:
    empty = [
        index
        for index, cell in enumerate(draft.cells, start=1)
        if not cell.block_ids or any(not block_id.strip() for block_id in cell.block_ids)
    ]
    if empty:
        raise DeterministicValidationError(
            f"Cell(s) without a source block at position(s) {empty}."
        )


def _reject_banned_labels(draft: ConceptCellsDraft) -> None:
    banned: list[str] = []
    for cell in draft.cells:
        if is_banned_or_smell_label(cell.label_fa):
            banned.append(cell.label_fa)
        if cell.label_source is not None and is_banned_or_smell_label(cell.label_source):
            banned.append(cell.label_source)
    if banned:
        raise DeterministicValidationError(
            "Banned or smell labels (structural/pedagogical, not a concept): "
            + "; ".join(banned)
        )


def _reject_uncovered_sections(
    draft: ConceptCellsDraft,
    sections: Sequence[DocumentMapSection],
    accepted_cells: Sequence[ConceptCell],
) -> None:
    covered = {section_id for cell in accepted_cells for section_id in cell.section_ids}
    covered.update(section_id for cell in draft.cells for section_id in cell.section_ids)
    required = {
        section.section_id
        for section in sections
        if section.function not in _SECTIONS_EXEMPT_FROM_COVERAGE
    }
    missing = sorted(required - covered)
    if missing:
        raise DeterministicValidationError(
            "Every non-front-matter/transition section needs a cell; uncovered: "
            + ", ".join(missing)
        )


def _duplicate_groups(labels: Sequence[str]) -> list[list[int]]:
    parent = list(range(len(labels)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for i, left in enumerate(labels):
        for j in range(i + 1, len(labels)):
            if cell_label_jaccard(left, labels[j]) >= _JACCARD_DUPLICATE:
                union(i, j)
    grouped: dict[int, list[int]] = {}
    for index in range(len(labels)):
        grouped.setdefault(find(index), []).append(index)
    return [group for group in grouped.values() if len(group) > 1]


def _duplicate_label_pairs(cells: Sequence[ConceptCellDraft]) -> str:
    pairs: list[str] = []
    for i, left in enumerate(cells):
        for right in cells[i + 1 :]:
            if cell_label_jaccard(left.label_fa, right.label_fa) >= _JACCARD_DUPLICATE:
                pairs.append(f"{left.label_fa!r} ~ {right.label_fa!r}")
    return "; ".join(pairs)


def _merge_draft_duplicates(cells: Sequence[ConceptCellDraft]) -> list[ConceptCellDraft]:
    groups = _duplicate_groups([cell.label_fa for cell in cells])
    drop: set[int] = set()
    merged = list(cells)
    for group in groups:
        keep, *rest = group
        merged[keep] = merged[keep].model_copy(
            update={
                "block_ids": _unique(
                    block_id for index in group for block_id in merged[index].block_ids
                ),
                "section_ids": _unique(
                    section_id for index in group for section_id in merged[index].section_ids
                ),
            }
        )
        drop.update(rest)
    return [cell for index, cell in enumerate(merged) if index not in drop]


def _merge_keyed_duplicates(
    cells: Sequence[ConceptCell],
    groups: list[list[int]],
) -> tuple[list[ConceptCell], list[str]]:
    drop: set[int] = set()
    merged = list(cells)
    warnings: list[str] = []
    for group in groups:
        ordered = sorted(group, key=lambda index: merged[index].cell_key)
        keep, *rest = ordered
        kept = merged[keep]
        merged[keep] = kept.model_copy(
            update={
                "block_ids": _unique(
                    block_id for index in ordered for block_id in merged[index].block_ids
                ),
                "section_ids": _unique(
                    section_id for index in ordered for section_id in merged[index].section_ids
                ),
            }
        )
        drop.update(rest)
        dropped_keys = ", ".join(merged[index].cell_key for index in rest)
        warnings.append(
            f"Merged near-duplicate cells {dropped_keys} into {kept.cell_key} "
            f"(Jaccard ≥ {_JACCARD_DUPLICATE})."
        )
    return [cell for index, cell in enumerate(merged) if index not in drop], warnings


def _related_candidates(
    cells: Sequence[ConceptCell],
    prior_cells: Sequence[ConceptCell],
) -> tuple[tuple[str, str], ...]:
    candidates: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def consider(left: ConceptCell, right: ConceptCell) -> None:
        if left.chapter_index == right.chapter_index:
            return
        same_source = (
            left.label_source is not None
            and right.label_source is not None
            and normalise_cell_label(left.label_source) == normalise_cell_label(right.label_source)
            and normalise_cell_label(left.label_source) != ""
        )
        similar = cell_label_jaccard(left.label_fa, right.label_fa) >= _JACCARD_DUPLICATE
        if not similar and not same_source:
            return
        pair = tuple(sorted((left.cell_key, right.cell_key)))
        if pair not in seen:
            seen.add(pair)
            candidates.append((pair[0], pair[1]))

    catalogue = list(cells) + list(prior_cells)
    for i, left in enumerate(catalogue):
        for right in catalogue[i + 1 :]:
            consider(left, right)
    return tuple(candidates)


def _tier_distribution_failure(
    draft_cells: Sequence[ConceptCellDraft],
    accepted_cells: Sequence[ConceptCell],
) -> str | None:
    tiers = [cell.tier for cell in accepted_cells] + [cell.tier for cell in draft_cells]
    count = len(tiers)
    if count < _TIER_DISTRIBUTION_MIN_CELLS:
        return None
    share_1 = tiers.count(1) / count
    share_3 = tiers.count(3) / count
    if _TIER1_SHARE_MIN <= share_1 <= _TIER1_SHARE_MAX and share_3 >= _TIER3_SHARE_MIN:
        return None
    return (
        f"Tier distribution for {count} cells is {share_1:.0%} tier-1 and {share_3:.0%} tier-3 "
        f"(need tier-1 in [15%, 45%] and tier-3 ≥ 10%)"
    )


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _edges_max_attempts(model_runner: ModelRunner, prompt_version: str | None) -> int:
    loader = getattr(model_runner, "prompt_loader", None)
    if loader is None:
        return 2
    version = prompt_version or _EDGES_PROMPT_VERSION
    return loader.load_contract(_EDGES_PROMPT_NAME, version=version).max_attempts


def _cell_edge_payload(cell: ConceptCell, section_titles: Mapping[str, str]) -> dict[str, Any]:
    """Metadata only: key, labels, kind, tier, chapter, section titles — no block text."""

    return {
        "cell_key": cell.cell_key,
        "label_fa": cell.label_fa,
        "label_source": cell.label_source,
        "kind": cell.kind,
        "tier": cell.tier,
        "chapter_index": cell.chapter_index,
        "section_titles": [
            section_titles.get(section_id, section_id) for section_id in cell.section_ids
        ],
    }


def _edges_from_draft(
    draft: ConceptEdgesDraft,
    chapter_by_key: Mapping[str, int],
) -> list[ConceptEdge]:
    converted: list[ConceptEdge] = []
    for edge in draft.edges:
        converted.append(
            ConceptEdge(
                source_key=edge.source_key,
                target_key=edge.target_key,
                type=edge.type,
                weight=edge.weight,
                confidence=edge.confidence,
                rationale_fa=edge.rationale_fa,
                created_by="ai",
                is_cross_chapter=chapter_by_key.get(edge.source_key)
                != chapter_by_key.get(edge.target_key),
            )
        )
    return converted


def _dedup_edges(draft: ConceptEdgesDraft) -> None:
    """Keep the strongest edge for each (source, target, type)."""

    best: dict[tuple[str, str, str], ConceptEdgeDraft] = {}
    order: list[tuple[str, str, str]] = []
    for edge in draft.edges:
        key = (edge.source_key, edge.target_key, edge.type)
        current = best.get(key)
        if current is None:
            best[key] = edge
            order.append(key)
            continue
        if (edge.weight, edge.confidence) > (current.weight, current.confidence):
            best[key] = edge
    if len(best) != len(draft.edges):
        dropped = len(draft.edges) - len(best)
        draft.edges[:] = [best[key] for key in order]
        draft.warnings.append(
            f"Removed {dropped} duplicate edge(s) sharing (source, target, type)."
        )


def _find_cycle_edge_indices(edges: Sequence[ConceptEdgeDraft]) -> list[int] | None:
    """Return one directed cycle among prerequisite/depends_on/extends, as edge indices."""

    adjacency: dict[str, list[tuple[str, int]]] = {}
    nodes: set[str] = set()
    for index, edge in enumerate(edges):
        if edge.type not in _CYCLE_EDGE_TYPES:
            continue
        adjacency.setdefault(edge.source_key, []).append((edge.target_key, index))
        nodes.add(edge.source_key)
        nodes.add(edge.target_key)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}
    parent_edge: dict[str, tuple[str, int]] = {}

    def dfs(node: str) -> list[int] | None:
        color[node] = GRAY
        for neighbor, edge_index in adjacency.get(node, []):
            state = color.get(neighbor, WHITE)
            if state == WHITE:
                parent_edge[neighbor] = (node, edge_index)
                found = dfs(neighbor)
                if found is not None:
                    return found
            elif state == GRAY:
                cycle = [edge_index]
                current = node
                while current != neighbor:
                    origin, via = parent_edge[current]
                    cycle.append(via)
                    current = origin
                cycle.reverse()
                return cycle
        color[node] = BLACK
        return None

    for node in nodes:
        if color.get(node, WHITE) == WHITE:
            found = dfs(node)
            if found is not None:
                return found
    return None


def _cycle_path(edges: Sequence[ConceptEdgeDraft], indices: Sequence[int]) -> str:
    if not indices:
        return ""
    keys = [edges[index].source_key for index in indices]
    keys.append(edges[indices[-1]].target_key)
    return " → ".join(keys)


def _lowest_weight_index(edges: Sequence[ConceptEdgeDraft], indices: Sequence[int]) -> int:
    return min(
        indices,
        key=lambda index: (
            edges[index].weight,
            edges[index].confidence,
            edges[index].source_key,
            edges[index].target_key,
            edges[index].type,
        ),
    )


def _promoted_tier(current: int, *, required: bool, prereq_out: int) -> int:
    tier = current
    if required or prereq_out >= _PREREQ_OUTDEGREE_TIER2:
        tier = min(tier, 2)
    if prereq_out >= _PREREQ_OUTDEGREE_TIER1:
        tier = min(tier, 1)
    return tier


def _reject_map_integrity(
    cells: Sequence[ConceptCell],
    edges: Sequence[ConceptEdge],
    chapters: Sequence[SourceChapter],
    sections: Sequence[DocumentMapSection],
) -> None:
    empty_blocks = [cell.cell_key for cell in cells if not cell.block_ids]
    if empty_blocks:
        raise ConceptMapIntegrityError(
            "Cell(s) with no source block: " + ", ".join(empty_blocks)
        )

    known_blocks = {block_id for chapter in chapters for block_id in chapter.block_ids}
    unknown_blocks = sorted(
        {
            block_id
            for cell in cells
            for block_id in cell.block_ids
            if known_blocks and block_id not in known_blocks
        }
    )
    known_keys = {cell.cell_key for cell in cells}
    unknown_edge_keys = sorted(
        {
            key
            for edge in edges
            for key in (edge.source_key, edge.target_key)
            if key not in known_keys
        }
    )
    unknown_sections: list[str] = []
    if sections:
        known_sections = {section.section_id for section in sections}
        unknown_sections = sorted(
            {
                section_id
                for cell in cells
                for section_id in cell.section_ids
                if section_id not in known_sections
            }
        )
    unknown_bits = []
    if unknown_blocks:
        unknown_bits.append("block_id " + ", ".join(unknown_blocks))
    if unknown_sections:
        unknown_bits.append("section_id " + ", ".join(unknown_sections))
    if unknown_edge_keys:
        unknown_bits.append("cell_key " + ", ".join(unknown_edge_keys))
    if unknown_bits:
        raise ConceptMapIntegrityError("Unknown IDs: " + "; ".join(unknown_bits))

    if not sections:
        return
    covered = {section_id for cell in cells for section_id in cell.section_ids}
    missing = sorted(
        section.section_id
        for section in sections
        if section.function not in _SECTIONS_EXEMPT_FROM_COVERAGE
        and section.section_id not in covered
    )
    if missing:
        raise ConceptMapIntegrityError(
            "Section(s) with no cell after consolidation: " + ", ".join(missing)
        )


def _needs_review_flags(
    concept_map: SourceConceptMap,
    sections: Sequence[DocumentMapSection],
    block_texts: Mapping[str, str],
) -> list[str]:
    flags: list[str] = []
    disagreed = [
        chapter
        for chapter in concept_map.chapters
        if chapter.detection_agreement == "disagreed"
    ]
    if disagreed:
        summary = ", ".join(
            f"{chapter.chapter_index}:{chapter.title}" for chapter in disagreed
        )
        flags.append(f"chapter detection disagreed: used TOC as source of truth ({summary})")

    cells_by_chapter: dict[int, list[ConceptCell]] = {}
    for cell in concept_map.cells:
        cells_by_chapter.setdefault(cell.chapter_index, []).append(cell)

    for chapter in concept_map.chapters:
        chapter_cells = cells_by_chapter.get(chapter.chapter_index, [])
        if len(chapter_cells) >= 2:
            tiers = {cell.tier for cell in chapter_cells}
            if len(tiers) == 1:
                flags.append(
                    f"single-tier chapter {chapter.chapter_index} (all tier {next(iter(tiers))})"
                )
        if sections:
            chapter_sections = _sections_for_chapter(chapter, sections)
            countable = [
                section
                for section in chapter_sections
                if section.function not in _SECTIONS_EXEMPT_FROM_COVERAGE
            ]
            if countable:
                ratio = len(chapter_cells) / len(countable)
                if ratio > _CELLS_PER_SECTION_RATIO_MAX or ratio < _CELLS_PER_SECTION_RATIO_MIN:
                    flags.append(
                        f"cells/sections ratio {ratio:.2f} in chapter {chapter.chapter_index} "
                        f"(cells={len(chapter_cells)}, sections={len(countable)})"
                    )

    for cell in concept_map.cells:
        if cell.estimated_minutes >= _OVERSIZE_CELL_MINUTES:
            flags.append(
                f"{cell.cell_key} is oversize ({cell.estimated_minutes} min)"
            )
        if not cell.label_source or not block_texts:
            continue
        text = " ".join(block_texts.get(block_id, "") for block_id in cell.block_ids)
        if not text.strip():
            continue
        overlap = _label_block_overlap(cell.label_source, text)
        if overlap < _LABEL_BLOCK_OVERLAP_MIN:
            flags.append(
                f"{cell.cell_key} label_source {cell.label_source!r} lexical overlap "
                f"{overlap:.2f} with block text"
            )
    return flags


def _label_block_overlap(label: str, text: str) -> float:
    """Share of label tokens that appear in the cell's block text (recall, not Jaccard)."""

    label_tokens = cell_label_tokens(label)
    if not label_tokens:
        return 1.0
    text_tokens = cell_label_tokens(text)
    return len(label_tokens & text_tokens) / len(label_tokens)
