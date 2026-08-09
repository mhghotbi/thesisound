from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from thesisound.config import Settings
from thesisound.domain import Project
from thesisound.modeling import ModelUsage
from thesisound.observability import (
    ModelCallSpec,
    ObservabilityLedger,
    ProviderMetadata,
    ledger_from_settings,
)
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
    cost_micros: int,
    retried: bool,
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
        metadata={
            "filename": "نام شخصی.pdf",
            "query": "پرسش خصوصی کاربر",
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
               SET cost_micros = ?, pricing_version = 'test-v1',
                   retry_scheduled = ?, provider_attempt_count = ?
             WHERE call_id = ?
            """,
            (cost_micros, int(retried), 2 if retried else 1, str(call_id)),
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
    cost_micros: int,
    retried: bool,
    cache_result: str,
    similarity: float,
    claim_count: int,
    code_version: str,
    prompt_version: str,
) -> UUID:
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
        attributes={"pipeline_code_version": code_version},
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
        subject_id="source-1",
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
        attributes={"cache": "document_map", "result": cache_result},
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
    )
    return trace_id


def test_export_and_compare_cover_phase_5(
    ledger: ObservabilityLedger,
    tmp_path: Path,
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
    )
    _write_run(
        ledger,
        project_id=project_id,
        workflow_run_id=run_b,
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

    reporter = ObservabilityReporter(ledger)
    export_dir = tmp_path / "export"
    result = reporter.export_project(project_id, export_dir)

    assert {item.name for item in export_dir.iterdir()} == {
        "spans.jsonl",
        "events.jsonl",
        "model_calls.jsonl",
        "manifest.json",
    }
    assert result.row_counts == {
        "spans.jsonl": 6,
        "events.jsonl": 2,
        "model_calls.jsonl": 2,
    }
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["pipeline_code_versions"] == ["commit-a", "commit-b"]
    assert manifest["prompt_versions"] == [
        {"prompt_id": "evidence-extraction", "prompt_version": "1"},
        {"prompt_id": "evidence-extraction", "prompt_version": "2"},
    ]
    for filename in ("spans.jsonl", "events.jsonl", "model_calls.jsonl"):
        digest = hashlib.sha256((export_dir / filename).read_bytes()).hexdigest()
        assert manifest["files"][filename]["sha256"] == digest

    exported = "\n".join(
        (export_dir / filename).read_text(encoding="utf-8")
        for filename in ("spans.jsonl", "events.jsonl", "model_calls.jsonl")
    )
    assert "09120000000" not in exported
    assert "پرسش خصوصی کاربر" not in exported
    assert "نام شخصی.pdf" not in exported
    assert "/home/alice" not in exported
    call_row = json.loads((export_dir / "model_calls.jsonl").read_text().splitlines()[0])
    assert call_row["metadata"]["query"]["length"] == len("پرسش خصوصی کاربر")
    assert call_row["metadata"]["filename"]["sha256"]

    comparison = reporter.compare_runs(run_a, run_b)
    assert comparison["summary"]["duration_ms"]["absolute"] == 1_000
    assert comparison["summary"]["total_tokens"]["absolute"] == 100
    assert comparison["summary"]["cost_micros"]["absolute"] == 2_000
    assert comparison["summary"]["retry_count"]["absolute"] == 1
    stage = next(row for row in comparison["stages"] if row["name"] == "corpus.source")
    assert stage["absolute"] == 400
    cache = next(row for row in comparison["cache_hit_rates"] if row["name"] == "document_map")
    assert cache["absolute"] == -1.0
    assert comparison["audio_qa"]["mean_similarity"]["absolute"] == pytest.approx(-0.2)
    evidence = next(row for row in comparison["evidence_yield"] if row["name"] == "source-1")
    assert evidence["absolute"] == 4
    assert comparison["run_a"]["pipeline_code_version"] == "commit-a"
    assert comparison["run_b"]["prompt_versions"][0]["prompt_version"] == "2"


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


def _login(client: TestClient) -> None:
    page = client.get("/login")
    client.post(
        "/login/request-code",
        data={
            "phone": "09120000000",
            "csrf_token": _csrf(page.text),
            "next_path": "/projects",
        },
    )
    page = client.get("/login/verify")
    client.post(
        "/login/verify",
        data={"code": "999999", "csrf_token": _csrf(page.text)},
    )


def test_operator_observability_page_is_read_only_and_depth_limited(
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
        started_at=datetime.now(UTC),
        process="test",
        pid=1,
        attributes={"pipeline_code_version": "web-test"},
    )
    ledger.start_span(running)

    with TestClient(app) as client:
        _login(client)
        simple = client.get(
            f"/projects/{project.project_id}/observability",
            follow_redirects=False,
        )
        assert simple.status_code == 303
        assert simple.headers["location"] == f"/projects/{project.project_id}"

        preferences = client.get(f"/projects/{project.project_id}")
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
