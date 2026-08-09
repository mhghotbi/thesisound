
from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import cache
from importlib import metadata
from pathlib import Path
from typing import Any

from thesisound.ports import DocumentInspection, ParsedDocument
from thesisound.services import document_normalizer
from thesisound.services.document_normalizer import normalize_docling_document
from thesisound.services.parser_identity import module_fingerprint

_SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".md", ".txt", ".epub",
    ".png", ".jpg", ".jpeg", ".tiff",
}


class DoclingUnavailableError(RuntimeError):
    """Raised when the optional Docling dependency is not installed."""


class DocumentParseError(RuntimeError):
    """Raised when Docling cannot return a usable document."""


@cache
def _cached_docling_version() -> str:
    try:
        return metadata.version("docling")
    except metadata.PackageNotFoundError:
        return "unknown"


class DoclingParser:
    name = "docling"

    def __init__(
        self,
        converter_factory: Callable[[], Any] | None = None,
        version_resolver: Callable[[], str] | None = None,
        *,
        offline: bool = True,
    ) -> None:
        self._converter_factory = converter_factory
        self._version_resolver = version_resolver
        self.offline = offline

    def supports(self, inspection: DocumentInspection) -> bool:
        return inspection.extension in _SUPPORTED_EXTENSIONS and not inspection.encrypted

    def identity(self) -> dict[str, str] | None:
        # An injected converter or version resolver means this instance's output
        # is not (only) Docling's -- typically a test double -- so it must never
        # be shared under a "docling" identity.
        if self._converter_factory is not None or self._version_resolver is not None:
            return None
        version = self._version()
        if version == "unknown":
            return None
        impl = module_fingerprint(sys.modules[__name__], document_normalizer)
        if impl is None:
            return None
        return {
            "parser": "docling",
            "docling": version,
            "offline": str(self.offline),
            "impl": impl,
        }

    def parse(self, path: Path, inspection: DocumentInspection) -> ParsedDocument:
        resolved = path.expanduser().resolve()
        if resolved != inspection.path.expanduser().resolve():
            raise ValueError("The inspected path and parsed path must refer to the same file.")
        if not self.supports(inspection):
            raise DocumentParseError(
                f"Docling does not support this inspection: {inspection.extension or 'unknown'}"
            )
        with _offline_model_environment(enabled=self.offline):
            converter = self._make_converter()
            try:
                result = converter.convert(resolved)
            except Exception as exc:
                raise DocumentParseError(
                    f"Docling conversion failed offline: {type(exc).__name__}. "
                    "Provision every required model during build/deploy; "
                    "runtime downloads are disabled."
                ) from exc

        document = getattr(result, "document", None)
        if document is None:
            raise DocumentParseError("Docling conversion returned no document.")
        parsed = normalize_docling_document(document, parser_version=self._version())
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
        return _cached_docling_version()


@contextmanager
def _offline_model_environment(*, enabled: bool) -> Iterator[None]:
    if not enabled:
        yield
        return
    updates = {
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "DO_NOT_TRACK": "1",
    }
    previous = {key: os.environ.get(key) for key in updates}
    removed_tokens = {
        key: os.environ.pop(key, None)
        for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_HUB_TOKEN")
    }
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for key, value in removed_tokens.items():
            if value is not None:
                os.environ[key] = value
