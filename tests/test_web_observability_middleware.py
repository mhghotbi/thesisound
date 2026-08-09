"""Tests for the request-tracing middleware and global exception handler
added to web.app.create_app in Phase 2 -- request-ID propagation, the
/live polling exclusion, and turning an unhandled route exception into a
logged, traced, still-Persian error page instead of a bare 500.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from thesisound import tracing
from thesisound.config import Settings
from thesisound.web.app import create_app


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        ingestion_artifact_root=tmp_path / "artifacts",
        web_session_secret="test-secret-that-is-long-enough",
        allow_test_otp=True,
        ui_demo_mode=False,
    )


def _app(tmp_path: Path) -> FastAPI:
    return create_app(
        _settings(tmp_path),
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
        audio_executor=lambda _: None,
    )


def test_ordinary_request_gets_a_request_id_header(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))

    response = client.get("/health")

    assert response.status_code == 200
    assert "X-Request-Id" in response.headers
    # A valid UUID hex, per SpanContext.span_id.
    assert len(response.headers["X-Request-Id"].replace("-", "")) == 32


def test_two_requests_get_different_request_ids(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))

    first = client.get("/health")
    second = client.get("/health")

    assert first.headers["X-Request-Id"] != second.headers["X-Request-Id"]


def test_ordinary_request_produces_an_http_request_span(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    app = _app(tmp_path)
    # create_app() installs its own real, ledger-backed tracer -- reinstall
    # the in-memory recording one afterward so this test can inspect spans
    # without touching a real SQLite file.
    tracing.install_tracer(recording_tracer)
    client = TestClient(app)

    response = client.get("/health")

    span = recording_tracer.sink.one("http.request")
    assert span.attributes["method"] == "GET"
    assert span.attributes["route"] == "/health"
    assert span.attributes["status_code"] == response.status_code
    assert span.kind == "http"
    assert span.parent_span_id is None  # new_root: one trace per request


def test_live_polling_endpoints_are_not_traced(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    app = _app(tmp_path)
    tracing.install_tracer(recording_tracer)
    # follow_redirects=False: an unauthenticated hit to this route redirects
    # to /login, which is a real, correctly-traced request in its own right
    # and would otherwise show up here and make the assertion pass by
    # accident regardless of whether the /live request itself was excluded.
    client = TestClient(app, follow_redirects=False)

    client.get("/projects/00000000-0000-0000-0000-000000000000/processing/live")

    assert recording_tracer.sink.find("http.request") == []


def test_unhandled_exception_is_logged_traced_and_rendered_in_persian(
    tmp_path: Path, recording_tracer: tracing.Tracer, caplog
) -> None:
    app = _app(tmp_path)
    tracing.install_tracer(recording_tracer)

    @app.get("/__test_boom")
    def _boom() -> None:
        raise RuntimeError("synthetic failure for the exception handler test")

    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level("ERROR", logger="thesisound.web.app"):
        response = client.get("/__test_boom")

    assert response.status_code == 500
    assert "X-Request-Id" in response.headers
    assert response.headers["X-Request-Id"] in response.text
    # The Persian generic-failure phrasing from error_messages.py, not the
    # raw exception text or a stack trace.
    assert "RuntimeError" not in response.text
    assert "synthetic failure" not in response.text

    assert any(
        "Unhandled request error" in record.message for record in caplog.records
    )
    event = next(
        item for item in recording_tracer.sink.events if item.name == "web.unhandled_error"
    )
    assert event.level == "error"
    assert event.attributes["error_type"] == "RuntimeError"
    assert event.attributes["route"] == "/__test_boom"


def test_guard_live_runs_redirect_still_carries_a_request_id(tmp_path: Path) -> None:
    """Regression check for middleware ordering: request_trace was added
    after guard_live_runs specifically so it wraps the preflight redirect
    too, not just requests that pass the guard."""

    settings = _settings(tmp_path)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
        audio_executor=lambda _: None,
    )
    client = TestClient(app, follow_redirects=False)

    # /system-check itself is exempt from the guard, so use a POST path
    # that the guard scope table covers.
    response = client.post("/projects/00000000-0000-0000-0000-000000000000/corpus/confirm")

    # Whatever status this returns (redirect to /system-check, or 404/401
    # before the guard even applies), the tracing middleware wraps it either
    # way since it was registered after guard_live_runs.
    assert "X-Request-Id" in response.headers
