from __future__ import annotations

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
        def extract_text(self) -> str:
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
