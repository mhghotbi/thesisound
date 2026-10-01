from __future__ import annotations

import platform
import re
import sys
import unicodedata
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
            if _is_rtl_dominant(text):
                text = _logical_text_from_layout(page.extract_text(extraction_mode="layout") or "")
        except Exception as exc:
            warnings.append(f"Page {page_index} extraction failed: {type(exc).__name__}")
            continue
        for paragraph in _paragraphs(_normalize_pdf_text(text)):
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


def _normalize_pdf_text(text: str) -> str:
    """Fold Arabic/Persian presentation forms, drop kashida, fold Persian YEH/KAF.

    Some embedded PDF fonts (seen on a Persian-typeset source) map glyph IDs
    straight to Unicode Arabic Presentation Forms (U+FB50-FDFF, U+FE70-FEFF)
    instead of shaping standard letters at render time; pypdf then extracts
    exactly those codepoints. The text reads fine to a human but never equals
    a model's reconstructed logical text, so every verbatim-quote comparison
    downstream fails. NFKC decomposes presentation forms to their canonical
    letters and is a no-op on text that is already canonical.

    Kashida (tatweel) only stretches a line for justification and carries no
    meaning. The same fonts often encode Persian YEH and KEHEH as their Arabic
    counterparts, which render identically but display with the wrong dots in
    a Persian UI; the fold applies only when Persian-only letters show the text
    is Persian, so Arabic sources keep their own letters.
    """

    text = unicodedata.normalize("NFKC", text).replace(_KASHIDA, "")
    if _PERSIAN_ONLY_LETTERS.search(text):
        text = text.translate(_PERSIAN_LETTER_FOLD)
    return text


# Arabic-script letters, including the presentation-form blocks some fonts emit.
_ARABIC_SCRIPT = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_LATIN_LETTER = re.compile(r"[A-Za-zÀ-ɏ]")
# A left-to-right run inside an RTL line: Latin letters and digits (Western,
# Arabic-Indic, Persian), joined by the neutrals that sit between them in a
# citation such as "Berkowitz & Keenan, 2010: 188". Brackets stay outside the
# run on purpose: they are mirrored with the RTL text around them.
_LTR_CHAR = r"A-Za-z0-9À-ɏ٠-٩۰-۹"
_LTR_RUN = re.compile(rf"[{_LTR_CHAR}](?:[{_LTR_CHAR} .,:;&'/%+\-_]*[{_LTR_CHAR}])?")
_DIGIT = r"0-9٠-٩۰-۹"
# One number: digits joined by single separators ("1398/11/06", "307-334").
# Separate numbers in an RTL line keep RTL order between them, so a run made of
# numbers alone is restored number by number, never as one LTR phrase.
_NUMBER = re.compile(rf"[{_DIGIT}]+(?:[.,:/\-][{_DIGIT}]+)*")
# Layout mode can print large, faux-bold title text twice, back to back.
_DOUBLED_PHRASE = re.compile(r"(.{10,}?) ?\1")
_MIRRORED = str.maketrans("()[]{}<>«»", ")(][}{><»«")
_KASHIDA = "ـ"
# Letters only Persian uses; their presence marks the text as Persian, where the
# Arabic YEH/KAF that some typesetting fonts emit are read as Persian YEH/KEHEH.
_PERSIAN_ONLY_LETTERS = re.compile(r"[پچژگکی]")
_PERSIAN_LETTER_FOLD = str.maketrans({"ي": "ی", "ك": "ک"})


def _is_rtl_dominant(text: str) -> bool:
    arabic = len(_ARABIC_SCRIPT.findall(text))
    return arabic > 0 and arabic >= len(_LATIN_LETTER.findall(text))


def _logical_text_from_layout(layout_text: str) -> str:
    """Rebuild reading order for an RTL page from pypdf's layout extraction.

    pypdf's default extraction joins text runs in content-stream order. Some
    Persian typesetting writes a line as several runs, and even splits words
    at their zero-width joins, laid out right-to-left but stored in whatever
    order the producer chose, so the extracted line comes out scrambled.
    Layout mode places every glyph by its position instead, which yields each
    line in visual (left-to-right) order. For an RTL line that is the logical
    text reversed: reverse it, put embedded Latin/number runs back in their own
    order, and mirror the paired punctuation that RTL display flips.
    """

    return "\n".join(_visual_line_to_logical(line) for line in layout_text.splitlines())


def _visual_line_to_logical(line: str) -> str:
    collapsed = re.sub(r" {2,}", " ", line.strip())
    if not _is_rtl_dominant(collapsed):
        return collapsed
    reversed_line = collapsed[::-1]
    restored = _LTR_RUN.sub(_restore_ltr_run, reversed_line)
    return _DOUBLED_PHRASE.sub(r"\1", restored.translate(_MIRRORED))


def _restore_ltr_run(match: re.Match[str]) -> str:
    run = match.group(0)
    if _LATIN_LETTER.search(run):
        return run[::-1]
    return _NUMBER.sub(lambda number: number.group(0)[::-1], run)


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
