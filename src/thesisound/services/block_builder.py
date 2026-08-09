from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from uuid import UUID

from thesisound.domain import Locator
from thesisound.ports import ParsedBlock, ParsedDocument
from thesisound.services.repeated_margin_cleaner import remove_repeated_margins
from thesisound.services.token_counter import estimate_tokens
from thesisound.source_analysis import BlockBuildReport, BlockType, SourceDocumentBlock

_HEADING_KINDS = {"heading", "title", "section_header"}
_STANDALONE_KINDS = {"table", "formula", "code"}
# Parser kinds that describe the wrapper around a text rather than the text itself.
FRONT_MATTER_KINDS = frozenset({"front_matter", "footnote", "reference"})
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?؟؛])\s+")


@dataclass
class _Accumulator:
    blocks: list[ParsedBlock] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)
    heading_path: list[str] = field(default_factory=list)
    block_type: BlockType = "other"
    estimated_tokens: int = 0

    def clear(self) -> None:
        self.blocks.clear()
        self.text_parts.clear()
        self.heading_path.clear()
        self.block_type = "other"
        self.estimated_tokens = 0


class BlockBuilder:
    def __init__(
        self,
        *,
        target_tokens: int = 1_200,
        maximum_tokens: int = 1_800,
        minimum_tokens: int = 80,
    ) -> None:
        if not 0 < minimum_tokens <= target_tokens <= maximum_tokens:
            raise ValueError("Expected minimum_tokens <= target_tokens <= maximum_tokens.")
        self.target_tokens = target_tokens
        self.maximum_tokens = maximum_tokens
        self.minimum_tokens = minimum_tokens

    def build(
        self,
        parsed: ParsedDocument,
        *,
        source_id: UUID,
    ) -> tuple[list[SourceDocumentBlock], BlockBuildReport]:
        cleaned, removed = remove_repeated_margins(parsed.blocks)
        expanded: list[ParsedBlock] = []
        split_keys: list[str] = []
        for block in cleaned:
            if block.kind.casefold() in _HEADING_KINDS:
                continue
            pieces = self._split_oversized(block)
            expanded.extend(pieces)
            if len(pieces) > 1:
                split_keys.append(block.source_block_key)

        output: list[SourceDocumentBlock] = []
        accumulator = _Accumulator()
        for block in expanded:
            kind = _block_type(block.kind)
            block_tokens = estimate_tokens(block.text)
            standalone = block.kind.casefold() in _STANDALONE_KINDS
            heading_changed = bool(
                accumulator.blocks and accumulator.heading_path != block.heading_path
            )
            would_exceed = bool(
                accumulator.blocks
                and accumulator.estimated_tokens + block_tokens > self.maximum_tokens
            )

            if heading_changed or would_exceed or standalone:
                self._flush(accumulator, output, source_id)
            if standalone:
                self._add(accumulator, block, kind)
                self._flush(accumulator, output, source_id)
                continue

            self._add(accumulator, block, kind)
            if accumulator.estimated_tokens >= self.target_tokens:
                self._flush(accumulator, output, source_id)

        self._flush(accumulator, output, source_id)
        output = self._merge_small_neighbors(output)
        _link_neighbors(output)

        warnings: list[str] = []
        if not output:
            warnings.append("No semantic blocks were produced from the parsed document.")
        if removed:
            warnings.append(f"Removed {len(removed)} repeated margin blocks.")
        report = BlockBuildReport(
            source_id=source_id,
            input_block_count=len(parsed.blocks),
            output_block_count=len(output),
            removed_margin_block_keys=removed,
            split_source_block_keys=split_keys,
            warnings=warnings,
        )
        return output, report

    def _split_oversized(self, block: ParsedBlock) -> list[ParsedBlock]:
        if estimate_tokens(block.text) <= self.maximum_tokens:
            return [block]

        paragraphs = [
            part.strip()
            for part in re.split(r"\n\s*\n", block.text)
            if part.strip()
        ]
        if len(paragraphs) == 1:
            paragraphs = [
                part.strip()
                for part in _SENTENCE_BOUNDARY.split(block.text)
                if part.strip()
            ]
        if len(paragraphs) == 1:
            return _split_by_characters(block, self.maximum_tokens)

        pieces: list[str] = []
        current: list[str] = []
        current_tokens = 0
        for paragraph in paragraphs:
            paragraph_tokens = estimate_tokens(paragraph)
            if current and current_tokens + paragraph_tokens > self.maximum_tokens:
                pieces.append("\n\n".join(current))
                current = []
                current_tokens = 0
            if paragraph_tokens > self.maximum_tokens:
                if current:
                    pieces.append("\n\n".join(current))
                    current = []
                    current_tokens = 0
                oversized = _split_by_characters(
                    block,
                    self.maximum_tokens,
                    paragraph,
                )
                pieces.extend(piece.text for piece in oversized)
                continue
            current.append(paragraph)
            current_tokens += paragraph_tokens
        if current:
            pieces.append("\n\n".join(current))
        return [
            _copy_piece(block, text, index)
            for index, text in enumerate(pieces, start=1)
        ]

    @staticmethod
    def _add(accumulator: _Accumulator, block: ParsedBlock, kind: BlockType) -> None:
        if not accumulator.blocks:
            accumulator.heading_path = list(block.heading_path)
            accumulator.block_type = kind
        elif accumulator.block_type != kind:
            accumulator.block_type = "other"
        accumulator.blocks.append(block)
        accumulator.text_parts.append(block.text.strip())
        accumulator.estimated_tokens += estimate_tokens(block.text)

    @staticmethod
    def _flush(
        accumulator: _Accumulator,
        output: list[SourceDocumentBlock],
        source_id: UUID,
    ) -> None:
        if not accumulator.blocks:
            return
        text = "\n\n".join(part for part in accumulator.text_parts if part).strip()
        if text:
            index = len(output) + 1
            output.append(
                SourceDocumentBlock(
                    block_id=_block_id(source_id, index, text),
                    source_id=source_id,
                    locator=_locator(accumulator.blocks, accumulator.heading_path),
                    heading_path=accumulator.heading_path,
                    block_type=accumulator.block_type,
                    text=text,
                    estimated_token_count=estimate_tokens(text),
                    source_block_keys=[
                        block.source_block_key for block in accumulator.blocks
                    ],
                )
            )
        accumulator.clear()

    def _merge_small_neighbors(
        self,
        blocks: list[SourceDocumentBlock],
    ) -> list[SourceDocumentBlock]:
        if len(blocks) < 2:
            return blocks
        merged: list[SourceDocumentBlock] = []
        for block in blocks:
            if (
                merged
                and block.estimated_token_count < self.minimum_tokens
                and merged[-1].heading_path == block.heading_path
                and merged[-1].block_type not in _STANDALONE_KINDS
                and block.block_type not in _STANDALONE_KINDS
                and merged[-1].estimated_token_count + block.estimated_token_count
                <= self.maximum_tokens
            ):
                previous = merged.pop()
                text = f"{previous.text}\n\n{block.text}"
                merged.append(
                    SourceDocumentBlock(
                        block_id=previous.block_id,
                        source_id=previous.source_id,
                        locator=_merge_locators(previous.locator, block.locator),
                        heading_path=previous.heading_path,
                        block_type=(
                            previous.block_type
                            if previous.block_type == block.block_type
                            else "other"
                        ),
                        text=text,
                        estimated_token_count=estimate_tokens(text),
                        source_block_keys=[
                            *previous.source_block_keys,
                            *block.source_block_keys,
                        ],
                    )
                )
            else:
                merged.append(block)
        return merged


