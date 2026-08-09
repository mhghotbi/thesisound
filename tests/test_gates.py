from __future__ import annotations

import re
from pathlib import Path

from thesisound.services.gates import GATE_REGISTRY

ROOT = Path(__file__).resolve().parents[1]


def test_gate_codes_are_unique_and_kebab_case() -> None:
    codes = [gate.code for gate in GATE_REGISTRY]
    assert len(codes) == len(set(codes))
    assert all(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", code) for code in codes)


def test_gate_order_is_contiguous_starting_at_one() -> None:
    assert [gate.order for gate in GATE_REGISTRY] == list(range(1, len(GATE_REGISTRY) + 1))


def test_every_enforced_at_reference_resolves() -> None:
    for gate in GATE_REGISTRY:
        if gate.enforced_at == "unenforced":
            continue
        path_text, line_text = gate.enforced_at.rsplit(":", 1)
        path = ROOT / path_text
        assert path.exists(), gate.code
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) >= int(line_text), gate.code
        assert lines[int(line_text) - 1].strip(), gate.code


def test_human_only_gates_match_the_documented_set() -> None:
    assert {gate.code for gate in GATE_REGISTRY if gate.actor == "human"} == {
        "brief-confirmed",
        "source-selection-confirmed",
        "episode-plan-approval",
        "script-review-decision",
        "final-listen",
    }


def test_sop_document_lists_every_gate_code() -> None:
    document = (ROOT / "docs/34-production-sop.md").read_text(encoding="utf-8")
    assert all(f"`{gate.code}`" in document for gate in GATE_REGISTRY)


def test_sop_document_lists_every_enforced_location() -> None:
    document = (ROOT / "docs/34-production-sop.md").read_text(encoding="utf-8")
    for gate in GATE_REGISTRY:
        expected = "Unenforced" if gate.enforced_at == "unenforced" else f"`{gate.enforced_at}`"
        assert expected in document, gate.code
