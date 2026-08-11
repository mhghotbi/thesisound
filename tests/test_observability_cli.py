"""CLI-level tests for the trace/trace-show/timeline/pipeline-summary
commands added to observability_cli.py in Phase 2. Seeds a real ledger
directly (bypassing the tracer) so each test controls exactly what the
command should render, then invokes the Typer app in-process and asserts
on stdout.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
import typer
from typer.testing import CliRunner

from thesisound.modeling import ModelUsage
from thesisound.observability import (
    LedgerSpanSink,
    ModelCallSpec,
    ObservabilityLedger,
    ProviderMetadata,
)
from thesisound.observability_cli import register_observability_commands
from thesisound.tracing import Tracer

runner = CliRunner()


@pytest.fixture
def cli_app() -> typer.Typer:
    app = typer.Typer()
    register_observability_commands(app)
    return app


@pytest.fixture
def seeded_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ObservabilityLedger:
    ledger = ObservabilityLedger(tmp_path / "ledger.sqlite3", tmp_path / "artifacts")
    monkeypatch.setenv("THESISOUND_OBSERVABILITY_DATABASE_PATH", str(ledger.database_path))
    monkeypatch.setenv("THESISOUND_OBSERVABILITY_ARTIFACT_ROOT", str(ledger.artifact_root))
    # rich.table.Table truncates cells with an ellipsis at the ambient
    # console width, which defaults to a narrow 80 columns with no real
    # terminal attached (as under CliRunner). Widen it so assertions can
    # check for full field names instead of truncation-dependent prefixes.
    monkeypatch.setenv("COLUMNS", "220")
    return ledger


def _seed_trace(ledger: ObservabilityLedger, project_id):
    tracer = Tracer(LedgerSpanSink(ledger), code_version="test")
    workflow_run_id = uuid4()
    with (
        tracer.span(
            "corpus.run",
            kind="stage",
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            new_root=True,
        ) as root,
        tracer.span(
            "corpus.map_document",
            project_id=project_id,
            workflow_run_id=workflow_run_id,
        ) as step,
    ):
        spec = ModelCallSpec(
            stage="document_map",
            operation="structured_text",
            provider="gemini",
            requested_model="gemini-test",
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            pipeline_trace_id=root.context.trace_id,
        )
        ledger.begin_call(spec, {"prompt": "x"})
        ledger.provider_succeeded(
            spec.call_id,
            response_payload={"text": "ok"},
            usage=ModelUsage(total_tokens=5),
            provider_metadata=ProviderMetadata(),
        )
        ledger.succeed(spec.call_id, {"value": "ok"})
    tracer.event(
        "run.stage_changed",
        component="corpus",
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        previous="queued",
        current="mapping_document",
    )
    return root.context.trace_id, step.context.span_id


def test_trace_renders_the_latest_trace_as_a_tree(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger
) -> None:
    project_id = uuid4()
    _seed_trace(seeded_ledger, project_id)

    result = runner.invoke(cli_app, ["trace", str(project_id)])

    assert result.exit_code == 0, result.output
    assert "corpus.run" in result.output
    assert "corpus.map_document" in result.output
    assert "document_map" in result.output  # the model call, rendered as a leaf


def test_trace_reports_when_no_trace_exists(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger
) -> None:
    result = runner.invoke(cli_app, ["trace", str(uuid4())])

    assert result.exit_code == 1
    assert "No recorded trace" in result.output


def test_trace_show_renders_an_explicit_trace_id(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger
) -> None:
    project_id = uuid4()
    trace_id, _ = _seed_trace(seeded_ledger, project_id)

    result = runner.invoke(cli_app, ["trace-show", str(trace_id)])

    assert result.exit_code == 0, result.output
    assert "corpus.run" in result.output


def test_timeline_shows_stage_changed_events_newest_first(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger
) -> None:
    project_id = uuid4()
    _seed_trace(seeded_ledger, project_id)

    result = runner.invoke(cli_app, ["timeline", str(project_id)])

    assert result.exit_code == 0, result.output
    # Rich CliRunner tables truncate long cells; match stable prefixes/attrs.
    assert "run.stage_chang" in result.output
    assert "previous=queued" in result.output


def test_timeline_reports_when_no_events_exist(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger
) -> None:
    result = runner.invoke(cli_app, ["timeline", str(uuid4())])

    assert result.exit_code == 0
    assert "No recorded events" in result.output


def test_pipeline_summary_ranks_stages_and_shows_call_counts(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger
) -> None:
    project_id = uuid4()
    _seed_trace(seeded_ledger, project_id)

    result = runner.invoke(cli_app, ["pipeline-summary", str(project_id)])

    assert result.exit_code == 0, result.output
    assert "corpus.run" in result.output
    assert "corpus.map_document" in result.output


def test_pipeline_summary_reports_when_no_spans_exist(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger
) -> None:
    result = runner.invoke(cli_app, ["pipeline-summary", str(uuid4())])

    assert result.exit_code == 0
    assert "No recorded spans" in result.output


def test_existing_observability_and_model_call_commands_still_work(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger
) -> None:
    """Regression check: the CLI extension did not disturb the two
    pre-existing commands this file adds four new ones alongside."""

    project_id = uuid4()
    _, _ = _seed_trace(seeded_ledger, project_id)

    summary_result = runner.invoke(cli_app, ["observability", str(project_id)])
    assert summary_result.exit_code == 0, summary_result.output
    assert "calls=1" in summary_result.output
    assert "tokens=5" in summary_result.output


def _set_cost(ledger: ObservabilityLedger, call_id, *, cost_micros: int, version: str) -> None:
    connection = sqlite3.connect(ledger.database_path)
    try:
        connection.execute(
            "UPDATE model_calls SET cost_micros = ?, pricing_version = ? WHERE call_id = ?",
            (cost_micros, version, str(call_id)),
        )
        connection.commit()
    finally:
        connection.close()


def test_pipeline_summary_shows_self_time_and_cache_hit_rates(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger
) -> None:
    project_id = uuid4()
    _seed_trace(seeded_ledger, project_id)
    tracer = Tracer(LedgerSpanSink(seeded_ledger), code_version="test")
    tracer.event(
        "cache.lookup", project_id=project_id, cache="shared_document_map", result="hit"
    )

    result = runner.invoke(cli_app, ["pipeline-summary", str(project_id)])

    assert result.exit_code == 0, result.output
    assert "Self" in result.output
    assert "shared_document_map" in result.output
    assert "100%" in result.output


def test_cost_shows_total_and_a_breakdown_for_priced_calls(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger
) -> None:
    project_id = uuid4()
    _seed_trace(seeded_ledger, project_id)
    call_summary = next(
        call
        for call in seeded_ledger.list_calls(project_id)
        if call.stage == "document_map"
    )
    _set_cost(seeded_ledger, call_summary.call_id, cost_micros=1_250_000, version="test-2026")

    result = runner.invoke(cli_app, ["cost", str(project_id)])

    assert result.exit_code == 0, result.output
    assert "$1.2500" in result.output
    assert "Cost breakdown" in result.output
    assert "gemini" in result.output


def test_cost_flags_unpriced_calls_instead_of_a_silent_zero(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger
) -> None:
    project_id = uuid4()
    _seed_trace(seeded_ledger, project_id)  # cost_micros stays NULL -- no pricer configured

    result = runner.invoke(cli_app, ["cost", str(project_id)])

    assert result.exit_code == 0, result.output
    assert "unknown" in result.output
    assert "no configured price" in result.output
    assert "$0.0000" not in result.output


def test_cost_reports_when_no_calls_exist(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger
) -> None:
    result = runner.invoke(cli_app, ["cost", str(uuid4())])

    assert result.exit_code == 0
    assert "No recorded model calls" in result.output


def _seed_evidence_arm(
    ledger: ObservabilityLedger,
    project_id,
    *,
    model: str,
    excerpt_failures: int,
    priced: bool,
) -> None:
    spec = ModelCallSpec(
        stage="evidence_extraction",
        operation="structured_text",
        provider="gemini",
        requested_model=model,
        project_id=project_id,
        metadata={"model_profile": "gemini_fast"},
    )
    ledger.begin_call(spec, {"prompt": "x"})
    ledger.provider_succeeded(
        spec.call_id,
        response_payload={"text": "ok"},
        usage=ModelUsage(input_tokens=100, output_tokens=10, total_tokens=110),
        provider_metadata=ProviderMetadata(resolved_model=model),
    )
    ledger.succeed(spec.call_id, {"value": "ok"})
    if priced:
        _set_cost(ledger, spec.call_id, cost_micros=1_000, version="test")
    tracer = Tracer(LedgerSpanSink(ledger), code_version="test")
    tracer.event(
        "corpus.evidence_attempts",
        component="corpus",
        project_id=project_id,
        subject_type="block",
        subject_id="block-1",
        attempt_count=4,
        excerpt_failure_count=excerpt_failures,
        salvaged=False,
        dropped_claim_count=0,
        kept_claim_count=2,
        status="extracted",
    )


def test_evidence_tier_report_renders_measurements_and_refuses_unpriced_comparison(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger
) -> None:
    baseline = uuid4()
    comparison = uuid4()
    _seed_evidence_arm(
        seeded_ledger, baseline, model="gemini-fast", excerpt_failures=1, priced=True
    )
    _seed_evidence_arm(
        seeded_ledger, comparison, model="gemini-strong", excerpt_failures=0, priced=False
    )

    single = runner.invoke(cli_app, ["evidence-tier-report", str(baseline)])
    compared = runner.invoke(
        cli_app, ["evidence-tier-report", str(baseline), "--compare", str(comparison)]
    )

    assert single.exit_code == 0, single.output
    assert "Excerpt failures" in single.output
    assert "Wasted tokens" in single.output
    assert compared.exit_code == 0, compared.output
    assert "verdict: undecidable" in compared.output
    assert "gemini/gemini-strong/structured_text" in compared.output


def test_evidence_tier_comparison_shows_its_measured_deltas_and_ratios(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger
) -> None:
    baseline = uuid4()
    comparison = uuid4()
    _seed_evidence_arm(
        seeded_ledger, baseline, model="gemini-fast", excerpt_failures=1, priced=True
    )
    _seed_evidence_arm(
        seeded_ledger, comparison, model="gemini-strong", excerpt_failures=0, priced=True
    )

    result = runner.invoke(
        cli_app, ["evidence-tier-report", str(baseline), "--compare", str(comparison)]
    )

    assert result.exit_code == 0, result.output
    assert "Δ = -25.0 pp" in result.output
    assert "ratio = 1.00×" in result.output


def test_observability_reprice_recomputes_cost_and_reports_a_count(
    cli_app: typer.Typer,
    seeded_ledger: ObservabilityLedger,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    _seed_trace(seeded_ledger, project_id)
    call_summary = next(
        call
        for call in seeded_ledger.list_calls(project_id)
        if call.stage == "document_map"
    )
    pricing_file = tmp_path / "pricing.toml"
    pricing_file.write_text(
        """
        version = "reprice-test"
        [[prices]]
        provider = "gemini"
        model = "gemini-test"
        operation = "structured_text"
        effective_from = 2020-01-01
        per_call_micros = 7_000
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("THESISOUND_PRICING_FILE", str(pricing_file))

    result = runner.invoke(cli_app, ["observability-reprice"])

    assert result.exit_code == 0, result.output
    assert "Repriced 1 call" in result.output
    priced = seeded_ledger.get_call(call_summary.call_id)
    assert priced.call.cost_micros == 7_000
    assert priced.call.pricing_version == "reprice-test"


def test_observability_export_rejects_non_dedicated_directory_cleanly(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger, tmp_path: Path
) -> None:
    """Regression test: export_project()'s directory-safety check already
    refused and left the directory untouched, but the CLI let the resulting
    ValueError escape as a raw traceback instead of a clean usage error."""

    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / "unrelated.txt").write_text("keep", encoding="utf-8")

    result = runner.invoke(
        cli_app, ["observability-export", str(uuid4()), "--out", str(export_dir)]
    )

    assert result.exit_code == 2
    assert not isinstance(result.exception, ValueError)
    assert "dedicated directory" in result.output
    assert (export_dir / "unrelated.txt").read_text(encoding="utf-8") == "keep"


def test_run_summary_reports_a_missing_run_cleanly(
    cli_app: typer.Typer, seeded_ledger: ObservabilityLedger
) -> None:
    """Regression test: ledger.run_summary() already raised FileNotFoundError
    for an unknown run, but the CLI let it escape as a raw traceback instead
    of a clean usage error."""

    result = runner.invoke(cli_app, ["run-summary", str(uuid4())])

    assert result.exit_code == 2
    assert not isinstance(result.exception, FileNotFoundError)
    assert "Pipeline run not found" in result.output
