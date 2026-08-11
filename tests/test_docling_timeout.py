from __future__ import annotations

from pathlib import Path

import pytest

from thesisound.adapters.parsers.docling_adapter import DoclingParser, DocumentParseError
from thesisound.ports import DocumentInspection, ParsedBlock, ParsedDocument
from thesisound.services.document_ingestion import ingest_document


_WORKER = "thesisound.adapters.parsers.docling_adapter"


class _StaticParser:
    def __init__(self, name: str, parsed: ParsedDocument) -> None:
        self.name = name
        self._parsed = parsed
        self.calls = 0

    def supports(self, inspection: DocumentInspection) -> bool:
        del inspection
        return True

    def parse(self, path: Path, inspection: DocumentInspection) -> ParsedDocument:
        del path, inspection
        self.calls += 1
        return self._parsed.model_copy(deep=True)


def test_docling_timeout_raises_parse_error(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    source.write_text("# Title\n\nBody text for inspection.\n", encoding="utf-8")
    inspection = DocumentInspection(
        path=source.resolve(),
        mime_type="text/markdown",
        extension=".md",
        file_size_bytes=source.stat().st_size,
        sha256="d" * 64,
        sampled_text_characters=40,
    )
    parser = DoclingParser(
        timeout_seconds=1,
        convert_worker_ref=f"{_WORKER}:testing_slow_convert_worker",
        version_resolver=lambda: "test",
    )

    with pytest.raises(DocumentParseError, match="1-second timeout"):
        parser.parse(source, inspection)


def test_docling_worker_success_path(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    source.write_text("# Title\n\nBody text for inspection.\n", encoding="utf-8")
    inspection = DocumentInspection(
        path=source.resolve(),
        mime_type="text/markdown",
        extension=".md",
        file_size_bytes=source.stat().st_size,
        sha256="e" * 64,
        sampled_text_characters=40,
    )
    parser = DoclingParser(
        timeout_seconds=10,
        convert_worker_ref=f"{_WORKER}:testing_fast_convert_worker",
        version_resolver=lambda: "test",
    )

    parsed = parser.parse(source, inspection)

    assert parsed.blocks
    assert parsed.blocks[0].text.startswith("A")


def test_ingestion_falls_back_when_native_fails_formula_gate(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    source.write_text("# Paper\n\nBody\n", encoding="utf-8")
    math_body = (
        r"The model computes \frac{1}{\sqrt{d_k}} and \mathrm{Attention}(Q,K,V). "
        r"It also uses \sum_i \alpha_i and \left( Q K^\top \right). "
        + ("Evidence text. " * 40)
    )
    weak = ParsedDocument(
        parser_name="native",
        parser_version="test",
        blocks=[
            ParsedBlock(
                source_block_key="h",
                text="Attention",
                page_start=1,
                page_end=1,
                kind="heading",
                heading_path=["Attention"],
            ),
            ParsedBlock(
                source_block_key="body",
                text=math_body,
                page_start=1,
                page_end=1,
                kind="text",
            ),
        ],
    )
    strong = ParsedDocument(
        parser_name="mineru",
        parser_version="test",
        blocks=[
            ParsedBlock(
                source_block_key="h",
                text="Attention",
                page_start=1,
                page_end=1,
                kind="heading",
                heading_path=["Attention"],
            ),
            ParsedBlock(
                source_block_key="body",
                text=math_body,
                page_start=1,
                page_end=1,
                kind="text",
            ),
            ParsedBlock(
                source_block_key="f1",
                text=r"\mathrm{Attention}(Q,K,V)",
                page_start=1,
                page_end=1,
                kind="formula",
            ),
        ],
    )
    native = _StaticParser("native", weak)
    mineru = _StaticParser("mineru", strong)

    result = ingest_document(
        source,
        parsers={"native": native, "mineru": mineru},
        parser_name="auto",
    )

    assert native.calls == 1
    assert mineru.calls == 1
    assert result.selected_parser == "mineru"
    assert result.safe_for_claim_extraction
    assert result.attempts[0].quality is not None
    assert not result.attempts[0].quality.safe_for_claim_extraction


def test_ingestion_uses_fallback_after_docling_timeout(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    source.write_text("# Title\n\nBody text for inspection.\n", encoding="utf-8")
    fallback = ParsedDocument(
        parser_name="mineru",
        parser_version="test",
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
    )
    docling = DoclingParser(
        timeout_seconds=1,
        convert_worker_ref=f"{_WORKER}:testing_slow_convert_worker",
        version_resolver=lambda: "test",
    )
    mineru = _StaticParser("mineru", fallback)

    result = ingest_document(
        source,
        parsers={"docling": docling, "mineru": mineru},
        parser_name="auto",
    )

    assert result.selected_parser == "mineru"
    assert result.safe_for_claim_extraction
    assert result.attempts[0].parser_name == "docling"
    assert result.attempts[0].status == "error"
    assert "timeout" in (result.attempts[0].error_message or "").lower()
    assert mineru.calls == 1
