"""Concept-map pipeline: Pass 0 (chapters), Pass 2/2.5 (cells), Pass 3 (consolidate).

Pass 0 (`detect_chapters`) is deterministic. Pass 2 calls `concept_cells/1.0.0`
through `ModelRunner` with `_validate_cells_draft`; Pass 2.5 (`normalise_cells`)
is pure. Pass 3 calls `concept_cells_consolidate/1.0.0` only when a chapter's
cell count exceeds its budget; applying keep/merge/remove is deterministic.
Orchestration that loops chapters arrives in a later step.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from statistics import median
from typing import Any
from uuid import UUID

from thesisound.concepts import (
    ConceptCell,
    ConceptCellDraft,
    ConceptCellsConsolidateDraft,
    ConceptCellsDraft,
    ConsolidateActionDraft,
    DetectedFrom,
    DetectionAgreement,
    SourceChapter,
    cell_label_jaccard,
    is_banned_or_smell_label,
    normalise_cell_label,
)
from thesisound.domain import DocumentMapSection
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.ports import ParsedDocument
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
                    f"{action.cell_key} merge_into {action.merge_into} is not a cell in this chapter."
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
