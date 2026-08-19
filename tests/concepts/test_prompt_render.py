import pytest

from thesisound.prompt_loader import PromptLoader, PromptRenderError


def _variables(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_id": "src-1",
        "chapter": {"chapter_index": 0, "title": "فصل یکم"},
        "sections": [{"section_id": "s001", "function": "argument"}],
        "blocks": [{"block_id": "b0001", "text": "full source paragraph, never cut."}],
        "chapter_awareness": {"accepted_cell_count": 0, "remaining_budget": 6},
        "budget": 6,
    }
    payload.update(overrides)
    return payload


def test_concept_cells_1_0_0_renders_with_fixture() -> None:
    loader = PromptLoader()
    contract = loader.load_contract("concept_cells")
    assert contract.version == "1.0.0"
    assert contract.model_tier == "fast"
    assert contract.output_model == "ConceptCellsDraft"
    assert contract.max_attempts == 3

    bundle = loader.load_bundle("concept_cells", _variables())
    assert "<SOURCE_ID>" in bundle.user_prompt
    assert "src-1" in bundle.user_prompt
    assert "full source paragraph, never cut." in bundle.user_prompt
    assert "فصل یکم" in bundle.user_prompt
    assert "remaining_budget" in bundle.user_prompt
    assert "{{" not in bundle.system_prompt + bundle.user_prompt
    assert "Do not generate cell keys" in bundle.system_prompt
    assert "smallest self-contained, meaningful and traceable" in bundle.system_prompt


def test_missing_placeholder_raises() -> None:
    with pytest.raises(PromptRenderError, match="missing prompt variables") as exc_info:
        PromptLoader().load_bundle("concept_cells", {"source_id": "src-1"})
    message = str(exc_info.value)
    assert "budget" in message
    assert "chapter" in message
    assert "blocks" in message


def test_concept_cells_consolidate_1_0_0_renders_with_fixture() -> None:
    loader = PromptLoader()
    contract = loader.load_contract("concept_cells_consolidate")
    assert contract.version == "1.0.0"
    assert contract.model_tier == "fast"
    assert contract.output_model == "ConceptCellsConsolidateDraft"
    assert contract.max_attempts == 2

    bundle = loader.load_bundle(
        "concept_cells_consolidate",
        {
            "chapter_title": "فصل یکم",
            "target_count": 6,
            "cells": [
                {
                    "cell_key": "ch00-c001",
                    "label_fa": "تمایز کنش و ساخت",
                    "kind": "distinction",
                    "tier": 1,
                    "section_titles": ["کنش"],
                    "granularity_rationale": "یک تمایز مستقل است.",
                    "estimated_minutes": 6,
                }
            ],
        },
    )
    assert "<CHAPTER_TITLE>" in bundle.user_prompt
    assert "فصل یکم" in bundle.user_prompt
    assert "ch00-c001" in bundle.user_prompt
    assert "تمایز کنش و ساخت" in bundle.user_prompt
    assert "{{" not in bundle.system_prompt + bundle.user_prompt
    assert "cell metadata only" in bundle.system_prompt
    assert "Never let a section lose its last cell" in bundle.system_prompt


def test_consolidate_missing_placeholder_raises() -> None:
    with pytest.raises(PromptRenderError, match="missing prompt variables") as exc_info:
        PromptLoader().load_bundle("concept_cells_consolidate", {"chapter_title": "فصل"})
    message = str(exc_info.value)
    assert "target_count" in message
    assert "cells" in message
