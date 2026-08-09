from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any
from uuid import UUID

from thesisound.observability import ObservabilityLedger, redact_text, redact_value

_EXPORT_FILES = ("spans.jsonl", "events.jsonl", "model_calls.jsonl")
_TRACE_PAGE_SIZE = 10
_EVENT_PAGE_SIZE = 50
_MAX_TRACE_NODES = 1_000
_MAX_WATERFALL_ROWS = 200
_HASHED_EXPORT_KEYS = {"query", "text", "excerpt", "filename", "topic", "prompt"}


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

    def export_project(self, project_id: UUID, out_dir: Path) -> ExportResult:
        directory = out_dir.expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        queries = {
            "spans.jsonl": (
                "SELECT * FROM pipeline_spans WHERE project_id = ? ORDER BY started_at, span_id",
                (str(project_id),),
            ),
            "events.jsonl": (
                "SELECT * FROM pipeline_events WHERE project_id = ? ORDER BY occurred_at, event_id",
                (str(project_id),),
            ),
            "model_calls.jsonl": (
                "SELECT * FROM model_calls WHERE project_id = ? ORDER BY started_at, call_id",
                (str(project_id),),
            ),
        }
        counts: dict[str, int] = {}
        digests: dict[str, str] = {}

        with self._connect() as connection:
            for filename, (query, params) in queries.items():
                path = directory / filename
                rows = (self._export_row(row) for row in connection.execute(query, params))
                counts[filename] = self._write_jsonl(path, rows)
                digests[filename] = self._sha256(path)

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

        manifest = redact_value(
            {
                "format_version": 1,
                "project_id": str(project_id),
                "exported_at": datetime.now(UTC).isoformat(),
                "schema_version": int(schema_row[0]) if schema_row else None,
                "redaction": (
                    "thesisound.observability.redact_value plus hashed sensitive "
                    "free-text attributes"
                ),
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
        )
        manifest_path = directory / "manifest.json"
        self._write_json(manifest_path, manifest)
        return ExportResult(
            directory=directory,
            manifest_path=manifest_path,
            row_counts=counts,
        )

    def compare_runs(self, run_a: UUID, run_b: UUID) -> dict[str, Any]:
        with self._connect() as connection:
            trace_a = self._resolve_trace(connection, run_a)
            trace_b = self._resolve_trace(connection, run_b)
            stats_a = self._trace_statistics(connection, trace_a)
            stats_b = self._trace_statistics(connection, trace_b)

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
    ) -> dict[str, Any]:
        trace_page = max(1, trace_page)
        event_page = max(1, event_page)
        depth = max(1, min(depth, 12))
        with self._connect() as connection:
            trace_count = int(
                connection.execute(
                    "SELECT COUNT(DISTINCT trace_id) FROM pipeline_spans WHERE project_id = ?",
                    (str(project_id),),
                ).fetchone()[0]
            )
            trace_pages = max(1, math.ceil(trace_count / _TRACE_PAGE_SIZE))
            trace_page = min(trace_page, trace_pages)
            trace_rows = connection.execute(
                """
                SELECT s.trace_id, s.name, s.status, s.started_at, s.ended_at,
                       s.duration_ms, s.attributes_json
                  FROM pipeline_spans AS s
                 WHERE s.project_id = ?
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
                    "SELECT COUNT(*) FROM pipeline_events WHERE project_id = ?",
                    (str(project_id),),
                ).fetchone()[0]
            )
            event_pages = max(1, math.ceil(event_count / _EVENT_PAGE_SIZE))
            event_page = min(event_page, event_pages)
            event_rows = connection.execute(
                """
                SELECT event_id, trace_id, span_id, occurred_at, name, component,
                       level, subject_type, subject_id, attributes_json
                  FROM pipeline_events
                 WHERE project_id = ?
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
                """
                SELECT COUNT(*),
                       COUNT(*) FILTER (
                           WHERE retry_scheduled = 1 OR provider_attempt_count > 1
                       )
                  FROM model_calls WHERE project_id = ?
                """,
                (str(project_id),),
            ).fetchone()
            error_rows = connection.execute(
                """
                SELECT call_id, started_at, stage, operation, provider,
                       COALESCE(resolved_model, requested_model) AS model,
                       status, error_type, error_message
                  FROM model_calls
                 WHERE project_id = ? AND status IN ('failed', 'rejected')
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

        summary = self.ledger.project_summary(project_id)
        model_call_count = int(retry_row[0] or 0)
        retry_count = int(retry_row[1] or 0)
        return {
            "summary": summary,
            "cost_breakdown": self.ledger.cost_breakdown(project_id),
            "stage_summary": self.ledger.stage_summary(project_id)[:20],
            "cache_rates": self.ledger.cache_hit_rates(project_id),
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

    def _trace_statistics(self, connection: sqlite3.Connection, trace_id: UUID) -> dict[str, Any]:
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
        stages = {
            row[0]: {"duration_ms": int(row[1] or 0), "count": int(row[2] or 0)}
            for row in connection.execute(
                """
                SELECT name, SUM(COALESCE(duration_ms, 0)), COUNT(*)
                  FROM pipeline_spans
                 WHERE trace_id = ? AND kind = 'stage'
                 GROUP BY name
                """,
                (str(trace_id),),
            )
        }
        model = connection.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(total_tokens), 0),
                   COALESCE(SUM(cost_micros), 0),
                   COUNT(*) FILTER (WHERE status = 'succeeded' AND cost_micros IS NULL),
                   COUNT(*) FILTER (
                       WHERE retry_scheduled = 1 OR provider_attempt_count > 1
                   )
              FROM model_calls
             WHERE pipeline_trace_id = ?
            """,
            (str(trace_id),),
        ).fetchone()
        call_count = int(model[0] or 0)
        unpriced_count = int(model[3] or 0)
        priced_count = call_count - unpriced_count
        cache: dict[str, dict[str, Any]] = {}
        for row in connection.execute(
            """
            SELECT json_extract(attributes_json, '$.cache') AS cache,
                   COUNT(*) FILTER (
                       WHERE json_extract(attributes_json, '$.result') = 'hit'
                   ),
                   COUNT(*) FILTER (
                       WHERE json_extract(attributes_json, '$.result') = 'miss'
                   )
              FROM pipeline_events
             WHERE trace_id = ? AND name = 'cache.lookup'
             GROUP BY cache
            """,
            (str(trace_id),),
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
            """
            SELECT attributes_json, metrics_json
              FROM pipeline_spans
             WHERE trace_id = ? AND name = 'audio.qa'
            """,
            (str(trace_id),),
        ).fetchall()
        similarities: list[float] = []
        verdicts: dict[str, int] = defaultdict(int)
        for row in audio_rows:
            attributes = self._load_json(row[0])
            metrics = self._load_json(row[1])
            value = metrics.get("similarity_ratio")
            if isinstance(value, int | float):
                similarities.append(float(value))
            verdicts[str(attributes.get("verdict") or "unknown")] += 1
        evidence: dict[str, dict[str, Any]] = {}
        for row in connection.execute(
            """
            SELECT subject_id, metrics_json
              FROM pipeline_spans
             WHERE trace_id = ? AND name = 'corpus.source'
             ORDER BY started_at
            """,
            (str(trace_id),),
        ):
            if not row[0]:
                continue
            metrics = self._load_json(row[1])
            evidence[str(row[0])] = {"claim_count": int(metrics.get("claim_count") or 0)}
        prompts = [
            {"prompt_id": row[0], "prompt_version": row[1]}
            for row in connection.execute(
                """
                SELECT DISTINCT prompt_id, prompt_version
                  FROM model_calls
                 WHERE pipeline_trace_id = ?
                   AND (prompt_id IS NOT NULL OR prompt_version IS NOT NULL)
                 ORDER BY prompt_id, prompt_version
                """,
                (str(trace_id),),
            )
        ]
        return {
            "trace_id": str(trace_id),
            "workflow_run_id": root[0],
            "root_name": root[1],
            "pipeline_code_version": root_attributes.get("pipeline_code_version"),
            "prompt_versions": prompts,
            "summary": {
                "duration_ms": int(root[4] or 0),
                "model_call_count": call_count,
                "retry_count": int(model[4] or 0),
                "total_tokens": int(model[1] or 0),
                "cost_micros": int(model[2] or 0) if priced_count else None,
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

        def build(parent: UUID | None, level: int) -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            for node in by_parent.get(parent, []):
                item = node.model_dump(mode="json")
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
            result.append(
                {
                    **self._safe_dict(row),
                    "left_percent": min(100.0, max(0.0, left)),
                    "width_percent": min(100.0 - left, width),
                }
            )
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
    def _resolve_trace(connection: sqlite3.Connection, identifier: UUID) -> UUID:
        value = str(identifier)
        row = connection.execute(
            "SELECT trace_id FROM pipeline_spans WHERE trace_id = ? LIMIT 1", (value,)
        ).fetchone()
        if row is None:
            row = connection.execute(
                """
                SELECT trace_id FROM pipeline_spans
                 WHERE workflow_run_id = ?
                 ORDER BY started_at LIMIT 1
                """,
                (value,),
            ).fetchone()
        if row is None:
            row = connection.execute(
                """
                SELECT pipeline_trace_id FROM model_calls
                 WHERE workflow_run_id = ? AND pipeline_trace_id IS NOT NULL
                 ORDER BY started_at LIMIT 1
                """,
                (value,),
            ).fetchone()
        if row is None or row[0] is None:
            raise FileNotFoundError(f"Run or trace not found: {identifier}")
        return UUID(row[0])

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
        return item

    @staticmethod
    def _event_row(row: sqlite3.Row) -> dict[str, Any]:
        item = ObservabilityReporter._safe_dict(row)
        item["attributes"] = ObservabilityReporter._load_json(item.pop("attributes_json", "{}"))
        return item

    @staticmethod
    def _export_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for key in list(item):
            if key.endswith("_json"):
                clean_key = key.removesuffix("_json")
                item[clean_key] = ObservabilityReporter._load_json(item.pop(key))
        if item.get("error_message"):
            item["error_message"] = redact_text(str(item["error_message"]))
        return ObservabilityReporter._redact_export_value(item)

    @staticmethod
    def _redact_export_value(value: Any, *, key: str | None = None) -> Any:
        normalized_key = key.casefold().replace("-", "_") if key else None
        if normalized_key in _HASHED_EXPORT_KEYS and isinstance(value, str):
            return {
                "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                "length": len(value),
            }
        if isinstance(value, dict):
            return {
                str(item_key): ObservabilityReporter._redact_export_value(
                    item_value, key=str(item_key)
                )
                for item_key, item_value in value.items()
            }
        if isinstance(value, list | tuple):
            return [ObservabilityReporter._redact_export_value(item) for item in value]
        return redact_value(value)

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
        return redact_value(loaded) if isinstance(loaded, dict) else {}

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    def _connect(self) -> closing[sqlite3.Connection]:
        connection = sqlite3.connect(self.ledger.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA query_only=ON")
        return closing(connection)

    @staticmethod
    def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
        temporary = path.with_suffix(path.suffix + ".tmp")
        count = 0
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
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
        temporary.replace(path)
        return count

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
