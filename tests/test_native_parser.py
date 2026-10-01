from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pypdf import PdfWriter

from thesisound.adapters.parsers.native_adapter import NativeDocumentParser
from thesisound.services.document_inspector import inspect_document


def test_native_parser_preserves_markdown_heading_context(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text(
        "# عنوان اصلی\n\nاین بند اول است و برای آزمون ساختار استفاده می‌شود.\n\n"
        "## بخش دوم\n\nاین بند دوم است و باید مسیر عنوان را حفظ کند.",
        encoding="utf-8",
    )

    parsed = NativeDocumentParser().parse(source, inspect_document(source))

    assert parsed.parser_name == "native"
    assert [block.kind for block in parsed.blocks] == ["heading", "text", "heading", "text"]
    assert parsed.blocks[-1].heading_path == ["عنوان اصلی", "بخش دوم"]


def test_native_pdf_parser_folds_arabic_presentation_forms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A font that embeds presentation-form glyphs instead of logical letters.

    Observed on a real source: pypdf extracted presentation-form codepoints
    instead of their plain letters. The text reads fine visually but never
    equals a model's reconstructed logical text, so every verbatim-quote
    check downstream rejected the block.

    The exact codepoints are asserted by name below rather than trusted by
    eye: RTL text pasted through an editor or terminal is not reliable
    enough for a test whose entire point is catching silent character
    substitution.
    """

    source = tmp_path / "source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with source.open("wb") as handle:
        writer.write(handle)
    inspection = inspect_document(source)

    # A presentation-form letter sandwiched between two plain ones, so the fix
    # must fold per-character rather than only detect an all-presentation-form
    # run. Each codepoint is verified by Unicode name, not trusted by eye.
    alef = "ا"
    seen_presentation_form = "ﺳ"
    noon_presentation_form = "ﻦ"
    presentation_form_text = alef + seen_presentation_form + noon_presentation_form
    expected = unicodedata.normalize("NFKC", presentation_form_text)
    assert unicodedata.name(alef) == "ARABIC LETTER ALEF"
    assert "SEEN" in unicodedata.name(seen_presentation_form)
    assert "NOON" in unicodedata.name(noon_presentation_form)
    assert unicodedata.name(seen_presentation_form) != "ARABIC LETTER SEEN"
    assert unicodedata.name(noon_presentation_form) != "ARABIC LETTER NOON"

    class FakePage:
        def extract_text(self, extraction_mode: str = "plain") -> str:
            # Layout mode returns a line in visual (left-to-right) order, as pypdf does.
            if extraction_mode == "layout":
                return presentation_form_text[::-1]
            return presentation_form_text

    class FakeReader:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.is_encrypted = False
            self.pages = [FakePage()]

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)

    parsed = NativeDocumentParser().parse(source, inspection)

    assert len(parsed.blocks) == 1
    text = parsed.blocks[0].text
    assert text == expected
    assert seen_presentation_form not in text
    assert noon_presentation_form not in text
    assert all(
        "PRESENTATION FORM" not in unicodedata.name(char, "") for char in text
    )


LAYOUT_FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "persian_pdf_layout_lines.json"


def _parse_fake_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    plain: str,
    layout: str | None,
) -> list[str]:
    source = tmp_path / "source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with source.open("wb") as handle:
        writer.write(handle)
    inspection = inspect_document(source)

    class FakePage:
        def extract_text(self, extraction_mode: str = "plain") -> str:
            if extraction_mode == "layout":
                if layout is None:
                    raise AssertionError("layout extraction must not run for this page")
                return layout
            return plain

    class FakeReader:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.is_encrypted = False
            self.pages = [FakePage()]

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)
    return [block.text for block in NativeDocumentParser().parse(source, inspection).blocks]


def test_native_pdf_parser_rebuilds_persian_lines_in_reading_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persian lines stored as out-of-order runs, observed on a real journal PDF.

    pypdf's default extraction joined the runs in content-stream order, so a
    line such as «برای آرنت، اولین و مهم‌ترین نتیجهٔ …» came out as fragments
    in the wrong order and every evidence excerpt shown to the reader was
    scrambled. The fixture holds pypdf's real layout-mode output for those
    lines (escaped, so no editor can reorder it): visual order, presentation
    forms, kashida, Arabic YEH, an embedded Latin citation and two numbers.
    """

    fixture = json.loads(LAYOUT_FIXTURE.read_text(encoding="utf-8"))
    lines = _parse_fake_pdf(
        tmp_path,
        monkeypatch,
        plain=fixture["plain_text_tail"],
        layout="\n".join(fixture["layout_lines"]),
    )
    text = "\n".join(lines)
    header, title, ideology, citation, consequence = text.splitlines()

    # Separate numbers keep RTL order between them; each number reads left-to-right.
    assert header.endswith("زمستان 1400: 307-334")
    # Layout mode printed the faux-bold title twice; it appears once.
    assert title.count("بدیلی") == 1
    assert title.endswith("«از جهان بیگانگی»")
    # Guillemets are mirrored back around the quoted words.
    assert "«ازجهان بیگانه»" in ideology
    # The Latin citation keeps its own order, inside correctly paired brackets.
    assert citation.endswith("بود (Berkowitz & Keenan, 2010: 188).")
    # The scrambled line now reads in order, with Persian YEH and no kashida.
    assert consequence.startswith("برای آرنت، اولین و مهمترین")
    assert consequence.endswith("این است که ما معنای وجود")
    assert "ـ" not in text
    assert "ي" not in text
    assert all("PRESENTATION FORM" not in unicodedata.name(char, "") for char in text)


def test_native_pdf_parser_leaves_left_to_right_pages_on_the_default_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = "The earth is the very quintessence of the human condition (Arendt, 1958: 2)."

    assert _parse_fake_pdf(tmp_path, monkeypatch, plain=plain, layout=None) == [plain]


def test_native_pdf_parser_keeps_arabic_letters_in_arabic_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The YEH/KAF fold is for Persian only; Arabic text has no Persian-only letters."""

    arabic = "في كتاب"  # «في كتاب»
    (text,) = _parse_fake_pdf(tmp_path, monkeypatch, plain=arabic, layout=arabic[::-1])

    assert text == arabic


def test_native_parser_reads_docx_without_docling(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p>
          <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
          <w:r><w:t>عنوان سند</w:t></w:r>
        </w:p>
        <w:p><w:r><w:t>متن اصلی سند برای استخراج واقعی.</w:t></w:r></w:p>
      </w:body>
    </w:document>
    """
    with ZipFile(source, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)

    parsed = NativeDocumentParser().parse(source, inspect_document(source))

    assert [block.text for block in parsed.blocks] == [
        "عنوان سند",
        "متن اصلی سند برای استخراج واقعی.",
    ]
    assert parsed.blocks[0].kind == "heading"
    assert parsed.blocks[1].heading_path == ["عنوان سند"]
