from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from time import perf_counter

from thesisound import tracing
from thesisound.ingestion import IngestionResult, ParseAttempt, ParserRoute
from thesisound.ports import DocumentParserPort, ParsedDocument, ParserIdentityPort
from thesisound.services.artifact_writer import IngestionArtifactWriter
from thesisound.services.document_inspector import inspect_document
from thesisound.services.parse_quality import assess_parse_quality
from thesisound.services.parsed_document_cache import ParsedDocumentCache, parse_cache_key
from thesisound.services.parser_router import route_parser


class DocumentIngestionError(RuntimeError):
    """Raised when ingestion cannot produce any parsed document."""


def ingest_document(
    path: Path,
    *,
    parsers: Mapping[str, DocumentParserPort],
    parser_name: str = "auto",
    artifact_writer: IngestionArtifactWriter | None = None,
    parse_cache: ParsedDocumentCache | None = None,
) -> IngestionResult:
    with tracing.span(
        "ingestion.ingest_document", component="ingestion", kind="stage", subject_type="document"
    ) as ingest:
        with tracing.span("ingestion.inspect", component="ingestion"):
            inspection = inspect_document(path)
        ingest.set(extension=inspection.extension, encrypted=inspection.encrypted)
        ingest.measure(page_count=inspection.page_count or 0)
        if artifact_writer is not None:
            artifact_writer.write_inspection(inspection)

        with tracing.span("ingestion.route", component="ingestion") as routing:
            route = _resolve_route(inspection, parsers, parser_name)
            routing.set(primary=route.primary, ordered=list(route.ordered_parsers))
        attempts: list[ParseAttempt] = []
        selected_attempt: ParseAttempt | None = None

        for name in route.ordered_parsers:
            with tracing.span(
                "ingestion.parse", component="ingestion", subject_type="parser", subject_id=name
            ) as attempt_span:
                parser = parsers.get(name)
                if parser is None:
                    attempt = ParseAttempt(
                        parser_name=name,
                        status="skipped",
                        duration_seconds=0,
                        error_type="ParserNotConfigured",
                        error_message=f"Parser '{name}' is not configured.",
                    )
                    attempts.append(attempt)
                    attempt_span.mark("skipped", reason="ParserNotConfigured")
                    if artifact_writer is not None:
                        artifact_writer.write_attempt(inspection, attempt)
                    continue
                if not parser.supports(inspection):
                    attempt = ParseAttempt(
                        parser_name=name,
                        status="skipped",
                        duration_seconds=0,
                        error_type="UnsupportedDocument",
                        error_message=f"Parser '{name}' does not support this document.",
                    )
                    attempts.append(attempt)
                    attempt_span.mark("skipped", reason="UnsupportedDocument")
                    if artifact_writer is not None:
                        artifact_writer.write_attempt(inspection, attempt)
                    continue

                # Resolved here rather than above the loop on purpose: MineruParser
                # .identity() shells out to `mineru --version`, and a .txt upload
                # that never reaches mineru must never pay for it.
                cache_key: str | None = None
                identity: Mapping[str, str] | None = None
                cached: ParsedDocument | None = None
                if parse_cache is not None and isinstance(parser, ParserIdentityPort):
                    identity = parser.identity()
                    if identity is not None:
                        cache_key = parse_cache_key(
                            inspection, parser_name=name, identity=identity
                        )
                        cached = parse_cache.load(cache_key, parser_name=name)
                        tracing.event(
                            "cache.lookup",
                            component="cache",
                            cache="shared_parsed_document",
                            result="hit" if cached is not None else "miss",
                            subject_type="parser",
                            subject_id=name,
                            content_key=cache_key[:16],
                        )

                started = perf_counter()
                try:
                    parsed = cached if cached is not None else parser.parse(path, inspection)
                    with tracing.span("ingestion.quality_gate", component="ingestion") as gate:
                        quality = assess_parse_quality(inspection, parsed)
                        gate.set(
                            verdict=quality.verdict, safe=quality.safe_for_claim_extraction
                        )
                    attempt = ParseAttempt(
                        parser_name=name,
                        status="success",
                        duration_seconds=perf_counter() - started,
                        parsed=parsed,
                        quality=quality,
                        from_cache=cached is not None,
                    )
                    attempt_span.measure(block_count=len(parsed.blocks))
                    attempt_span.set(
                        verdict=quality.verdict,
                        source="shared_cache" if cached is not None else "parser",
                    )
                    # Not gated on quality.safe_for_claim_extraction: an
                    # unsafe-but-successful parse is still a correct parse of
                    # these bytes, and caching it is what stops the fallback
                    # chain from re-running a slow parser that will fail the
                    # same gate again.
                    if cached is None and cache_key is not None and identity is not None:
                        parse_cache.save(
                            cache_key,
                            parsed,
                            source_sha256=inspection.sha256,
                            identity=identity,
                        )
                except Exception as exc:  # adapters convert provider details to domain errors
                    attempt = ParseAttempt(
                        parser_name=name,
                        status="error",
                        duration_seconds=perf_counter() - started,
                        error_type=type(exc).__name__,
                        error_message=str(exc)[:1_000],
                    )
                    # The loop deliberately continues to the next parser rather than
                    # aborting, so mark() rather than letting the exception propagate
                    # and end the whole ingest_document span early.
                    attempt_span.mark("error", reason=type(exc).__name__)

                attempts.append(attempt)
                if artifact_writer is not None:
                    artifact_writer.write_attempt(inspection, attempt)

                if attempt.quality is not None and attempt.quality.safe_for_claim_extraction:
                    selected_attempt = attempt
                    break

        if selected_attempt is None:
            successful = [attempt for attempt in attempts if attempt.parsed is not None]
            if successful:
                selected_attempt = max(successful, key=_attempt_rank)

        result = IngestionResult(
            inspection=inspection,
            route=route,
            attempts=attempts,
            selected_parser=selected_attempt.parser_name if selected_attempt else None,
            parsed=selected_attempt.parsed if selected_attempt else None,
            quality=selected_attempt.quality if selected_attempt else None,
            safe_for_claim_extraction=bool(
                selected_attempt
                and selected_attempt.quality
                and selected_attempt.quality.safe_for_claim_extraction
            ),
        )
        ingest.set(
            selected_parser=result.selected_parser,
            safe=result.safe_for_claim_extraction,
        )
        if artifact_writer is not None:
            artifact_writer.write_result(result)
        return result


def _resolve_route(
    inspection,
    parsers: Mapping[str, DocumentParserPort],
    parser_name: str,
) -> ParserRoute:
    if parser_name == "auto":
        return route_parser(inspection, parsers.keys())
    if parser_name not in parsers:
        raise DocumentIngestionError(f"Unknown parser: {parser_name}")
    return ParserRoute(
        primary=parser_name,
        reasons=["The parser was explicitly selected by the caller."],
    )


def _attempt_rank(attempt: ParseAttempt) -> tuple[int, int, int]:
    quality = attempt.quality
    if quality is None:
        return (0, 0, 0)
    verdict_rank = {"pass": 4, "warning": 3, "retry": 2, "manual_review": 1}
    total_text = sum(len(block.text) for block in attempt.parsed.blocks) if attempt.parsed else 0
    return (
        int(quality.safe_for_claim_extraction),
        verdict_rank.get(quality.verdict, 0),
        total_text,
    )
