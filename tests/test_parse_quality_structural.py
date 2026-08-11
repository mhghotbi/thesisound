from __future__ import annotations

from pathlib import Path

from thesisound.ports import DocumentInspection, ParsedBlock, ParsedDocument
from thesisound.services.parse_quality import (
    assess_parse_quality,
    math_signal_strength,
    reading_order_regression_ratio,
)
from thesisound.services.parser_benchmark import _score


def _inspection(*, pages: int = 10, file_size: int = 100_000) -> DocumentInspection:
    return DocumentInspection(
        path=Path("paper.pdf"),
        mime_type="application/pdf",
        extension=".pdf",
        file_size_bytes=file_size,
        sha256="c" * 64,
        page_count=pages,
        sampled_text_characters=5_000,
        image_only_ratio=0,
    )


def _block(
    text: str,
    *,
    key: str | None = None,
    kind: str = "text",
    page: int | None = 1,
) -> ParsedBlock:
    return ParsedBlock(
        source_block_key=key or text[:24] or "block",
        text=text,
        page_start=page,
        page_end=page,
        kind=kind,
        heading_path=["Section"] if kind == "heading" else [],
    )


def test_math_signal_strength_detects_latex() -> None:
    text = r"Attention uses Softmax(QK^T / sqrt(d_k)). \frac{1}{\sqrt{d_k}} \mathrm{Attention}"
    assert math_signal_strength(text) >= 2


def test_formula_damage_marks_math_without_formula_blocks_unsafe() -> None:
    math_text = (
        r"The model computes \frac{1}{\sqrt{d_k}} and \mathrm{Attention}(Q,K,V). "
        r"It also uses \sum_i \alpha_i and \left( Q K^\top \right)."
    )
    parsed = ParsedDocument(
        parser_name="native",
        parser_version="test",
        blocks=[
            _block("Introduction", kind="heading", page=1),
            _block(math_text + (" body " * 40), page=1),
            _block("More prose without structure. " * 20, page=2),
        ],
    )

    report = assess_parse_quality(_inspection(pages=2), parsed)

    assert any(issue.issue_type == "formula_damage" for issue in report.issues)
    assert report.verdict == "retry"
    assert not report.safe_for_claim_extraction
    assert report.suggested_parser == "mineru"


def test_formula_blocks_avoid_formula_damage() -> None:
    math_text = (
        r"The model computes \frac{1}{\sqrt{d_k}} and \mathrm{Attention}(Q,K,V). "
        r"It also uses \sum_i \alpha_i and \left( Q K^\top \right)."
    )
    parsed = ParsedDocument(
        parser_name="mineru",
        parser_version="test",
        blocks=[
            _block("Introduction", kind="heading", page=1),
            _block(math_text + (" body " * 40), page=1),
            _block(r"\mathrm{Attention}(Q,K,V)", kind="formula", page=1),
            _block("More prose without structure. " * 20, page=2),
        ],
    )

    report = assess_parse_quality(_inspection(pages=2), parsed)

    assert not any(issue.issue_type == "formula_damage" for issue in report.issues)
    assert report.safe_for_claim_extraction


def test_table_damage_when_pipe_rows_lack_table_blocks() -> None:
    table = "\n".join(
        [
            "| Model | BLEU | Cost |",
            "| --- | --- | --- |",
            "| Base | 27.3 | 1.0 |",
            "| Big | 28.4 | 2.3 |",
            "| Ensemble | 29.1 | 4.1 |",
        ]
    )
    parsed = ParsedDocument(
        parser_name="native",
        parser_version="test",
        blocks=[
            _block("Results", kind="heading", page=1),
            _block(table + "\n" + ("Discussion prose. " * 30), page=1),
            _block("Continuation of results. " * 20, page=2),
        ],
    )

    report = assess_parse_quality(_inspection(pages=2), parsed)

    assert any(issue.issue_type == "table_damage" for issue in report.issues)


def test_wrong_reading_order_from_page_regressions() -> None:
    blocks = [
        _block(f"Block {index} " + ("text " * 20), key=f"b{index}", page=page)
        for index, page in enumerate([1, 2, 3, 2, 1, 3, 2, 1, 2, 1], start=1)
    ]
    blocks[0] = _block("Heading", key="h", kind="heading", page=1)
    assert reading_order_regression_ratio(blocks) >= 0.15

    parsed = ParsedDocument(parser_name="native", parser_version="test", blocks=blocks)
    report = assess_parse_quality(_inspection(pages=3), parsed)

    assert any(issue.issue_type == "wrong_reading_order" for issue in report.issues)


def test_fragmentation_flags_extreme_blocks_per_page() -> None:
    blocks = [_block("Heading", key="h", kind="heading", page=1)]
    for index in range(350):
        page = (index % 5) + 1
        blocks.append(_block(f"tiny-{index}", key=f"t{index}", page=page))

    parsed = ParsedDocument(parser_name="docling", parser_version="test", blocks=blocks)
    report = assess_parse_quality(_inspection(pages=5), parsed)

    assert any("fragmented" in issue.evidence for issue in report.issues)
    assert report.verdict == "retry"
    assert not report.safe_for_claim_extraction


def test_benchmark_score_prefers_formula_preserving_parser() -> None:
    shared = dict(
        locator_coverage=1.0,
        page_coverage=1.0,
        heading_coverage=0.2,
        duplicate_ratio=0.0,
        math_signal_strength=3,
        table_signal_strength=0,
        reading_order_regression_ratio=0.0,
    )
    docling = _score(
        verdict="pass",
        safe=True,
        issue_count=0,
        formula_blocks=0,
        table_blocks=0,
        blocks_per_page=50.0,
        mean_block_chars=40.0,
        **shared,
    )
    mineru = _score(
        verdict="pass",
        safe=True,
        issue_count=0,
        formula_blocks=5,
        table_blocks=0,
        blocks_per_page=13.7,
        mean_block_chars=200.0,
        **shared,
    )

    assert mineru > docling
    assert mineru - docling >= 10
