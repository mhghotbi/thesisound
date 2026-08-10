from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from rich.console import Console

from thesisound.config import Settings
from thesisound.domain import Project
from thesisound.modeling import ModelUsage
from thesisound.observability import (
    ModelCallSpec,
    ObservabilityLedger,
    ProviderMetadata,
    ledger_from_settings,
)
from thesisound.observability_cli import _render_delta_table
from thesisound.pipeline import WorkspaceStore
from thesisound.services.observability_reporting import ObservabilityReporter
from thesisound.tracing import EventRecord, SpanContext, SpanRecord, Tracer
from thesisound.web.app import create_app


def _write_span(
    ledger: ObservabilityLedger,
    *,
    trace_id: UUID,
    span_id: UUID,
    project_id: UUID,
    workflow_run_id: UUID,
    name: str,
    kind: str,
    started_at: datetime,
    duration_ms: int,
    parent_span_id: UUID | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    attributes: dict[str, object] | None = None,
    metrics: dict[str, float] | None = None,
) -> None:
    record = SpanRecord(
        context=SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
        ),
        parent_span_id=parent_span_id,
        name=name,
        component=name.split(".", 1)[0],
        kind=kind,
        subject_type=subject_type,
        subject_id=subject_id,
        started_at=started_at,
        process="test",
        pid=1,
        attributes=attributes or {},
        metrics=metrics or {},
    )
    ledger.start_span(record)
    record.status = "ok"
    record.ended_at = started_at + timedelta(milliseconds=duration_ms)
    record.duration_ms = duration_ms
    ledger.end_span(record)


def _write_event(
    ledger: ObservabilityLedger,
    *,
    trace_id: UUID,
    span_id: UUID,
    project_id: UUID,
    workflow_run_id: UUID,
    occurred_at: datetime,
    name: str,
    attributes: dict[str, object],
) -> None:
    ledger.record_event(
        EventRecord(
            event_id=uuid4(),
            trace_id=trace_id,
            span_id=span_id,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            occurred_at=occurred_at,
            name=name,
            component=name.split(".", 1)[0],
            level="info",
            subject_type=None,
            subject_id=None,
            attributes=attributes,
        )
    )


