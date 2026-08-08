
from __future__ import annotations

from collections.abc import Collection

from thesisound.ingestion import ParserRoute
from thesisound.ports import DocumentInspection

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


class ParserRoutingError(ValueError):
    """Raised when no configured parser can safely accept a document."""


def route_parser(
    inspection: DocumentInspection,
    available_parsers: Collection[str],
) -> ParserRoute:
    """Choose the cheapest adequate parser and ordered quality fallbacks."""

    available = set(available_parsers)
    if inspection.encrypted:
        raise ParserRoutingError("Encrypted documents must be decrypted before parsing.")
    if not available:
        raise ParserRoutingError("No document parsers are configured.")

    reasons: list[str] = []
    if inspection.extension == ".epub":
        if "epub" not in available:
            raise ParserRoutingError("The EPUB parser is not configured.")
        return ParserRoute(
            primary="epub",
            reasons=["EPUB requires package-manifest and spine-aware parsing."],
        )

    is_image = inspection.extension in _IMAGE_EXTENSIONS
    is_pdf = inspection.mime_type == "application/pdf"
    needs_ocr = is_image or (
        is_pdf
        and inspection.image_only_ratio is not None
        and inspection.image_only_ratio >= 0.67
    )

    if needs_ocr and "local-ocr" in available:
        reasons.append(
            "The source has no reliable text layer; use short-lived self-hosted OCR first."
        )
        return ParserRoute(
            primary="local-ocr",
            fallbacks=_available_in_order(available, "docling", "mineru", "native"),
            reasons=reasons,
        )

    if needs_ocr and "mineru" in available:
        reasons.append("Sampled pages contain little or no extractable text; OCR is required.")
        return ParserRoute(
            primary="mineru",
            fallbacks=_available_in_order(available, "docling", "native"),
            reasons=reasons,
        )

    if inspection.likely_complex_layout and "docling" in available:
        reasons.append("The text-bearing document needs structure-aware local parsing.")
        return ParserRoute(
            primary="docling",
            fallbacks=_available_in_order(available, "native", "local-ocr", "mineru"),
            reasons=reasons,
        )

    if inspection.likely_complex_layout and "local-ocr" in available:
        reasons.append("The document needs explicit layout and reading-order recovery.")
        return ParserRoute(
            primary="local-ocr",
            fallbacks=_available_in_order(available, "native", "mineru"),
            reasons=reasons,
        )

    if "native" in available:
        reasons.append("A healthy text layer should be extracted without loading OCR models.")
        return ParserRoute(
            primary="native",
            fallbacks=_available_in_order(available, "docling", "local-ocr", "mineru"),
            reasons=reasons,
        )

    if "docling" in available:
        reasons.append("Docling is the default local parser for text-bearing documents.")
        return ParserRoute(
            primary="docling",
            fallbacks=_available_in_order(available, "local-ocr", "mineru"),
            reasons=reasons,
        )

    if "local-ocr" in available:
        reasons.append("Local OCR is the only configured parser that can accept this document.")
        return ParserRoute(primary="local-ocr", reasons=reasons)

    if "mineru" in available:
        reasons.append("MinerU is the only configured parser that can accept this document.")
        return ParserRoute(primary="mineru", reasons=reasons)

    fallback = sorted(available)[0]
    reasons.append("No preferred parser is available; using the first configured parser.")
    return ParserRoute(primary=fallback, reasons=reasons)


def _available_in_order(available: set[str], *names: str) -> list[str]:
    return [name for name in names if name in available]
