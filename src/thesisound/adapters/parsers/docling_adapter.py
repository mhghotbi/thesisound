from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import cache
from importlib import metadata
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from thesisound.ports import DocumentInspection, ParsedBlock, ParsedDocument
from thesisound.services import document_normalizer
from thesisound.services.document_normalizer import normalize_docling_document
from thesisound.services.parser_identity import module_fingerprint

_SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".md", ".txt", ".epub",
    ".png", ".jpg", ".jpeg", ".tiff",
}

_DEFAULT_TIMEOUT_SECONDS = 360


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


def _docling_convert_worker(
    path: str,
    *,
    offline: bool,
    parser_version: str,
) -> dict[str, Any]:
    """Killable process entrypoint for Docling conversion."""

    resolved = Path(path)
    with _offline_model_environment(enabled=offline):
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise DoclingUnavailableError(
                "Docling is optional. Install it with: uv sync --extra parsers"
            ) from exc
        try:
            result = DocumentConverter().convert(resolved)
        except Exception as exc:
            raise DocumentParseError(
                f"Docling conversion failed offline: {type(exc).__name__}. "
                "Provision every required model during build/deploy; "
                "runtime downloads are disabled."
            ) from exc

    document = getattr(result, "document", None)
    if document is None:
        raise DocumentParseError("Docling conversion returned no document.")
    parsed = normalize_docling_document(document, parser_version=parser_version)
    if not parsed.blocks:
        raise DocumentParseError("Docling produced no usable content blocks.")
    return parsed.model_dump(mode="json")


def testing_slow_convert_worker(
    path: str,
    *,
    offline: bool,
    parser_version: str,
) -> dict[str, Any]:
    """Test-only worker that exceeds any short timeout."""

    del path, offline, parser_version
    import time

    time.sleep(30)
    return ParsedDocument(
        parser_name="docling",
        parser_version="test",
        blocks=[
            ParsedBlock(
                source_block_key="late",
                text="Timed-out worker payload.",
                page_start=1,
                page_end=1,
                kind="text",
            )
        ],
    ).model_dump(mode="json")


def testing_fast_convert_worker(
    path: str,
    *,
    offline: bool,
    parser_version: str,
) -> dict[str, Any]:
    """Test-only worker that returns a minimal safe parse."""

    del path, offline
    return ParsedDocument(
        parser_name="docling",
        parser_version=parser_version,
        blocks=[
            ParsedBlock(
                source_block_key="ok",
                text="A" * 250,
                page_start=1,
                page_end=1,
                kind="text",
                heading_path=["Ok"],
            )
        ],
    ).model_dump(mode="json")


def _docling_worker_main(
    queue: Any,
    path: str,
    offline: bool,
    parser_version: str,
    worker_name: str | None,
) -> None:
    """Child-process wrapper that always puts a tagged result on the queue."""

    try:
        worker = _resolve_convert_worker(worker_name)
        payload = worker(path, offline=offline, parser_version=parser_version)
        queue.put(("ok", payload))
    except Exception as exc:  # noqa: BLE001 - boundary to parent process
        queue.put(("error", type(exc).__name__, str(exc)))


def _resolve_convert_worker(worker_name: str | None) -> Callable[..., dict[str, Any]]:
    if worker_name is None:
        return _docling_convert_worker
    module_name, _, attr = worker_name.rpartition(":")
    if not module_name or not attr:
        raise DocumentParseError(f"Invalid Docling worker reference: {worker_name}")
    module = __import__(module_name, fromlist=[attr])
    worker = getattr(module, attr)
    if not callable(worker):
        raise DocumentParseError(f"Docling worker is not callable: {worker_name}")
    return worker


class DoclingParser:
    name = "docling"

    def __init__(
        self,
        converter_factory: Callable[[], Any] | None = None,
        version_resolver: Callable[[], str] | None = None,
        *,
        offline: bool = True,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
        convert_worker_ref: str | None = None,
    ) -> None:
        self._converter_factory = converter_factory
        self._version_resolver = version_resolver
        self.offline = offline
        self.timeout_seconds = timeout_seconds
        # Picklable "module:attr" reference for timeout tests / alternate workers.
        self._convert_worker_ref = convert_worker_ref

    def supports(self, inspection: DocumentInspection) -> bool:
        return inspection.extension in _SUPPORTED_EXTENSIONS and not inspection.encrypted

    def identity(self) -> dict[str, str] | None:
        # An injected converter, version resolver, or alternate worker means this
        # instance's output is not (only) stock Docling, so it must never be
        # shared under a "docling" identity.
        if (
            self._converter_factory is not None
            or self._version_resolver is not None
            or self._convert_worker_ref is not None
        ):
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
        if self._converter_factory is not None:
            return self._parse_with_injected_converter(resolved)

        ctx = get_context("spawn")
        queue = ctx.Queue(maxsize=1)
        process = ctx.Process(
            target=_docling_worker_main,
            args=(
                queue,
                str(resolved),
                self.offline,
                self._version(),
                self._convert_worker_ref,
            ),
        )
        process.start()
        process.join(timeout=self.timeout_seconds)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
            raise DocumentParseError(
                f"Docling exceeded the {self.timeout_seconds}-second timeout."
            )

        if queue.empty():
            raise DocumentParseError(
                f"Docling worker exited without a result (exit={process.exitcode})."
            )
        message = queue.get_nowait()
        if message[0] == "error":
            _, error_type, error_message = message
            raise DocumentParseError(f"{error_type}: {error_message}")
        parsed = ParsedDocument.model_validate(message[1])
        if not parsed.blocks:
            raise DocumentParseError("Docling produced no usable content blocks.")
        return parsed

    def _parse_with_injected_converter(self, resolved: Path) -> ParsedDocument:
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
