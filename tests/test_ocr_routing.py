
from pathlib import Path

from thesisound.ports import DocumentInspection
from thesisound.services.parser_router import route_parser


def _inspection(*, image_only_ratio=0, complex_layout=False):
    return DocumentInspection(
        path=Path("sample.pdf"),
        mime_type="application/pdf",
        extension=".pdf",
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


def test_complex_digital_pdf_uses_structured_parser_before_ocr() -> None:
    route = route_parser(
        _inspection(complex_layout=True), {"native", "docling", "local-ocr"}
    )
    assert route.primary == "docling"
    assert "local-ocr" in route.fallbacks
