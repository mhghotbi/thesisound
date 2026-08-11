from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from thesisound.ports import DocumentInspection, ParsedDocument
from thesisound.quality import ParseReport


class ParserRoute(BaseModel):
    primary: str
    fallbacks: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    @property
    def ordered_parsers(self) -> list[str]:
        return [self.primary, *self.fallbacks]


class ParseAttempt(BaseModel):
    parser_name: str
    status: Literal["success", "error", "skipped"]
    duration_seconds: float = Field(ge=0)
    parsed: ParsedDocument | None = None
    quality: ParseReport | None = None
    error_type: str | None = None
    error_message: str | None = None
    from_cache: bool = False


class IngestionResult(BaseModel):
    inspection: DocumentInspection
    route: ParserRoute
    attempts: list[ParseAttempt]
    selected_parser: str | None = None
    parsed: ParsedDocument | None = None
    quality: ParseReport | None = None
    safe_for_claim_extraction: bool = False


class ParserBenchmarkMetrics(BaseModel):
    parser_name: str
    status: Literal["success", "error", "skipped"]
    duration_seconds: float = Field(ge=0)
    verdict: str | None = None
    safe_for_claim_extraction: bool = False
    block_count: int = Field(default=0, ge=0)
    text_characters: int = Field(default=0, ge=0)
    locator_coverage: float = Field(default=0, ge=0, le=1)
    page_coverage: float | None = Field(default=None, ge=0, le=1)
    heading_coverage: float = Field(default=0, ge=0, le=1)
    duplicate_ratio: float = Field(default=0, ge=0, le=1)
    formula_blocks: int = Field(default=0, ge=0)
    table_blocks: int = Field(default=0, ge=0)
    blocks_per_page: float | None = Field(default=None, ge=0)
    reading_order_regression_ratio: float = Field(default=0, ge=0, le=1)
    math_signal_strength: int = Field(default=0, ge=0, le=3)
    table_signal_strength: int = Field(default=0, ge=0, le=3)
    issue_count: int = Field(default=0, ge=0)
    score: float = Field(default=0, ge=0, le=100)
    error_type: str | None = None
    error_message: str | None = None


class DocumentBenchmark(BaseModel):
    path: Path
    sha256: str
    metrics: list[ParserBenchmarkMetrics]
    recommended_parser: str | None = None


class BenchmarkAggregate(BaseModel):
    parser_name: str
    documents_attempted: int = Field(ge=0)
    successful_documents: int = Field(ge=0)
    safe_documents: int = Field(ge=0)
    mean_score: float = Field(ge=0, le=100)
    mean_duration_seconds: float = Field(ge=0)


class BenchmarkSuite(BaseModel):
    root: Path
    documents: list[DocumentBenchmark]
    aggregate: list[BenchmarkAggregate]
