from __future__ import annotations

import sqlite3
from contextlib import closing
from uuid import UUID

from thesisound.observability import (
    CacheHitRateSummary,
    CostBreakdownRow,
    ObservabilityLedger,
    ProjectUsageSummary,
    StageSummary,
)


class ObservabilityRollup:
    """Read-only derived metrics over the observability ledger.

    The ledger remains a persistence boundary. Aggregation SQL lives here so
    CLI and web reporting share definitions without turning the store itself
    into an analytics service.
    """

    def __init__(self, ledger: ObservabilityLedger) -> None:
        self.database_path = ledger.database_path

    def project_summary(self, project_id: UUID) -> ProjectUsageSummary:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE status = 'succeeded'),
                       COUNT(*) FILTER (WHERE status = 'failed'),
                       COUNT(*) FILTER (WHERE status = 'rejected'),
                       COALESCE(SUM(provider_attempt_count), 0),
                       COALESCE(SUM(input_tokens), 0),
                       COALESCE(SUM(output_tokens), 0),
                       COALESCE(SUM(thinking_tokens), 0),
                       COALESCE(SUM(cached_tokens), 0),
                       COALESCE(SUM(total_tokens), 0),
                       COALESCE(SUM(latency_ms), 0),
                       COALESCE(SUM(cost_micros), 0),
                       COUNT(*) FILTER (
                           WHERE status = 'succeeded' AND cost_micros IS NULL
                       )
                FROM model_calls
                WHERE project_id = ?
                """,
                (str(project_id),),
            ).fetchone()
        values = row or (0,) * 13
        return ProjectUsageSummary(
            project_id=project_id,
            call_count=int(values[0] or 0),
            succeeded_count=int(values[1] or 0),
            failed_count=int(values[2] or 0),
            rejected_count=int(values[3] or 0),
            provider_attempt_count=int(values[4] or 0),
            input_tokens=int(values[5] or 0),
            output_tokens=int(values[6] or 0),
            thinking_tokens=int(values[7] or 0),
            cached_tokens=int(values[8] or 0),
            total_tokens=int(values[9] or 0),
            total_latency_ms=int(values[10] or 0),
            total_cost_micros=int(values[11] or 0),
            unpriced_succeeded_count=int(values[12] or 0),
        )

    def stage_summary(self, project_id: UUID) -> list[StageSummary]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                WITH child_time AS (
                    SELECT parent_span_id AS parent, SUM(duration_ms) AS ms
                      FROM pipeline_spans
                     WHERE project_id = ? AND parent_span_id IS NOT NULL
                     GROUP BY parent_span_id
                )
                SELECT s.name, s.component,
                       COUNT(*),
                       COALESCE(SUM(s.duration_ms), 0),
                       MAX(0, COALESCE(SUM(s.duration_ms - COALESCE(c.ms, 0)), 0)),
                       COUNT(*) FILTER (WHERE s.status = 'error')
                  FROM pipeline_spans s
                  LEFT JOIN child_time c ON c.parent = s.span_id
                 WHERE s.project_id = ?
                 GROUP BY s.name, s.component
                 ORDER BY 5 DESC
                """,
                (str(project_id), str(project_id)),
            ).fetchall()
        return [
            StageSummary(
                name=row[0],
                component=row[1],
                call_count=row[2],
                total_ms=row[3],
                avg_ms=round(row[3] / row[2]) if row[2] else 0,
                self_total_ms=row[4],
                self_avg_ms=round(row[4] / row[2]) if row[2] else 0,
                error_count=row[5],
            )
            for row in rows
        ]

    def cost_breakdown(self, project_id: UUID) -> list[CostBreakdownRow]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT stage, provider, COALESCE(resolved_model, requested_model),
                       COUNT(*),
                       COUNT(*) FILTER (
                           WHERE status = 'succeeded' AND cost_micros IS NULL
                       ),
                       COALESCE(SUM(cost_micros), 0),
                       COALESCE(SUM(total_tokens), 0)
                FROM model_calls
                WHERE project_id = ? AND status = 'succeeded'
                GROUP BY stage, provider, COALESCE(resolved_model, requested_model)
                ORDER BY SUM(cost_micros) DESC
                """,
                (str(project_id),),
            ).fetchall()
        return [
            CostBreakdownRow(
                stage=row[0],
                provider=row[1],
                model=row[2],
                call_count=row[3],
                unpriced_count=row[4],
                total_cost_micros=row[5],
                total_tokens=row[6],
            )
            for row in rows
        ]

    def cache_hit_rates(self, project_id: UUID) -> list[CacheHitRateSummary]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT json_extract(attributes_json, '$.cache') AS cache,
                       COUNT(*) FILTER (
                           WHERE json_extract(attributes_json, '$.result') = 'hit'
                       ),
                       COUNT(*) FILTER (
                           WHERE json_extract(attributes_json, '$.result') = 'miss'
                       )
                FROM pipeline_events
                WHERE project_id = ? AND name = 'cache.lookup'
                GROUP BY cache
                ORDER BY cache
                """,
                (str(project_id),),
            ).fetchall()
        return [
            CacheHitRateSummary(cache=row[0], hits=row[1], misses=row[2])
            for row in rows
            if row[0] is not None
        ]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA query_only=ON")
        return connection
