"""Deterministic pre-run token (and optional price) estimates (`10b` B1.8)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from thesisound.concepts import ConceptCell, SourceConceptMap
from thesisound.config import Settings
from thesisound.domain import Project
from thesisound.services.cell_selection import SelectedCell
from thesisound.services.model_pricing import CostCalculator

# Initial ledger-calibrated multipliers (`10b` B1.8).
MAP_TOKEN_MULTIPLIER = 1.0
CELLS_TOKEN_MULTIPLIER = 1.1
EXTRACTION_TOKEN_MULTIPLIER = 1.3
# Pass 0 provisional minutes = Σ tokens / 300.
TOKENS_PER_MINUTE = 300
# Plan / script / verify input is proportional to spoken words.
WORDS_PER_MINUTE = 130
UNKNOWN_PRICE_STATUS = "unknown — tokens only"
PRICED_STATUS = "priced"

_STAGE_ORDER = ("map", "cells", "extraction", "plan", "script", "verify")


class CostEstimate(BaseModel):
    """Pre-run estimate: input tokens per stage, and a price when the table has rows."""

    input_tokens: dict[str, int]
    total_input_tokens: int = Field(ge=0)
    cost_micros: int | None = Field(default=None, ge=0)
    pricing_version: str | None = None
    price_status: str


def estimate_tokens(chapter_tokens: int) -> dict[str, int]:
    """Input-token estimate per concept-map model pass, from in-scope chapter tokens.

    ``map`` is Pass 1 (document map, 1.0×). ``cells`` is Pass 2 (1.1×). Other
    B1.8 stages are estimated by ``estimate``.
    """

    if chapter_tokens < 0:
        raise ValueError("chapter_tokens must be >= 0.")
    mapped = round(chapter_tokens * MAP_TOKEN_MULTIPLIER)
    cells = round(chapter_tokens * CELLS_TOKEN_MULTIPLIER)
    return {"map": mapped, "cells": cells, "total": mapped + cells}


def estimate(
    project: Project,
    concept_map: SourceConceptMap,
    in_scope: Sequence[ConceptCell | SelectedCell],
    *,
    block_tokens: dict[str, int] | None = None,
    pricing_file: Path | None = None,
    settings: Settings | None = None,
) -> CostEstimate:
    """Input tokens per pipeline stage, priced from ``model-pricing.toml`` when possible.

    Map/cells use scoped-chapter tokens; extraction uses unique in-scope cell
    blocks (1.3×); plan/script/verify are ``Σ cell minutes × 130`` words each.
    Missing or unmatched pricing rows yield ``unknown — tokens only``.
    """

    settings = settings or Settings()
    cells = [item.cell if isinstance(item, SelectedCell) else item for item in in_scope]
    chapter_tokens = _chapter_tokens(project, concept_map, block_tokens)
    in_scope_tokens = _in_scope_tokens(cells, block_tokens)
    map_cells = estimate_tokens(chapter_tokens)
    minutes = sum(cell.estimated_minutes for cell in cells)
    spoken_words = round(minutes * WORDS_PER_MINUTE)
    input_tokens = {
        "map": map_cells["map"],
        "cells": map_cells["cells"],
        "extraction": round(in_scope_tokens * EXTRACTION_TOKEN_MULTIPLIER),
        "plan": spoken_words,
        "script": spoken_words,
        "verify": spoken_words,
    }
    total = sum(input_tokens[stage] for stage in _STAGE_ORDER)
    input_tokens["total"] = total
    return _with_price(
        input_tokens,
        total,
        pricing_file=pricing_file if pricing_file is not None else settings.pricing_file,
        settings=settings,
    )


def _chapter_tokens(
    project: Project,
    concept_map: SourceConceptMap,
    block_tokens: dict[str, int] | None,
) -> int:
    indexes = (
        set(project.scope.chapter_indexes)
        if project.scope is not None and project.scope.chapter_indexes is not None
        else None
    )
    chapters = [
        chapter
        for chapter in concept_map.chapters
        if indexes is None or chapter.chapter_index in indexes
    ]
    if block_tokens is not None:
        ids = [block_id for chapter in chapters for block_id in chapter.block_ids]
        return sum(block_tokens.get(block_id, 0) for block_id in ids)
    return round(sum(chapter.estimated_minutes for chapter in chapters) * TOKENS_PER_MINUTE)


def _in_scope_tokens(
    cells: Sequence[ConceptCell],
    block_tokens: dict[str, int] | None,
) -> int:
    if block_tokens is not None:
        block_ids = {block_id for cell in cells for block_id in cell.block_ids}
        return sum(block_tokens.get(block_id, 0) for block_id in block_ids)
    return round(sum(cell.estimated_minutes for cell in cells) * TOKENS_PER_MINUTE)


def _with_price(
    input_tokens: dict[str, int],
    total: int,
    *,
    pricing_file: Path,
    settings: Settings,
) -> CostEstimate:
    calculator = CostCalculator(pricing_file)
    stage_models = {
        "map": settings.model_fast,
        "cells": settings.model_fast,
        "extraction": settings.model_strong,
        "plan": settings.model_strong,
        "script": settings.model_strong,
        "verify": settings.model_fast,
    }
    started_at = datetime.now(UTC)
    micros = 0
    version: str | None = calculator.version if calculator.version != "unset" else None
    for stage in _STAGE_ORDER:
        priced = calculator.price(
            provider="gemini",
            model=stage_models[stage],
            operation="structured_text",
            started_at=started_at,
            input_tokens=input_tokens[stage],
            output_tokens=None,
            cached_tokens=None,
        )
        if priced is None:
            return CostEstimate(
                input_tokens=input_tokens,
                total_input_tokens=total,
                cost_micros=None,
                pricing_version=version,
                price_status=UNKNOWN_PRICE_STATUS,
            )
        micros += priced.cost_micros
        version = priced.pricing_version
    return CostEstimate(
        input_tokens=input_tokens,
        total_input_tokens=total,
        cost_micros=micros,
        pricing_version=version,
        price_status=PRICED_STATUS,
    )
