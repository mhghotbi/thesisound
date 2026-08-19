"""Data models for the source concept map (chapters, cells, edges, statistics).

Shapes from `10b` B1.2/B1.3/B1.5 and draft models from `10c` P1 Step 1, plus
the banned/smell label lists used by Pass 2 (`10c` P1 Step 4).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

CELL_KEY_PATTERN = re.compile(r"^ch\d{2}-c\d{3}$")
_LABEL_TOKEN = re.compile(r"\w+", re.UNICODE)
_ZWNJ = "\u200c"

# Structural / pedagogical labels banned as the whole label or as a prefix
# (`10b` A.8; `10c` P1 Step 4). Numbered forms ("chapter 2", "بخش دوم") are
# handled by the regexes below, not by these sets.
BANNED_LABELS_EN: frozenset[str] = frozenset(
    {
        "introduction",
        "intro",
        "preface",
        "foreword",
        "prologue",
        "epilogue",
        "section",
        "summary",
        "conclusion",
        "note",
        "notes",
        "remark",
        "remarks",
        "figure",
        "table",
        "background",
        "appendix",
        "overview",
        "abstract",
        "further reading",
        "contents",
        "acknowledgements",
        "acknowledgments",
        "bibliography",
        "references",
        "index",
        "glossary",
    }
)
BANNED_LABELS_FA: frozenset[str] = frozenset(
    {
        "مقدمه",
        "پیشگفتار",
        "دیباچه",
        "خلاصه",
        "جمع بندی",
        "نتیجه گیری",
        "یادداشت",
        "تذکر",
        "شکل",
        "جدول",
        "نمودار",
        "پیوست",
        "چکیده",
        "درآمد",
        "پیش زمینه",
        "مطالعه بیشتر",
        "فهرست",
        "منابع",
        "کتابنامه",
        "سپاسگزاری",
    }
)
# Words that are only banned as the entire label, or when followed by a number /
# ordinal ("part 2", "فصل یکم"). They are legitimate inside a real concept name.
BANNED_NUMBERED_HEADS_EN: frozenset[str] = frozenset({"chapter", "part", "example"})
BANNED_NUMBERED_HEADS_FA: frozenset[str] = frozenset({"فصل", "بخش", "قسمت", "مثال"})
_FA_ORDINAL = r"(?:اول|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم|یکم)"
_EN_NUMBERED_LABEL = re.compile(
    r"^(?:chapter|part|example|section|figure|table)\s+(?:[0-9]+|[ivxlcdm]+)\b"
)
_FA_NUMBERED_LABEL = re.compile(
    rf"^(?:فصل|بخش|قسمت|مثال|شکل|جدول)\s+(?:[0-9]+|[۰-۹]+|{_FA_ORDINAL})\b"
)


def normalise_cell_label(label: str) -> str:
    """Fold a cell label for banned-list and Jaccard comparison."""

    text = label.replace("ي", "ی").replace("ك", "ک").replace(_ZWNJ, " ")
    text = text.casefold().strip()
    text = re.sub(r"[«»\"'`،,.:;!?()\[\]{}]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def cell_label_tokens(label: str) -> frozenset[str]:
    return frozenset(_LABEL_TOKEN.findall(normalise_cell_label(label)))


def cell_label_jaccard(left: str, right: str) -> float:
    """Word-set Jaccard of two labels after `normalise_cell_label`."""

    left_tokens = cell_label_tokens(left)
    right_tokens = cell_label_tokens(right)
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def is_banned_or_smell_label(label: str) -> bool:
    """True when a label is a structural/pedagogical title rather than a concept."""

    text = normalise_cell_label(label)
    if not text or text.isdigit():
        return True
    if text in BANNED_LABELS_EN or text in BANNED_LABELS_FA:
        return True
    if text in BANNED_NUMBERED_HEADS_EN or text in BANNED_NUMBERED_HEADS_FA:
        return True
    if _EN_NUMBERED_LABEL.match(text) or _FA_NUMBERED_LABEL.match(text):
        return True
    return any(text.startswith(f"{banned} ") for banned in BANNED_LABELS_EN | BANNED_LABELS_FA)

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