def _split_by_characters(
    block: ParsedBlock,
    maximum_tokens: int,
    text: str | None = None,
) -> list[ParsedBlock]:
    value = text or block.text
    maximum_characters = max(200, int(maximum_tokens * 3.5))
    pieces = [
        value[index : index + maximum_characters].strip()
        for index in range(0, len(value), maximum_characters)
    ]
    return [
        _copy_piece(block, piece, index)
        for index, piece in enumerate(pieces, start=1)
        if piece
    ]


def _copy_piece(block: ParsedBlock, text: str, index: int) -> ParsedBlock:
    return block.model_copy(
        update={
            "source_block_key": f"{block.source_block_key}#part-{index}",
            "text": text,
        }
    )


def _block_id(source_id: UUID, index: int, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"blk-{str(source_id)[:8]}-{index:05d}-{digest}"


def _block_type(kind: str) -> BlockType:
    normalized = kind.casefold()
    if normalized in FRONT_MATTER_KINDS:
        return "front_matter"
    if normalized == "table":
        return "table"
    if normalized == "formula":
        return "formula"
    if normalized == "code":
        return "code"
    return "other"


def _locator(blocks: list[ParsedBlock], heading_path: list[str]) -> Locator:
    starts = [block.page_start for block in blocks if block.page_start is not None]
    ends = [block.page_end for block in blocks if block.page_end is not None]
    return Locator(
        page_start=min(starts) if starts else None,
        page_end=max(ends) if ends else None,
        chapter=heading_path[0] if heading_path else None,
        section=heading_path[-1] if heading_path else None,
    )


def _merge_locators(first: Locator, second: Locator) -> Locator:
    starts = [
        page for page in (first.page_start, second.page_start) if page is not None
    ]
    ends = [
        page for page in (first.page_end, second.page_end) if page is not None
    ]
    return Locator(
        page_start=min(starts) if starts else None,
        page_end=max(ends) if ends else None,
        chapter=first.chapter or second.chapter,
        section=first.section or second.section,
    )


def _link_neighbors(blocks: list[SourceDocumentBlock]) -> None:
    for index, block in enumerate(blocks):
        block.previous_block_id = blocks[index - 1].block_id if index > 0 else None
        block.next_block_id = (
            blocks[index + 1].block_id if index + 1 < len(blocks) else None
        )
