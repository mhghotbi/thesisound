from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from thesisound.ports import DocumentInspection, ParsedBlock, ParsedDocument

_KEY = re.compile(r"\A[0-9a-f]{64}\Z")
_SCHEMA_VERSION = 1


class CachedParse(BaseModel):
    """One parser's output for one file, stored with no trace of who parsed it.

    Blocks and warnings are held flat rather than as an embedded ParsedDocument,
    because ParsedDocument carries `raw_artifact_ref` -- an absolute path into the
    artifact tree of whichever project happened to parse first, which the web flow
    then moves. A field that must never round-trip is better absent than nulled.
    """

    schema_version: Literal[1] = 1
    cache_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_name: str
    parser_version: str
    parser_identity: dict[str, str]
    blocks: list[ParsedBlock]
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def parse_cache_key(
    inspection: DocumentInspection,
    *,
    parser_name: str,
    identity: Mapping[str, str],
) -> str:
    """Name the exact (bytes, parser, algorithm) triple whose output can be shared.

    Only the three inspection fields a parser actually reads are folded in: the
    extension, because the native parser dispatches on it and the same bytes named
    .pdf and .txt are two different documents; `encrypted`, which gates supports();
    and `likely_complex_layout`, the one field the OCR worker reads. Page counts,
    file sizes, mime types and sampled character counts are deliberately absent --
    no parse() consults them, they drift with the installed pypdf, and mime_type is
    read from the OS registry, so including them would discard entries for parsers
    that never touch any of it.

    Provider and algorithm versions live in `identity`, where each parser states
    them precisely, rather than in a whole-inspection hash that only guesses.
    """

    payload = {
        "schema_version": _SCHEMA_VERSION,
        "sha256": inspection.sha256,
        "extension": inspection.extension,
        "encrypted": inspection.encrypted,
        "likely_complex_layout": inspection.likely_complex_layout,
        "parser_name": parser_name,
        "parser_identity": dict(identity),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ParsedDocumentCache:
    """Share the one artifact whose cost is measured in minutes: the parse.

    A parse describes the file, not the project, so the same bytes never need OCR
    twice -- not for a second upload, not for a second user. Everything downstream
    of the parse is cheap and is recomputed locally: the quality gate is a pure
    function of (inspection, parsed), so its verdict always reflects the code
    running now rather than the code that ran first.

    Two requests parsing the same file at once both miss, both parse and both
    write. That duplicated work is deliberate. A lock file would trade it for a
    crashed worker wedging ingestion of that document permanently, with no
    operator-visible cause -- a far worse failure on a machine nobody is watching.
    """

    def __init__(self, artifact_root: Path) -> None:
        self.root = artifact_root.expanduser().resolve() / "_shared" / "parsed-documents"

    def path(self, cache_key: str) -> Path:
        if not _KEY.match(cache_key):
            raise ValueError("A parsed-document cache key must be a sha256 digest.")
        return self.root / f"{cache_key}.json"

    def load(self, cache_key: str, *, parser_name: str) -> ParsedDocument | None:
        """Rebuild a stored parse for this parser, or return None to parse fresh."""

        cached = self._load_raw(cache_key)
        if cached is None or cached.parser_name != parser_name or not cached.blocks:
            return None
        return ParsedDocument(
            parser_name=cached.parser_name,
            parser_version=cached.parser_version,
            blocks=cached.blocks,
            warnings=cached.warnings,
        )

    def save(
        self,
        cache_key: str,
        parsed: ParsedDocument,
        *,
        source_sha256: str,
        identity: Mapping[str, str],
    ) -> Path | None:
        """Store a successful, non-empty parse. Never raises; never rewrites."""

        if not parsed.blocks:
            return None
        try:
            path = self.path(cache_key)
        except ValueError:
            return None
        if self._load_raw(cache_key) is not None:
            # Already cached under this key. The store is tracked in git, so a
            # rewrite that only moves `created_at` would diff on every ingest;
            # entries are written once and never mutated.
            return path

        record = CachedParse(
            cache_key=cache_key,
            source_sha256=source_sha256,
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
            parser_identity=dict(identity),
            blocks=parsed.blocks,
            warnings=parsed.warnings,
        )
        payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2)
        # A per-writer temporary name, unlike document_map_cache's fixed
        # `.json.tmp`: two web requests can parse the same file at the same
        # time, and on Windows two writers sharing one temporary path corrupt
        # each other's bytes rather than merely racing. Kept short (not
        # `<key>.json.<uuid>.tmp`) because Windows' default MAX_PATH is 260
        # characters and a deep artifact root has little room left for a
        # 64-char key repeated twice in one filename.
        temporary = path.parent / f"{uuid4().hex}.tmp"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(payload + "\n", encoding="utf-8")
            temporary.replace(path)
        except OSError:
            temporary.unlink(missing_ok=True)
            return None
        return path

    def _load_raw(self, cache_key: str) -> CachedParse | None:
        try:
            cached = CachedParse.model_validate_json(
                self.path(cache_key).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        if cached.cache_key != cache_key:
            return None
        return cached
