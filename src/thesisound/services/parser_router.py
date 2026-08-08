from __future__ import annotations

from collections.abc import Collection

from thesisound.ingestion import ParserRoute
from thesisound.ports import DocumentInspection


class ParserRoutingError(ValueError):
    """Raised when no configured parser can safely accept a document."""


def route_parser(
    inspection: DocumentInspection,
    available_parsers: Collection[str],
) -> ParserRoute:
    """Choose a primary parser and ordered fallbacks from inspection signals."""

    available = set(available_parsers)
    if inspection.encrypted:
        raise ParserRoutingError("Encrypted documents must be decrypted before parsing.")
    if not available:
        raise ParserRoutingError("No document parsers are configured.")

    reasons: list[str] = []
    is_pdf_or_image = inspection.mime_type == "application/pdf" or inspection.extension in {
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".bmp",
        ".webp",
    }
    needs_ocr = (
        is_pdf_or_image
        and inspection.image_only_ratio is not None
        and inspection.image_only_ratio >= 0.67
    )

    if needs_ocr and "mineru" in available:
        reasons.append("Sampled pages contain little or no extractable text; OCR is required.")
        return ParserRoute(
            primary="mineru",
            fallbacks=[name for name in ("docling",) if name in available],
            reasons=reasons,
        )

    if inspection.likely_complex_layout and "mineru" in available:
        reasons.append("Inspection detected layout signals that benefit from MinerU parsing.")
        return ParserRoute(
            primary="mineru",
            fallbacks=[name for name in ("docling",) if name in available],
            reasons=reasons,
        )

    if "docling" in available:
        reasons.append("Docling is the default local parser for text-bearing documents.")
        return ParserRoute(
            primary="docling",
            fallbacks=[name for name in ("mineru",) if name in available],
            reasons=reasons,
        )

    if "mineru" in available:
        reasons.append("MinerU is the only configured parser that can accept this document.")
        return ParserRoute(primary="mineru", reasons=reasons)

    fallback = sorted(available)[0]
    reasons.append("No preferred parser is available; using the first configured parser.")
    return ParserRoute(primary=fallback, reasons=reasons)
