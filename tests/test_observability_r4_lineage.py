from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from thesisound import tracing
from thesisound.modeling import ModelUsage
from thesisound.observability import (
    ModelCallSpec,
    ObservabilityLedger,
    PipelineRunSpec,
    ProviderMetadata,
    _MIGRATIONS,
)
from thesisound.services.lineage_events import (
    emit_cache_lookup,
    emit_quality_label,
    emit_review_decision,
)
from thesisound.services.observability_rollup import ObservabilityRollup
from thesisound.tracing import SpanContext, SpanRecord


def test_fresh_ledger_has_v5_environment_and_cost_columns(tmp_path: Path) -> None:
    ledger = ObservabilityLedger(tmp_path / "ledger.sqlite3", tmp_path / "artifacts")
    connection = sqlite3.connect(ledger.database_path)
    try:
        version = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        model_cols = {row[1] for row in connection.execute("PRAGMA table_info(model_calls)")}
        run_cols = {row[1] for row in connection.execute("PRAGMA table_info(pipeline_runs)")}
    finally:
        connection.close()

    assert int(version) == len(_MIGRATIONS)
    assert {"environment", "is_synthetic"} <= model_cols
    assert {
        "environment",
        "is_synthetic",
        "total_cost_micros",
        "priced_call_count",
        "unpriced_call_count",
    } <= run_cols


def test_writers_stamp_environment_and_synthetic(tmp_path: Path) -> None:
    ledger = ObservabilityLedger(
        tmp_path / "ledger.sqlite3",
        tmp_path / "artifacts",
        environment="test",
        is_synthetic=True,
    )
    project_id = uuid4()
    run_id = uuid4()
    trace_id = uuid4()
    ledger.begin_run(
        PipelineRunSpec(
            workflow_run_id=run_id,
            project_id=project_id,
            trace_id=trace_id,
            kind="script",
            started_at=datetime.now(UTC),
        )
    )
    spec = ModelCallSpec(
        project_id=project_id,
        workflow_run_id=run_id,
        pipeline_trace_id=trace_id,
        stage="document_map",
        operation="structured_text",
        provider="gemini",
        requested_model="gemini-test",
    )
    ledger.begin_call(spec, {"prompt": "x"})
    connection = sqlite3.connect(ledger.database_path)
    try:
        call_row = connection.execute(
            "SELECT environment, is_synthetic FROM model_calls WHERE call_id = ?",
            (str(spec.call_id),),
        ).fetchone()
        run_row = connection.execute(
            "SELECT environment, is_synthetic FROM pipeline_runs WHERE workflow_run_id = ?",
            (str(run_id),),
        ).fetchone()
    finally:
        connection.close()
    assert call_row == ("test", 1)
    assert run_row == ("test", 1)


def test_production_begin_call_requires_linkage(tmp_path: Path) -> None:
    ledger = ObservabilityLedger(
        tmp_path / "ledger.sqlite3",
        tmp_path / "artifacts",
        environment="production",
        is_synthetic=False,
    )
    with pytest.raises(ValueError, match="project_id"):
        ledger.begin_call(
            ModelCallSpec(
                stage="document_map",
                operation="structured_text",
                provider="gemini",
                requested_model="gemini-test",
            ),
            {"prompt": "x"},
        )


def test_synthetic_production_exempt_from_linkage(tmp_path: Path) -> None:
    ledger = ObservabilityLedger(
        tmp_path / "ledger.sqlite3",
        tmp_path / "artifacts",
        environment="production",
        is_synthetic=True,
    )
    call_id = ledger.begin_call(
        ModelCallSpec(
            stage="document_map",
            operation="structured_text",
            provider="gemini",
            requested_model="gemini-test",
        ),
        {"prompt": "x"},
    )
    assert ledger.get_call(call_id).call.call_id == call_id


def test_finish_run_rolls_up_cost_fields(tmp_path: Path) -> None:
    class FixedPricer:
        def price(self, **_kwargs):
            from thesisound.observability import CostResult

            return CostResult(cost_micros=1_500, pricing_version="test-v1")

    ledger = ObservabilityLedger(
        tmp_path / "ledger.sqlite3",
        tmp_path / "artifacts",
        cost_pricer=FixedPricer(),
    )
    project_id = uuid4()
    run_id = uuid4()
    ledger.begin_run(
        PipelineRunSpec(
            workflow_run_id=run_id,
            project_id=project_id,
            trace_id=uuid4(),
            kind="script",
            started_at=datetime.now(UTC),
        )
    )
    spec = ModelCallSpec(
        project_id=project_id,
        workflow_run_id=run_id,
        pipeline_trace_id=uuid4(),
        stage="writer",
        operation="structured_text",
        provider="gemini",
        requested_model="gemini-test",
    )
    ledger.begin_call(spec, {"prompt": "x"})
    ledger.provider_succeeded(
        spec.call_id,
        response_payload={"ok": True},
        usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        provider_metadata=ProviderMetadata(resolved_model="gemini-test"),
    )
    ledger.succeed(spec.call_id, {"ok": True})
    ledger.finish_run(run_id, status="succeeded")
    summary = ledger.run_summary(run_id)
    assert summary.priced_call_count == 1
    assert summary.unpriced_call_count == 0
    assert summary.total_cost_micros == 1_500


