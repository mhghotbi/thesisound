from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from thesisound.ports import ParsedBlock, ParsedDocument

_HEADING_LABELS = {"title", "section_header"}
_FRONT_MATTER_LABELS = {"page_header", "page_footer", "footnote"}
_SAFE_KEY = re.compile(r"[^a-zA-Z0-9_.:/-]+")


def normalize_docling_document(
    document: Any,
    *,
    parser_version: str,
    raw_artifact_ref: str | None = None,
) -> ParsedDocument:
    """Convert a DoclingDocument-like object into stable internal blocks.

    Only a small public surface is assumed: ``iterate_items`` and item
    attributes such as ``text``, ``label``, ``prov`` and ``self_ref``. This
    keeps Docling objects outside the domain layer and allows lightweight tests.
    """

    warnings: list[str] = []
    blocks: list[ParsedBlock] = []
    heading_stack: list[tuple[int, str]] = []

    for position, (item, level) in enumerate(_iterate_items(document), start=1):
        label = _label_value(getattr(item, "label", None))
        text = _extract_item_text(item, document)
        if not text:
            continue

        if label in _HEADING_LABELS:
            heading_stack = _update_heading_stack(heading_stack, level, text)
        heading_path = [heading for _, heading in heading_stack]

        pages = _page_numbers(getattr(item, "prov", None))
        source_key = _source_key(getattr(item, "self_ref", None), position)
        blocks.append(
            ParsedBlock(
                source_block_key=source_key,
                text=text,
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                heading_path=heading_path,
                kind=_normalize_kind(label),
            )
        )

    if not blocks:
        warnings.append("Docling returned no non-empty content items.")
    elif all(block.page_start is None for block in blocks):
        warnings.append("No page provenance was available in the parsed document.")

    return ParsedDocument(
        parser_name="docling",
        parser_version=parser_version,
        blocks=blocks,
        warnings=warnings,
        raw_artifact_ref=raw_artifact_ref,
    )


def _iterate_items(document: Any) -> Iterable[tuple[Any, int]]:
    iterate = getattr(document, "iterate_items", None)
    if not callable(iterate):
        raise TypeError("Docling document does not expose iterate_items().")
    try:
        return iterate(traverse_pictures=True)
    except TypeError:
        return iterate()


def _extract_item_text(item: Any, document: Any) -> str:
    text = getattr(item, "text", None)
    if isinstance(text, str) and text.strip():
        return _clean_text(text)

    export_markdown = getattr(item, "export_to_markdown", None)
    if callable(export_markdown):
        for call in (
            lambda: export_markdown(doc=document),
            lambda: export_markdown(document),
            lambda: export_markdown(),
        ):
            try:
                rendered = call()
            except (TypeError, AttributeError):
                continue
            if isinstance(rendered, str) and rendered.strip():
                return _clean_text(rendered)
    return ""


def _clean_text(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\x00", "").splitlines()]
    return "\n".join(lines).strip()


def _label_value(label: Any) -> str:
    if label is None:
        return "other"
    value = getattr(label, "value", label)
    return str(value).lower()


def _normalize_kind(label: str) -> str:
    if label in _FRONT_MATTER_LABELS:
        return "front_matter"
    if label in _HEADING_LABELS:
        return "heading"
    if label in {"table", "picture", "code", "formula", "list_item"}:
        return label
    if label in {"paragraph", "text", "caption", "reference"}:
        return "text"
    return label or "other"


def _update_heading_stack(
    stack: list[tuple[int, str]], level: int, heading: str
) -> list[tuple[int, str]]:
    retained = [
        (existing_level, text)
        for existing_level, text in stack
        if existing_level < level
    ]
    retained.append((level, heading))
    return retained


def _page_numbers(provenance: Any) -> list[int]:
    if not provenance:
        return []
    pages: list[int] = []
    for item in provenance:
        page = getattr(item, "page_no", None)
        if isinstance(page, int) and page > 0:
            pages.append(page)
    return sorted(set(pages))


def _source_key(self_ref: Any, position: int) -> str:
    raw = str(self_ref or f"item-{position}")
    cleaned = _SAFE_KEY.sub("-", raw).strip("-")
    return cleaned or f"item-{position}"
