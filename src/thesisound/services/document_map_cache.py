from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field

from thesisound.domain import CrossSectionThread, DocumentMap, DocumentMapSection
from thesisound.services.document_mapper import scope_locator
from thesisound.source_analysis import SourceDocumentBlock

_CONTENT_KEY = re.compile(r"\A[0-9a-f]{64}\Z")
MAP_BUILDER_VERSION = 2
"""Bumped when a mapper change makes previously cached maps wrong.

Version 2: `document_map_merge` produced no cross-partition structure at all
before prompt version 1.1.0, so every multi-partition map cached under version 1
is missing its global layer.
"""


class CachedMapSection(BaseModel):
    section_id: str
    content_block_indexes: list[int] = Field(default_factory=list)
    title: str
    function: str
    key_concepts: list[str] = Field(default_factory=list)
    depends_on_section_ids: list[str] = Field(default_factory=list)
    required_for_global_understanding: bool = False
    unresolved_context: list[str] = Field(default_factory=list)


class CachedDocumentMap(BaseModel):
    """A document map stored without any trace of the source it was built for.

    Sections point at positions in the content-block run instead of block IDs,
    because a block ID carries the source that produced it. Locators are absent on
    purpose: page numbers belong to the file in hand, not to the text, and reusing
    them across two copies of a book would cite the wrong pages.
    """

    content_key: str
    builder_version: int = 1
    content_block_count: int = Field(ge=1)
    working_thesis: str | None = None
    sections: list[CachedMapSection] = Field(default_factory=list)
    cross_section_threads: list[CrossSectionThread] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DocumentMapCache:
    """Share the one expensive question-independent artifact between sources.

    A document map describes the book, not the research question, so the same text
    never needs mapping twice — not for a second upload, not for another project.
    """

    def __init__(self, workspace_root: Path) -> None:
        self.root = workspace_root.expanduser().resolve() / "_shared" / "document-maps"

    def path(self, content_key: str) -> Path:
        if not _CONTENT_KEY.match(content_key):
            raise ValueError("A document-map cache key must be a sha256 digest.")
        return self.root / f"{content_key}.json"

    def load(
        self,
        content_key: str,
        blocks: list[SourceDocumentBlock],
        *,
        source_id: UUID,
    ) -> DocumentMap | None:
        """Rebuild a stored map for these blocks, or return None to map from scratch."""

        content = _content_blocks(blocks)
        if not content:
            return None
        try:
            cached = CachedDocumentMap.model_validate_json(
                self.path(content_key).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        if cached.content_key != content_key:
            return None
        if cached.content_block_count != len(content):
            return None
        if cached.builder_version != MAP_BUILDER_VERSION:
            return None
        try:
            return DocumentMap(
                source_id=source_id,
                scope_locator=scope_locator(blocks),
                working_thesis=cached.working_thesis,
                sections=[
                    DocumentMapSection(
                        section_id=section.section_id,
                        source_block_ids=[
                            content[index].block_id
                            for index in section.content_block_indexes
                        ],
                        title=section.title,
                        function=section.function,
                        key_concepts=section.key_concepts,
                        depends_on_section_ids=section.depends_on_section_ids,
                        required_for_global_understanding=(
                            section.required_for_global_understanding
                        ),
                        unresolved_context=section.unresolved_context,
                    )
                    for section in cached.sections
                ],
                cross_section_threads=cached.cross_section_threads,
                warnings=cached.warnings,
            )
        except (IndexError, ValueError):
            return None

    def save(
        self,
        content_key: str,
        blocks: list[SourceDocumentBlock],
        document_map: DocumentMap,
    ) -> Path | None:
        content = _content_blocks(blocks)
        if not content:
            return None
        index_by_id = {block.block_id: index for index, block in enumerate(content)}
        cached = CachedDocumentMap(
            content_key=content_key,
            builder_version=MAP_BUILDER_VERSION,
            content_block_count=len(content),
            working_thesis=document_map.working_thesis,
            sections=[
                CachedMapSection(
                    section_id=section.section_id,
                    content_block_indexes=[
                        index_by_id[block_id]
                        for block_id in section.source_block_ids
                        if block_id in index_by_id
                    ],
                    title=section.title,
                    function=section.function,
                    key_concepts=section.key_concepts,
                    depends_on_section_ids=section.depends_on_section_ids,
                    required_for_global_understanding=(
                        section.required_for_global_understanding
                    ),
                    unresolved_context=section.unresolved_context,
                )
                for section in document_map.sections
            ],
            cross_section_threads=document_map.cross_section_threads,
            warnings=document_map.warnings,
        )
        path = self.path(content_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(cached.model_dump(mode="json"), ensure_ascii=False, indent=2)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(payload + "\n", encoding="utf-8")
        temporary.replace(path)
        return path


def _content_blocks(blocks: list[SourceDocumentBlock]) -> list[SourceDocumentBlock]:
    return [block for block in blocks if block.block_type != "front_matter"]
