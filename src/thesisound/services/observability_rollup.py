from __future__ import annotations

import sqlite3
from contextlib import closing
from uuid import UUID

from thesisound.observability import (
    CacheHitRateSummary,
    CostBreakdownRow,
    EvidenceTierSummary,
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
                       COALESCE(SUM(cost_micros) FILTER (WHERE status = 'succeeded'), 0),
                       COUNT(*) FILTER (
                           WHERE status = 'succeeded' AND cost_micros IS NULL
                       ),
                       COALESCE(SUM(cost_micros) FILTER (
                           WHERE status IN ('rejected', 'failed')
                       ), 0),
                       COUNT(*) FILTER (
                           WHERE status IN ('rejected', 'failed') AND cost_micros IS NULL
                       )
                FROM model_calls
                WHERE project_id = ?
                """,
                (str(project_id),),
            ).fetchone()
        values = row or (0,) * 15
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
            wasted_cost_micros=int(values[13] or 0),
            unpriced_wasted_count=int(values[14] or 0),
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
                       COALESCE(SUM(cost_micros) FILTER (WHERE status = 'succeeded'), 0),
                       COUNT(*) FILTER (WHERE status IN ('rejected', 'failed')),
                       COALESCE(SUM(cost_micros) FILTER (
                           WHERE status IN ('rejected', 'failed')
                       ), 0),
                       COUNT(*) FILTER (
                           WHERE status IN ('rejected', 'failed') AND cost_micros IS NULL
                       ),
                       COALESCE(SUM(total_tokens), 0)
                FROM model_calls
                WHERE project_id = ? AND status IN ('succeeded', 'rejected', 'failed')
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
                wasted_call_count=row[6],
                wasted_cost_micros=row[7],
                unpriced_wasted_count=row[8],
                total_tokens=row[9],
            )
            for row in rows
        ]

    def evidence_tier_summary(self, project_id: UUID) -> EvidenceTierSummary:
        """Return the persisted E3 measurements for one experiment arm."""

        with closing(self._connect()) as connection:
            calls = connection.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(provider_attempt_count), 0),
                       COALESCE(SUM(total_tokens) FILTER (WHERE status = 'succeeded'), 0),
                       COALESCE(SUM(total_tokens) FILTER (
                           WHERE status IN ('rejected', 'failed')
                       ), 0),
                       COALESCE(SUM(cost_micros) FILTER (WHERE status = 'succeeded'), 0),
                       COALESCE(SUM(cost_micros) FILTER (
                           WHERE status IN ('rejected', 'failed')
                       ), 0),
                       COUNT(*) FILTER (WHERE cost_micros IS NULL),
                       GROUP_CONCAT(DISTINCT COALESCE(resolved_model, requested_model)),
                       GROUP_CONCAT(DISTINCT json_extract(metadata_json, '$.model_profile'))
                  FROM model_calls
                 WHERE project_id = ? AND stage LIKE 'evidence_extraction%'
                   AND status IN ('succeeded', 'rejected', 'failed')
                """,
                (str(project_id),),
            ).fetchone()
            events = connection.execute(
                """
                SELECT COUNT(*),
                       COALESCE(SUM(json_extract(attributes_json, '$.attempt_count')), 0),
                       COALESCE(SUM(json_extract(attributes_json, '$.excerpt_failure_count')), 0),
                       COALESCE(SUM(CASE WHEN json_extract(
                           attributes_json, '$.salvaged'
                       ) THEN 1 ELSE 0 END), 0),
                       COALESCE(SUM(json_extract(attributes_json, '$.dropped_claim_count')), 0),
                       COALESCE(SUM(json_extract(attributes_json, '$.kept_claim_count')), 0),
                       COALESCE(SUM(CASE WHEN json_extract(
                           attributes_json, '$.status'
                       ) = 'extracted' THEN 1 ELSE 0 END), 0)
                  FROM pipeline_events
                 WHERE project_id = ? AND name = 'corpus.evidence_attempts'
                """,
                (str(project_id),),
            ).fetchone()
            latency_rows = connection.execute(
                """
                SELECT latency_ms FROM model_calls
                 WHERE project_id = ? AND stage LIKE 'evidence_extraction%'
                   AND latency_ms IS NOT NULL
                 ORDER BY latency_ms
                """,
                (str(project_id),),
            ).fetchall()
            unpriced_rows = connection.execute(
                """
                SELECT DISTINCT provider, COALESCE(resolved_model, requested_model), operation
                  FROM model_calls
                 WHERE project_id = ? AND stage LIKE 'evidence_extraction%'
                   AND status IN ('succeeded', 'rejected', 'failed') AND cost_micros IS NULL
                 ORDER BY provider, 2, operation
                """,
                (str(project_id),),
            ).fetchall()
        calls = calls or (0,) * 9
        events = events or (0,) * 7
        latencies = [int(row[0]) for row in latency_rows]
        return EvidenceTierSummary(
            project_id=project_id,
            resolved_model=calls[7],
            model_profile=calls[8],
            call_count=int(calls[0] or 0),
            provider_attempt_count=int(calls[1] or 0),
            delivered_tokens=int(calls[2] or 0),
            wasted_tokens=int(calls[3] or 0),
            delivered_cost_micros=int(calls[4] or 0),
            wasted_cost_micros=int(calls[5] or 0),
            unpriced_count=int(calls[6] or 0),
            block_count=int(events[0] or 0),
            validation_attempt_count=int(events[1] or 0),
            excerpt_failure_count=int(events[2] or 0),
            salvaged_block_count=int(events[3] or 0),
            dropped_claim_count=int(events[4] or 0),
            kept_claim_count=int(events[5] or 0),
            extracted_block_count=int(events[6] or 0),
            unpriced_rows=[tuple(row) for row in unpriced_rows],
            latency_p50_ms=_percentile(latencies, 0.50),
            latency_p95_ms=_percentile(latencies, 0.95),
        )

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


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    return values[min(len(values) - 1, round((len(values) - 1) * fraction))]
