from __future__ import annotations

import json
import re
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from thesisound.source_analysis import (
    CrossSectionThreadDraft,
    DocumentMapDraft,
    DocumentMapDraftSection,
    SourceDocumentBlock,
)

_CONTENT_KEY = re.compile(r"\A[0-9a-f]{64}\Z")

PART_BUILDER_VERSION = 2
"""Bumped when a mapper or prompt change makes previously cached partitions wrong.

Bump this together with MAP_BUILDER_VERSION in document_map_cache.py whenever the
`document_map` prompt changes materially; the two caches store output from the
same prompt at different granularities. This constant is defined here rather than
imported from document_map_cache to avoid an import cycle -- see Step 3c.
"""


class CachedPartitionSection(BaseModel):
    """A mapped section stored without any trace of the source it came from.

    block_indexes are positions in the partition's block run; block IDs carry the
    source that produced them, so storing them would block reuse across two
    uploads of the same book.
    """

    section_id: str
    block_indexes: list[int] = Field(default_factory=list)
    title: str
    function: str
    key_concepts: list[str] = Field(default_factory=list)
    depends_on_section_ids: list[str] = Field(default_factory=list)
    required_for_global_understanding: bool = False
    unresolved_context: list[str] = Field(default_factory=list)


class CachedDocumentMapPart(BaseModel):
    content_key: str
    builder_version: int = 1
    block_count: int = Field(ge=1)
    working_thesis: str | None = None
    sections: list[CachedPartitionSection] = Field(default_factory=list)
    cross_section_threads: list[CrossSectionThreadDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DocumentMapPartCache:
    """Keep partitions that already succeeded when a later partition fails.

    A partition map costs one large model call and depends only on that
    partition's text, so losing it to an unrelated failure elsewhere in the
    document re-buys work that was already paid for.
    """

    def __init__(self, workspace_root: Path) -> None:
        self.root = workspace_root.expanduser().resolve() / "_shared" / "document-map-parts"

    def path(self, content_key: str) -> Path:
        if not _CONTENT_KEY.match(content_key):
            raise ValueError("A document-map-part cache key must be a sha256 digest.")
        return self.root / f"{content_key}.json"

    def load(
        self,
        content_key: str,
        blocks: list[SourceDocumentBlock],
    ) -> DocumentMapDraft | None:
        """Rebuild a stored partition draft, or return None to map from scratch.

        Never raises: any inconsistency means re-map, which is correct but costs a
        call, whereas a wrong draft would corrupt the document map.
        """

        if not blocks:
            return None
        try:
            cached = CachedDocumentMapPart.model_validate_json(
                self.path(content_key).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        if cached.content_key != content_key:
            return None
        if cached.builder_version != PART_BUILDER_VERSION:
            return None
        if cached.block_count != len(blocks):
            return None
        try:
            return DocumentMapDraft(
                working_thesis=cached.working_thesis,
                sections=[
                    DocumentMapDraftSection(
                        section_id=section.section_id,
                        source_block_ids=[
                            blocks[index].block_id for index in section.block_indexes
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
        draft: DocumentMapDraft,
    ) -> Path | None:
        if not blocks:
            return None
        index_by_id = {block.block_id: index for index, block in enumerate(blocks)}
        sections: list[CachedPartitionSection] = []
        for section in draft.sections:
            indexes = [
                index_by_id[block_id]
                for block_id in section.source_block_ids
                if block_id in index_by_id
            ]
            if len(indexes) != len(section.source_block_ids):
                # A section referencing a block outside this partition cannot be
                # rebuilt faithfully; storing it would silently drop content.
                return None
            sections.append(
                CachedPartitionSection(
                    section_id=section.section_id,
                    block_indexes=indexes,
                    title=section.title,
                    function=section.function,
                    key_concepts=section.key_concepts,
                    depends_on_section_ids=section.depends_on_section_ids,
                    required_for_global_understanding=(section.required_for_global_understanding),
                    unresolved_context=section.unresolved_context,
                )
            )
        cached = CachedDocumentMapPart(
            content_key=content_key,
            builder_version=PART_BUILDER_VERSION,
            block_count=len(blocks),
            working_thesis=draft.working_thesis,
            sections=sections,
            cross_section_threads=draft.cross_section_threads,
            warnings=draft.warnings,
        )
        path = self.path(content_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(cached.model_dump(mode="json"), ensure_ascii=False, indent=2)
        # Partitions are mapped concurrently and two partitions with identical text
        # share a content key, so a fixed ".tmp" name would let two writers interleave
        # into the same file. Caching is an optimisation: a write that loses the race
        # must return None, never fail the document map that already paid for the call.
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(payload + "\n", encoding="utf-8")
            temporary.replace(path)
        except OSError:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            return None
        return path