def test_check_workflow_linkage_reports_missing_fields(ledger: ObservabilityLedger) -> None:
    run_id = uuid4()
    project_id = uuid4()
    trace_id = uuid4()
    span_id = uuid4()
    ledger.begin_run(
        PipelineRunSpec(
            workflow_run_id=run_id,
            project_id=project_id,
            trace_id=trace_id,
            kind="script",
            started_at=datetime.now(UTC),
        )
    )
    ledger.start_span(
        SpanRecord(
            context=SpanContext(
                trace_id=trace_id,
                span_id=span_id,
                project_id=project_id,
                workflow_run_id=run_id,
            ),
            parent_span_id=None,
            name="script.run",
            component="script",
            kind="stage",
            subject_type=None,
            subject_id=None,
            started_at=datetime.now(UTC),
            process="test",
            pid=1,
        )
    )
    report = ledger.check_workflow_linkage(run_id)
    assert report.ok


def test_rollup_excludes_synthetic_by_default(tmp_path: Path) -> None:
    project_id = uuid4()
    real = ObservabilityLedger(
        tmp_path / "ledger.sqlite3",
        tmp_path / "artifacts",
        environment="production",
        is_synthetic=False,
    )
    synth = ObservabilityLedger(
        tmp_path / "ledger.sqlite3",
        tmp_path / "artifacts",
        environment="test",
        is_synthetic=True,
    )
    for ledger, model in ((real, "real-model"), (synth, "synth-model")):
        spec = ModelCallSpec(
            project_id=project_id,
            workflow_run_id=uuid4(),
            pipeline_trace_id=uuid4(),
            stage="document_map",
            operation="structured_text",
            provider="gemini",
            requested_model=model,
        )
        ledger.begin_call(spec, {"prompt": "x"})
        ledger.provider_succeeded(
            spec.call_id,
            response_payload={"ok": True},
            usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            provider_metadata=ProviderMetadata(resolved_model=model),
        )
        ledger.succeed(spec.call_id, {"ok": True})

    rollup = ObservabilityRollup(real)
    assert rollup.project_summary(project_id).call_count == 1
    assert rollup.project_summary(project_id, include_synthetic=True).call_count == 2
    assert len(real.list_calls(project_id)) == 1
    assert len(real.list_calls(project_id, include_synthetic=True)) == 2


def test_lineage_helpers_emit_cache_review_and_quality(recording_tracer) -> None:
    previous = tracing.tracer()
    tracing.install_tracer(recording_tracer)
    project_id = uuid4()
    try:
        emit_cache_lookup(
            cache="web_search",
            result="hit",
            project_id=project_id,
            lookup_key="abc123",
            avoided_calls=1,
        )
        emit_review_decision(
            disposition="approved",
            subject_type="script",
            subject_id="proj",
            reviewer="tester",
        )
        emit_quality_label(
            label_source="audio_qa",
            subject_type="audio_chunk",
            subject_id="c1",
            verdict="pass",
            score=0.99,
        )
    finally:
        tracing.install_tracer(previous)

    names = [event.name for event in recording_tracer.sink.events]
    assert names == ["cache.lookup", "review.decision", "quality.label"]
    cache_event = recording_tracer.sink.events[0]
    assert cache_event.project_id == project_id
    cache_attrs = cache_event.attributes
    assert cache_attrs["lookup_key"] == "abc123"
    assert cache_attrs["avoided_calls"] == 1
    assert "project_id" not in cache_attrs


def test_production_root_span_requires_workflow(tmp_path: Path) -> None:
    ledger = ObservabilityLedger(
        tmp_path / "ledger.sqlite3",
        tmp_path / "artifacts",
        environment="production",
        is_synthetic=False,
    )
    with pytest.raises(ValueError, match="workflow_run_id"):
        ledger.start_span(
            SpanRecord(
                context=SpanContext(
                    trace_id=uuid4(),
                    span_id=uuid4(),
                    project_id=uuid4(),
                    workflow_run_id=None,
                ),
                parent_span_id=None,
                name="script.run",
                component="script",
                kind="stage",
                subject_type=None,
                subject_id=None,
                started_at=datetime.now(UTC),
                process="test",
                pid=1,
            )
        )
