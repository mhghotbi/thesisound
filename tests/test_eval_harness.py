from __future__ import annotations

from pathlib import Path

import pytest

from thesisound.services.eval_harness import (
    CaseMetrics,
    dry_run,
    evaluate_gates,
    load_cases,
)


def _case(**overrides) -> CaseMetrics:
    values = dict(
        case_id="case",
        project_id="00000000-0000-0000-0000-000000000001",
        checks_verdict="pass",
        verification_verdict="pass",
        unsupported_claim_ratio=0.0,
        quality_overall=0.8,
        script_outcome="verified",
        revision_accepted=None,
        revision_delta=None,
        coverage_recommendation="continue",
        max_supported_minutes=10,
        can_plan_episode=True,
        estimated_minutes=5.0,
        skipped_block_count=0,
        call_count=10,
        failed_count=0,
        total_tokens=1000,
        wall_clock_seconds=1.0,
        cost_micros=100,
        cost_is_partial=False,
        cost_micros_per_output_minute=20,
        expectations={},
    )
    values.update(overrides)
    return CaseMetrics(**values)


def test_dry_run_validates_cases_and_constructs_no_model_client(monkeypatch) -> None:
    import thesisound.source_cli as source_cli

    monkeypatch.setattr(
        source_cli,
        "GeminiStructuredModel",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("constructed")),
    )
    payload = dry_run(Path("benchmarks/eval").resolve())
    assert payload["model_clients_constructed"] == 0
    assert len(payload["cases"]) >= 3


def test_missing_source_file_fails_dry_run_with_named_case(tmp_path: Path) -> None:
    root = tmp_path / "eval"
    case = root / "cases" / "missing-source"
    case.mkdir(parents=True)
    (root / "gates.toml").write_text("min_verified_case_rate = 0.8\n", encoding="utf-8")
    (case / "case.toml").write_text(
        """sources = ["absent.md"]
[brief]
normalized_topic = "x"
topic_type = "concept"
central_question = "x?"
target_duration_minutes = 5
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing-source: missing source"):
        dry_run(root)


def test_malformed_case_toml_fails_dry_run(tmp_path: Path) -> None:
    root = tmp_path / "eval"
    case = root / "cases" / "bad-case"
    case.mkdir(parents=True)
    (root / "gates.toml").write_text("min_verified_case_rate = 0.8\n", encoding="utf-8")
    (case / "case.toml").write_text("[brief\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bad-case: malformed case.toml"):
        load_cases(root)


def test_unknown_cost_marks_cost_gate_skipped_not_passed() -> None:
    case = _case(cost_micros=None, cost_is_partial=True, cost_micros_per_output_minute=None)
    gates = evaluate_gates([case], {"max_cost_micros_per_output_minute": 50})
    assert gates[0].status == "skipped"


def test_review_required_counts_against_verified_rate() -> None:
    gates = evaluate_gates(
        [_case(script_outcome="review_required")],
        {"min_verified_case_rate": 0.8},
    )
    assert gates[0].status == "fail"
