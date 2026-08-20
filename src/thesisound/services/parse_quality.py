from __future__ import annotations

import re
from collections import Counter

from thesisound.domain import Locator
from thesisound.ports import DocumentInspection, ParsedBlock, ParsedDocument
from thesisound.quality import ParseIssue, ParseReport

_NORMALIZE_SPACE = re.compile(r"\s+")
_SUSPICIOUS_OCR = re.compile(r"(?:\ufffd|\x00|[|Il1]{8,}|[^\w\s]{12,})")
_MIN_DUPLICATE_CONTENT_CHARACTERS = 80
_LATEX_COMMAND = re.compile(
    r"\\(?:frac|sum|prod|int|mathrm|mathbf|left|right|begin|end|alpha|beta|gamma|"
    r"delta|theta|lambda|sigma|omega|partial|infty|cdot|times|leq|geq|neq)\b"
)
_INLINE_MATH = re.compile(r"(?<!\$)\$(?!\$)([^$\n]{1,120})\$(?!\$)")
_DISPLAY_MATH = re.compile(r"\$\$[^$]+\$\$|\\\[[^\]]+\\\]|\\\([^)]+\\\)")
_UNICODE_MATH = re.compile(r"[∑∏∫∂∇∞≈≠≤≥±×·√∈∉⊂⊃∀∃→←⇒⇔αβγδθλμσφω]")
_PIPE_ROW = re.compile(r"^\s*\|.+\|\s*$", re.MULTILINE)
_TAB_ROW = re.compile(r"^[^\t\n]+\t+[^\t\n]+(?:\t+[^\t\n]+)+$", re.MULTILINE)
_FRAGMENTATION_BLOCKS_PER_PAGE = 40
_FRAGMENTATION_MEAN_CHARS = 80
_READING_ORDER_MIN_LOCATED = 8


