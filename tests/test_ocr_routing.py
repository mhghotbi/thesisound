from pathlib import Path

from thesisound.ports import DocumentInspection
from thesisound.services.parser_router import route_parser


def _inspection(
    *,
    image_only_ratio=0,
    complex_layout=False,
    extension=".pdf",
    mime_type="application/pdf",
):
    return DocumentInspection(
        path=Path(f"sample{extension}"),
        mime_type=mime_type,
        extension=extension,
        file_size_bytes=1000,
        sha256="a" * 64,
        page_count=2,
        sampled_text_characters=1000 if not image_only_ratio else 0,
        image_only_ratio=image_only_ratio,
        likely_complex_layout=complex_layout,
    )


def test_scan_prefers_local_ocr_when_provisioned() -> None:
    route = route_parser(_inspection(image_only_ratio=1), {"native", "docling", "local-ocr"})
    assert route.primary == "local-ocr"
    assert route.fallbacks == ["docling", "native"]


def test_clean_digital_pdf_avoids_model_load() -> None:
    route = route_parser(_inspection(), {"native", "docling", "local-ocr"})
    assert route.primary == "native"


def test_complex_digital_pdf_probes_native_before_structured_parsers() -> None:
    route = route_parser(
        _inspection(complex_layout=True), {"native", "docling", "local-ocr", "mineru"}
    )
    assert route.primary == "native"
    assert route.fallbacks == ["docling", "mineru", "local-ocr"]


def test_complex_layout_without_native_uses_docling() -> None:
    route = route_parser(
        _inspection(complex_layout=True), {"docling", "local-ocr", "mineru"}
    )
    assert route.primary == "docling"
    assert route.fallbacks == ["mineru", "local-ocr"]


def test_html_prefers_docling() -> None:
    route = route_parser(
        _inspection(extension=".html", mime_type="text/html"),
        {"native", "docling", "local-ocr", "mineru"},
    )
    assert route.primary == "docling"
    assert route.fallbacks == ["local-ocr", "mineru"]


def test_epub_uses_epub_parser() -> None:
    route = route_parser(
        _inspection(extension=".epub", mime_type="application/epub+zip"),
        {"native", "epub", "docling"},
    )
    assert route.primary == "epub"
    assert route.fallbacks == []
