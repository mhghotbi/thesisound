from __future__ import annotations

from collections import Counter, defaultdict

from thesisound.ports import ParsedBlock

_MARGIN_KINDS = {"page_header", "page_footer", "header", "footer"}


def remove_repeated_margins(
    blocks: list[ParsedBlock],
    *,
    minimum_repetitions: int = 3,
    maximum_characters: int = 160,
) -> tuple[list[ParsedBlock], list[str]]:
    """Remove only high-confidence repeated page furniture.

    Explicit header/footer labels are removed immediately. Unlabelled text is
    removed only when the same short normalized string appears on at least three
    distinct pages. Headings, tables, formulas, code, and blocks without page
    provenance are never removed by the repetition heuristic.
    """

    page_sets: dict[str, set[int]] = defaultdict(set)
    counts: Counter[str] = Counter()
    for block in blocks:
        normalized = _normalize(block.text)
        if not _eligible_for_heuristic(block, normalized, maximum_characters):
            continue
        counts[normalized] += 1
        if block.page_start is not None:
            page_sets[normalized].add(block.page_start)
        if block.page_end is not None:
            page_sets[normalized].add(block.page_end)

    repeated = {
        text
        for text, count in counts.items()
        if count >= minimum_repetitions and len(page_sets[text]) >= minimum_repetitions
    }

    kept: list[ParsedBlock] = []
    removed: list[str] = []
    for block in blocks:
        kind = block.kind.casefold()
        normalized = _normalize(block.text)
        explicit_margin = kind in _MARGIN_KINDS
        inferred_margin = normalized in repeated and kind not in {
            "heading",
            "title",
            "section_header",
            "table",
            "formula",
            "code",
        }
        if explicit_margin or inferred_margin:
            removed.append(block.source_block_key)
        else:
            kept.append(block)
    return kept, removed


def _eligible_for_heuristic(block: ParsedBlock, normalized: str, limit: int) -> bool:
    return bool(
        normalized
        and len(normalized) <= limit
        and block.page_start is not None
        and block.kind.casefold()
        not in {"heading", "title", "section_header", "table", "formula", "code"}
    )


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())