def assess_parse_quality(
    inspection: DocumentInspection,
    parsed: ParsedDocument,
) -> ParseReport:
    """Apply deterministic gates before claim extraction is allowed."""

    issues: list[ParseIssue] = []
    suggested_parser: str | None = None

    if inspection.encrypted:
        issues.append(
            ParseIssue(
                issue_type="other",
                severity="blocking",
                evidence="The source is encrypted and was not safely parsed.",
            )
        )

    non_empty = [block for block in parsed.blocks if block.text.strip()]
    if not non_empty:
        issues.append(
            ParseIssue(
                issue_type="missing_text",
                severity="blocking",
                evidence="The parser produced no non-empty blocks.",
            )
        )
        return _build_report(issues, suggested_parser="mineru")

    total_characters = sum(len(block.text.strip()) for block in non_empty)
    if total_characters < 200:
        severity = "high" if inspection.file_size_bytes > 20_000 else "medium"
        issues.append(
            ParseIssue(
                issue_type="missing_text",
                severity=severity,
                evidence=f"Only {total_characters} text characters were parsed.",
            )
        )

    duplicate_ratio = duplicate_content_ratio(non_empty)
    if duplicate_ratio >= 0.25:
        issues.append(
            ParseIssue(
                issue_type="repetition",
                severity="high" if duplicate_ratio >= 0.5 else "medium",
                evidence=(
                    f"{duplicate_ratio:.0%} of substantive parsed characters repeat "
                    "content already emitted."
                ),
            )
        )

    corruption_ratio = _corruption_ratio(non_empty)
    if corruption_ratio >= 0.02:
        issues.append(
            ParseIssue(
                issue_type="ocr_corruption",
                severity="high" if corruption_ratio >= 0.08 else "medium",
                evidence=f"Suspicious OCR patterns affect {corruption_ratio:.1%} of blocks.",
            )
        )
        suggested_parser = "mineru"

    if inspection.mime_type == "application/pdf":
        missing_locator_ratio = sum(
            block.page_start is None for block in non_empty
        ) / len(non_empty)
        if missing_locator_ratio >= 0.2:
            issues.append(
                ParseIssue(
                    issue_type="locator_mismatch",
                    severity="high" if missing_locator_ratio >= 0.6 else "medium",
                    evidence=f"{missing_locator_ratio:.0%} of PDF blocks have no page locator.",
                )
            )

        if inspection.page_count:
            located_pages = {
                page
                for block in non_empty
                for page in _block_pages(block.page_start, block.page_end)
            }
            page_coverage = len(located_pages) / inspection.page_count
            if page_coverage < 0.5 and inspection.page_count >= 4:
                issues.append(
                    ParseIssue(
                        issue_type="missing_text",
                        severity="high" if page_coverage < 0.2 else "medium",
                        affected_locators=[
                            Locator(page_start=1, page_end=inspection.page_count)
                        ],
                        evidence=f"Parsed blocks cover only {page_coverage:.0%} of PDF pages.",
                    )
                )

    if inspection.image_only_ratio is not None and inspection.image_only_ratio >= 0.67:
        issues.append(
            ParseIssue(
                issue_type="missing_text",
                severity="high",
                evidence=(
                    f"{inspection.image_only_ratio:.0%} of sampled pages had no extractable "
                    "text; OCR-oriented parsing is recommended."
                ),
            )
        )
        suggested_parser = "mineru"

    has_heading = any(block.kind == "heading" or block.heading_path for block in non_empty)
    if len(non_empty) >= 12 and not has_heading:
        issues.append(
            ParseIssue(
                issue_type="lost_headings",
                severity="medium",
                evidence="No heading hierarchy survived in a document with at least 12 blocks.",
            )
        )

    joined = "\n".join(block.text for block in non_empty)
    formula_count = sum(1 for block in non_empty if block.kind.casefold() == "formula")
    table_count = sum(1 for block in non_empty if block.kind.casefold() == "table")
    math_strength = math_signal_strength(joined)
    table_strength = table_signal_strength(joined)

    if math_strength >= 2 and formula_count == 0:
        issues.append(
            ParseIssue(
                issue_type="formula_damage",
                severity="high",
                evidence=(
                    f"Math signals are present (strength={math_strength}) but no formula "
                    "blocks were preserved."
                ),
            )
        )
        suggested_parser = "mineru"
    elif math_strength == 1 and formula_count == 0:
        issues.append(
            ParseIssue(
                issue_type="formula_damage",
                severity="medium",
                evidence="Weak math signals are present but no formula blocks were preserved.",
            )
        )
        suggested_parser = suggested_parser or "mineru"

    if (
        table_strength >= 2
        and table_count == 0
        and inspection.mime_type == "application/pdf"
        and (inspection.page_count or 0) >= 2
    ):
        issues.append(
            ParseIssue(
                issue_type="table_damage",
                severity="high" if table_strength >= 3 else "medium",
                evidence=(
                    f"Table-like structure is present (strength={table_strength}) but no "
                    "table blocks were preserved."
                ),
            )
        )
        suggested_parser = suggested_parser or "mineru"

    regression_ratio = reading_order_regression_ratio(non_empty)
    if regression_ratio >= 0.15:
        issues.append(
            ParseIssue(
                issue_type="wrong_reading_order",
                severity="high" if regression_ratio >= 0.3 else "medium",
                evidence=(
                    f"{regression_ratio:.0%} of located block transitions regress in page order."
                ),
            )
        )
        suggested_parser = suggested_parser or "docling"

    fragmentation = fragmentation_stats(inspection, non_empty)
    if fragmentation is not None:
        blocks_per_page, mean_chars = fragmentation
        if (
            blocks_per_page > _FRAGMENTATION_BLOCKS_PER_PAGE
            and mean_chars < _FRAGMENTATION_MEAN_CHARS
        ):
            issues.append(
                ParseIssue(
                    issue_type="other",
                    severity="high" if blocks_per_page > 60 else "medium",
                    evidence=(
                        f"Parsed output is fragmented ({blocks_per_page:.1f} blocks/page, "
                        f"mean {mean_chars:.0f} characters/block)."
                    ),
                )
            )
            suggested_parser = suggested_parser or "mineru"

    return _build_report(issues, suggested_parser=suggested_parser)


