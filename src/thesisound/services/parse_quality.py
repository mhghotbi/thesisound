from __future__ import annotations

import re
from collections import Counter

from thesisound.domain import Locator
from thesisound.ports import DocumentInspection, ParsedBlock, ParsedDocument
from thesisound.quality import ParseIssue, ParseReport

_NORMALIZE_SPACE = re.compile(r"\s+")
_SUSPICIOUS_OCR = re.compile(r"(?:\ufffd|\x00|[|Il1]{8,}|[^\w\s]{12,})")


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

    duplicate_ratio = _duplicate_ratio(non_empty)
    if duplicate_ratio >= 0.25:
        issues.append(
            ParseIssue(
                issue_type="repetition",
                severity="high" if duplicate_ratio >= 0.5 else "medium",
                evidence=f"{duplicate_ratio:.0%} of normalized blocks are duplicates.",
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

    return _build_report(issues, suggested_parser=suggested_parser)


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


def _duplicate_ratio(blocks: list[ParsedBlock]) -> float:
    normalized = [
        _NORMALIZE_SPACE.sub(" ", block.text.strip()).casefold()
        for block in blocks
        if block.text.strip()
    ]
    if len(normalized) < 2:
        return 0.0
    counts = Counter(normalized)
    duplicate_instances = sum(count - 1 for count in counts.values() if count > 1)
    return duplicate_instances / len(normalized)


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
