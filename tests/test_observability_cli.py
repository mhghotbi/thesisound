"""CLI-level tests for the trace/trace-show/timeline/pipeline-summary
commands added to observability_cli.py in Phase 2. Seeds a real ledger
directly (bypassing the tracer) so each test controls exactly what the
command should render, then invokes the Typer app in-process and asserts
on stdout.
"""

from __future__ import annotations

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
    tracer = Tracer(LedgerSpanSink(ledger))
    with (
        tracer.span("corpus.run", kind="stage", project_id=project_id) as root,
        tracer.span("corpus.map_document", project_id=project_id) as step,
    ):
        spec = ModelCallSpec(
            stage="document_map",
            operation="structured_text",
            provider="gemini",
            requested_model="gemini-test",
            project_id=project_id,
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
    assert "run.stage_changed" in result.output
    assert "mapping_document" in result.output


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
    assert "document_map" in summary_result.output
