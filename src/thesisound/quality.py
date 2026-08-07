from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from thesisound.domain import Locator


class ParseIssue(BaseModel):
    issue_type: Literal[
        "missing_text",
        "wrong_reading_order",
        "ocr_corruption",
        "lost_headings",
        "table_damage",
        "formula_damage",
        "repetition",
        "locator_mismatch",
        "language_inconsistency",
        "other",
    ]
    severity: Literal["low", "medium", "high", "blocking"]
    affected_locators: list[Locator] = Field(default_factory=list)
    evidence: str


class ParseReport(BaseModel):
    verdict: Literal["pass", "warning", "retry", "manual_review"]
    issues: list[ParseIssue] = Field(default_factory=list)
    suggested_parser: str | None = None
    safe_for_claim_extraction: bool
