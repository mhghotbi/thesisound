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
    content_type: str | None = None
    size_bytes: int = Field(ge=0)
    status: UiSourceStatus = UiSourceStatus.PROCESSING
    selected: bool = False
    issue_summary: str | None = None
    is_demo_result: bool = False


class UiSourceManifestStore:
    """UI-side upload manifest.

    It does not replace ingestion artifacts. It records pre-ingestion status until
    the real ingestion service promotes a source into the project domain model.
    """

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
