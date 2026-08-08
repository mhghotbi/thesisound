from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

from thesisound.adapters.parsers.epub_adapter import (
    EpubDocumentParseError,
    EpubDocumentParser,
)
from thesisound.services.document_ingestion import ingest_document
from thesisound.services.document_inspector import inspect_document


def _write_epub(path: Path, *, bad_href: str | None = None) -> None:
    container = """<?xml version="1.0" encoding="UTF-8"?>
    <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
      <rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
      </rootfiles>
    </container>
    """
    chapter_one_href = bad_href or "chapter-1.xhtml"
    package = f"""<?xml version="1.0" encoding="UTF-8"?>
    <package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:identifier id="book-id">urn:test:epub</dc:identifier>
        <dc:title>کتاب آزمایشی</dc:title>
        <dc:language>fa</dc:language>
      </metadata>
      <manifest>
        <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
        <item id="c1" href="{chapter_one_href}" media-type="application/xhtml+xml"/>
        <item id="c2" href="chapter-2.xhtml" media-type="application/xhtml+xml"/>
      </manifest>
      <spine>
        <itemref idref="c1"/>
        <itemref idref="c2"/>
      </spine>
    </package>
    """
    long_one = " ".join(["این فصل درباره کنش، آزادی و جهان مشترک توضیح می‌دهد."] * 6)
    long_two = " ".join(["فصل دوم تمایز میان کار، ساختن و کنش را بررسی می‌کند."] * 6)
    chapter_one = f"""<html xmlns="http://www.w3.org/1999/xhtml" lang="fa">
      <head><title>فصل اول</title><style>.x {{ color: red; }}</style></head>
      <body><h1>فصل اول: کنش</h1><p>{long_one}</p><script>نباید دیده شود</script></body>
    </html>"""
    chapter_two = f"""<html xmlns="http://www.w3.org/1999/xhtml" lang="fa">
      <head><title>فصل دوم</title></head>
      <body><h1>فصل دوم: تمایزها</h1><p>{long_two}</p></body>
    </html>"""
    nav = """<html xmlns="http://www.w3.org/1999/xhtml"><body>
      <nav><ol><li>فصل اول</li><li>فصل دوم</li></ol></nav>
    </body></html>"""

    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr("META-INF/container.xml", container, compress_type=ZIP_DEFLATED)
        archive.writestr("OEBPS/content.opf", package, compress_type=ZIP_DEFLATED)
        archive.writestr("OEBPS/nav.xhtml", nav, compress_type=ZIP_DEFLATED)
        if bad_href is None:
            archive.writestr(
                "OEBPS/chapter-1.xhtml", chapter_one, compress_type=ZIP_DEFLATED
            )
        archive.writestr("OEBPS/chapter-2.xhtml", chapter_two, compress_type=ZIP_DEFLATED)


def test_epub_parser_follows_spine_and_preserves_heading_context(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    _write_epub(source)

    inspection = inspect_document(source)
    parsed = EpubDocumentParser().parse(source, inspection)

    assert inspection.mime_type == "application/epub+zip"
    assert parsed.parser_name == "epub"
    assert [block.kind for block in parsed.blocks] == ["heading", "text", "heading", "text"]
    assert parsed.blocks[1].heading_path == ["فصل اول: کنش"]
    assert parsed.blocks[3].heading_path == ["فصل دوم: تمایزها"]
    assert "نباید دیده شود" not in " ".join(block.text for block in parsed.blocks)
    assert "epubcfi(" in parsed.blocks[0].source_block_key


def test_epub_auto_ingestion_passes_quality_gate(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    _write_epub(source)

    result = ingest_document(
        source,
        parsers={"epub": EpubDocumentParser()},
        parser_name="auto",
    )

    assert result.route.primary == "epub"
    assert result.selected_parser == "epub"
    assert result.safe_for_claim_extraction is True
    assert result.quality is not None
    assert result.quality.verdict in {"pass", "warning"}


def test_epub_parser_rejects_unsafe_absolute_spine_path(tmp_path: Path) -> None:
    source = tmp_path / "unsafe.epub"
    _write_epub(source, bad_href="/outside.xhtml")

    with pytest.raises(EpubDocumentParseError, match="Unsafe EPUB archive path"):
        EpubDocumentParser().parse(source, inspect_document(source))
