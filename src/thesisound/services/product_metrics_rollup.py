"""Recomputable daily product-metric rollups over the catalogue."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

from thesisound.product_metrics.catalogue import CATALOGUE, MetricDefinition
from thesisound.product_metrics.store import ProductEventStore


class ProductMetricsRollup:
    """Iterate the catalogue, upsert product_metric_daily. Idempotent (D8)."""

    def __init__(self, store: ProductEventStore) -> None:
        self.database_path = store.database_path

    def compute(self, *, since: date | None = None) -> int:
        """Recompute all catalogue metrics. Returns number of rows upserted."""

        computed_at = datetime.now(UTC).isoformat()
        since_text = since.isoformat() if since else None
        upserted = 0
        with closing(self._connect_readonly()) as reader:
            results: list[tuple[MetricDefinition, list[sqlite3.Row]]] = []
            reader.row_factory = sqlite3.Row
            for metric in CATALOGUE:
                rows = reader.execute(metric.sql).fetchall()
                results.append((metric, rows))

        with closing(self._connect_write()) as writer, writer:
            for metric, rows in results:
                if since_text is not None:
                    writer.execute(
                        """
                        DELETE FROM product_metric_daily
                         WHERE metric_key = ? AND day >= ?
                        """,
                        (metric.key, since_text),
                    )
                else:
                    writer.execute(
                        "DELETE FROM product_metric_daily WHERE metric_key = ?",
                        (metric.key,),
                    )
                for row in rows:
                    day = str(row["day"] or "")
                    if not day:
                        continue
                    if since_text is not None and day < since_text:
                        continue
                    value = row["value"]
                    if value is None:
                        continue
                    writer.execute(
                        """
                        INSERT INTO product_metric_daily(
                            metric_key, day, dimension_json, value,
                            numerator, denominator, computed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(metric_key, day, dimension_json) DO UPDATE SET
                            value = excluded.value,
                            numerator = excluded.numerator,
                            denominator = excluded.denominator,
                            computed_at = excluded.computed_at
                        """,
                        (
                            metric.key,
                            day,
                            str(row["dimension_json"] or "{}"),
                            float(value),
                            None if row["numerator"] is None else float(row["numerator"]),
                            None if row["denominator"] is None else float(row["denominator"]),
                            computed_at,
                        ),
                    )
                    upserted += 1
        return upserted

    def list_metrics(
        self,
        *,
        metric_key: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        params: list[object] = []
        if metric_key is not None:
            clauses.append("metric_key = ?")
            params.append(metric_key)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT metric_key, day, dimension_json, value, numerator, denominator, computed_at
              FROM product_metric_daily
              {where}
             ORDER BY day DESC, metric_key
             LIMIT ?
        """
        params.append(limit)
        with closing(self._connect_readonly()) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [
            {
                "metric_key": row[0],
                "day": row[1],
                "dimension_json": row[2],
                "value": row[3],
                "numerator": row[4],
                "denominator": row[5],
                "computed_at": row[6],
            }
            for row in rows
        ]

    def _connect_readonly(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True, timeout=30)
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA query_only=ON")
        return connection

    def _connect_write(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection


def rollup_from_path(database_path: Path, *, since: date | None = None) -> int:
    store = ProductEventStore(database_path)
    return ProductMetricsRollup(store).compute(since=since)
