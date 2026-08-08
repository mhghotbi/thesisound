from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

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
