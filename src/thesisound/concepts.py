"""Data models for the source concept map (chapters, cells, edges, statistics).

This module only defines the shapes from `10b` B1.2/B1.3/B1.5 plus the model
draft shapes from `10c` P1 Step 1. No builder, prompt, cache, or overlay
service lives here yet — those arrive in later steps.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

CELL_KEY_PATTERN = re.compile(r"^ch\d{2}-c\d{3}$")

DetectedFrom = Literal["heading", "toc", "single"]
DetectionAgreement = Literal["agreed", "toc_only", "heading_only", "disagreed"]
ConceptCellKind = Literal[
    "definition",
    "distinction",
    "argument",
    "position",
    "objection",
    "response",
    "example",
    "thread",
]
ConceptCellTier = Literal[1, 2, 3]
CreatedBy = Literal["ai", "user"]
ConceptEdgeType = Literal[
    "prerequisite",
    "depends_on",
    "related",
    "extends",
    "contrasts",
    "objects_to",
    "responds_to",
    "instance_of",
]
ConsolidateActionKind = Literal["keep", "merge", "remove"]


class SourceChapter(BaseModel):
    """One chapter as detected by Pass 0 (B1.2)."""

    chapter_index: int = Field(ge=0)
    title: str = Field(min_length=1)
    heading_path: list[str] = Field(default_factory=list)
    block_ids: list[str] = Field(min_length=1)
    estimated_minutes: float = Field(ge=0)
    detected_from: DetectedFrom
    detection_agreement: DetectionAgreement


class ConceptCell(BaseModel):
    """The smallest self-contained, traceable teaching unit of a source (B1.3)."""

    cell_key: str = Field(pattern=CELL_KEY_PATTERN.pattern)
    label_fa: str = Field(min_length=1)
    label_source: str | None = None
    kind: ConceptCellKind
    tier: ConceptCellTier
    tier_promoted: bool = False
    chapter_index: int = Field(ge=0)
    section_ids: list[str] = Field(min_length=1)
    block_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    granularity_rationale: str = Field(min_length=1)
    estimated_minutes: float = Field(ge=0.5, le=30)
    created_by: CreatedBy = "ai"


class ConceptEdge(BaseModel):
    """A directed relation between two concept cells (B1.3)."""

    source_key: str = Field(pattern=CELL_KEY_PATTERN.pattern)
    target_key: str = Field(pattern=CELL_KEY_PATTERN.pattern)
    type: ConceptEdgeType
    weight: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    rationale_fa: str = Field(min_length=1)
    created_by: CreatedBy = "ai"
    is_cross_chapter: bool = False


class ConceptMapStatistics(BaseModel):
    """Pass 5 statistics over a built concept map (B1.3)."""

    cell_count: int = Field(ge=0)
    cells_per_tier: dict[int, int] = Field(default_factory=dict)
    cells_per_chapter: dict[int, int] = Field(default_factory=dict)
    edges_per_type: dict[str, int] = Field(default_factory=dict)
    orphan_cell_keys: list[str] = Field(default_factory=list)
    cross_chapter_edge_count: int = Field(ge=0, default=0)
    promoted_cell_keys: list[str] = Field(default_factory=list)
    needs_review: list[str] = Field(default_factory=list)


class SourceConceptMap(BaseModel):
    """The full, cacheable concept map for one source (B1.3)."""

    source_fingerprint: str = Field(min_length=1)
    builder_version: int = Field(ge=1)
    chapters: list[SourceChapter] = Field(default_factory=list)
    cells: list[ConceptCell] = Field(default_factory=list)
    edges: list[ConceptEdge] = Field(default_factory=list)
    statistics: ConceptMapStatistics
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConceptMapOverlay(BaseModel):
    """Per-project, per-source owner corrections layered on the cached map (B1.3)."""

    source_fingerprint: str = Field(min_length=1)
    version: int = Field(ge=1)
    added_cells: list[ConceptCell] = Field(default_factory=list)
    removed_cell_keys: list[str] = Field(default_factory=list)
    added_edges: list[ConceptEdge] = Field(default_factory=list)
    removed_edge_keys: list[str] = Field(default_factory=list)
    tier_overrides: dict[str, ConceptCellTier] = Field(default_factory=dict)


class LessonPart(BaseModel):
    """Placeholder shape reserved for P3 (`10b` B1.5); not built yet."""

    part_index: int = Field(ge=1)
    title_fa: str = Field(min_length=1)
    cell_keys: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    estimated_minutes: float = Field(ge=0)
    graph_backed: bool = False
    flags: list[str] = Field(default_factory=list)


class ConceptCellDraft(BaseModel):
    """Raw model output for one cell before `cell_key` assignment (`10c` P1 Step 1)."""

    label_fa: str = Field(min_length=1)
    label_source: str | None = None
    kind: ConceptCellKind
    tier: ConceptCellTier
    section_ids: list[str] = Field(min_length=1)
    block_ids: list[str] = Field(min_length=1)
    granularity_rationale: str = Field(min_length=1)
    estimated_minutes: float = Field(ge=0.5, le=30)


class ConceptCellsDraft(BaseModel):
    """`concept_cells` prompt output for one chapter (Pass 2)."""

    cells: list[ConceptCellDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ConsolidateActionDraft(BaseModel):
    """One keep/merge/remove decision from the consolidation prompt (Pass 3)."""

    cell_key: str = Field(pattern=CELL_KEY_PATTERN.pattern)
    action: ConsolidateActionKind
    merge_into: str | None = None
    reason: str = Field(min_length=1)

    @field_validator("merge_into")
    @classmethod
    def _validate_merge_into_pattern(cls, value: str | None) -> str | None:
        if value is not None and not CELL_KEY_PATTERN.match(value):
            raise ValueError(f"merge_into must match {CELL_KEY_PATTERN.pattern!r}: {value!r}")
        return value


class ConceptCellsConsolidateDraft(BaseModel):
    """`concept_cells_consolidate` prompt output for one chapter (Pass 3)."""

    actions: list[ConsolidateActionDraft] = Field(default_factory=list)


class ConceptEdgeDraft(BaseModel):
    """Raw model output for one edge before validation (Pass 4)."""

    source_key: str = Field(pattern=CELL_KEY_PATTERN.pattern)
    target_key: str = Field(pattern=CELL_KEY_PATTERN.pattern)
    type: ConceptEdgeType
    weight: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    rationale_fa: str = Field(min_length=1)


class ConceptEdgesDraft(BaseModel):
    """`concept_edges` prompt output for one chapter or chapter pair (Pass 4)."""

    edges: list[ConceptEdgeDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
