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


def test_unknown_quality_skips_quality_gate_instead_of_passing_subset() -> None:
    gates = evaluate_gates(
        [_case(case_id="known"), _case(case_id="unknown", quality_overall=None)],
        {"min_quality_overall": 0.7},
    )
    assert gates[0].status == "skipped"


def test_report_exit_codes_distinguish_gate_failure_from_case_error() -> None:
    from thesisound.services.eval_harness import EvalReport, GateEvaluation

    failed = EvalReport(
        generated_at="2026-08-09T00:00:00+00:00",
        cases=(),
        gates=(GateEvaluation("gate", "fail", 0.0, 1.0, ">="),),
    )
    errored = EvalReport(
        generated_at="2026-08-09T00:00:00+00:00",
        cases=(),
        gates=(),
        errors=("case: failed",),
    )

    assert failed.exit_code == 1
    assert errored.exit_code == 2


def test_full_case_uses_production_sequence_and_never_constructs_audio(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import builtins
    from types import SimpleNamespace
    from uuid import uuid4

    from thesisound.domain import EpisodePlan, EpisodeSegment, Script, ScriptTurn
    from thesisound.episode import CoverageReport
    from thesisound.pipeline import WorkspaceStore
    from thesisound.script import (
        Glossary,
        ScriptCheckReport,
        ScriptPipelineResult,
        ScriptQualityScore,
        VerificationDraft,
    )
    from thesisound.services import eval_harness

    source_path = tmp_path / "source.md"
    source_path.write_text("# Source\n\nA compact argument.", encoding="utf-8")
    case = eval_harness.EvalCase(
        case_id="fake-e2e",
        directory=tmp_path,
        brief=load_cases(Path("benchmarks/eval").resolve())[0].brief,
        sources=(source_path,),
        expectations={"must_cover": ["argument"]},
    )
    calls: list[str] = []

    class FakeSourceService:
        def analyze_source(self, *args, **kwargs) -> None:
            calls.append("source-analysis")

    class FakeEpisodeService:
        def __init__(self, root: Path) -> None:
            self.root = root

        def prepare_episode(self, project_id, **kwargs):
            calls.append("episode-preparation")
            workspace = WorkspaceStore(self.root)
            project = workspace.load_project(project_id)
            project.episode_plan = EpisodePlan(
                title="Plan",
                listener_outcome="Understand the argument",
                estimated_duration_minutes=5,
                segments=[
                    EpisodeSegment(
                        segment_id="segment-1",
                        title="Argument",
                        purpose="Explain",
                        estimated_minutes=5,
                        claim_ids=["claim-1"],
                        key_question="Why?",
                        speaker_dynamic="explanation",
                    )
                ],
            )
            project.state = eval_harness.ProjectState.EPISODE_PLANNED
            workspace.save_project(project)
            coverage = CoverageReport(
                project_id=project_id,
                central_question_status="well_covered",
                max_supported_minutes=5,
                recommendation="continue",
                recommendation_reason="Enough material.",
                can_plan_episode=True,
                model_run_id=uuid4(),
            )
            return coverage, None, None, None, project.episode_plan, []

    class FakeScriptService:
        def run(self, project_id, **kwargs):
            calls.append("script-pipeline")
            quality = ScriptQualityScore(
                evidence_fidelity=0.9,
                qualification_preservation=0.9,
                stance_and_disagreement=0.9,
                terminology_consistency=0.9,
                listenability=0.9,
            )
            return ScriptPipelineResult(
                glossary=Glossary(project_id=project_id, model_run_id=uuid4()),
                script=Script(
                    title="Script",
                    turns=[
                        ScriptTurn(
                            turn_id="turn-1",
                            segment_id="segment-1",
                            speaker="A",
                            spoken_text_fa="متن آزمایشی",
                            editorial_only=True,
                        )
                    ],
                ),
                checks=ScriptCheckReport(
                    project_id=project_id,
                    verdict="pass",
                    word_count=2,
                    estimated_minutes=1,
                    substantive_turn_count=0,
                ),
                verification=VerificationDraft(
                    verdict="pass",
                    unsupported_claim_ratio=0,
                    quality=quality,
                ),
            )

    monkeypatch.setattr(
        eval_harness,
        "ingest_uploaded_source",
        lambda *args, **kwargs: SimpleNamespace(
            artifact_ref="ingestion-result.json",
            safe_for_claim_extraction=True,
            issue_summary=None,
            status="ready",
        ),
    )
    monkeypatch.setattr(
        eval_harness,
        "_build_services",
        lambda settings, root, project_id: (
            FakeSourceService(),
            FakeEpisodeService(root),
            FakeScriptService(),
        ),
    )
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("thesisound.audio"):
            raise AssertionError("audio composition must not be constructed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    metrics = eval_harness._run_case(case, tmp_path / "runtime", settings=None)

    assert calls == ["source-analysis", "episode-preparation", "script-pipeline"]
    assert metrics.script_outcome == "verified"
    assert metrics.quality_overall == pytest.approx(0.9)
    assert metrics.coverage_recommendation == "continue"
    assert metrics.can_plan_episode is True
    assert metrics.expectations == {"must_cover": ["argument"]}
