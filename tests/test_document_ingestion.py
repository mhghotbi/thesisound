from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from thesisound.adapters.parsers.docling_adapter import DoclingParser, DocumentParseError
from thesisound.ports import DocumentInspection, ParsedBlock, ParsedDocument
from thesisound.services.document_inspector import inspect_document
from thesisound.services.document_normalizer import normalize_docling_document
from thesisound.services.parse_quality import assess_parse_quality

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "sample.md"


@dataclass
class FakeProvenance:
    page_no: int


@dataclass
class FakeItem:
    self_ref: str
    label: str
    text: str
    prov: list[FakeProvenance]


class FakeDocument:
    def __init__(self, items: list[tuple[FakeItem, int]]) -> None:
        self._items = items

    def iterate_items(self, **_: object):
        return iter(self._items)


class FakeConverter:
    def __init__(self, document: FakeDocument) -> None:
        self.document = document
        self.received: Path | None = None

    def convert(self, path: Path, **_: object):
        self.received = path
        return SimpleNamespace(document=self.document)


def test_inspector_hashes_and_samples_text_fixture() -> None:
    inspection = inspect_document(FIXTURE)

    assert inspection.extension == ".md"
    assert inspection.mime_type in {"text/markdown", "text/plain"}
    assert inspection.file_size_bytes > 0
    assert len(inspection.sha256) == 64
    assert inspection.sampled_text_characters > 100
    assert not inspection.encrypted


def test_normalizer_preserves_reading_order_headings_and_pages() -> None:
    document = FakeDocument(
        [
            (FakeItem("#/texts/0", "title", "A title", [FakeProvenance(1)]), 1),
            (
                FakeItem("#/texts/1", "paragraph", "Opening claim", [FakeProvenance(1)]),
                2,
            ),
            (
                FakeItem("#/texts/2", "section_header", "Details", [FakeProvenance(2)]),
                2,
            ),
            (
                FakeItem("#/texts/3", "paragraph", "Detailed claim", [FakeProvenance(2)]),
                3,
            ),
        ]
    )

    parsed = normalize_docling_document(document, parser_version="test")

    assert [block.text for block in parsed.blocks] == [
        "A title",
        "Opening claim",
        "Details",
        "Detailed claim",
    ]
    assert parsed.blocks[1].heading_path == ["A title"]
    assert parsed.blocks[3].heading_path == ["A title", "Details"]
    assert parsed.blocks[3].page_start == 2
    assert parsed.blocks[3].page_end == 2


def test_docling_adapter_uses_injected_converter_without_docling_install() -> None:
    document = FakeDocument(
        [(FakeItem("#/texts/0", "paragraph", "Useful text", [FakeProvenance(1)]), 1)]
    )
    converter = FakeConverter(document)
    inspection = inspect_document(FIXTURE)
    parser = DoclingParser(
        converter_factory=lambda: converter,
        version_resolver=lambda: "2.test",
    )

    parsed = parser.parse(FIXTURE, inspection)

    assert converter.received == FIXTURE.resolve()
    assert parsed.parser_name == "docling"
    assert parsed.parser_version == "2.test"
    assert parsed.blocks[0].text == "Useful text"


def test_docling_adapter_rejects_mismatched_inspection() -> None:
    inspection = inspect_document(FIXTURE)
    parser = DoclingParser(converter_factory=lambda: FakeConverter(FakeDocument([])))

    with pytest.raises(ValueError, match="same file"):
        parser.parse(Path("another.md"), inspection)


def test_quality_gate_passes_structured_parse() -> None:
    inspection = DocumentInspection(
        path=Path("paper.pdf"),
        mime_type="application/pdf",
        extension=".pdf",
        file_size_bytes=50_000,
        sha256="a" * 64,
        page_count=2,
        sampled_text_characters=1_000,
        image_only_ratio=0,
    )
    parsed = ParsedDocument(
        parser_name="docling",
        parser_version="test",
        blocks=[
            ParsedBlock(
                source_block_key="1",
                text="A" * 250,
                page_start=1,
                page_end=1,
                heading_path=["One"],
                kind="text",
            ),
            ParsedBlock(
                source_block_key="2",
                text="B" * 250,
                page_start=2,
                page_end=2,
                heading_path=["Two"],
                kind="text",
            ),
        ],
    )

    report = assess_parse_quality(inspection, parsed)

    assert report.verdict == "pass"
    assert report.safe_for_claim_extraction


def test_quality_gate_requests_ocr_fallback_for_image_only_pdf() -> None:
    inspection = DocumentInspection(
        path=Path("scan.pdf"),
        mime_type="application/pdf",
        extension=".pdf",
        file_size_bytes=100_000,
        sha256="b" * 64,
        page_count=10,
        sampled_text_characters=0,
        image_only_ratio=1,
    )
    parsed = ParsedDocument(
        parser_name="docling",
        parser_version="test",
        blocks=[
            ParsedBlock(
                source_block_key="1",
                text="short",
                kind="text",
            )
        ],
    )

    report = assess_parse_quality(inspection, parsed)

    assert report.verdict == "retry"
    assert not report.safe_for_claim_extraction
    assert report.suggested_parser == "mineru"


def test_adapter_fails_when_converter_returns_no_blocks() -> None:
    inspection = inspect_document(FIXTURE)
    parser = DoclingParser(
        converter_factory=lambda: FakeConverter(FakeDocument([])),
        version_resolver=lambda: "test",
    )

    with pytest.raises(DocumentParseError, match="no usable content"):
        parser.parse(FIXTURE, inspection)
