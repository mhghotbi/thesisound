from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from thesisound.concepts import (
    ConceptCell,
    ConceptMapStatistics,
    SourceChapter,
    SourceConceptMap,
)
from thesisound.config import Settings
from thesisound.domain import Project, ProjectScope
from thesisound.services.cost_estimate import (
    EXTRACTION_TOKEN_MULTIPLIER,
    UNKNOWN_PRICE_STATUS,
    WORDS_PER_MINUTE,
    estimate,
    estimate_tokens,
)


def test_estimate_tokens_uses_b18_multipliers() -> None:
    assert estimate_tokens(1000) == {"map": 1000, "cells": 1100, "total": 2100}


def test_estimate_tokens_zero() -> None:
    assert estimate_tokens(0) == {"map": 0, "cells": 0, "total": 0}


def test_estimate_tokens_rejects_negative() -> None:
    try:
        estimate_tokens(-1)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def _chapter() -> SourceChapter:
    return SourceChapter(
        chapter_index=0,
        title="فصل",
        heading_path=["فصل"],
        block_ids=["b0001", "b0002"],
        estimated_minutes=10.0,
        detected_from="heading",
        detection_agreement="agreed",
    )


def _cell(cell_key: str, *block_ids: str, minutes: float = 5.0) -> ConceptCell:
    number = int(cell_key.split("-c")[1])
    return ConceptCell(
        cell_key=cell_key,
        label_fa=f"مفهوم {number}",
        kind="definition",
        tier=1,
        chapter_index=0,
        section_ids=[f"s{number:03d}"],
        block_ids=list(block_ids) or [f"b{number:04d}"],
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=minutes,
    )


def _map(cells: list[ConceptCell]) -> SourceConceptMap:
    return SourceConceptMap(
        source_fingerprint="b" * 64,
        builder_version=1,
        chapters=[_chapter()],
        cells=cells,
        edges=[],
        statistics=ConceptMapStatistics(cell_count=len(cells)),
        created_at=datetime.now(UTC),
    )


def _settings() -> Settings:
    return Settings(
        model_fast="gemini-3.5-flash-lite",
        model_strong="gemini-3.6-flash",
    )


def test_estimate_uses_block_tokens_and_b18_stage_multipliers() -> None:
    cells = [_cell("ch00-c001", "b0001", minutes=10.0)]
    result = estimate(
        Project(raw_input="موضوع"),
        _map(cells),
        cells,
        block_tokens={"b0001": 1000, "b0002": 500},
        pricing_file=Path("/nonexistent/model-pricing.toml"),
        settings=_settings(),
    )
    spoken = round(10.0 * WORDS_PER_MINUTE)
    assert result.input_tokens["map"] == 1500
    assert result.input_tokens["cells"] == 1650
    assert result.input_tokens["extraction"] == round(1000 * EXTRACTION_TOKEN_MULTIPLIER)
    assert result.input_tokens["plan"] == spoken
    assert result.input_tokens["script"] == spoken
    assert result.input_tokens["verify"] == spoken
    assert result.input_tokens["total"] == result.total_input_tokens
    assert result.price_status == UNKNOWN_PRICE_STATUS
    assert result.cost_micros is None


def test_estimate_dedupes_shared_blocks_for_extraction() -> None:
    cells = [
        _cell("ch00-c001", "b0001", "b0002", minutes=4.0),
        _cell("ch00-c002", "b0002", minutes=4.0),
    ]
    result = estimate(
        Project(raw_input="موضوع"),
        _map(cells),
        cells,
        block_tokens={"b0001": 100, "b0002": 50},
        pricing_file=Path("/nonexistent/model-pricing.toml"),
        settings=_settings(),
    )
    assert result.input_tokens["extraction"] == round(150 * EXTRACTION_TOKEN_MULTIPLIER)


def test_estimate_prices_when_table_has_matching_rows(tmp_path: Path) -> None:
    pricing = tmp_path / "model-pricing.toml"
    pricing.write_text(
        """
version = "test-table"
[[prices]]
provider = "gemini"
model = "gemini-3.5-flash-lite"
operation = "structured_text"
effective_from = 2026-01-01
input_per_million_micros = 1_000_000
output_per_million_micros = 0
[[prices]]
provider = "gemini"
model = "gemini-3.6-flash"
operation = "structured_text"
effective_from = 2026-01-01
input_per_million_micros = 2_000_000
output_per_million_micros = 0
""".strip()
        + "\n",
        encoding="utf-8",
    )
    cells = [_cell("ch00-c001", "b0001", minutes=10.0)]
    result = estimate(
        Project(raw_input="موضوع"),
        _map(cells),
        cells,
        block_tokens={"b0001": 1_000_000, "b0002": 0},
        pricing_file=pricing,
        settings=_settings(),
    )
    assert result.price_status == "priced"
    assert result.pricing_version == "test-table"
    assert result.cost_micros is not None
    assert result.cost_micros > 0


def test_estimate_uses_chapter_minutes_when_block_tokens_omitted() -> None:
    cells = [_cell("ch00-c001", "b0001", minutes=2.0)]
    result = estimate(
        Project(raw_input="موضوع"),
        _map(cells),
        cells,
        pricing_file=Path("/nonexistent/model-pricing.toml"),
        settings=_settings(),
    )
    # chapter estimated_minutes = 10 → 3000 tokens × 1.0 / 1.1
    assert result.input_tokens["map"] == 3000
    assert result.input_tokens["cells"] == 3300
    assert result.input_tokens["extraction"] == round(2.0 * 300 * EXTRACTION_TOKEN_MULTIPLIER)


def test_estimate_respects_chapter_scope() -> None:
    source_id = uuid4()
    other = SourceChapter(
        chapter_index=1,
        title="دیگر",
        heading_path=["دیگر"],
        block_ids=["b1000"],
        estimated_minutes=40.0,
        detected_from="heading",
        detection_agreement="agreed",
    )
    concept_map = _map([_cell("ch00-c001", "b0001", minutes=2.0)])
    concept_map = concept_map.model_copy(update={"chapters": [_chapter(), other]})
    result = estimate(
        Project(
            raw_input="موضوع",
            scope=ProjectScope(source_id=source_id, chapter_indexes=[0]),
        ),
        concept_map,
        [_cell("ch00-c001", "b0001", minutes=2.0)],
        block_tokens={"b0001": 100, "b0002": 100, "b1000": 9_000},
        pricing_file=Path("/nonexistent/model-pricing.toml"),
        settings=_settings(),
    )
    assert result.input_tokens["map"] == 200
