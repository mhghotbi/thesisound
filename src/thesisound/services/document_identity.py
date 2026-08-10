from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from thesisound.ports import ParsedDocument
from thesisound.services.block_builder import FRONT_MATTER_KINDS
from thesisound.source_analysis import SourceDocumentBlock

_DIACRITICS = re.compile(r"[ً-ٰٟ]")
_NON_WORD = re.compile(r"[^\w؀-ۿ]+", re.UNICODE)
_ARABIC_LETTERS = str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه"})
_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


def normalize_for_identity(text: str) -> str:
    """Fold away differences two parsers can produce from the very same words.

    Half-spaces, Arabic and Persian letter forms, diacritics, digit shapes,
    punctuation and whitespace all vary between parser routes and between two
    exports of one book. None of them change which text this is.
    """

    value = text.translate(_ARABIC_LETTERS).translate(_DIGITS)
    value = _DIACRITICS.sub("", value)
    value = _NON_WORD.sub(" ", value.casefold())
    return " ".join(value.split())


def content_key(texts: Iterable[str]) -> str:
    """Hash an ordered run of texts; position is part of the identity."""

    digest = hashlib.sha256()
    for text in texts:
        digest.update(normalize_for_identity(text).encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()


def parsed_document_key(parsed: ParsedDocument) -> str:
    """Identify a document by its body text rather than by its file bytes.

    Front matter, footnotes and references are left out, so a different cover or a
    different file wrapper around the same book still lands on the same key. That
    holds only as far as the parser labels those parts: a cover page that comes
    through as ordinary body text does change the key, and the caller then treats
    the document as a new one.
    """

    return content_key(
        block.text for block in parsed.blocks if block.kind.casefold() not in FRONT_MATTER_KINDS
    )


def block_sequence_key(blocks: list[SourceDocumentBlock]) -> str:
    """Identify the exact content-block run a document map was built for.

    Heading paths are folded in because the mapper reads them too, so two documents
    that share their prose but not their headings must not share a map. Block IDs and
    locators are left out: they name the source and the file, not the text.
    """

    return content_key(
        " ".join([*block.heading_path, block.text])
        for block in blocks
        if block.block_type != "front_matter"
    )


def partition_block_key(blocks: list[SourceDocumentBlock]) -> str:
    """Identify one document-map partition by exactly the text the prompt saw.

    Unlike block_sequence_key this keeps front matter: _map_partition sends every
    block in the partition to the model and lets the draft reference any of them,
    so two partitions that differ only in front matter must not share a cache
    entry. Each heading item and block text are separate fields so their
    boundaries cannot collide. Block IDs and locators stay out: they name the
    source, not the text.
    """

    fields: list[str] = []
    for block in blocks:
        fields.append("partition block")
        for index, heading in enumerate(block.heading_path):
            fields.extend((f"heading {index}", heading))
        fields.extend(("text", block.text))
    return content_key(fields)
