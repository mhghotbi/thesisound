from __future__ import annotations

from enum import StrEnum
from json import dumps
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class UiSourceStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    REVIEW = "review"
    BLOCKED = "blocked"


class UiSourceManifest(BaseModel):
    source_id: UUID = Field(default_factory=uuid4)
    filename: str
    display_title: str | None = None
    content_type: str | None = None
    size_bytes: int = Field(ge=0)
    status: UiSourceStatus = UiSourceStatus.PROCESSING
    selected: bool = False
    issue_summary: str | None = None
    quality_issues: list[str] = Field(default_factory=list)
    is_demo_result: bool = False
    parser_name: str | None = None
    quality_verdict: str | None = None
    safe_for_claim_extraction: bool = False
    block_count: int = Field(default=0, ge=0)
    text_characters: int = Field(default=0, ge=0)
    attempted_parsers: list[str] = Field(default_factory=list)
    artifact_ref: str | None = None
    inspection_sha256: str | None = None
    origin: str = "local_upload"
    canonical_url: str | None = None
    retrieval_scope: str | None = None

    @property
    def title(self) -> str:
        return self.display_title or self.filename


class UiSourceManifestStore:
    """UI-side source manifest backed by real ingestion artifacts."""

    def __init__(self, project_directory: Path) -> None:
        self._path = project_directory / "ui-source-manifest.json"

    def load(self) -> list[UiSourceManifest]:
        if not self._path.exists():
            return []
        payload: Any = __import__("json").loads(self._path.read_text(encoding="utf-8"))
        return [UiSourceManifest.model_validate(item) for item in payload]

    def save(self, sources: list[UiSourceManifest]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".json.tmp")
        temporary.write_text(
            dumps(
                [source.model_dump(mode="json") for source in sources],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self._path)

    def add(self, source: UiSourceManifest) -> UiSourceManifest:
        sources = self.load()
        sources.append(source)
        self.save(sources)
        return source

    def get(self, source_id: UUID) -> UiSourceManifest:
        source = next((item for item in self.load() if item.source_id == source_id), None)
        if source is None:
            raise FileNotFoundError(f"Source not found: {source_id}")
        return source

    def replace(self, source: UiSourceManifest) -> UiSourceManifest:
        sources = self.load()
        replaced = False
        for index, current in enumerate(sources):
            if current.source_id == source.source_id:
                sources[index] = source
                replaced = True
                break
        if not replaced:
            raise FileNotFoundError(f"Source not found: {source.source_id}")
        self.save(sources)
        return source

    def remove(self, source_id: UUID) -> UiSourceManifest:
        sources = self.load()
        removed = next((item for item in sources if item.source_id == source_id), None)
        if removed is None:
            raise FileNotFoundError(f"Source not found: {source_id}")
        self.save([item for item in sources if item.source_id != source_id])
        return removed

    def toggle(self, source_id: UUID) -> UiSourceManifest:
        sources = self.load()
        selected: UiSourceManifest | None = None
        for source in sources:
            if source.source_id != source_id:
                continue
            if source.status != UiSourceStatus.READY:
                raise ValueError("Only ready sources can be selected")
            source.selected = not source.selected
            selected = source
        if selected is None:
            raise FileNotFoundError(f"Source not found: {source_id}")
        self.save(sources)
        return selected

    def reset_selection(self) -> None:
        sources = self.load()
        for source in sources:
            source.selected = False
        self.save(sources)
