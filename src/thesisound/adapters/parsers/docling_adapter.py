from __future__ import annotations

from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any

from thesisound.ports import DocumentInspection, ParsedDocument
from thesisound.services.document_normalizer import normalize_docling_document

_SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".htm",
    ".md",
    ".txt",
    ".epub",
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
}


class DoclingUnavailableError(RuntimeError):
    """Raised when the optional Docling dependency is not installed."""


class DocumentParseError(RuntimeError):
    """Raised when Docling cannot return a usable document."""


class DoclingParser:
    name = "docling"

    def __init__(
        self,
        converter_factory: Callable[[], Any] | None = None,
        version_resolver: Callable[[], str] | None = None,
    ) -> None:
        self._converter_factory = converter_factory
        self._version_resolver = version_resolver

    def supports(self, inspection: DocumentInspection) -> bool:
        return inspection.extension in _SUPPORTED_EXTENSIONS and not inspection.encrypted

    def parse(self, path: Path, inspection: DocumentInspection) -> ParsedDocument:
        resolved = path.expanduser().resolve()
        if resolved != inspection.path.expanduser().resolve():
            raise ValueError("The inspected path and parsed path must refer to the same file.")
        if not self.supports(inspection):
            raise DocumentParseError(
                f"Docling does not support this inspection: {inspection.extension or 'unknown'}"
            )

        converter = self._make_converter()
        try:
            result = converter.convert(resolved)
        except Exception as exc:
            raise DocumentParseError(f"Docling conversion failed: {type(exc).__name__}") from exc

        document = getattr(result, "document", None)
        if document is None:
            raise DocumentParseError("Docling conversion returned no document.")

        parsed = normalize_docling_document(
            document,
            parser_version=self._version(),
        )
        if not parsed.blocks:
            raise DocumentParseError("Docling produced no usable content blocks.")
        return parsed

    def _make_converter(self) -> Any:
        if self._converter_factory is not None:
            return self._converter_factory()
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise DoclingUnavailableError(
                "Docling is optional. Install it with: uv sync --extra parsers"
            ) from exc
        return DocumentConverter()

    def _version(self) -> str:
        if self._version_resolver is not None:
            return self._version_resolver()
        try:
            return metadata.version("docling")
        except metadata.PackageNotFoundError:
            return "unknown"
