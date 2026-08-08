from __future__ import annotations

import shutil
from importlib.util import find_spec
from pathlib import Path
from uuid import UUID

from thesisound.adapters.parsers.docling_adapter import DoclingParser
from thesisound.adapters.parsers.epub_adapter import EpubDocumentParser
from thesisound.adapters.parsers.mineru_adapter import MineruParser
from thesisound.adapters.parsers.native_adapter import NativeDocumentParser
from thesisound.config import Settings
from thesisound.ports import DocumentParserPort
from thesisound.services.artifact_writer import IngestionArtifactWriter
from thesisound.services.document_ingestion import ingest_document
from thesisound.web.source_manifest import UiSourceManifest, UiSourceStatus


def ingest_uploaded_source(
    path: Path,
    *,
    source_id: UUID,
    filename: str,
    content_type: str | None,
    size_bytes: int,
    settings: Settings,
    artifact_root: Path,
) -> UiSourceManifest:
    """Run real inspection, parser routing, quality gates, and artifact persistence."""

    writer = IngestionArtifactWriter(artifact_root)
    parsers = build_web_parsers(settings, writer)
    try:
        result = ingest_document(
            path,
            parsers=parsers,
            parser_name="auto",
            artifact_writer=writer,
        )
    except Exception as exc:
        return UiSourceManifest(
            source_id=source_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            status=UiSourceStatus.BLOCKED,
            issue_summary=_ingestion_error_message(exc),
            attempted_parsers=list(parsers),
        )

    parsed = result.parsed
    quality = result.quality
    if result.safe_for_claim_extraction:
        status = UiSourceStatus.READY
    elif parsed is not None:
        status = UiSourceStatus.REVIEW
    else:
        status = UiSourceStatus.BLOCKED

    result_path = writer.document_dir(result.inspection) / "ingestion-result.json"
    artifact_ref = str(result_path.relative_to(writer.root)) if result_path.exists() else None
    return UiSourceManifest(
        source_id=source_id,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        status=status,
        issue_summary=_quality_summary(status, quality.verdict if quality else None),
        parser_name=result.selected_parser,
        quality_verdict=quality.verdict if quality else None,
        safe_for_claim_extraction=result.safe_for_claim_extraction,
        block_count=len(parsed.blocks) if parsed else 0,
        text_characters=(sum(len(block.text) for block in parsed.blocks) if parsed else 0),
        attempted_parsers=[attempt.parser_name for attempt in result.attempts],
        artifact_ref=artifact_ref,
        inspection_sha256=result.inspection.sha256,
    )


def build_web_parsers(
    settings: Settings,
    writer: IngestionArtifactWriter,
) -> dict[str, DocumentParserPort]:
    """Configure locally available parsers with safe native and EPUB baselines."""

    parsers: dict[str, DocumentParserPort] = {
        "native": NativeDocumentParser(),
        "epub": EpubDocumentParser(),
    }
    if find_spec("docling") is not None:
        parsers["docling"] = DoclingParser()
    if _command_available(settings.mineru_command):
        parsers["mineru"] = MineruParser(
            command=settings.mineru_command,
            timeout_seconds=settings.mineru_timeout_seconds,
            backend=settings.mineru_backend,
            model_source=settings.mineru_model_source,
            output_root=writer.root / "raw" / "mineru",
        )
    return parsers


def _command_available(command: str) -> bool:
    candidate = Path(command).expanduser()
    if candidate.parent != Path(".") or candidate.is_absolute():
        return candidate.exists() and candidate.is_file()
    return shutil.which(command) is not None


def _quality_summary(status: UiSourceStatus, verdict: str | None) -> str | None:
    if status == UiSourceStatus.READY and verdict == "pass":
        return None
    if status == UiSourceStatus.READY:
        return "فایل قابل‌استفاده است، اما چند هشدار غیرمسدودکننده در استخراج ثبت شد."
    if status == UiSourceStatus.REVIEW:
        return "استخراج انجام شد، اما کیفیت برای استفاده خودکار کافی نیست و باید بازبینی شود."
    return "هیچ خروجی قابل‌اتکایی برای این فایل تولید نشد."


def _ingestion_error_message(error: Exception) -> str:
    if isinstance(error, FileNotFoundError):
        return "فایل بارگذاری‌شده پیدا نشد."
    if isinstance(error, ValueError):
        return f"فایل قابل پردازش نیست: {str(error)[:240]}"
    return f"پردازش فایل با خطای {type(error).__name__} متوقف شد."
