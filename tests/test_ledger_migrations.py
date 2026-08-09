from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from thesisound.observability import (
    _MIGRATIONS,
    _SCHEMA_V1,
    ModelCallSpec,
    ObservabilityLedger,
)


def _schema_version(database_path: Path) -> int | None:
    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
    finally:
        connection.close()
    return int(row[0]) if row else None


def test_fresh_ledger_reaches_latest_schema_version(tmp_path: Path) -> None:
    ledger = ObservabilityLedger(tmp_path / "ledger.sqlite3", tmp_path / "artifacts")

    assert _schema_version(ledger.database_path) == len(_MIGRATIONS)


def test_pre_migration_ledger_is_adopted_without_losing_data(tmp_path: Path) -> None:
    database_path = tmp_path / "ledger.sqlite3"
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)

    # Simulate a ledger written by the pre-migration code: the v1 tables
    # exist (via the historical CREATE TABLE IF NOT EXISTS script) but there
    # is no schema_meta table and therefore no recorded version at all.
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript(_SCHEMA_V1)
        connection.execute(
            """
            INSERT INTO model_calls(
                call_id, stage, operation, provider, requested_model,
                logical_attempt, status, started_at, provider_attempt_count,
                grounding_mode, retry_scheduled, metadata_json
            ) VALUES (?, 'document_map', 'structured_text', 'gemini', 'gemini-test',
                      1, 'succeeded', '2026-01-01T00:00:00+00:00', 1, 'none', 0, '{}')
            """,
            (str(uuid4()),),
        )
        connection.commit()
    finally:
        connection.close()

    row_count_before = sqlite3.connect(database_path).execute(
        "SELECT COUNT(*) FROM model_calls"
    ).fetchone()[0]
    assert row_count_before == 1

    # Opening it through the real ledger must adopt it: apply the (already
    # satisfied) v1 migration idempotently, stamp schema_meta, and keep the
    # pre-existing row untouched.
    ledger = ObservabilityLedger(database_path, artifact_root)

    assert _schema_version(ledger.database_path) == len(_MIGRATIONS)
    row_count_after = sqlite3.connect(database_path).execute(
        "SELECT COUNT(*) FROM model_calls"
    ).fetchone()[0]
    assert row_count_after == 1


def test_reopening_an_up_to_date_ledger_is_a_no_op(tmp_path: Path) -> None:
    database_path = tmp_path / "ledger.sqlite3"
    artifact_root = tmp_path / "artifacts"

    first = ObservabilityLedger(database_path, artifact_root)
    spec = ModelCallSpec(
        stage="document_map",
        operation="structured_text",
        provider="gemini",
        requested_model="gemini-test",
    )
    first.begin_call(spec, {"prompt": "hello"})

    # Re-opening the same file must not fail, must not duplicate the
    # schema_meta row, and must not touch existing data.
    second = ObservabilityLedger(database_path, artifact_root)

    connection = sqlite3.connect(database_path)
    try:
        version_rows = connection.execute(
            "SELECT COUNT(*) FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        call_rows = connection.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0]
    finally:
        connection.close()

    assert version_rows == 1
    assert call_rows == 1
    assert second.get_call(spec.call_id).call.call_id == spec.call_id


def test_re_applying_every_migration_twice_is_safe(tmp_path: Path) -> None:
    """Guards the executescript()-is-not-transactional hazard: each migration
    must be safe to run again from scratch (IF NOT EXISTS everywhere, and
    any ALTER TABLE guarded so a repeat is a no-op)."""

    database_path = tmp_path / "ledger.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        for migration in _MIGRATIONS:
            for _ in range(2):
                if callable(migration):
                    migration(connection)
                else:
                    connection.executescript(migration)
    finally:
        connection.close()


def test_fresh_ledger_has_pipeline_spans_and_events_tables(tmp_path: Path) -> None:
    ledger = ObservabilityLedger(tmp_path / "ledger.sqlite3", tmp_path / "artifacts")

    connection = sqlite3.connect(ledger.database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        model_calls_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(model_calls)")
        }
    finally:
        connection.close()

    assert {"pipeline_spans", "pipeline_events", "trace_nodes"} <= tables
    assert {"pipeline_trace_id", "parent_span_id", "cost_micros", "pricing_version"} <= (
        model_calls_columns
    )


def test_upgrading_a_v1_only_ledger_preserves_data_and_adds_v2(tmp_path: Path) -> None:
    """Simulates a ledger written before pipeline_spans existed: real
    ledger.sqlite3 files like this exist on disk today and must upgrade
    without losing their model_calls history."""

    database_path = tmp_path / "ledger.sqlite3"
    artifact_root = tmp_path / "artifacts"

    # Create a v1 ledger the normal way, then downgrade its recorded
    # version to 1 to simulate "written by a build that only had v1".
    v1_ledger = ObservabilityLedger(database_path, artifact_root)
    spec = ModelCallSpec(
        stage="document_map",
        operation="structured_text",
        provider="gemini",
        requested_model="gemini-test",
    )
    v1_ledger.begin_call(spec, {"prompt": "hello"})
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("UPDATE schema_meta SET value = '1' WHERE key = 'schema_version'")
        connection.commit()
    finally:
        connection.close()

    upgraded = ObservabilityLedger(database_path, artifact_root)

    assert _schema_version(upgraded.database_path) == len(_MIGRATIONS)
    assert upgraded.get_call(spec.call_id).call.call_id == spec.call_id
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        connection.close()
    assert "pipeline_spans" in tables


def test_newer_schema_version_than_supported_raises(tmp_path: Path) -> None:
    database_path = tmp_path / "ledger.sqlite3"
    artifact_root = tmp_path / "artifacts"

    # A ledger already at the current version...
    ObservabilityLedger(database_path, artifact_root)

    # ...but stamped from a future build that speaks a schema this build
    # does not understand yet.
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "UPDATE schema_meta SET value = ? WHERE key = 'schema_version'",
            (str(len(_MIGRATIONS) + 1),),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="newer than this build supports"):
        ObservabilityLedger(database_path, artifact_root)


def test_fresh_ledger_has_the_pipeline_runs_table(tmp_path: Path) -> None:
    ledger = ObservabilityLedger(tmp_path / "ledger.sqlite3", tmp_path / "artifacts")
    connection = sqlite3.connect(ledger.database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()

    assert "pipeline_runs" in tables


def test_upgrading_a_v2_ledger_adds_pipeline_runs(tmp_path: Path) -> None:
    database_path = tmp_path / "ledger.sqlite3"
    artifact_root = tmp_path / "artifacts"
    ledger = ObservabilityLedger(database_path, artifact_root)
    spec = ModelCallSpec(
        stage="document_map",
        operation="structured_text",
        provider="gemini",
        requested_model="gemini-test",
    )
    ledger.begin_call(spec, {"prompt": "hello"})
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("DROP TABLE pipeline_runs")
        connection.execute(
            "UPDATE schema_meta SET value = '2' WHERE key = 'schema_version'"
        )
        connection.commit()
    finally:
        connection.close()

    upgraded = ObservabilityLedger(database_path, artifact_root)

    assert upgraded.get_call(spec.call_id).call.call_id == spec.call_id
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()
    assert "pipeline_runs" in tables
