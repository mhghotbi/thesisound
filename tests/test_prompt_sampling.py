"""Per-contract sampling: pinned analytical stages, unpinned creative ones."""

from __future__ import annotations

import json
from pathlib import Path

from thesisound.modeling import PromptContract, sampling_for_attempt

ROOT = Path(__file__).parents[1]
PROMPTS = ROOT / "prompts"

# Stages whose answer must not move between runs. Anything not listed here is
# deliberately left on the provider default.
PINNED_STAGES = frozenset(
    {
        "evidence_extraction",
        "evidence_extraction_batch",
        "document_map",
        "document_map_merge",
        "concept_cells",
        "concept_cells_consolidate",
        "concept_edges",
        "claim_reconciliation",
        "claim_reconciliation_merge",
        "coverage_audit",
    }
)


def _contract(**kwargs: object) -> PromptContract:
    base: dict[str, object] = {
        "id": "test",
        "version": "1.0.0",
        "model_tier": "fast",
        "output_model": "Draft",
    }
    return PromptContract.model_validate(base | kwargs)


def test_an_unpinned_contract_leaves_the_provider_default_alone() -> None:
    temperature, seed = sampling_for_attempt(_contract(), attempt=1)
    assert temperature is None
    assert seed is None


def test_a_pinned_contract_is_deterministic_on_the_first_attempt() -> None:
    contract = _contract(temperature=0, seed=7)
    assert sampling_for_attempt(contract, attempt=1) == (0, 7)


def test_retries_add_temperature_so_contract_repair_can_differ() -> None:
    """`model_retry` stops early on an identical repair, so a frozen retry is wasted."""

    contract = _contract(temperature=0, seed=7, retry_temperature_step=0.3)
    assert sampling_for_attempt(contract, attempt=2)[0] == 0.3
    assert sampling_for_attempt(contract, attempt=3)[0] == 0.6


def test_the_seed_is_held_across_attempts_so_the_whole_ladder_replays() -> None:
    contract = _contract(temperature=0, seed=7)
    seeds = {sampling_for_attempt(contract, attempt=n)[1] for n in (1, 2, 3)}
    assert seeds == {7}


def test_escalation_never_exceeds_the_providers_ceiling() -> None:
    contract = _contract(temperature=1.9, seed=7, retry_temperature_step=1.0)
    assert sampling_for_attempt(contract, attempt=5)[0] == 2.0


def test_every_analytical_contract_on_disk_is_pinned() -> None:
    """A new version of an analytical prompt must not silently go unpinned."""

    unpinned: list[str] = []
    for path in sorted(PROMPTS.glob("*/*/contract.json")):
        stage = path.parent.parent.name
        if stage not in PINNED_STAGES:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("temperature") != 0 or data.get("seed") is None:
            unpinned.append(f"{stage}/{path.parent.name}")
    assert unpinned == []


def test_creative_contracts_are_left_unpinned() -> None:
    """Pinning the Persian writer would flatten it; that is a deliberate choice."""

    for stage in ("persian_script_segment", "persian_lesson_prose", "script_reviser"):
        for path in sorted((PROMPTS / stage).glob("*/contract.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data.get("temperature") is None, f"{stage}/{path.parent.name}"