def math_signal_strength(text: str) -> int:
    """Return 0–3 strength for LaTeX / math markup surviving in plain text."""

    strength = 0
    latex_hits = len(_LATEX_COMMAND.findall(text))
    inline_hits = len(_INLINE_MATH.findall(text))
    display_hits = len(_DISPLAY_MATH.findall(text))
    unicode_hits = len(_UNICODE_MATH.findall(text))
    if latex_hits >= 2 or display_hits >= 1 or (latex_hits >= 1 and inline_hits >= 1):
        strength = 2
    elif latex_hits >= 1 or inline_hits >= 2 or unicode_hits >= 4:
        strength = 1
    if latex_hits >= 4 or (latex_hits >= 2 and inline_hits >= 2) or unicode_hits >= 10:
        strength = 3
    return strength


def table_signal_strength(text: str) -> int:
    """Return 0–3 strength for tabular markup surviving in plain text."""

    pipe_rows = len(_PIPE_ROW.findall(text))
    tab_rows = len(_TAB_ROW.findall(text))
    if pipe_rows >= 4 or tab_rows >= 4:
        return 3
    if pipe_rows >= 2 or tab_rows >= 2:
        return 2
    if pipe_rows >= 1 or tab_rows >= 1:
        return 1
    return 0


def reading_order_regression_ratio(blocks: list[ParsedBlock]) -> float:
    """Fraction of consecutive located blocks whose page_start decreases."""

    pages = [block.page_start for block in blocks if block.page_start is not None]
    if len(pages) < _READING_ORDER_MIN_LOCATED:
        return 0.0
    regressions = sum(
        1
        for previous, current in zip(pages, pages[1:], strict=False)
        if current < previous
    )
    transitions = len(pages) - 1
    return regressions / transitions if transitions else 0.0


def fragmentation_stats(
    inspection: DocumentInspection,
    blocks: list[ParsedBlock],
) -> tuple[float, float] | None:
    """Return (blocks_per_page, mean_block_chars) for multi-page PDFs."""

    if inspection.mime_type != "application/pdf":
        return None
    page_count = inspection.page_count or 0
    if page_count < 4 or not blocks:
        return None
    mean_chars = sum(len(block.text.strip()) for block in blocks) / len(blocks)
    return len(blocks) / page_count, mean_chars


def _build_report(issues: list[ParseIssue], suggested_parser: str | None) -> ParseReport:
    severities = {issue.severity for issue in issues}
    if "blocking" in severities:
        verdict = "manual_review"
        safe = False
    elif "high" in severities:
        verdict = "retry"
        safe = False
    elif "medium" in severities:
        verdict = "warning"
        safe = True
    else:
        verdict = "pass"
        safe = True
    return ParseReport(
        verdict=verdict,
        issues=issues,
        suggested_parser=suggested_parser,
        safe_for_claim_extraction=safe,
    )


def duplicate_content_ratio(blocks: list[ParsedBlock]) -> float:
    """Return duplicate character share for substantial exact-repeat blocks.

    Academic PDFs may legitimately contain many repeated short tokens in tables,
    diagrams, vocabularies, or visualisation appendices. Counting those blocks
    equally creates false positives. This metric therefore considers only
    normalized blocks with at least 80 characters and weights duplicates by
    character volume.
    """

    normalized = [
        _NORMALIZE_SPACE.sub(" ", block.text.strip()).casefold()
        for block in blocks
        if len(_NORMALIZE_SPACE.sub(" ", block.text.strip()))
        >= _MIN_DUPLICATE_CONTENT_CHARACTERS
    ]
    total_characters = sum(len(text) for text in normalized)
    if total_characters == 0:
        return 0.0
    counts = Counter(normalized)
    duplicate_characters = sum(
        (count - 1) * len(text)
        for text, count in counts.items()
        if count > 1
    )
    return duplicate_characters / total_characters


def _corruption_ratio(blocks: list[ParsedBlock]) -> float:
    if not blocks:
        return 0.0
    suspicious = sum(bool(_SUSPICIOUS_OCR.search(block.text)) for block in blocks)
    return suspicious / len(blocks)


def _block_pages(start: int | None, end: int | None) -> range:
    if start is None:
        return range(0)
    stop = end if end is not None and end >= start else start
    return range(start, stop + 1)
