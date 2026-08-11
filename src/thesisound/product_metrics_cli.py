"""CLI for product metrics rollup and inspection."""

from __future__ import annotations

from datetime import date

import typer
from rich.console import Console
from rich.table import Table

from thesisound.config import Settings
from thesisound.observability import ledger_from_settings
from thesisound.product_metrics.store import ProductEventStore
from thesisound.services.product_metrics_rollup import ProductMetricsRollup

console = Console()
metrics_app = typer.Typer(no_args_is_help=True, help="Product metrics rollup and inspection")


def register_product_metrics_commands(app: typer.Typer) -> None:
    app.add_typer(metrics_app, name="metrics")


@metrics_app.command("rollup")
def metrics_rollup(
    since: str | None = typer.Option(
        None,
        "--since",
        help="Recompute from this YYYY-MM-DD inclusive.",
    ),
) -> None:
    """Recompute product_metric_daily from raw product_events."""

    settings = Settings()
    # Ensure ledger migrations (including product_events) have run.
    ledger_from_settings(settings)
    since_date = date.fromisoformat(since) if since else None
    store = ProductEventStore(settings.resolved_observability_database_path)
    count = ProductMetricsRollup(store).compute(since=since_date)
    console.print(f"Upserted {count} product_metric_daily row(s).")


@metrics_app.command("show")
def metrics_show(
    metric: str | None = typer.Option(None, "--metric", help="Filter by metric key."),
    limit: int = typer.Option(50, min=1, max=2_000),
) -> None:
    """Show rolled-up product metrics."""

    settings = Settings()
    ledger_from_settings(settings)
    store = ProductEventStore(settings.resolved_observability_database_path)
    rows = ProductMetricsRollup(store).list_metrics(metric_key=metric, limit=limit)
    table = Table(show_lines=False)
    table.add_column("Day")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_column("Num", justify="right")
    table.add_column("Den", justify="right")
    table.add_column("Dims")
    for row in rows:
        table.add_row(
            str(row["day"]),
            str(row["metric_key"]),
            f"{row['value']:.4g}" if row["value"] is not None else "",
            "" if row["numerator"] is None else f"{row['numerator']:.4g}",
            "" if row["denominator"] is None else f"{row['denominator']:.4g}",
            str(row["dimension_json"] or "{}"),
        )
    console.print(table)
