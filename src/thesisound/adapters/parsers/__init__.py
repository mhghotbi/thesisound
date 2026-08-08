
"""Document parser adapters."""

from thesisound.adapters.parsers.docling_adapter import DoclingParser
from thesisound.adapters.parsers.epub_adapter import EpubDocumentParser
from thesisound.adapters.parsers.local_ocr_adapter import LocalOcrParser
from thesisound.adapters.parsers.native_adapter import NativeDocumentParser

__all__ = ["DoclingParser", "EpubDocumentParser", "LocalOcrParser", "NativeDocumentParser"]
