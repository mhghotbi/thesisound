"""Pass 0 of the concept-map pipeline: split a source into chapters.

Design: `10b` B1.2 (`SourceChapter`), `10b` B2 Pass 0 (the two detectors and the
reconciliation thresholds). Plan: `10c` P1 Step 2. Deterministic; no model call.
"""

from __future__ import annotations

from bisect import bisect_right
from statistics import median

from thesisound.concepts import DetectedFrom, DetectionAgreement, SourceChapter
from thesisound.ports import ParsedDocument
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