def _write_call(
    ledger: ObservabilityLedger,
    *,
    trace_id: UUID,
    parent_span_id: UUID,
    project_id: UUID,
    workflow_run_id: UUID,
    prompt_version: str,
    tokens: int,
    cost_micros: int | None,
    retried: bool,
    fail: bool = False,
    subject_id: str = "private-source-id",
) -> UUID:
    spec = ModelCallSpec(
        pipeline_trace_id=trace_id,
        parent_span_id=parent_span_id,
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        stage="corpus",
        operation="structured_text",
        provider="test",
        requested_model="test-model",
        prompt_id="evidence-extraction",
        prompt_version=prompt_version,
        subject_type="source",
        subject_id=subject_id,
        metadata={
            "provider": "test",
            "filename": "نام شخصی.pdf",
            "size_bytes": 4321,
            "query": ["پرسش خصوصی کاربر"],
            "topic": "موضوع خصوصی",
            "excerpt": "گزیده خصوصی",
            "path": "/home/alice/private/source.pdf",
        },
    )
    call_id = ledger.begin_call(
        spec,
        {
            "phone": "09120000000",
            "prompt": "متن خصوصی منبع",
        },
    )
    if fail:
        ledger.fail(call_id, RuntimeError("private failure message محرمانه"))
    else:
        ledger.provider_succeeded(
            call_id,
            response_payload={"ok": True},
            usage=ModelUsage(
                input_tokens=tokens // 2,
                output_tokens=tokens - (tokens // 2),
                total_tokens=tokens,
            ),
            provider_metadata=ProviderMetadata(
                resolved_model="test-model",
                http_status=200,
                finish_reason="stop",
            ),
        )
        ledger.succeed(call_id, {"text": "خروجی خصوصی"})
    with sqlite3.connect(ledger.database_path) as connection:
        connection.execute(
            """
            UPDATE model_calls
               SET cost_micros = ?, pricing_version = ?,
                   retry_scheduled = ?, provider_attempt_count = ?
             WHERE call_id = ?
            """,
            (
                cost_micros,
                "test-v1" if cost_micros is not None else None,
                int(retried),
                2 if retried else 1,
                str(call_id),
            ),
        )
    return call_id


def _write_run(
    ledger: ObservabilityLedger,
    *,
    project_id: UUID,
    workflow_run_id: UUID,
    started_at: datetime,
    duration_ms: int,
    stage_ms: int,
    tokens: int,
    cost_micros: int | None,
    retried: bool,
    cache_result: str,
    similarity: float,
    claim_count: int,
    code_version: str,
    prompt_version: str,
    source_id: str = "source-1",
) -> tuple[UUID, UUID]:
    trace_id = uuid4()
    root_id = uuid4()
    _write_span(
        ledger,
        trace_id=trace_id,
        span_id=root_id,
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        name="corpus.run",
        kind="stage",
        started_at=started_at,
        duration_ms=duration_ms,
        attributes={
            "pipeline_code_version": code_version,
            "topic": "عنوان خصوصی که نباید صادر شود",
        },
    )
    _write_span(
        ledger,
        trace_id=trace_id,
        span_id=uuid4(),
        parent_span_id=root_id,
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        name="corpus.source",
        kind="stage",
        started_at=started_at + timedelta(milliseconds=50),
        duration_ms=stage_ms,
        subject_type="source",
        subject_id=source_id,
        metrics={"claim_count": float(claim_count)},
    )
    _write_span(
        ledger,
        trace_id=trace_id,
        span_id=uuid4(),
        parent_span_id=root_id,
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        name="audio.qa",
        kind="internal",
        started_at=started_at + timedelta(milliseconds=100),
        duration_ms=20,
        attributes={"verdict": "pass" if similarity >= 0.8 else "review"},
        metrics={"similarity_ratio": similarity},
    )
    _write_event(
        ledger,
        trace_id=trace_id,
        span_id=root_id,
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        occurred_at=started_at + timedelta(milliseconds=10),
        name="cache.lookup",
        attributes={
            "cache": "document_map",
            "result": cache_result,
            "excerpt": "یادداشت خصوصی",
        },
    )
    _write_call(
        ledger,
        trace_id=trace_id,
        parent_span_id=root_id,
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        prompt_version=prompt_version,
        tokens=tokens,
        cost_micros=cost_micros,
        retried=retried,
        subject_id=source_id,
    )
    return trace_id, root_id


def test_export_is_allowlisted_and_uses_one_snapshot(
    ledger: ObservabilityLedger,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    run_id = uuid4()
    started = datetime(2026, 1, 1, tzinfo=UTC)
    trace_id, root_id = _write_run(
        ledger,
        project_id=project_id,
        workflow_run_id=run_id,
        started_at=started,
        duration_ms=1_000,
        stage_ms=400,
        tokens=100,
        cost_micros=1_000,
        retried=False,
        cache_result="hit",
        similarity=0.9,
        claim_count=4,
        code_version="commit-a",
        prompt_version="1",
        source_id="source-private-id",
    )

    reporter = ObservabilityReporter(ledger)
    original_write_jsonl = reporter._write_jsonl
    injected = False

    def write_jsonl_and_inject(path: Path, rows: Any) -> int:
        nonlocal injected
        count = original_write_jsonl(path, rows)
        if path.name == "spans.jsonl" and not injected:
            injected = True
            _write_event(
                ledger,
                trace_id=trace_id,
                span_id=root_id,
                project_id=project_id,
                workflow_run_id=run_id,
                occurred_at=started + timedelta(seconds=2),
                name="after.snapshot",
                attributes={"private_note": "نباید در snapshot باشد"},
            )
        return count

    monkeypatch.setattr(reporter, "_write_jsonl", write_jsonl_and_inject)
    export_dir = tmp_path / "export"
    result = reporter.export_project(project_id, export_dir)

    assert {item.name for item in export_dir.iterdir()} == {
        "spans.jsonl",
        "events.jsonl",
        "model_calls.jsonl",
        "manifest.json",
    }
    assert result.row_counts == {
        "spans.jsonl": 3,
        "events.jsonl": 1,
        "model_calls.jsonl": 1,
    }
    assert len(ledger.list_events_by_project(project_id)) == 2

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["format_version"] == 3
    assert manifest["pipeline_code_versions"] == ["commit-a"]
    assert manifest["prompt_versions"] == [
        {"prompt_id": "evidence-extraction", "prompt_version": "1"}
    ]
    assert "thesisound.observability.redact_value" in manifest["redaction"]["policy"]
    for filename in ("spans.jsonl", "events.jsonl", "model_calls.jsonl"):
        digest = hashlib.sha256((export_dir / filename).read_bytes()).hexdigest()
        assert manifest["files"][filename]["sha256"] == digest

    exported = "\n".join(
        (export_dir / filename).read_text(encoding="utf-8")
        for filename in ("spans.jsonl", "events.jsonl", "model_calls.jsonl")
    )
    for private_value in (
        "09120000000",
        "پرسش خصوصی کاربر",
        "نام شخصی.pdf",
        "/home/alice",
        "موضوع خصوصی",
        "گزیده خصوصی",
        "عنوان خصوصی که نباید صادر شود",
        "یادداشت خصوصی",
        "نباید در snapshot باشد",
    ):
        assert private_value not in exported

    call_row = json.loads((export_dir / "model_calls.jsonl").read_text().splitlines()[0])
    assert call_row["subject_id"] == "source-private-id"
    assert call_row["metadata"]["provider"] == "test"
    assert call_row["metadata"]["query"]["sha256"]
    assert call_row["metadata"]["topic"]["sha256"]
    assert call_row["metadata"]["excerpt"]["sha256"]
    assert call_row["metadata"]["filename"]["extension"] == ".pdf"
    assert call_row["metadata"]["filename"]["size_bytes"] == 4321
    event_row = json.loads((export_dir / "events.jsonl").read_text().splitlines()[0])
    assert event_row["attributes"]["cache"] == "document_map"
    assert event_row["attributes"]["result"] == "hit"
    assert event_row["attributes"]["excerpt"]["sha256"]

    second_dir = tmp_path / "export-second"
    reporter.export_project(project_id, second_dir)
    second_call = json.loads((second_dir / "model_calls.jsonl").read_text().splitlines()[0])
    assert second_call["metadata"]["query"]["sha256"] == call_row["metadata"]["query"]["sha256"]
    assert (
        second_call["metadata"]["filename"]["filename_sha256"]
        == call_row["metadata"]["filename"]["filename_sha256"]
    )


def test_export_refuses_to_replace_non_dedicated_directory(
    ledger: ObservabilityLedger,
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    marker = export_dir / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="dedicated directory"):
        ObservabilityReporter(ledger).export_project(project_id, export_dir)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_compare_run_ids_aggregate_every_trace_and_preserve_unknown_cost(
    ledger: ObservabilityLedger,
) -> None:
    project_id = uuid4()
    run_a = uuid4()
    run_b = uuid4()
    started = datetime(2026, 1, 1, tzinfo=UTC)

    _write_run(
        ledger,
        project_id=project_id,
        workflow_run_id=run_a,
        started_at=started,
        duration_ms=1_000,
        stage_ms=400,
        tokens=100,
        cost_micros=1_000,
        retried=False,
        cache_result="hit",
        similarity=0.9,
        claim_count=4,
        code_version="commit-a",
        prompt_version="1",
        source_id="source-a",
    )
    _write_run(
        ledger,
        project_id=project_id,
        workflow_run_id=run_a,
        started_at=started + timedelta(seconds=2),
        duration_ms=500,
        stage_ms=200,
        tokens=50,
        cost_micros=500,
        retried=True,
        cache_result="miss",
        similarity=0.8,
        claim_count=2,
        code_version="commit-a",
        prompt_version="1",
        source_id="source-b",
    )
    trace_b, root_b = _write_run(
        ledger,
        project_id=project_id,
        workflow_run_id=run_b,
        started_at=started + timedelta(minutes=1),
        duration_ms=800,
        stage_ms=300,
        tokens=80,
        cost_micros=None,
        retried=False,
        cache_result="miss",
        similarity=0.7,
        claim_count=3,
        code_version="commit-b",
        prompt_version="2",
        source_id="source-c",
    )
    _write_call(
        ledger,
        trace_id=trace_b,
        parent_span_id=root_b,
        project_id=project_id,
        workflow_run_id=run_b,
        prompt_version="2",
        tokens=0,
        cost_micros=None,
        retried=False,
        fail=True,
        subject_id="source-c",
    )

    comparison = ObservabilityReporter(ledger).compare_runs(run_a, run_b)

    assert comparison["run_a"]["scope"] == "run"
    assert comparison["run_a"]["trace_count"] == 2
    assert comparison["run_a"]["summary"]["duration_ms"] == 2_500
    assert comparison["run_a"]["summary"]["model_call_count"] == 2
    assert comparison["run_a"]["summary"]["total_tokens"] == 150
    assert comparison["run_a"]["summary"]["cost_micros"] == 1_500
    assert comparison["run_a"]["summary"]["retry_count"] == 1
    assert set(comparison["run_a"]["evidence_yield"]) == {"source-a", "source-b"}

    # One unpriced success plus one failed call must remain "unknown", not $0.
    assert comparison["run_b"]["summary"]["model_call_count"] == 2
    assert comparison["run_b"]["summary"]["priced_count"] == 0
    assert comparison["run_b"]["summary"]["unpriced_count"] == 1
    assert comparison["run_b"]["summary"]["cost_micros"] is None
    assert comparison["summary"]["cost_micros"]["absolute"] is None


def test_trace_ids_still_compare_as_single_traces(ledger: ObservabilityLedger) -> None:
    project_id = uuid4()
    started = datetime(2026, 1, 1, tzinfo=UTC)
    trace_a, _ = _write_run(
        ledger,
        project_id=project_id,
        workflow_run_id=uuid4(),
        started_at=started,
        duration_ms=1_000,
        stage_ms=400,
        tokens=100,
        cost_micros=1_000,
        retried=False,
        cache_result="hit",
        similarity=0.9,
        claim_count=4,
        code_version="commit-a",
        prompt_version="1",
    )
    trace_b, _ = _write_run(
        ledger,
        project_id=project_id,
        workflow_run_id=uuid4(),
        started_at=started + timedelta(minutes=1),
        duration_ms=2_000,
        stage_ms=800,
        tokens=200,
        cost_micros=3_000,
        retried=True,
        cache_result="miss",
        similarity=0.7,
        claim_count=8,
        code_version="commit-b",
        prompt_version="2",
    )

    comparison = ObservabilityReporter(ledger).compare_runs(trace_a, trace_b)
    assert comparison["run_a"]["scope"] == "trace"
    assert comparison["summary"]["duration_ms"]["absolute"] == 1_000
    assert comparison["summary"]["total_tokens"]["absolute"] == 100
    assert comparison["summary"]["cost_micros"]["absolute"] == 2_000
    cache = next(row for row in comparison["cache_hit_rates"] if row["name"] == "document_map")
    assert cache["absolute"] == -1.0
    assert comparison["audio_qa"]["mean_similarity"]["absolute"] == pytest.approx(-0.2)


class _RecordingSink:
    def __init__(self) -> None:
        self.spans: list[SpanRecord] = []

    def begin(self, record: SpanRecord) -> None:
        return None

    def end(self, record: SpanRecord) -> None:
        self.spans.append(record)

    def event(self, record: EventRecord) -> None:
        return None


def test_root_spans_are_stamped_with_pipeline_code_version() -> None:
    sink = _RecordingSink()
    tracer = Tracer(sink, code_version="abc123")

    with tracer.span("corpus.run", kind="stage"), tracer.span("corpus.source", kind="stage"):
        pass

    root = next(item for item in sink.spans if item.name == "corpus.run")
    child = next(item for item in sink.spans if item.name == "corpus.source")
    assert root.attributes["pipeline_code_version"] == "abc123"
    assert "pipeline_code_version" not in child.attributes


def test_running_nodes_report_elapsed_duration(ledger: ObservabilityLedger) -> None:
    project_id = uuid4()
    trace_id = uuid4()
    span_id = uuid4()
    started = datetime.now(UTC) - timedelta(seconds=2)
    running = SpanRecord(
        context=SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            project_id=project_id,
            workflow_run_id=uuid4(),
        ),
        parent_span_id=None,
        name="corpus.extract_evidence",
        component="corpus",
        kind="stage",
        subject_type="source",
        subject_id="source-1",
        started_at=started,
        process="test",
        pid=1,
        attributes={"pipeline_code_version": "web-test"},
    )
    ledger.start_span(running)

    overview = ObservabilityReporter(ledger).project_overview(project_id, trace_id=trace_id)
    assert overview["waterfall"][0]["duration_ms"] >= 1_500
    assert overview["trace_tree"][0]["duration_ms"] >= 1_500
    assert overview["traces"][0]["duration_ms"] >= 1_500


def test_summary_delta_table_formats_units() -> None:
    console = Console(record=True, width=160)
    _render_delta_table(
        console,
        "Run summary",
        [
            {
                "name": "duration_ms",
                "before": 1_000,
                "after": 2_000,
                "absolute": 1_000,
                "percent": 1.0,
            },
            {
                "name": "cost_micros",
                "before": 1_000,
                "after": 2_000,
                "absolute": 1_000,
                "percent": 1.0,
            },
        ],
        metric_name="summary",
    )
    rendered = console.export_text()
    assert "1000 ms" in rendered
    assert "$0.0010" in rendered


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        ingestion_artifact_root=tmp_path / "artifacts",
        web_session_secret="test-secret-that-is-long-enough",
        allow_test_otp=True,
        test_otp_phone="09120000000",
        test_otp_code="999999",
        otp_resend_cooldown_seconds=5,
        ui_demo_mode=False,
        web_secure_cookies=False,
    )


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _login_password(client: TestClient, username: str, password: str) -> None:
    page = client.get("/login/password")
    response = client.post(
        "/login/password",
        data={
            "username": username,
            "password": password,
            "csrf_token": _csrf(page.text),
            "next_path": "/projects",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_observability_requires_real_operator_role_and_remains_read_only(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
        audio_executor=lambda _: None,
    )
    workspace = WorkspaceStore(settings.ensure_workspace_root())
    project = Project(raw_input="اخلاق کانت")
    workspace.save_project(project)
    app.state.accounts.create_password_user("member-user", "member-pass", role="member")
    app.state.accounts.create_password_user("operator-user", "operator-pass", role="operator")

    ledger = ledger_from_settings(settings)
    trace_id = uuid4()
    span_id = uuid4()
    running = SpanRecord(
        context=SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            project_id=project.project_id,
            workflow_run_id=uuid4(),
        ),
        parent_span_id=None,
        name="corpus.extract_evidence",
        component="corpus",
        kind="stage",
        subject_type="source",
        subject_id="source-1",
        started_at=datetime.now(UTC) - timedelta(seconds=1),
        process="test",
        pid=1,
        attributes={"pipeline_code_version": "web-test"},
    )
    ledger.start_span(running)

    # A member can choose the advanced UI mode, but that preference must not
    # grant the operator role or access to another project's telemetry.
    with TestClient(app) as client:
        _login_password(client, "member-user", "member-pass")
        preferences = client.get("/projects")
        changed = client.post(
            "/ui/preferences",
            data={"csrf_token": _csrf(preferences.text), "mode": "operator"},
        )
        assert changed.status_code == 204
        denied = client.get(
            f"/projects/{project.project_id}/observability",
            follow_redirects=False,
        )
        assert denied.status_code == 303
        assert denied.headers["location"] == f"/projects/{project.project_id}"
        assert client.get(f"/projects/{project.project_id}/observability/live").status_code == 403

    # The real operator role authorizes the data, while the existing UI mode
    # still gates whether the technical operator surface is presented.
    with TestClient(app) as client:
        _login_password(client, "operator-user", "operator-pass")
        simple = client.get(f"/projects/{project.project_id}/observability", follow_redirects=False)
        assert simple.status_code == 303
        assert client.get(f"/projects/{project.project_id}/observability/live").status_code == 403

        preferences = client.get("/projects")
        changed = client.post(
            "/ui/preferences",
            data={"csrf_token": _csrf(preferences.text), "mode": "operator"},
        )
        assert changed.status_code == 204

        page = client.get(f"/projects/{project.project_id}/observability")
        assert page.status_code == 200
        assert "corpus.extract_evidence" in page.text
        assert "every 2s" in page.text
        assert "آبشار مرحله‌ها" in page.text

        live = client.get(f"/projects/{project.project_id}/observability/live")
        assert live.status_code == 200
        assert "corpus.extract_evidence" in live.text

        assert client.post(f"/projects/{project.project_id}/observability").status_code == 405
        assert (
            client.get(f"/projects/{project.project_id}/observability?depth=13").status_code == 422
        )
