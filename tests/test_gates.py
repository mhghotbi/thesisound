from __future__ import annotations

import re
from pathlib import Path

from thesisound.services.gates import GATE_REGISTRY

ROOT = Path(__file__).resolve().parents[1]

_ENFORCEMENT_MARKERS = {
    "brief-confirmed": "BRIEF_READY",
    "source-selection-confirmed": "confirm_corpus",
    "parse-quality": "assess_parse_quality",
    "evidence-validation": "validate_evidence_collection",
    "evidence-retention": "evidence_retention_holds",
    "coverage-duration": "can_plan_episode",
    "episode-plan-approval": "require_current",
    "script-checks": "def check",
    "independent-verification": "def verify",
    "script-review-decision": "generate_audio",
    "audio-start": "generate_audio",
    "audio-qa": "Audio QA",
}


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


def test_gate_registry_pointers_resolve_to_enforcement() -> None:
    for gate in GATE_REGISTRY:
        if gate.enforced_at == "unenforced":
            continue
        path_text, line_text = gate.enforced_at.rsplit(":", 1)
        line = (ROOT / path_text).read_text(encoding="utf-8").splitlines()[int(line_text) - 1]
        marker = _ENFORCEMENT_MARKERS[gate.code]
        assert marker.lower() in line.lower(), (gate.code, line, marker)


def test_exactly_three_human_blocking_build_path_gates() -> None:
    codes = {
        gate.code
        for gate in GATE_REGISTRY
        if gate.actor == "human" and gate.blocking
    }
    assert codes == {
        "source-selection-confirmed",
        "episode-plan-approval",
        "audio-start",
    }


def test_human_only_gates_match_the_documented_set() -> None:
    assert {gate.code for gate in GATE_REGISTRY if gate.actor == "human"} == {
        "brief-confirmed",
        "source-selection-confirmed",
        "episode-plan-approval",
        "script-review-decision",
        "audio-start",
        "final-listen",
    }


def test_sop_document_lists_every_gate_code() -> None:
    document = (ROOT / "docs/06-operations/03-production-sop.md").read_text(encoding="utf-8")
    assert all(f"`{gate.code}`" in document for gate in GATE_REGISTRY)


def test_sop_document_lists_every_enforced_location() -> None:
    document = (ROOT / "docs/06-operations/03-production-sop.md").read_text(encoding="utf-8")
    for gate in GATE_REGISTRY:
        expected = "Unenforced" if gate.enforced_at == "unenforced" else f"`{gate.enforced_at}`"
        assert expected in document, gate.code


def test_sop_document_lists_every_registry_fact() -> None:
    document = (ROOT / "docs/06-operations/03-production-sop.md").read_text(encoding="utf-8")
    for gate in GATE_REGISTRY:
        assert gate.reads in document, f"{gate.code}: reads"
        assert gate.writes in document, f"{gate.code}: writes"
        assert gate.blocked_means in document, f"{gate.code}: blocked_means"
