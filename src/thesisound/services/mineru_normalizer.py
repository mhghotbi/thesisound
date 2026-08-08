from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from thesisound.ports import ParsedBlock, ParsedDocument

_SAFE_KEY = re.compile(r"[^a-zA-Z0-9_.:/-]+")
_AUXILIARY_TYPES = {
    "header",
    "footer",
    "page_header",
    "page_footer",
    "page_number",
    "aside_text",
    "page_aside_text",
    "page_footnote",
}


class MineruOutputError(ValueError):
    """Raised when MinerU output cannot be normalized safely."""


def normalize_mineru_output(
    output_root: Path,
    *,
    source_path: Path,
    parser_version: str,
) -> ParsedDocument:
    """Normalize the most stable MinerU structured output available.

    MinerU currently emits content-list files specifically intended for
    downstream processing. V2 is preferred when present, then the legacy flat
    content list, and finally middle.json as a compatibility fallback.
    """

    root = output_root.expanduser().resolve()
    if not root.exists():
        raise MineruOutputError(f"MinerU output directory does not exist: {root}")

    selected = _select_output_file(root, source_path.stem)
    if selected is None:
        raise MineruOutputError("MinerU produced no supported structured JSON output.")

    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MineruOutputError(f"Could not read MinerU output: {selected.name}") from exc

    if selected.name.endswith("_content_list_v2.json"):
        blocks = _normalize_content_list_v2(payload)
    elif selected.name.endswith("_content_list.json"):
        blocks = _normalize_content_list(payload)
    elif selected.name.endswith("_middle.json"):
        blocks = _normalize_middle(payload)
    else:  # defensive guard if selection rules are extended later
        raise MineruOutputError(f"Unsupported MinerU output file: {selected.name}")

    warnings: list[str] = []
    if not blocks:
        warnings.append("MinerU returned no non-empty content blocks.")
    elif all(block.page_start is None for block in blocks):
        warnings.append("No page provenance was available in the MinerU output.")
    if not any(block.kind == "heading" for block in blocks):
        warnings.append("No heading hierarchy was found in the MinerU output.")

    return ParsedDocument(
        parser_name="mineru",
        parser_version=parser_version,
        blocks=blocks,
        warnings=warnings,
        raw_artifact_ref=str(selected),
    )


def _select_output_file(root: Path, source_stem: str) -> Path | None:
    patterns = (
        "*_content_list_v2.json",
        "*_content_list.json",
        "*_middle.json",
    )
    for pattern in patterns:
        candidates = sorted(path for path in root.rglob(pattern) if path.is_file())
        exact = [path for path in candidates if path.name.startswith(source_stem)]
        if exact:
            return exact[0]
        if candidates:
            return candidates[0]
    return None


def _normalize_content_list(payload: Any) -> list[ParsedBlock]:
    if not isinstance(payload, list):
        raise MineruOutputError("MinerU content_list.json must contain a list.")

    blocks: list[ParsedBlock] = []
    heading_stack: list[tuple[int, str]] = []
    for position, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "other").lower()
        text_level = _positive_int(item.get("text_level"))
        text = _content_list_text(item, item_type)
        if not text:
            continue
        if item_type == "text" and text_level:
            heading_stack = _update_heading_stack(heading_stack, text_level, text)
            kind = "heading"
        else:
            kind = _normalize_kind(item_type)
        page = _page_number(item.get("page_idx"))
        blocks.append(
            ParsedBlock(
                source_block_key=f"mineru-flat-{position}",
                text=text,
                page_start=page,
                page_end=page,
                heading_path=[heading for _, heading in heading_stack],
                kind=kind,
            )
        )
    return blocks


def _normalize_content_list_v2(payload: Any) -> list[ParsedBlock]:
    if not isinstance(payload, list):
        raise MineruOutputError("MinerU content_list_v2.json must contain a page list.")

    blocks: list[ParsedBlock] = []
    heading_stack: list[tuple[int, str]] = []
    position = 0
    for page_index, page_items in enumerate(payload):
        if not isinstance(page_items, list):
            continue
        for item in page_items:
            if not isinstance(item, dict):
                continue
            position += 1
            item_type = str(item.get("type") or "other").lower()
            content = item.get("content")
            text = _collect_text(content)
            if not text:
                continue
            if item_type == "title":
                level = 1
                if isinstance(content, dict):
                    level = _positive_int(content.get("level")) or 1
                heading_stack = _update_heading_stack(heading_stack, level, text)
                kind = "heading"
            else:
                kind = _normalize_kind(item_type)
            page = page_index + 1
            blocks.append(
                ParsedBlock(
                    source_block_key=f"mineru-v2-page-{page}-item-{position}",
                    text=text,
                    page_start=page,
                    page_end=page,
                    heading_path=[heading for _, heading in heading_stack],
                    kind=kind,
                )
            )
    return blocks


