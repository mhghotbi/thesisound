from __future__ import annotations

import json
import subprocess
from pathlib import Path

from reportlab.pdfgen import canvas

from thesisound.adapters.parsers.mineru_adapter import MineruParser
from thesisound.ingestion import ParserRoute
from thesisound.ports import DocumentInspection, ParsedBlock, ParsedDocument
from thesisound.services.artifact_writer import IngestionArtifactWriter
from thesisound.services.document_ingestion import ingest_document
from thesisound.services.document_inspector import inspect_document
from thesisound.services.parser_benchmark import benchmark_document
from thesisound.services.parser_router import route_parser


class FakeParser:
    def __init__(self, name: str, parsed: ParsedDocument) -> None:
        self.name = name
        self.parsed = parsed
        self.calls = 0

    def supports(self, inspection: DocumentInspection) -> bool:
        return not inspection.encrypted

    def parse(self, path: Path, inspection: DocumentInspection) -> ParsedDocument:
        self.calls += 1
        assert path.resolve() == inspection.path.resolve()
        return self.parsed


def _make_text_pdf(path: Path, *, pages: int = 2) -> None:
    pdf = canvas.Canvas(str(path))
    for page in range(1, pages + 1):
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(72, 760, f"Section {page}")
        pdf.setFont("Helvetica", 11)
        for line in range(12):
            pdf.drawString(
                72,
                730 - line * 20,
                f"Page {page} line {line}: evidence-grounded document ingestion text.",
            )
        pdf.showPage()
    pdf.save()


def _make_image_only_like_pdf(path: Path, *, pages: int = 3) -> None:
    pdf = canvas.Canvas(str(path))
    for _ in range(pages):
        pdf.rect(72, 300, 400, 300, stroke=1, fill=0)
        pdf.showPage()
    pdf.save()


def _good_parse(parser_name: str = "mineru") -> ParsedDocument:
    return ParsedDocument(
        parser_name=parser_name,
        parser_version="test",
        blocks=[
            ParsedBlock(
                source_block_key="heading",
                text="A structured heading",
                page_start=1,
                page_end=1,
                heading_path=["A structured heading"],
                kind="heading",
            ),
            ParsedBlock(
                source_block_key="body-1",
                text="A" * 350,
                page_start=1,
                page_end=1,
                heading_path=["A structured heading"],
                kind="text",
            ),
            ParsedBlock(
                source_block_key="body-2",
                text="B" * 350,
                page_start=2,
                page_end=2,
                heading_path=["A structured heading"],
                kind="text",
            ),
        ],
    )


def _poor_parse(parser_name: str = "docling") -> ParsedDocument:
    return ParsedDocument(
        parser_name=parser_name,
        parser_version="test",
        blocks=[
            ParsedBlock(
                source_block_key="short",
                text="short",
                kind="text",
            )
        ],
    )


def test_inspector_reads_generated_text_pdf(tmp_path: Path) -> None:
    path = tmp_path / "text.pdf"
    _make_text_pdf(path)

    inspection = inspect_document(path)

    assert inspection.page_count == 2
    assert inspection.sampled_text_characters > 500
    assert inspection.image_only_ratio == 0
    assert not inspection.encrypted


def test_inspector_detects_pdf_without_extractable_text(tmp_path: Path) -> None:
    path = tmp_path / "scan-like.pdf"
    _make_image_only_like_pdf(path)

    inspection = inspect_document(path)

    assert inspection.page_count == 3
    assert inspection.sampled_text_characters == 0
    assert inspection.image_only_ratio == 1


def test_router_prefers_mineru_for_ocr_and_docling_for_text(tmp_path: Path) -> None:
    scan = tmp_path / "scan.pdf"
    text = tmp_path / "text.pdf"
    _make_image_only_like_pdf(scan)
    _make_text_pdf(text)

    scan_route = route_parser(inspect_document(scan), {"docling", "mineru"})
    text_route = route_parser(inspect_document(text), {"docling", "mineru"})

    assert scan_route.primary == "mineru"
    assert scan_route.fallbacks == ["docling"]
    assert text_route.primary == "docling"
    assert text_route.fallbacks == ["mineru"]


def test_mineru_adapter_runs_cli_and_normalizes_content_list(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    _make_text_pdf(source, pages=1)
    inspection = inspect_document(source)
    output_root = tmp_path / "mineru-output"

    def runner(
        command: list[str],
        timeout_seconds: int,
        environment,
    ) -> subprocess.CompletedProcess[str]:
        assert command[0] == "mineru"
        assert command[1:3] == ["-p", str(source.resolve())]
        assert timeout_seconds == 60
        assert "PATH" in environment
        output = Path(command[command.index("-o") + 1]) / "paper" / "auto"
        output.mkdir(parents=True)
        payload = [
            {
                "type": "text",
                "text": "Introduction",
                "text_level": 1,
                "page_idx": 0,
            },
            {
                "type": "text",
                "text": "This is the main argument. " * 20,
                "page_idx": 0,
            },
        ]
        (output / "paper_content_list.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    parser = MineruParser(
        timeout_seconds=60,
        output_root=output_root,
        runner=runner,
        version_resolver=lambda: "3.test",
    )
    parsed = parser.parse(source, inspection)

    assert parsed.parser_name == "mineru"
    assert parsed.parser_version == "3.test"
    assert parsed.blocks[0].kind == "heading"
    assert parsed.blocks[1].heading_path == ["Introduction"]
    assert parsed.blocks[1].page_start == 1
    assert parsed.raw_artifact_ref is not None


def test_ingestion_falls_back_when_primary_parse_is_unsafe(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    _make_text_pdf(source)
    docling = FakeParser("docling", _poor_parse())
    mineru = FakeParser("mineru", _good_parse())
    writer = IngestionArtifactWriter(tmp_path / "artifacts")

    result = ingest_document(
        source,
        parsers={"docling": docling, "mineru": mineru},
        parser_name="auto",
        artifact_writer=writer,
    )

    assert result.route == ParserRoute(
        primary="docling",
        fallbacks=["mineru"],
        reasons=["Docling is the default local parser for text-bearing documents."],
    )
    assert [attempt.parser_name for attempt in result.attempts] == ["docling", "mineru"]
    assert result.selected_parser == "mineru"
    assert result.safe_for_claim_extraction
    assert (writer.document_dir(result.inspection) / "ingestion-result.json").exists()


def test_benchmark_recommends_safe_high_quality_parser(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    _make_text_pdf(source)

    benchmark = benchmark_document(
        source,
        parsers={
            "docling": FakeParser("docling", _poor_parse()),
            "mineru": FakeParser("mineru", _good_parse()),
        },
    )

    assert benchmark.recommended_parser == "mineru"
    metrics = {item.parser_name: item for item in benchmark.metrics}
    assert metrics["mineru"].safe_for_claim_extraction
    assert metrics["mineru"].score > metrics["docling"].score
    assert metrics["mineru"].page_coverage == 1
