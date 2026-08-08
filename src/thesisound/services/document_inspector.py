from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Any

from thesisound.ports import DocumentInspection

_PDF_HEADER = b"%PDF-"
_TEXT_SAMPLE_BYTES = 256_000
_COMPLEX_LAYOUT_PATTERNS = (
    re.compile(r"\S {4,}\S"),
    re.compile(r"(?:^|\n).{0,40}\s{8,}.{0,40}(?:\n|$)"),
)


class DocumentInspectionError(ValueError):
    """Raised when a source cannot be safely inspected."""


def inspect_document(path: Path) -> DocumentInspection:
    """Inspect a local document without invoking a parser or model.

    Unknown values remain unknown and are reported as warnings instead of
    being guessed. PDF page sampling uses the lightweight ``pypdf`` dependency.
    """

    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    if not resolved.is_file():
        raise DocumentInspectionError(f"Expected a file, got: {resolved}")

    size = resolved.stat().st_size
    if size == 0:
        raise DocumentInspectionError(f"Document is empty: {resolved}")

    extension = resolved.suffix.lower()
    header = _read_prefix(resolved, 16)
    mime_type = _detect_mime_type(resolved, header)
    warnings: list[str] = []

    page_count: int | None = None
    encrypted = False
    sampled_text_characters = 0
    image_only_ratio: float | None = None
    likely_complex_layout = False

    if header.startswith(_PDF_HEADER) or extension == ".pdf":
        if not header.startswith(_PDF_HEADER):
            warnings.append("The .pdf extension is present but the PDF header is missing.")
        pdf_metrics = _inspect_pdf(resolved)
        page_count = pdf_metrics["page_count"]
        encrypted = pdf_metrics["encrypted"]
        sampled_text_characters = pdf_metrics["sampled_text_characters"]
        image_only_ratio = pdf_metrics["image_only_ratio"]
        likely_complex_layout = pdf_metrics["likely_complex_layout"]
        warnings.extend(pdf_metrics["warnings"])
    else:
        sample = _read_prefix(resolved, _TEXT_SAMPLE_BYTES)
        decoded = _decode_text_sample(sample)
        if decoded is not None:
            sampled_text_characters = len(decoded.strip())
            likely_complex_layout = _looks_like_complex_layout(decoded)
        else:
            warnings.append("No safe text sample could be decoded during inspection.")

    return DocumentInspection(
        path=resolved,
        mime_type=mime_type,
        extension=extension,
        file_size_bytes=size,
        sha256=_sha256(resolved),
        page_count=page_count,
        encrypted=encrypted,
        sampled_text_characters=sampled_text_characters,
        image_only_ratio=image_only_ratio,
        likely_complex_layout=likely_complex_layout,
        warnings=warnings,
    )


def _inspect_pdf(path: Path) -> dict[str, Any]:
    warnings: list[str] = []
    try:
        from pypdf import PdfReader
    except ImportError:
        return {
            "page_count": None,
            "encrypted": False,
            "sampled_text_characters": 0,
            "image_only_ratio": None,
            "likely_complex_layout": False,
            "warnings": [
                "Install pypdf to inspect PDF pages, encryption, and text coverage."
            ],
        }

    try:
        reader = PdfReader(path, strict=False)
    except Exception as exc:  # pypdf exposes several parser-specific exceptions
        return {
            "page_count": None,
            "encrypted": False,
            "sampled_text_characters": 0,
            "image_only_ratio": None,
            "likely_complex_layout": False,
            "warnings": [f"pypdf could not inspect this PDF: {type(exc).__name__}"],
        }

    encrypted = bool(reader.is_encrypted)
    if encrypted:
        try:
            page_count = len(reader.pages)
        except Exception:
            page_count = None
        return {
            "page_count": page_count,
            "encrypted": True,
            "sampled_text_characters": 0,
            "image_only_ratio": None,
            "likely_complex_layout": False,
            "warnings": ["Encrypted PDFs require explicit decryption before parsing."],
        }

    page_count = len(reader.pages)
    sample_indices = _sample_page_indices(page_count)
    extracted_samples: list[str] = []
    empty_pages = 0
    for index in sample_indices:
        try:
            text = reader.pages[index].extract_text() or ""
        except Exception as exc:
            warnings.append(
                f"Text extraction failed on sampled page {index + 1}: {type(exc).__name__}"
            )
            text = ""
        stripped = text.strip()
        extracted_samples.append(stripped)
        if not stripped:
            empty_pages += 1

    combined = "\n".join(extracted_samples).strip()
    ratio = empty_pages / len(sample_indices) if sample_indices else None
    return {
        "page_count": page_count,
        "encrypted": False,
        "sampled_text_characters": len(combined),
        "image_only_ratio": ratio,
        "likely_complex_layout": _looks_like_complex_layout(combined),
        "warnings": warnings,
    }


def _sample_page_indices(page_count: int) -> list[int]:
    if page_count <= 0:
        return []
    candidates = {0, page_count // 2, page_count - 1}
    return sorted(index for index in candidates if 0 <= index < page_count)


def _looks_like_complex_layout(text: str) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in _COMPLEX_LAYOUT_PATTERNS)


def _detect_mime_type(path: Path, header: bytes) -> str:
    if header.startswith(_PDF_HEADER):
        return "application/pdf"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _decode_text_sample(data: bytes) -> str | None:
    for encoding in ("utf-8", "utf-8-sig", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _read_prefix(path: Path, size: int) -> bytes:
    with path.open("rb") as handle:
        return handle.read(size)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
