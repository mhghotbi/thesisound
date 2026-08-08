from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from statistics import fmean
from time import perf_counter

from thesisound.ingestion import (
    BenchmarkAggregate,
    BenchmarkSuite,
    DocumentBenchmark,
    ParserBenchmarkMetrics,
)
from thesisound.ports import DocumentInspection, DocumentParserPort, ParsedBlock
from thesisound.services.artifact_writer import IngestionArtifactWriter
from thesisound.services.document_inspector import inspect_document
from thesisound.services.parse_quality import assess_parse_quality, duplicate_content_ratio

_SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".epub",
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".htm",
    ".md",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}


def benchmark_document(
    path: Path,
    *,
    parsers: Mapping[str, DocumentParserPort],
    artifact_writer: IngestionArtifactWriter | None = None,
) -> DocumentBenchmark:
    inspection = inspect_document(path)
    if artifact_writer is not None:
        artifact_writer.write_inspection(inspection)

    metrics: list[ParserBenchmarkMetrics] = []
    for name, parser in parsers.items():
        if not parser.supports(inspection):
            metrics.append(
                ParserBenchmarkMetrics(
                    parser_name=name,
                    status="skipped",
                    duration_seconds=0,
                    error_type="UnsupportedDocument",
                    error_message=f"Parser '{name}' does not support this document.",
                )
            )
            continue

        started = perf_counter()
        try:
            parsed = parser.parse(path, inspection)
            quality = assess_parse_quality(inspection, parsed)
            metrics.append(
                _build_metrics(
                    inspection,
                    name,
                    parsed.blocks,
                    duration_seconds=perf_counter() - started,
                    quality=quality,
                )
            )
        except Exception as exc:  # adapters intentionally isolate provider exceptions
            metrics.append(
                ParserBenchmarkMetrics(
                    parser_name=name,
                    status="error",
                    duration_seconds=perf_counter() - started,
                    error_type=type(exc).__name__,
                    error_message=str(exc)[:1_000],
                )
            )

    successful = [metric for metric in metrics if metric.status == "success"]
    recommended = max(successful, key=_recommendation_key).parser_name if successful else None
    benchmark = DocumentBenchmark(
        path=inspection.path,
        sha256=inspection.sha256,
        metrics=metrics,
        recommended_parser=recommended,
    )
    if artifact_writer is not None:
        artifact_writer.write_benchmark(benchmark)
    return benchmark


def benchmark_directory(
    root: Path,
    *,
    parsers: Mapping[str, DocumentParserPort],
    recursive: bool = False,
    artifact_writer: IngestionArtifactWriter | None = None,
) -> BenchmarkSuite:
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)
    documents = [
        benchmark_document(path, parsers=parsers, artifact_writer=artifact_writer)
        for path in iter_documents(resolved, recursive=recursive)
    ]
    return BenchmarkSuite(
        root=resolved,
        documents=documents,
        aggregate=_aggregate(documents, parsers.keys()),
    )


def iter_documents(root: Path, *, recursive: bool) -> Iterable[Path]:
    iterator = root.rglob("*") if recursive else root.glob("*")
    return (
        path
        for path in sorted(iterator)
        if path.is_file() and path.suffix.lower() in _SUPPORTED_EXTENSIONS
    )


def _build_metrics(
    inspection: DocumentInspection,
    parser_name: str,
    blocks: list[ParsedBlock],
    *,
    duration_seconds: float,
    quality,
) -> ParserBenchmarkMetrics:
    non_empty = [block for block in blocks if block.text.strip()]
    block_count = len(non_empty)
    text_characters = sum(len(block.text.strip()) for block in non_empty)
    locator_coverage = (
        sum(block.page_start is not None for block in non_empty) / block_count
        if block_count
        else 0
    )
    heading_coverage = (
        sum(block.kind == "heading" or bool(block.heading_path) for block in non_empty)
        / block_count
        if block_count
        else 0
    )
    duplicate_ratio = duplicate_content_ratio(non_empty)
    page_coverage = _page_coverage(inspection, non_empty)
    score = _score(
        verdict=quality.verdict,
        safe=quality.safe_for_claim_extraction,
        locator_coverage=locator_coverage,
        page_coverage=page_coverage,
        heading_coverage=heading_coverage,
        duplicate_ratio=duplicate_ratio,
        issue_count=len(quality.issues),
    )
    return ParserBenchmarkMetrics(
        parser_name=parser_name,
        status="success",
        duration_seconds=duration_seconds,
        verdict=quality.verdict,
        safe_for_claim_extraction=quality.safe_for_claim_extraction,
        block_count=block_count,
        text_characters=text_characters,
        locator_coverage=locator_coverage,
        page_coverage=page_coverage,
        heading_coverage=heading_coverage,
        duplicate_ratio=duplicate_ratio,
        issue_count=len(quality.issues),
        score=score,
    )


def _score(
    *,
    verdict: str,
    safe: bool,
    locator_coverage: float,
    page_coverage: float | None,
    heading_coverage: float,
    duplicate_ratio: float,
    issue_count: int,
) -> float:
    verdict_score = {
        "pass": 60,
        "warning": 48,
        "retry": 20,
        "manual_review": 5,
    }.get(verdict, 0)
    score = verdict_score
    score += 12 * locator_coverage
    score += 12 * (page_coverage if page_coverage is not None else locator_coverage)
    score += 8 * min(heading_coverage * 4, 1)
    score += 8 if safe else 0
    score -= 12 * duplicate_ratio
    score -= min(issue_count * 2, 10)
    return round(min(max(score, 0), 100), 2)


def _page_coverage(
    inspection: DocumentInspection,
    blocks: list[ParsedBlock],
) -> float | None:
    if not inspection.page_count:
        return None
    pages: set[int] = set()
    for block in blocks:
        if block.page_start is None:
            continue
        end = block.page_end if block.page_end is not None else block.page_start
        pages.update(range(block.page_start, end + 1))
    return min(len(pages) / inspection.page_count, 1)


def _recommendation_key(metric: ParserBenchmarkMetrics) -> tuple[int, float, float]:
    return (
        int(metric.safe_for_claim_extraction),
        metric.score,
        -metric.duration_seconds,
    )


def _aggregate(
    documents: list[DocumentBenchmark],
    parser_names: Iterable[str],
) -> list[BenchmarkAggregate]:
    by_parser: dict[str, list[ParserBenchmarkMetrics]] = defaultdict(list)
    for document in documents:
        for metric in document.metrics:
            by_parser[metric.parser_name].append(metric)

    aggregates: list[BenchmarkAggregate] = []
    for parser_name in parser_names:
        values = by_parser.get(parser_name, [])
        successful = [value for value in values if value.status == "success"]
        aggregates.append(
            BenchmarkAggregate(
                parser_name=parser_name,
                documents_attempted=len(values),
                successful_documents=len(successful),
                safe_documents=sum(value.safe_for_claim_extraction for value in successful),
                mean_score=fmean(value.score for value in successful) if successful else 0,
                mean_duration_seconds=(
                    fmean(value.duration_seconds for value in successful) if successful else 0
                ),
            )
        )
    return aggregates
