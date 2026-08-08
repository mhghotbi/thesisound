
from __future__ import annotations

import shutil
from importlib.util import find_spec
from pathlib import Path
from uuid import UUID

from thesisound.adapters.parsers.docling_adapter import DoclingParser
from thesisound.adapters.parsers.epub_adapter import EpubDocumentParser
from thesisound.adapters.parsers.local_ocr_adapter import LocalOcrParser
from thesisound.adapters.parsers.mineru_adapter import MineruParser
from thesisound.adapters.parsers.native_adapter import NativeDocumentParser
from thesisound.config import Settings
from thesisound.ports import DocumentParserPort
from thesisound.quality import ParseIssue, ParseReport
from thesisound.services.artifact_writer import IngestionArtifactWriter
from thesisound.services.document_ingestion import ingest_document
from thesisound.web.source_manifest import UiSourceManifest, UiSourceStatus

_ISSUE_LABELS = {
    "missing_text": "بخشی از متن احتمالاً استخراج نشده",
    "wrong_reading_order": "ترتیب خواندن بخشی از متن مشکوک است",
    "ocr_corruption": "در بخشی از OCR نویسه‌های خراب دیده شده",
    "lost_headings": "برخی عنوان‌ها یا ساختار بخش‌ها از دست رفته",
    "table_damage": "ساختار برخی جدول‌ها آسیب دیده",
    "formula_damage": "برخی فرمول‌ها کامل استخراج نشده",
    "repetition": "بخشی از متن تکراری تشخیص داده شده",
    "locator_mismatch": "شماره صفحه یا نشانی بخشی از متن دقیق نیست",
    "language_inconsistency": "زبان یا جهت متن در بخشی ناسازگار است",
    "other": "یک مسئله استخراج ثبت شده",
}
_SEVERITY_LABELS = {
    "low": "کم‌اهمیت", "medium": "متوسط", "high": "جدی", "blocking": "مسدودکننده",
}


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
        issue_summary=_quality_summary(status, quality),
        quality_issues=_quality_issue_messages(quality),
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
    """Configure parsers without loading any model into the web process."""

    parsers: dict[str, DocumentParserPort] = {
        "native": NativeDocumentParser(),
        "epub": EpubDocumentParser(),
    }
    local_ocr = LocalOcrParser.from_environment(
        output_root=writer.root / "raw" / "local-ocr"
    )
    if local_ocr.is_ready():
        parsers["local-ocr"] = local_ocr
    if find_spec("docling") is not None:
        parsers["docling"] = DoclingParser(offline=True)
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


def _quality_summary(status: UiSourceStatus, quality: ParseReport | None) -> str | None:
    verdict = quality.verdict if quality else None
    if status == UiSourceStatus.READY and verdict == "pass":
        return "استخراج با موفقیت انجام شد و متن برای ساخت شاهدها قابل‌استفاده است."
    if status == UiSourceStatus.READY:
        return (
            "متن قابل‌استفاده است و تحلیل ادامه پیدا می‌کند. برچسب «هشدار» یعنی "
            "استخراج متوقف نشده، اما چند مورد برای شفافیت ثبت شده است؛ جزئیات را "
            "پایین همین منبع ببینید."
        )
    if status == UiSourceStatus.REVIEW:
        return (
            "متن استخراج شده، اما کیفیت آن برای استناد خودکار کافی نیست. این منبع "
            "تا زمان رفع مسئله وارد شاهدها نمی‌شود."
        )
    return "از این فایل متن قابل‌اتکایی تولید نشد؛ فایل یا استخراج‌کننده دیگری لازم است."


def _quality_issue_messages(quality: ParseReport | None) -> list[str]:
    if quality is None:
        return []
    return [_describe_issue(issue) for issue in quality.issues]


def _describe_issue(issue: ParseIssue) -> str:
    label = _ISSUE_LABELS.get(issue.issue_type, _ISSUE_LABELS["other"])
    severity = _SEVERITY_LABELS.get(issue.severity, issue.severity)
    locator = _locator_summary(issue)
    evidence = " ".join(issue.evidence.split())[:240]
    parts = [f"{label} (شدت: {severity})"]
    if locator:
        parts.append(locator)
    if evidence:
        parts.append(f"نشانه ثبت‌شده: {evidence}")
    return "؛ ".join(parts)


def _locator_summary(issue: ParseIssue) -> str | None:
    pages: list[str] = []
    for locator in issue.affected_locators:
        if locator.page_start is None:
            continue
        if locator.page_end and locator.page_end != locator.page_start:
            pages.append(f"صفحه‌های {locator.page_start} تا {locator.page_end}")
        else:
            pages.append(f"صفحه {locator.page_start}")
    if not pages:
        return None
    return "محل: " + "، ".join(dict.fromkeys(pages))


def _ingestion_error_message(error: Exception) -> str:
    if isinstance(error, FileNotFoundError):
        return "فایل بارگذاری‌شده پیدا نشد."
    if isinstance(error, ValueError):
        return f"فایل قابل پردازش نیست: {str(error)[:240]}"
    return f"پردازش فایل با خطای {type(error).__name__} متوقف شد."
