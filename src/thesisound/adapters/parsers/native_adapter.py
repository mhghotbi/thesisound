from __future__ import annotations

import platform
import re
import sys
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from thesisound.ports import DocumentInspection, ParsedBlock, ParsedDocument
from thesisound.services.parser_identity import module_fingerprint, package_version

_SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WORD = {"w": _WORD_NAMESPACE}


class NativeDocumentParseError(RuntimeError):
    """Raised when the dependency-light parser cannot produce usable blocks."""


class NativeDocumentParser:
    """Parse common source files without optional heavyweight dependencies.

    This parser is deliberately conservative. It provides a production-safe baseline
    for the web flow and lets Docling or MinerU replace it when those richer parsers
    are installed and routed for a document.
    """

    name = "native"

    def supports(self, inspection: DocumentInspection) -> bool:
        return inspection.extension in _SUPPORTED_EXTENSIONS and not inspection.encrypted

    def identity(self) -> dict[str, str] | None:
        impl = module_fingerprint(sys.modules[__name__])
        if impl is None:
            return None
        return {
            "parser": "native",
            "version": "1",
            # pypdf drives the PDF branch; the stdlib drives .docx/.txt/.md. Both
            # are included even though each only matters for some extensions --
            # these are the cheap parsers, so over-invalidating them costs nothing.
            "pypdf": package_version("pypdf"),
            "python": platform.python_version(),
            "impl": impl,
        }

    def parse(self, path: Path, inspection: DocumentInspection) -> ParsedDocument:
        resolved = path.expanduser().resolve()
        if resolved != inspection.path.expanduser().resolve():
            raise ValueError("The inspected path and parsed path must refer to the same file.")
        if not self.supports(inspection):
            raise NativeDocumentParseError(
                f"Native parser does not support: {inspection.extension or 'unknown'}"
            )

        if inspection.extension == ".pdf":
            blocks, warnings = _parse_pdf(resolved)
        elif inspection.extension == ".docx":
            blocks, warnings = _parse_docx(resolved)
        else:
            blocks, warnings = _parse_text(resolved, markdown=inspection.extension == ".md")

        if not blocks:
            raise NativeDocumentParseError("Native parser produced no usable content blocks.")
        return ParsedDocument(
            parser_name=self.name,
            parser_version="1",
            blocks=blocks,
            warnings=warnings,
        )


def _parse_text(path: Path, *, markdown: bool) -> tuple[list[ParsedBlock], list[str]]:
    text = _decode_text(path.read_bytes())
    if text is None:
        raise NativeDocumentParseError("Text encoding is not supported.")
    if markdown:
        return _blocks_from_markdown(text), []
    return _blocks_from_paragraphs(text), []


def _parse_pdf(path: Path) -> tuple[list[ParsedBlock], list[str]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise NativeDocumentParseError("Install pypdf to parse PDF files.") from exc

    try:
        reader = PdfReader(path, strict=False)
    except Exception as exc:
        raise NativeDocumentParseError(
            f"PDF could not be opened: {type(exc).__name__}"
        ) from exc
    if reader.is_encrypted:
        raise NativeDocumentParseError("Encrypted PDF files must be decrypted first.")

    blocks: list[ParsedBlock] = []
    warnings: list[str] = []
    for page_index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            warnings.append(f"Page {page_index} extraction failed: {type(exc).__name__}")
            continue
        for paragraph in _paragraphs(text):
            blocks.append(
                ParsedBlock(
                    source_block_key=f"page-{page_index}-block-{len(blocks) + 1}",
                    text=paragraph,
                    page_start=page_index,
                    page_end=page_index,
                    kind="text",
                )
            )
    return blocks, warnings


def _parse_docx(path: Path) -> tuple[list[ParsedBlock], list[str]]:
    try:
        with ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError, OSError) as exc:
        raise NativeDocumentParseError("DOCX structure is invalid or incomplete.") from exc

    root = ElementTree.fromstring(xml)
    blocks: list[ParsedBlock] = []
    heading_path: list[str] = []
    for paragraph in root.findall(".//w:body/w:p", _WORD):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", _WORD)).strip()
        if not text:
            continue
        style_node = paragraph.find("./w:pPr/w:pStyle", _WORD)
        style = "" if style_node is None else style_node.get(f"{{{_WORD_NAMESPACE}}}val", "")
        heading_level = _word_heading_level(style)
        if heading_level is not None:
            heading_path = heading_path[: heading_level - 1]
            heading_path.append(text)
            kind = "heading"
        else:
            kind = "text"
        blocks.append(
            ParsedBlock(
                source_block_key=f"docx-block-{len(blocks) + 1}",
                text=text,
                heading_path=list(heading_path),
                kind=kind,
            )
        )
    return blocks, []


def _blocks_from_markdown(text: str) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    heading_path: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        paragraph = "\n".join(pending).strip()
        pending.clear()
        if not paragraph:
            return
        blocks.append(
            ParsedBlock(
                source_block_key=f"markdown-block-{len(blocks) + 1}",
                text=paragraph,
                heading_path=list(heading_path),
                kind="text",
            )
        )

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        heading = _MARKDOWN_HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            heading_path = heading_path[: level - 1]
            heading_path.append(title)
            blocks.append(
                ParsedBlock(
                    source_block_key=f"markdown-block-{len(blocks) + 1}",
                    text=title,
                    heading_path=list(heading_path),
                    kind="heading",
                )
            )
        elif line.strip():
            pending.append(line.strip())
        else:
            flush()
    flush()
    return blocks


def _blocks_from_paragraphs(text: str) -> list[ParsedBlock]:
    return [
        ParsedBlock(
            source_block_key=f"text-block-{index}",
            text=paragraph,
            kind="text",
        )
        for index, paragraph in enumerate(_paragraphs(text), start=1)
    ]


def _paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return [
        "\n".join(line.strip() for line in chunk.splitlines() if line.strip())
        for chunk in re.split(r"\n\s*\n", normalized)
        if chunk.strip()
    ]


def _decode_text(data: bytes) -> str | None:
    for encoding in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _word_heading_level(style: str) -> int | None:
    match = re.search(r"heading\s*([1-6])", style, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None