def _normalize_middle(payload: Any) -> list[ParsedBlock]:
    if not isinstance(payload, dict):
        raise MineruOutputError("MinerU middle.json must contain an object.")
    pages = payload.get("pdf_info")
    if not isinstance(pages, list):
        raise MineruOutputError("MinerU middle.json has no pdf_info page list.")

    blocks: list[ParsedBlock] = []
    heading_stack: list[tuple[int, str]] = []
    position = 0
    ordered_pages = sorted(
        (page for page in pages if isinstance(page, dict)),
        key=lambda page: _non_negative_int(page.get("page_idx")) or 0,
    )
    for page in ordered_pages:
        page_number = (_non_negative_int(page.get("page_idx")) or 0) + 1
        page_blocks = page.get("para_blocks") or page.get("preproc_blocks") or []
        if not isinstance(page_blocks, list):
            continue
        for item in page_blocks:
            if not isinstance(item, dict):
                continue
            position += 1
            item_type = str(item.get("type") or "other").lower()
            text = _collect_text(item)
            if not text:
                continue
            if item_type in {"title", "doc_title", "section_header"}:
                heading_stack = _update_heading_stack(heading_stack, 1, text)
                kind = "heading"
            else:
                kind = _normalize_kind(item_type)
            blocks.append(
                ParsedBlock(
                    source_block_key=f"mineru-middle-page-{page_number}-item-{position}",
                    text=text,
                    page_start=page_number,
                    page_end=page_number,
                    heading_path=[heading for _, heading in heading_stack],
                    kind=kind,
                )
            )
    return blocks


def _content_list_text(item: dict[str, Any], item_type: str) -> str:
    if item_type in {"text", "equation"}:
        return _clean_text(str(item.get("text") or ""))
    if item_type == "table":
        return _join_values(
            item.get("table_caption"),
            item.get("table_body"),
            item.get("table_footnote"),
        )
    if item_type in {"image", "chart"}:
        return _join_values(
            item.get("image_caption") or item.get("chart_caption"),
            item.get("content"),
            item.get("image_footnote") or item.get("chart_footnote"),
        )
    if item_type in {"code", "algorithm"}:
        return _join_values(
            item.get("code_caption") or item.get("algorithm_caption"),
            item.get("code_body") or item.get("algorithm_body") or item.get("text"),
            item.get("code_footnote") or item.get("algorithm_footnote"),
        )
    return _collect_text(item)


def _collect_text(value: Any) -> str:
    parts: list[str] = []
    _collect_text_parts(value, parts, key=None)
    return _clean_text("\n".join(parts))


def _collect_text_parts(value: Any, parts: list[str], key: str | None) -> None:
    if isinstance(value, str):
        if key not in {"img_path", "image_path", "path", "url"} and value.strip():
            parts.append(value)
        return
    if isinstance(value, list):
        for child in value:
            _collect_text_parts(child, parts, key=key)
        return
    if isinstance(value, dict):
        for child_key, child in value.items():
            if child_key in {"bbox", "score", "angle", "page_idx", "text_level"}:
                continue
            _collect_text_parts(child, parts, key=child_key)


def _join_values(*values: Any) -> str:
    parts = [_collect_text(value) for value in values]
    return _clean_text("\n".join(part for part in parts if part))


def _clean_text(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\x00", "").splitlines()]
    compact: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and (not compact or compact[-1] != stripped):
            compact.append(stripped)
    return "\n".join(compact).strip()


def _normalize_kind(item_type: str) -> str:
    if item_type in _AUXILIARY_TYPES:
        return "front_matter"
    if item_type in {"title", "doc_title", "section_header"}:
        return "heading"
    if item_type in {"paragraph", "text"}:
        return "text"
    if item_type in {"list", "index"}:
        return "list_item"
    if item_type in {"equation", "equation_interline", "interline_equation"}:
        return "formula"
    return item_type or "other"


def _update_heading_stack(
    stack: list[tuple[int, str]], level: int, heading: str
) -> list[tuple[int, str]]:
    retained = [item for item in stack if item[0] < level]
    retained.append((level, heading))
    return retained


def _page_number(value: Any) -> int | None:
    page_index = _non_negative_int(value)
    return page_index + 1 if page_index is not None else None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    return None


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _safe_key(value: str) -> str:
    cleaned = _SAFE_KEY.sub("-", value).strip("-")
    return cleaned or "item"


def iter_supported_outputs(root: Path) -> Iterable[Path]:
    """Expose discovered structured outputs for diagnostics and tests."""

    for pattern in ("*_content_list_v2.json", "*_content_list.json", "*_middle.json"):
        yield from sorted(root.rglob(pattern))
