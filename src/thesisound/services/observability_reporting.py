from __future__ import annotations

import hashlib
import json
import math
import shutil
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any
from uuid import UUID, uuid4

from thesisound.observability import SENSITIVE_ATTRIBUTES, ObservabilityLedger, redact_value
from thesisound.services.observability_rollup import ObservabilityRollup

_EXPORT_FILES = ("spans.jsonl", "events.jsonl", "model_calls.jsonl")
_EXPORT_ARTIFACTS = frozenset((*_EXPORT_FILES, "manifest.json"))
_TRACE_PAGE_SIZE = 10
_EVENT_PAGE_SIZE = 50
_MAX_TRACE_NODES = 1_000
_MAX_WATERFALL_ROWS = 200


@dataclass(frozen=True, slots=True)
class ExportResult:
    directory: Path
    manifest_path: Path
    row_counts: dict[str, int]


class ObservabilityReporter:
    """Read-only reporting over the observability ledger.

    The ledger remains the source of truth and write boundary. This service
    owns derived views used by both CLI and web surfaces, so export, compare,
    and the operator page cannot silently disagree about definitions.
    """

    def __init__(self, ledger: ObservabilityLedger) -> None:
        self.ledger = ledger
        self.rollup = ObservabilityRollup(ledger)

    def export_project(self, project_id: UUID, out_dir: Path) -> ExportResult:
        directory = out_dir.expanduser().resolve()
        staging = self._prepare_staging_directory(directory)
        counts: dict[str, int] = {}
        digests: dict[str, str] = {}
        snapshot_started_at = datetime.now(UTC).isoformat()

        try:
            with self._connect() as connection:
                # A single explicit read transaction pins one WAL snapshot for
                # every output file and the manifest, even while a live run is
                # still appending rows through other connections.
                connection.execute("BEGIN")
                try:
                    span_rows = connection.execute(
                        """
                        SELECT span_id, trace_id, parent_span_id, project_id,
                               workflow_run_id, name, component, kind,
                               subject_type, subject_id, status, started_at,
                               ended_at, duration_ms, process, pid, error_type,
                               error_message, attributes_json, metrics_json
                          FROM pipeline_spans
                         WHERE project_id = ?
                         ORDER BY started_at, span_id
                        """,
                        (str(project_id),),
                    )
                    counts["spans.jsonl"] = self._write_jsonl(
                        staging / "spans.jsonl",
                        (self._export_span_row(row) for row in span_rows),
                    )
                    digests["spans.jsonl"] = self._sha256(staging / "spans.jsonl")

                    event_rows = connection.execute(
                        """
                        SELECT event_id, trace_id, span_id, project_id,
                               workflow_run_id, occurred_at, name, component,
                               level, subject_type, subject_id, attributes_json
                          FROM pipeline_events
                         WHERE project_id = ?
                         ORDER BY occurred_at, event_id
                        """,
                        (str(project_id),),
                    )
                    counts["events.jsonl"] = self._write_jsonl(
                        staging / "events.jsonl",
                        (self._export_event_row(row) for row in event_rows),
                    )
                    digests["events.jsonl"] = self._sha256(staging / "events.jsonl")

                    call_rows = connection.execute(
                        """
                        SELECT call_id, trace_id, parent_call_id,
                               pipeline_trace_id, parent_span_id, project_id,
                               workflow_run_id, stage, operation, provider,
                               requested_model, resolved_model, prompt_id,
                               prompt_version, subject_type, subject_id,
                               logical_attempt, status, started_at, ended_at,
                               latency_ms, timeout_ms, provider_attempt_count,
                               input_tokens, output_tokens, thinking_tokens,
                               cached_tokens, total_tokens, finish_reason,
                               grounding_mode, http_status, error_type,
                               error_code, error_message, retry_scheduled,
                               retry_reason, backoff_ms, request_sha256,
                               raw_response_sha256, parsed_output_sha256,
                               metadata_json, cost_micros, pricing_version
                          FROM model_calls
                         WHERE project_id = ?
                         ORDER BY started_at, call_id
                        """,
                        (str(project_id),),
                    )
                    counts["model_calls.jsonl"] = self._write_jsonl(
                        staging / "model_calls.jsonl",
                        (self._export_model_call_row(row) for row in call_rows),
                    )
                    digests["model_calls.jsonl"] = self._sha256(staging / "model_calls.jsonl")

                    prompt_versions = [
                        {"prompt_id": row[0], "prompt_version": row[1]}
                        for row in connection.execute(
                            """
                            SELECT DISTINCT prompt_id, prompt_version
                              FROM model_calls
                             WHERE project_id = ?
                               AND (prompt_id IS NOT NULL OR prompt_version IS NOT NULL)
                             ORDER BY prompt_id, prompt_version
                            """,
                            (str(project_id),),
                        )
                    ]
                    code_versions = [
                        row[0]
                        for row in connection.execute(
                            """
                            SELECT DISTINCT json_extract(
                                       attributes_json, '$.pipeline_code_version'
                                   )
                              FROM pipeline_spans
                             WHERE project_id = ?
                               AND parent_span_id IS NULL
                               AND json_extract(
                                       attributes_json, '$.pipeline_code_version'
                                   ) IS NOT NULL
                             ORDER BY 1
                            """,
                            (str(project_id),),
                        )
                    ]
                    schema_row = connection.execute(
                        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                    ).fetchone()
                    connection.execute("COMMIT")
                except BaseException:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise

            manifest = {
                "format_version": 3,
                "project_id": str(project_id),
                "snapshot_started_at": snapshot_started_at,
                "exported_at": datetime.now(UTC).isoformat(),
                "schema_version": int(schema_row[0]) if schema_row else None,
                "redaction": {
                    "policy": "thesisound.observability.redact_value; payload storage forced off",
                    "sensitive_attributes": sorted(SENSITIVE_ATTRIBUTES),
                    "fingerprints": "deterministic SHA-256; filenames use a 16-hex SHA prefix",
                },
                "pipeline_code_versions": code_versions,
                "prompt_versions": prompt_versions,
                "files": {
                    filename: {
                        "rows": counts[filename],
                        "sha256": digests[filename],
                    }
                    for filename in _EXPORT_FILES
                },
            }
            self._write_json(staging / "manifest.json", manifest)
            self._publish_staging_directory(staging, directory)
        except BaseException:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise

        return ExportResult(
            directory=directory,
            manifest_path=directory / "manifest.json",
            row_counts=counts,
        )

    def compare_runs(self, run_a: UUID, run_b: UUID) -> dict[str, Any]:
        with self._connect() as connection:
            stats_a = self._identifier_statistics(connection, run_a)
            stats_b = self._identifier_statistics(connection, run_b)

        return {
            "run_a": stats_a,
            "run_b": stats_b,
            "summary": {
                key: self._delta(stats_a["summary"].get(key), stats_b["summary"].get(key))
                for key in (
                    "duration_ms",
                    "model_call_count",
                    "retry_count",
                    "total_tokens",
                    "cost_micros",
                )
            },
            "stages": self._keyed_deltas(
                stats_a["stages"], stats_b["stages"], value_key="duration_ms"
            ),
            "cache_hit_rates": self._keyed_deltas(
                stats_a["cache_hit_rates"], stats_b["cache_hit_rates"], value_key="hit_rate"
            ),
            "audio_qa": {
                "a": stats_a["audio_qa"],
                "b": stats_b["audio_qa"],
                "mean_similarity": self._delta(
                    stats_a["audio_qa"].get("mean_similarity"),
                    stats_b["audio_qa"].get("mean_similarity"),
                ),
            },
            "evidence_yield": self._keyed_deltas(
                stats_a["evidence_yield"], stats_b["evidence_yield"], value_key="claim_count"
            ),
        }

    def project_overview(
        self,
        project_id: UUID,
        *,
        trace_id: UUID | None = None,
        trace_page: int = 1,
        event_page: int = 1,
        depth: int = 6,
        include_synthetic: bool = False,
    ) -> dict[str, Any]:
        trace_page = max(1, trace_page)
        event_page = max(1, event_page)
        depth = max(1, min(depth, 12))
        synth = "1=1" if include_synthetic else "is_synthetic = 0"
        with self._connect() as connection:
            trace_count = int(
                connection.execute(
                    f"SELECT COUNT(DISTINCT trace_id) FROM pipeline_spans "
                    f"WHERE project_id = ? AND {synth}",
                    (str(project_id),),
                ).fetchone()[0]
            )
            trace_pages = max(1, math.ceil(trace_count / _TRACE_PAGE_SIZE))
            trace_page = min(trace_page, trace_pages)
            trace_rows = connection.execute(
                f"""
                SELECT s.trace_id, s.name, s.status, s.started_at, s.ended_at,
                       s.duration_ms, s.attributes_json
                  FROM pipeline_spans AS s
                 WHERE s.project_id = ?
                   AND {"s.is_synthetic = 0" if not include_synthetic else "1=1"}
                   AND s.span_id = (
                       SELECT candidate.span_id
                         FROM pipeline_spans AS candidate
                        WHERE candidate.trace_id = s.trace_id
                        ORDER BY
                              CASE WHEN candidate.parent_span_id IS NULL
                                   THEN 0 ELSE 1 END,
                              candidate.started_at, candidate.span_id
                        LIMIT 1
                   )
                 ORDER BY s.started_at DESC
                 LIMIT ? OFFSET ?
                """,
                (
                    str(project_id),
                    _TRACE_PAGE_SIZE,
                    (trace_page - 1) * _TRACE_PAGE_SIZE,
                ),
            ).fetchall()
            traces = [self._trace_row(row) for row in trace_rows]
            selected_trace = self._select_trace(connection, project_id, trace_id, traces)

            event_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM pipeline_events WHERE project_id = ? AND {synth}",
                    (str(project_id),),
                ).fetchone()[0]
            )
            event_pages = max(1, math.ceil(event_count / _EVENT_PAGE_SIZE))
            event_page = min(event_page, event_pages)
            event_rows = connection.execute(
                f"""
                SELECT event_id, trace_id, span_id, occurred_at, name, component,
                       level, subject_type, subject_id, attributes_json
                  FROM pipeline_events
                 WHERE project_id = ? AND {synth}
                 ORDER BY occurred_at DESC
                 LIMIT ? OFFSET ?
                """,
                (
                    str(project_id),
                    _EVENT_PAGE_SIZE,
                    (event_page - 1) * _EVENT_PAGE_SIZE,
                ),
            ).fetchall()
            events = [self._event_row(row) for row in event_rows]
            retry_row = connection.execute(
                f"""
                SELECT COUNT(*),
                       COUNT(*) FILTER (
                           WHERE retry_scheduled = 1 OR provider_attempt_count > 1
                       )
                  FROM model_calls WHERE project_id = ? AND {synth}
                """,
                (str(project_id),),
            ).fetchone()
            error_rows = connection.execute(
                f"""
                SELECT call_id, started_at, stage, operation, provider,
                       COALESCE(resolved_model, requested_model) AS model,
                       status, error_type, error_message
                  FROM model_calls
                 WHERE project_id = ? AND status IN ('failed', 'rejected')
                   AND {synth}
                 ORDER BY started_at DESC
                 LIMIT 20
                """,
                (str(project_id),),
            ).fetchall()
            errors = [self._safe_dict(row) for row in error_rows]

        trace_tree: list[dict[str, Any]] = []
        waterfall: list[dict[str, Any]] = []
        if selected_trace is not None:
            trace_tree = self._trace_tree(selected_trace, depth=depth)
            waterfall = self._waterfall(selected_trace)

        summary = self.rollup.project_summary(
            project_id, include_synthetic=include_synthetic
        )
        model_call_count = int(retry_row[0] or 0)
        retry_count = int(retry_row[1] or 0)
        return {
            "summary": summary,
            "cost_breakdown": self.rollup.cost_breakdown(
                project_id, include_synthetic=include_synthetic
            ),
            "stage_summary": self.rollup.stage_summary(
                project_id, include_synthetic=include_synthetic
            )[:20],
            "cache_rates": self.rollup.cache_hit_rates(
                project_id, include_synthetic=include_synthetic
            ),
            "retry_count": retry_count,
            "retry_rate": retry_count / model_call_count if model_call_count else 0.0,
            "traces": traces,
            "trace_count": trace_count,
            "trace_page": trace_page,
            "trace_pages": trace_pages,
            "selected_trace_id": selected_trace,
            "trace_tree": trace_tree,
            "waterfall": waterfall,
            "trace_depth": depth,
            "events": events,
            "event_page": event_page,
            "event_pages": event_pages,
            "errors": errors,
            "current_span": self.current_open_span(project_id),
        }

    def current_open_span(self, project_id: UUID) -> dict[str, Any] | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT span_id, trace_id, parent_span_id, name, component, kind,
                           subject_type, subject_id, started_at, attributes_json
                      FROM pipeline_spans
                     WHERE project_id = ? AND status = 'running'
                     ORDER BY started_at DESC
                     LIMIT 1
                    """,
                    (str(project_id),),
                ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        item = self._safe_dict(row)
        started = self._parse_timestamp(item["started_at"])
        item["elapsed_ms"] = max(0, round((datetime.now(UTC) - started).total_seconds() * 1000))
        item["attributes"] = self._load_json(item.pop("attributes_json", "{}"))
        return item

    def live_status(self, project_id: UUID) -> dict[str, Any]:
        current = self.current_open_span(project_id)
        with self._connect() as connection:
            latest_trace = connection.execute(
                """
                SELECT trace_id, name, status, started_at, ended_at, duration_ms
                  FROM pipeline_spans
                 WHERE project_id = ? AND parent_span_id IS NULL
                 ORDER BY started_at DESC LIMIT 1
                """,
                (str(project_id),),
            ).fetchone()
            latest_error = connection.execute(
                """
                SELECT occurred_at, name, component, attributes_json
                  FROM pipeline_events
                 WHERE project_id = ? AND level = 'error'
                 ORDER BY occurred_at DESC LIMIT 1
                """,
                (str(project_id),),
            ).fetchone()
        return {
            "current_span": current,
            "latest_trace": self._safe_dict(latest_trace) if latest_trace else None,
            "latest_error": self._event_row(latest_error) if latest_error else None,
        }

    def _identifier_statistics(
        self,
        connection: sqlite3.Connection,
        identifier: UUID,
    ) -> dict[str, Any]:
        value = str(identifier)
        run_row = connection.execute(
            """
            SELECT kind, started_at, finished_at, duration_ms
              FROM pipeline_runs
             WHERE workflow_run_id = ?
            """,
            (value,),
        ).fetchone()
        run_exists = (
            run_row is not None
            or connection.execute(
                """
            SELECT 1
              FROM pipeline_spans
             WHERE workflow_run_id = ?
             LIMIT 1
            """,
                (value,),
            ).fetchone()
            is not None
        )
        if not run_exists:
            run_exists = (
                connection.execute(
                    """
                SELECT 1
                  FROM model_calls
                 WHERE workflow_run_id = ?
                 LIMIT 1
                """,
                    (value,),
                ).fetchone()
                is not None
            )
        if run_exists:
            return self._run_statistics(connection, identifier, run_row)

        trace_exists = (
            connection.execute(
                "SELECT 1 FROM pipeline_spans WHERE trace_id = ? LIMIT 1",
                (value,),
            ).fetchone()
            is not None
        )
        if not trace_exists:
            trace_exists = (
                connection.execute(
                    """
                SELECT 1
                  FROM model_calls
                 WHERE pipeline_trace_id = ?
                 LIMIT 1
                """,
                    (value,),
                ).fetchone()
                is not None
            )
        if trace_exists:
            return self._trace_statistics(connection, identifier)
        raise FileNotFoundError(f"Run or trace not found: {identifier}")

    def _run_statistics(
        self,
        connection: sqlite3.Connection,
        run_id: UUID,
        run_row: sqlite3.Row | None,
    ) -> dict[str, Any]:
        value = str(run_id)
        roots = connection.execute(
            """
            SELECT trace_id, name, started_at, ended_at, duration_ms,
                   attributes_json
              FROM pipeline_spans
             WHERE workflow_run_id = ? AND parent_span_id IS NULL
             ORDER BY started_at, span_id
            """,
            (value,),
        ).fetchall()
        code_versions = sorted(
            {
                version
                for root in roots
                if (version := self._load_json(root[5]).get("pipeline_code_version"))
            }
        )

        if run_row is not None:
            duration_ms = self._duration_from_values(run_row[1], run_row[2], run_row[3])
            root_name = str(run_row[0])
        elif roots:
            starts = [self._parse_timestamp(root[2]) for root in roots]
            ends = [
                self._parse_timestamp(root[3]) if root[3] else datetime.now(UTC) for root in roots
            ]
            duration_ms = max(
                0,
                round((max(ends) - min(starts)).total_seconds() * 1000),
            )
            root_name = roots[0][1]
        else:
            envelope = connection.execute(
                """
                SELECT MIN(started_at), MAX(ended_at)
                  FROM model_calls
                 WHERE workflow_run_id = ?
                """,
                (value,),
            ).fetchone()
            if envelope is None or envelope[0] is None:
                raise FileNotFoundError(f"Run not found: {run_id}")
            duration_ms = self._duration_from_values(envelope[0], envelope[1], None)
            root_name = "run"

        pipeline_code_version = None
        if len(code_versions) == 1:
            pipeline_code_version = code_versions[0]
        elif code_versions:
            pipeline_code_version = "mixed:" + ",".join(str(item) for item in code_versions)

        return self._scope_statistics(
            connection,
            scope="run",
            identifier=run_id,
            workflow_run_id=run_id,
            root_name=root_name,
            duration_ms=duration_ms,
            pipeline_code_version=pipeline_code_version,
            pipeline_code_versions=code_versions,
            trace_count=len({root[0] for root in roots}),
        )

    def _trace_statistics(
        self,
        connection: sqlite3.Connection,
        trace_id: UUID,
    ) -> dict[str, Any]:
        root = connection.execute(
            """
            SELECT workflow_run_id, name, started_at, ended_at, duration_ms,
                   attributes_json
              FROM pipeline_spans
             WHERE trace_id = ? AND parent_span_id IS NULL
             ORDER BY started_at LIMIT 1
            """,
            (str(trace_id),),
        ).fetchone()
        if root is None:
            raise FileNotFoundError(f"Trace not found: {trace_id}")
        root_attributes = self._load_json(root[5])
        code_version = root_attributes.get("pipeline_code_version")
        return self._scope_statistics(
            connection,
            scope="trace",
            identifier=trace_id,
            workflow_run_id=UUID(root[0]) if root[0] else None,
            root_name=root[1],
            duration_ms=self._duration_from_values(root[2], root[3], root[4]),
            pipeline_code_version=code_version,
            pipeline_code_versions=[code_version] if code_version else [],
            trace_count=1,
        )

    def _scope_statistics(
        self,
        connection: sqlite3.Connection,
        *,
        scope: str,
        identifier: UUID,
        workflow_run_id: UUID | None,
        root_name: str,
        duration_ms: int,
        pipeline_code_version: Any,
        pipeline_code_versions: list[Any],
        trace_count: int,
    ) -> dict[str, Any]:
        value = str(identifier)
        span_column = "trace_id" if scope == "trace" else "workflow_run_id"
        event_column = span_column
        call_column = "pipeline_trace_id" if scope == "trace" else "workflow_run_id"

        stages = {
            row[0]: {"duration_ms": int(row[1] or 0), "count": int(row[2] or 0)}
            for row in connection.execute(
                f"""
                SELECT name, SUM(COALESCE(duration_ms, 0)), COUNT(*)
                  FROM pipeline_spans
                 WHERE {span_column} = ? AND kind = 'stage'
                 GROUP BY name
                """,  # noqa: S608
                (value,),
            )
        }
        model = connection.execute(
            f"""
            SELECT COUNT(*),
                   COALESCE(SUM(total_tokens), 0),
                   COALESCE(SUM(cost_micros), 0),
                   COUNT(*) FILTER (
                       WHERE status = 'succeeded' AND cost_micros IS NULL
                   ),
                   COUNT(*) FILTER (
                       WHERE status = 'succeeded' AND cost_micros IS NOT NULL
                   ),
                   COUNT(*) FILTER (
                       WHERE retry_scheduled = 1 OR provider_attempt_count > 1
                   )
              FROM model_calls
             WHERE {call_column} = ?
            """,  # noqa: S608
            (value,),
        ).fetchone()
        call_count = int(model[0] or 0)
        unpriced_count = int(model[3] or 0)
        priced_count = int(model[4] or 0)

        cache: dict[str, dict[str, Any]] = {}
        for row in connection.execute(
            f"""
            SELECT json_extract(attributes_json, '$.cache') AS cache,
                   COUNT(*) FILTER (
                       WHERE json_extract(attributes_json, '$.result') = 'hit'
                   ),
                   COUNT(*) FILTER (
                       WHERE json_extract(attributes_json, '$.result') = 'miss'
                   )
              FROM pipeline_events
             WHERE {event_column} = ? AND name = 'cache.lookup'
             GROUP BY cache
            """,  # noqa: S608
            (value,),
        ):
            if row[0] is None:
                continue
            hits, misses = int(row[1] or 0), int(row[2] or 0)
            cache[str(row[0])] = {
                "hits": hits,
                "misses": misses,
                "hit_rate": hits / (hits + misses) if hits + misses else 0.0,
            }

        audio_rows = connection.execute(
            f"""
            SELECT attributes_json, metrics_json
              FROM pipeline_spans
             WHERE {span_column} = ? AND name = 'audio.qa'
            """,  # noqa: S608
            (value,),
        ).fetchall()
        similarities: list[float] = []
        verdicts: dict[str, int] = defaultdict(int)
        for row in audio_rows:
            attributes = self._load_json(row[0])
            metrics = self._load_json(row[1])
            similarity = metrics.get("similarity_ratio")
            if isinstance(similarity, int | float):
                similarities.append(float(similarity))
            verdicts[str(attributes.get("verdict") or "unknown")] += 1

        evidence: dict[str, dict[str, Any]] = {}
        for row in connection.execute(
            f"""
            SELECT subject_id, metrics_json
              FROM pipeline_spans
             WHERE {span_column} = ? AND name = 'corpus.source'
             ORDER BY started_at
            """,  # noqa: S608
            (value,),
        ):
            if not row[0]:
                continue
            metrics = self._load_json(row[1])
            claim_count = int(metrics.get("claim_count") or 0)
            source = str(row[0])
            previous = evidence.get(source, {}).get("claim_count", 0)
            evidence[source] = {"claim_count": max(int(previous), claim_count)}

        prompts = [
            {"prompt_id": row[0], "prompt_version": row[1]}
            for row in connection.execute(
                f"""
                SELECT DISTINCT prompt_id, prompt_version
                  FROM model_calls
                 WHERE {call_column} = ?
                   AND (prompt_id IS NOT NULL OR prompt_version IS NOT NULL)
                 ORDER BY prompt_id, prompt_version
                """,  # noqa: S608
                (value,),
            )
        ]
        return {
            "scope": scope,
            "trace_id": str(identifier),
            "workflow_run_id": str(workflow_run_id) if workflow_run_id else None,
            "trace_count": trace_count,
            "root_name": root_name,
            "pipeline_code_version": pipeline_code_version,
            "pipeline_code_versions": pipeline_code_versions,
            "prompt_versions": prompts,
            "summary": {
                "duration_ms": duration_ms,
                "model_call_count": call_count,
                "retry_count": int(model[5] or 0),
                "total_tokens": int(model[1] or 0),
                "cost_micros": int(model[2] or 0) if priced_count > 0 else None,
                "priced_count": priced_count,
                "unpriced_count": unpriced_count,
            },
            "stages": stages,
            "cache_hit_rates": cache,
            "audio_qa": self._distribution(similarities, verdicts),
            "evidence_yield": evidence,
        }

    def _trace_tree(self, trace_id: UUID, *, depth: int) -> list[dict[str, Any]]:
        nodes = self.ledger.get_trace(trace_id)[:_MAX_TRACE_NODES]
        by_parent: dict[UUID | None, list[Any]] = defaultdict(list)
        ids = {node.node_id for node in nodes}
        for node in nodes:
            parent = node.parent_id if node.parent_id in ids else None
            by_parent[parent].append(node)
        for children in by_parent.values():
            children.sort(key=lambda item: item.started_at)
        now = datetime.now(UTC)

        def build(parent: UUID | None, level: int) -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            for node in by_parent.get(parent, []):
                item = node.model_dump(mode="json")
                if node.duration_ms is None:
                    ended = node.ended_at or now
                    item["duration_ms"] = max(
                        0,
                        round((ended - node.started_at).total_seconds() * 1000),
                    )
                descendants = by_parent.get(node.node_id, [])
                if level < depth:
                    item["children"] = build(node.node_id, level + 1)
                    item["truncated_children"] = 0
                else:
                    item["children"] = []
                    item["truncated_children"] = len(descendants)
                result.append(item)
            return result

        return build(None, 1)

    def _waterfall(self, trace_id: UUID) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT span_id, name, status, started_at, ended_at, duration_ms,
                       subject_type, subject_id
                  FROM pipeline_spans
                 WHERE trace_id = ? AND kind = 'stage'
                 ORDER BY started_at
                 LIMIT ?
                """,
                (str(trace_id), _MAX_WATERFALL_ROWS),
            ).fetchall()
        if not rows:
            return []
        now = datetime.now(UTC)
        starts = [self._parse_timestamp(row[3]) for row in rows]
        ends = [self._parse_timestamp(row[4]) if row[4] else now for row in rows]
        trace_start = min(starts)
        trace_end = max(ends)
        total_ms = max(1, (trace_end - trace_start).total_seconds() * 1000)
        result: list[dict[str, Any]] = []
        for row, started, ended in zip(rows, starts, ends, strict=True):
            left = (started - trace_start).total_seconds() * 1000 / total_ms * 100
            duration = max(0, (ended - started).total_seconds() * 1000)
            width = max(0.8, duration / total_ms * 100)
            item = self._safe_dict(row)
            item["duration_ms"] = round(duration)
            item["left_percent"] = min(100.0, max(0.0, left))
            item["width_percent"] = min(100.0 - left, width)
            result.append(item)
        return result

    def _select_trace(
        self,
        connection: sqlite3.Connection,
        project_id: UUID,
        requested: UUID | None,
        traces: list[dict[str, Any]],
    ) -> UUID | None:
        if requested is not None:
            found = connection.execute(
                "SELECT 1 FROM pipeline_spans WHERE project_id = ? AND trace_id = ? LIMIT 1",
                (str(project_id), str(requested)),
            ).fetchone()
            if found is None:
                raise FileNotFoundError(f"Trace not found for project: {requested}")
            return requested
        return UUID(traces[0]["trace_id"]) if traces else None

    @staticmethod
    def _delta(before: Any, after: Any) -> dict[str, Any]:
        if before is None or after is None:
            return {"before": before, "after": after, "absolute": None, "percent": None}
        absolute = after - before
        percent = absolute / before if before else None
        return {"before": before, "after": after, "absolute": absolute, "percent": percent}

    def _keyed_deltas(
        self,
        before: dict[str, dict[str, Any]],
        after: dict[str, dict[str, Any]],
        *,
        value_key: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for name in sorted(set(before) | set(after)):
            a = before.get(name, {}).get(value_key, 0)
            b = after.get(name, {}).get(value_key, 0)
            rows.append({"name": name, **self._delta(a, b)})
        return rows

    @staticmethod
    def _distribution(values: list[float], verdicts: dict[str, int]) -> dict[str, Any]:
        if not values:
            return {
                "count": 0,
                "mean_similarity": None,
                "median_similarity": None,
                "p95_similarity": None,
                "verdicts": dict(verdicts),
            }
        ordered = sorted(values)
        p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
        return {
            "count": len(values),
            "mean_similarity": mean(values),
            "median_similarity": median(values),
            "p95_similarity": ordered[p95_index],
            "verdicts": dict(verdicts),
        }

    @staticmethod
    def _trace_row(row: sqlite3.Row) -> dict[str, Any]:
        item = ObservabilityReporter._safe_dict(row)
        item["attributes"] = ObservabilityReporter._load_json(item.pop("attributes_json", "{}"))
        if item.get("duration_ms") is None and item.get("started_at"):
            started = ObservabilityReporter._parse_timestamp(str(item["started_at"]))
            ended = (
                ObservabilityReporter._parse_timestamp(str(item["ended_at"]))
                if item.get("ended_at")
                else datetime.now(UTC)
            )
            item["duration_ms"] = max(
                0,
                round((ended - started).total_seconds() * 1000),
            )
        return item

    @staticmethod
    def _event_row(row: sqlite3.Row) -> dict[str, Any]:
        item = ObservabilityReporter._safe_dict(row)
        item["attributes"] = ObservabilityReporter._load_json(item.pop("attributes_json", "{}"))
        return item

    @staticmethod
    def _export_span_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["attributes"] = ObservabilityReporter._load_json(item.pop("attributes_json", "{}"))
        item["metrics"] = ObservabilityReporter._load_json(item.pop("metrics_json", "{}"))
        return redact_value(item, store_payloads=False)

    @staticmethod
    def _export_event_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["attributes"] = ObservabilityReporter._load_json(item.pop("attributes_json", "{}"))
        return redact_value(item, store_payloads=False)

    @staticmethod
    def _export_model_call_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = ObservabilityReporter._load_json(item.pop("metadata_json", "{}"))
        return redact_value(item, store_payloads=False)

    @staticmethod
    def _safe_dict(row: sqlite3.Row | None) -> dict[str, Any]:
        return redact_value(dict(row)) if row is not None else {}

    @staticmethod
    def _load_json(value: Any) -> dict[str, Any]:
        if not value:
            return {}
        try:
            loaded = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
        return redact_value(loaded, store_payloads=True) if isinstance(loaded, dict) else {}

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _duration_from_values(started: Any, ended: Any, duration_ms: Any) -> int:
        if duration_ms is not None:
            return max(0, int(duration_ms))
        if not started:
            return 0
        start = ObservabilityReporter._parse_timestamp(str(started))
        end = ObservabilityReporter._parse_timestamp(str(ended)) if ended else datetime.now(UTC)
        return max(0, round((end - start).total_seconds() * 1000))

    def _connect(self) -> closing[sqlite3.Connection]:
        connection = sqlite3.connect(self.ledger.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA query_only=ON")
        return closing(connection)

    @staticmethod
    def _prepare_staging_directory(directory: Path) -> Path:
        if directory == directory.parent:
            raise ValueError("Observability export cannot target the filesystem root.")
        directory.parent.mkdir(parents=True, exist_ok=True)
        if directory.exists():
            if not directory.is_dir():
                raise ValueError(f"Observability export target is not a directory: {directory}")
            unexpected = sorted(
                item.name for item in directory.iterdir() if item.name not in _EXPORT_ARTIFACTS
            )
            if unexpected:
                joined = ", ".join(unexpected[:5])
                raise ValueError(
                    "Observability export requires a dedicated directory; "
                    f"unexpected existing entries: {joined}"
                )
        staging = directory.parent / f".{directory.name}.tmp-{uuid4().hex}"
        staging.mkdir()
        return staging

    @staticmethod
    def _publish_staging_directory(staging: Path, directory: Path) -> None:
        if not directory.exists():
            staging.replace(directory)
            return
        backup = directory.parent / f".{directory.name}.bak-{uuid4().hex}"
        directory.replace(backup)
        try:
            staging.replace(directory)
        except BaseException:
            backup.replace(directory)
            raise
        else:
            shutil.rmtree(backup, ignore_errors=True)

    @staticmethod
    def _write_jsonl(path: Path, rows: Any) -> int:
        count = 0
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    )
                )
                handle.write("\n")
                count += 1
        return count

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
