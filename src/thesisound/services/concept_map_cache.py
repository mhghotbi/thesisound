"""Content-addressed cache for source concept maps.

The AI map is immutable once Pass 5 succeeds. A builder-version bump invalidates
both the source-level file and every per-chapter sub-entry, so a chapter re-run
does not rebuild chapters that are still valid for the current builder.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from thesisound.concepts import ConceptCell, ConceptEdge, SourceChapter, SourceConceptMap
from thesisound.services.document_identity import content_key
from thesisound.source_analysis import SourceDocumentBlock

_CONTENT_KEY = re.compile(r"\A[0-9a-f]{64}\Z")
CONCEPT_MAP_BUILDER_VERSION = 1
"""Bumped when a cells/edges/statistics change makes previously cached maps wrong."""


class CachedChapterConceptMap(BaseModel):
    """One chapter's cells and intra-chapter edges, reusable across projects."""

    source_fingerprint: str
    chapter_hash: str
    builder_version: int = CONCEPT_MAP_BUILDER_VERSION
    chapter: SourceChapter
    cells: list[ConceptCell] = Field(default_factory=list)
    intra_edges: list[ConceptEdge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def chapter_hash(chapter: SourceChapter, blocks: Sequence[SourceDocumentBlock]) -> str:
    """Identify a chapter by index plus the heading+text run the model saw."""

    by_id = {block.block_id: block for block in blocks}
    ordered = [by_id[block_id] for block_id in chapter.block_ids if block_id in by_id]
    return content_key(
        [
            str(chapter.chapter_index),
            *(
                " ".join([*block.heading_path, block.text])
                for block in ordered
                if block.block_type != "front_matter"
            ),
        ]
    )


_PATH_DIGEST_CHARS = 24
"""How much of a digest names a file on disk.

Two full sha256 digests spend 134 characters on the nested chapter path alone,
which pushed the whole path past the Windows 260-character limit under a pytest
temporary directory and made every chapter write fail there. The stored value
still has to be a full digest -- callers are validated below -- but 96 bits is far
more identity than a per-machine cache of books needs to stay collision-free.
"""


def _path_name(digest: str) -> str:
    return digest[:_PATH_DIGEST_CHARS]


class ConceptMapCache:
    """Share the expensive concept map between uploads of the same book.

    Source-level path: ``_shared/concept-maps/<fingerprint>.json``.
    Per-chapter path: ``_shared/concept-maps/<fingerprint>/<chapter_hash>.json``,
    where each name is the leading `_PATH_DIGEST_CHARS` of the digest.
    """

    def __init__(self, workspace_root: Path) -> None:
        self.root = workspace_root.expanduser().resolve() / "_shared" / "concept-maps"

    def source_path(self, fingerprint: str) -> Path:
        _require_digest(fingerprint, "source fingerprint")
        return self.root / f"{_path_name(fingerprint)}.json"

    def chapter_path(self, fingerprint: str, chapter_key: str) -> Path:
        _require_digest(fingerprint, "source fingerprint")
        _require_digest(chapter_key, "chapter hash")
        return self.root / _path_name(fingerprint) / f"{_path_name(chapter_key)}.json"

    def load_source(self, fingerprint: str) -> SourceConceptMap | None:
        try:
            cached = SourceConceptMap.model_validate_json(
                self.source_path(fingerprint).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        if cached.source_fingerprint != fingerprint:
            return None
        if cached.builder_version != CONCEPT_MAP_BUILDER_VERSION:
            return None
        return cached

    def save_source(self, concept_map: SourceConceptMap) -> Path | None:
        if concept_map.builder_version != CONCEPT_MAP_BUILDER_VERSION:
            return None
        path = self.source_path(concept_map.source_fingerprint)
        _atomic_write(
            path,
            json.dumps(concept_map.model_dump(mode="json"), ensure_ascii=False, indent=2),
        )
        return path

    def load_chapter(
        self,
        fingerprint: str,
        chapter_key: str,
    ) -> CachedChapterConceptMap | None:
        try:
            cached = CachedChapterConceptMap.model_validate_json(
                self.chapter_path(fingerprint, chapter_key).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        if cached.source_fingerprint != fingerprint:
            return None
        if cached.chapter_hash != chapter_key:
            return None
        if cached.builder_version != CONCEPT_MAP_BUILDER_VERSION:
            return None
        return cached

    def save_chapter(self, entry: CachedChapterConceptMap) -> Path | None:
        if entry.builder_version != CONCEPT_MAP_BUILDER_VERSION:
            return None
        path = self.chapter_path(entry.source_fingerprint, entry.chapter_hash)
        _atomic_write(
            path,
            json.dumps(entry.model_dump(mode="json"), ensure_ascii=False, indent=2),
        )
        return path


def _require_digest(value: str, label: str) -> None:
    if not _CONTENT_KEY.match(value):
        raise ValueError(f"A concept-map {label} must be a sha256 digest.")


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload + "\n", encoding="utf-8")
    temporary.replace(path)
