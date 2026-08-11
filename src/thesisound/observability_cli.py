from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from thesisound.config import Settings
from thesisound.observability import (
    CallDetail,
    EvidenceTierSummary,
    ObservabilityLedger,
    TraceNode,
    ledger_from_settings,
)
from thesisound.services.observability_reporting import ObservabilityReporter
from thesisound.services.observability_rollup import ObservabilityRollup


def _format_cost(micros: int | None) -> str:
    if micros is None:
        return "unknown"
    return f"${micros / 1_000_000:,.4f}"


def register_observability_commands(app: typer.Typer) -> None:
    @app.command("observability")
    def project_observability(
        project_id: UUID,
        stage: str | None = typer.Option(None, help="Filter by pipeline stage."),
        status: str | None = typer.Option(None, help="Filter by call status."),
        limit: int = typer.Option(100, min=1, max=2_000),
        include_synthetic: bool = typer.Option(
            False,
            "--include-synthetic",
            help="Include test/synthetic telemetry rows (excluded by default).",
        ),
    ) -> None:
        """Show model calls, attempts, token use, latency, and failures for one project."""

        settings = Settings()
        ledger = ledger_from_settings(settings)
        rollup = ObservabilityRollup(ledger)
        summary = rollup.project_summary(project_id, include_synthetic=include_synthetic)
        console = Console()
        console.print(
            f"[bold]Project {project_id}[/bold] · calls={summary.call_count} · "
            f"attempts={summary.provider_attempt_count} · tokens={summary.total_tokens} · "
            f"latency={summary.total_latency_ms} ms"
        )
        table = Table(show_lines=False)
        table.add_column("Started")
        table.add_column("Stage")
        table.add_column("Operation")
        table.add_column("Model")
        table.add_column("Status")
        table.add_column("Attempts", justify="right")
        table.add_column("Tokens", justify="right")
        table.add_column("Latency", justify="right")
        table.add_column("Call ID")
        for call in ledger.list_calls(
            project_id,
            stage=stage,
            status=status,
            limit=limit,
            include_synthetic=include_synthetic,
        ):
            table.add_row(
                call.started_at.isoformat(timespec="seconds"),
                call.stage,
                call.operation,
                call.resolved_model or call.requested_model,
                call.status,
                str(call.provider_attempt_count),
                str(call.total_tokens or 0),
                f"{call.latency_ms or 0} ms",
                str(call.call_id),
            )
        console.print(table)

    @app.command("runs")
    def runs(
        project_id: UUID,
        limit: int = typer.Option(50, min=1, max=2_000),
        include_synthetic: bool = typer.Option(
            False,
            "--include-synthetic",
            help="Include test/synthetic telemetry rows (excluded by default).",
        ),
    ) -> None:
        """Show one aggregate row per pipeline workflow run."""

        ledger = ledger_from_settings(Settings())
        console = Console()
        table = Table(show_lines=False)
        table.add_column("Started")
        table.add_column("Kind")
        table.add_column("Status")
        table.add_column("Duration", justify="right")
        table.add_column("Calls", justify="right")
        table.add_column("Failed", justify="right")
        table.add_column("Total tokens", justify="right")
        table.add_column("Cost", justify="right")
        table.add_column("Run ID")
        for run in ledger.list_runs(
            project_id, limit=limit, include_synthetic=include_synthetic
        ):
            cost_label = (
                "unknown"
                if run.unpriced_call_count > 0 and run.priced_call_count == 0
                else _format_cost(run.total_cost_micros)
            )
            table.add_row(
                run.started_at.isoformat(timespec="seconds"),
                run.kind,
                run.status,
                f"{run.duration_ms or 0} ms",
                str(run.call_count),
                str(run.failed_call_count),
                str(run.total_tokens),
                cost_label,
                str(run.workflow_run_id),
            )
        console.print(table)

    @app.command("run-summary")
    def run_summary(run_id: UUID) -> None:
        """Print the persisted aggregate for one pipeline workflow run."""

        try:
            summary = ledger_from_settings(Settings()).run_summary(run_id)
        except FileNotFoundError as exc:
            raise typer.BadParameter(str(exc)) from exc
        Console().print_json(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False))

    @app.command("model-call")
    def model_call(
        call_id: UUID,
        show_request: bool = typer.Option(False, help="Print the redacted request artifact."),
        show_response: bool = typer.Option(False, help="Print the redacted raw response."),
        show_output: bool = typer.Option(False, help="Print the parsed output artifact."),
    ) -> None:
        """Inspect one model call and all provider/key attempts."""

        settings = Settings()
        ledger = ledger_from_settings(settings)
        detail = ledger.get_call(call_id)
        console = Console()
        _print_detail(console, detail)
        artifacts = (
            ("request", detail.request_artifact_path, show_request),
            ("raw response", detail.raw_response_artifact_path, show_response),
            ("parsed output", detail.parsed_output_artifact_path, show_output),
        )
        for label, path, enabled in artifacts:
            if enabled and path:
                console.rule(label)
                console.print_json(ledger.read_artifact(path))

    @app.command("observability-export")
    def observability_export(
        project_id: UUID,
        out: Path = typer.Option(  # noqa: B008
            ...,
            "--out",
            help="Directory for spans/events/model-calls JSONL and manifest.json.",
        ),
    ) -> None:
        """Export one project's fully redacted observability records."""

        reporter = ObservabilityReporter(ledger_from_settings(Settings()))
        try:
            result = reporter.export_project(project_id, out)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console = Console()
        table = Table(title=f"Observability export for {project_id}")
        table.add_column("File")
        table.add_column("Rows", justify="right")
        for filename, count in result.row_counts.items():
            table.add_row(filename, str(count))
        console.print(table)
        console.print(f"Manifest: [bold]{result.manifest_path}[/bold]")

    @app.command("trace")
    def trace(
        target: str = typer.Argument(
            ...,
            help="Project UUID, or the literal 'compare'.",
        ),
        run_a: UUID | None = typer.Argument(  # noqa: B008
            None,
            help="First run/trace UUID when target is 'compare'.",
        ),
        run_b: UUID | None = typer.Argument(  # noqa: B008
            None,
            help="Second run/trace UUID when target is 'compare'.",
        ),
    ) -> None:
        """Show the latest project trace, or compare two runs/traces."""

        settings = Settings()
        ledger = ledger_from_settings(settings)
        console = Console()
        if target == "compare":
            if run_a is None or run_b is None:
                raise typer.BadParameter("trace compare requires <run-a> and <run-b> UUIDs.")
            try:
                comparison = ObservabilityReporter(ledger).compare_runs(run_a, run_b)
            except FileNotFoundError as exc:
                raise typer.BadParameter(str(exc)) from exc
            _render_comparison(console, comparison)
            return
        if run_a is not None or run_b is not None:
            raise typer.BadParameter("Extra arguments are only valid for 'trace compare'.")
        try:
            project_id = UUID(target)
        except ValueError as exc:
            raise typer.BadParameter("Expected a project UUID or 'compare'.") from exc
        recent = ledger.list_recent_traces(project_id, limit=1)
        if not recent:
            console.print(f"[yellow]No recorded trace for project {project_id}.[/yellow]")
            raise typer.Exit(code=1)
        _render_trace(console, ledger, recent[0])

    @app.command("trace-show")
    def trace_show(trace_id: UUID) -> None:
        """Show one trace by ID as a span tree, model calls inline as leaves."""

        settings = Settings()
        ledger = ledger_from_settings(settings)
        console = Console()
        _render_trace(console, ledger, trace_id)

    @app.command("timeline")
    def timeline(
        project_id: UUID,
        limit: int = typer.Option(100, min=1, max=2_000),
    ) -> None:
        """Show append-only pipeline events for a project: state changes,
        cache hits, gate blocks -- newest first, across every trace."""

        settings = Settings()
        ledger = ledger_from_settings(settings)
        console = Console()
        events = ledger.list_events_by_project(project_id, limit=limit)
        if not events:
            console.print(f"[yellow]No recorded events for project {project_id}.[/yellow]")
            return
        table = Table(show_lines=False)
        table.add_column("Occurred")
        table.add_column("Level")
        table.add_column("Name")
        table.add_column("Component")
        table.add_column("Attributes")
        for event in events:
            level_style = (
                "red" if event.level == "error" else ("yellow" if event.level == "warn" else "")
            )
            table.add_row(
                event.occurred_at.isoformat(timespec="seconds"),
                f"[{level_style}]{event.level}[/{level_style}]" if level_style else event.level,
                event.name,
                event.component,
                ", ".join(f"{key}={value}" for key, value in event.attributes.items()),
            )
        console.print(table)

    @app.command("pipeline-summary")
    def pipeline_summary(
        project_id: UUID,
        include_synthetic: bool = typer.Option(
            False,
            "--include-synthetic",
            help="Include test/synthetic telemetry rows (excluded by default).",
        ),
    ) -> None:
        """Rank every recorded span name by self time (total minus children)
        across every trace for a project -- where the wall clock actually
        goes -- plus cache hit rates, the biggest cost lever in the system."""

        settings = Settings()
        ledger = ledger_from_settings(settings)
        rollup = ObservabilityRollup(ledger)
        console = Console()
        rows = rollup.stage_summary(project_id, include_synthetic=include_synthetic)
        if not rows:
            console.print(f"[yellow]No recorded spans for project {project_id}.[/yellow]")
            return
        table = Table(title=f"Stage summary for {project_id}")
        table.add_column("Name")
        table.add_column("Component")
        table.add_column("Calls", justify="right")
        table.add_column("Self", justify="right")
        table.add_column("Total", justify="right")
        table.add_column("Avg", justify="right")
        table.add_column("Errors", justify="right")
        for row in rows:
            table.add_row(
                row.name,
                row.component,
                str(row.call_count),
                f"{row.self_total_ms} ms",
                f"{row.total_ms} ms",
                f"{row.avg_ms} ms",
                str(row.error_count) if row.error_count == 0 else f"[red]{row.error_count}[/red]",
            )
        console.print(table)

        cache_rows = rollup.cache_hit_rates(
            project_id, include_synthetic=include_synthetic
        )
        if cache_rows:
            cache_table = Table(title="Cache hit rates")
            cache_table.add_column("Cache")
            cache_table.add_column("Hits", justify="right")
            cache_table.add_column("Misses", justify="right")
            cache_table.add_column("Hit rate", justify="right")
            for cache_row in cache_rows:
                cache_table.add_row(
                    cache_row.cache,
                    str(cache_row.hits),
                    str(cache_row.misses),
                    f"{cache_row.hit_rate:.0%}",
                )
            console.print(cache_table)

    @app.command("cost")
    def cost(
        project_id: UUID,
        include_synthetic: bool = typer.Option(
            False,
            "--include-synthetic",
            help="Include test/synthetic telemetry rows (excluded by default).",
        ),
    ) -> None:
        """Show total spend and a stage/provider/model breakdown for one
        project. A model with no configured price shows as unknown, never
        as a silent 0 -- see config/model-pricing.toml."""

        settings = Settings()
        ledger = ledger_from_settings(settings)
        rollup = ObservabilityRollup(ledger)
        console = Console()
        summary = rollup.project_summary(project_id, include_synthetic=include_synthetic)
        if summary.call_count == 0:
            console.print(f"[yellow]No recorded model calls for project {project_id}.[/yellow]")
            return
        priced_count = summary.succeeded_count - summary.unpriced_succeeded_count
        caveat = ""
        if summary.unpriced_succeeded_count:
            caveat = (
                f" [yellow]({summary.unpriced_succeeded_count} succeeded call(s) have no "
                "configured price and are excluded from this total)[/yellow]"
            )
        # priced_count == 0 means every succeeded call is unpriced, so the sum is
        # vacuously 0 -- show "unknown" rather than a number that looks like a real $0.
        total_display = _format_cost(summary.total_cost_micros if priced_count else None)
        console.print(f"[bold]Project {project_id}[/bold] · total cost={total_display}{caveat}")
        wasted_count = summary.failed_count + summary.rejected_count
        if wasted_count:
            wasted_priced_count = wasted_count - summary.unpriced_wasted_count
            wasted_display = _format_cost(
                summary.wasted_cost_micros if wasted_priced_count else None
            )
            wasted_caveat = ""
            if summary.unpriced_wasted_count:
                wasted_caveat = (
                    f" [yellow]({summary.unpriced_wasted_count} rejected/failed call(s) "
                    "have no configured price)[/yellow]"
                )
            console.print(f"Wasted retry/failure spend={wasted_display}{wasted_caveat}")
        rows = rollup.cost_breakdown(project_id, include_synthetic=include_synthetic)
        if not rows:
            return
        table = Table(title="Cost breakdown")
        table.add_column("Stage")
        table.add_column("Provider")
        table.add_column("Model")
        table.add_column("Calls", justify="right")
        table.add_column("Tokens", justify="right")
        table.add_column("Delivered cost", justify="right")
        table.add_column("Wasted calls", justify="right")
        table.add_column("Wasted cost", justify="right")
        for row in rows:
            cost_cell = (
                _format_cost(row.total_cost_micros)
                if row.total_cost_micros or not row.unpriced_count
                else "unknown"
            )
            if row.unpriced_count:
                cost_cell += f" [yellow](+{row.unpriced_count} unpriced)[/yellow]"
            wasted_cell = (
                _format_cost(row.wasted_cost_micros)
                if row.wasted_call_count and not row.unpriced_wasted_count
                else ("unknown" if row.wasted_call_count else "—")
            )
            if row.unpriced_wasted_count:
                wasted_cell += f" [yellow](+{row.unpriced_wasted_count} unpriced)[/yellow]"
            table.add_row(
                row.stage,
                row.provider,
                row.model,
                str(row.call_count),
                str(row.total_tokens),
                cost_cell,
                str(row.wasted_call_count),
                wasted_cell,
            )
        console.print(table)

    @app.command("evidence-tier-report")
    def evidence_tier_report(
        project_id: UUID,
        compare: UUID | None = typer.Option(  # noqa: B008
            None, help="Project ID for the strong-tier arm."
        ),
        as_json: bool = typer.Option(False, "--json", help="Render the measurement as JSON."),
    ) -> None:
        """Report the persisted E3 evidence-extraction measurements."""

        rollup = ObservabilityRollup(ledger_from_settings(Settings()))
        console = Console()
        baseline = rollup.evidence_tier_summary(project_id)
        if baseline.call_count == 0:
            console.print(
                f"[yellow]No recorded evidence-extraction calls for project {project_id}.[/yellow]"
            )
            return
        comparison = rollup.evidence_tier_summary(compare) if compare else None
        if comparison is not None and comparison.call_count == 0:
            console.print(
                f"[yellow]No recorded evidence-extraction calls for project {compare}.[/yellow]"
            )
            return
        if as_json:
            payload: dict[str, object] = {"baseline": _tier_payload(baseline)}
            if comparison is not None:
                payload["compare"] = _tier_payload(comparison)
                payload["verdict"] = _tier_verdict(baseline, comparison)[0]
            console.print_json(json.dumps(payload, ensure_ascii=False))
            return
        _render_tier_summary(console, baseline, label="A")
        if comparison is not None:
            _render_tier_summary(console, comparison, label="B")
            verdict, reason = _tier_verdict(baseline, comparison)
            _render_tier_comparison(console, baseline, comparison, verdict, reason)

    @app.command("observability-reprice")
    def observability_reprice(
        since: str | None = typer.Option(
            None,
            help="Only recompute calls started on or after this UTC date, e.g. 2026-01-01.",
        ),
    ) -> None:
        """Recompute cost_micros for already-succeeded calls against the
        current config/model-pricing.toml -- the "what-if" number. Does not
        change the audit number succeed() already persisted at call time
        unless this is run; a price row added after a call still leaves
        that call unpriced until you do."""

        settings = Settings()
        ledger = ledger_from_settings(settings)
        console = Console()
        assert ledger.cost_pricer is not None  # ledger_from_settings() always configures one
        parsed_since = _parse_since(since) if since is not None else None
        updated = ledger.reprice(ledger.cost_pricer, since=parsed_since)
        console.print(f"Repriced {updated} call(s).")


def _tier_payload(summary: EvidenceTierSummary) -> dict[str, object]:
    payload = summary.model_dump(mode="json")
    payload["excerpt_failure_rate"] = summary.excerpt_failure_rate
    payload["claims_per_kept_block"] = summary.claims_per_kept_block
    return payload


def _render_tier_summary(console: Console, summary: EvidenceTierSummary, *, label: str) -> None:
    table = Table(title=f"Evidence tier arm {label}: {summary.project_id}")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Resolved model", summary.resolved_model or "unknown")
    table.add_row("Model profile", summary.model_profile or "unknown")
    table.add_row("Model calls", str(summary.call_count))
    table.add_row("Provider attempts", str(summary.provider_attempt_count))
    table.add_row("Validation attempts", str(summary.validation_attempt_count))
    table.add_row(
        "Excerpt failures",
        _format_rate(summary.excerpt_failure_rate),
    )
    table.add_row("Blocks", str(summary.block_count))
    table.add_row("Salvaged blocks", str(summary.salvaged_block_count))
    table.add_row("Dropped claims", str(summary.dropped_claim_count))
    table.add_row("Claims / kept block", _format_ratio(summary.claims_per_kept_block))
    table.add_row("Delivered tokens", str(summary.delivered_tokens))
    table.add_row("Wasted tokens", str(summary.wasted_tokens))
    table.add_row("Delivered cost", _format_cost_or_unknown(summary.delivered_cost_micros, summary))
    table.add_row("Wasted cost", _format_cost_or_unknown(summary.wasted_cost_micros, summary))
    table.add_row("Latency p50", _format_latency(summary.latency_p50_ms))
    table.add_row("Latency p95", _format_latency(summary.latency_p95_ms))
    console.print(table)


def _render_tier_comparison(
    console: Console,
    baseline: EvidenceTierSummary,
    comparison: EvidenceTierSummary,
    verdict: str,
    reason: str,
) -> None:
    reduction = _difference(baseline.excerpt_failure_rate, comparison.excerpt_failure_rate)
    baseline_cost = baseline.delivered_cost_micros + baseline.wasted_cost_micros
    comparison_cost = comparison.delivered_cost_micros + comparison.wasted_cost_micros
    cost_ratio = comparison_cost / baseline_cost if baseline_cost else None
    yield_ratio = _ratio(comparison.claims_per_kept_block, baseline.claims_per_kept_block)
    excerpt_delta = _difference(comparison.excerpt_failure_rate, baseline.excerpt_failure_rate)
    displayed_cost_ratio = (
        cost_ratio if not baseline.unpriced_count and not comparison.unpriced_count else None
    )
    table = Table(title="E3 decision worksheet")
    table.add_column("Metric")
    table.add_column("A", justify="right")
    table.add_column("B", justify="right")
    table.add_column("Decision", justify="right")
    table.add_row(
        "Excerpt-failure rate",
        _format_rate(baseline.excerpt_failure_rate),
        _format_rate(comparison.excerpt_failure_rate),
        f"Δ = {_format_percentage_points(excerpt_delta)}; "
        + _pass_fail(reduction is not None and reduction > 0.15, "threshold > 15 pp"),
    )
    table.add_row(
        "Total cost",
        _format_cost(baseline_cost) if not baseline.unpriced_count else "unknown",
        _format_cost(comparison_cost) if not comparison.unpriced_count else "unknown",
        f"ratio = {_format_ratio(displayed_cost_ratio, suffix='×')}; "
        + _pass_fail(cost_ratio is not None and cost_ratio <= 1.2, "threshold <= 1.20×"),
    )
    table.add_row(
        "Claim yield / block",
        _format_ratio(baseline.claims_per_kept_block),
        _format_ratio(comparison.claims_per_kept_block),
        f"ratio = {_format_ratio(yield_ratio, suffix='×')}",
    )
    table.add_row(
        "Latency p50",
        _format_latency(baseline.latency_p50_ms),
        _format_latency(comparison.latency_p50_ms),
        "context only",
    )
    console.print(table)
    console.print(f"[bold]verdict: {verdict}[/bold]" + (f" ({reason})" if reason else ""))


def _tier_verdict(
    baseline: EvidenceTierSummary, comparison: EvidenceTierSummary
) -> tuple[str, str]:
    if baseline.unpriced_count or comparison.unpriced_count:
        missing = sorted(set(baseline.unpriced_rows + comparison.unpriced_rows))
        detail = ", ".join("/".join(row) for row in missing)
        return "undecidable", f"missing price rows: {detail}"
    reduction = _difference(baseline.excerpt_failure_rate, comparison.excerpt_failure_rate)
    baseline_cost = baseline.delivered_cost_micros + baseline.wasted_cost_micros
    comparison_cost = comparison.delivered_cost_micros + comparison.wasted_cost_micros
    if reduction is None or baseline_cost == 0:
        return "undecidable", "insufficient priced measurements"
    if reduction > 0.15 and comparison_cost / baseline_cost <= 1.2:
        return "switch", ""
    return "keep", ""


def _format_cost_or_unknown(value: int, summary: EvidenceTierSummary) -> str:
    return "unknown" if summary.unpriced_count else _format_cost(value)


def _format_rate(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.1%}"


def _format_percentage_points(value: float | None) -> str:
    return "unknown" if value is None else f"{value * 100:+.1f} pp"


def _format_ratio(value: float | None, *, suffix: str = "") -> str:
    return "unknown" if value is None else f"{value:.2f}{suffix}"


def _format_latency(value: int | None) -> str:
    return "unknown" if value is None else f"{value} ms"


def _difference(before: float | None, after: float | None) -> float | None:
    return None if before is None or after is None else before - after


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _pass_fail(passed: bool, threshold: str) -> str:
    return f"{'PASS' if passed else 'FAIL'} ({threshold})"


def _display_metric(name: str, value: object) -> str:
    if value is None:
        return "unknown"
    if name == "cost_micros":
        return _format_cost(int(value))
    if name == "duration_ms":
        return f"{int(value)} ms"
    if name == "hit_rate" or name.endswith("similarity"):
        return f"{float(value):.2%}"
    return str(value)


def _render_delta_table(
    console: Console,
    title: str,
    rows: list[dict[str, object]],
    *,
    metric_name: str,
) -> None:
    if not rows:
        return
    table = Table(title=title)
    table.add_column("Name")
    table.add_column("A", justify="right")
    table.add_column("B", justify="right")
    table.add_column("Delta", justify="right")
    table.add_column("Delta %", justify="right")
    for row in rows:
        percent = row.get("percent")
        display_metric = str(row["name"]) if metric_name == "summary" else metric_name
        table.add_row(
            str(row["name"]),
            _display_metric(display_metric, row.get("before")),
            _display_metric(display_metric, row.get("after")),
            _display_metric(display_metric, row.get("absolute")),
            "unknown" if percent is None else f"{float(percent):+.1%}",
        )
    console.print(table)


def _render_comparison(console: Console, comparison: dict[str, object]) -> None:
    run_a = comparison["run_a"]
    run_b = comparison["run_b"]
    assert isinstance(run_a, dict)
    assert isinstance(run_b, dict)
    console.print(
        f"[bold]A[/bold] {run_a['trace_id']} · code="
        f"{run_a.get('pipeline_code_version') or 'unknown'}"
    )
    console.print(
        f"[bold]B[/bold] {run_b['trace_id']} · code="
        f"{run_b.get('pipeline_code_version') or 'unknown'}"
    )
    console.print(
        "Prompt versions A: " + json.dumps(run_a.get("prompt_versions", []), ensure_ascii=False)
    )
    console.print(
        "Prompt versions B: " + json.dumps(run_b.get("prompt_versions", []), ensure_ascii=False)
    )

    summary = comparison["summary"]
    assert isinstance(summary, dict)
    summary_rows = [
        {"name": name, **delta} for name, delta in summary.items() if isinstance(delta, dict)
    ]
    _render_delta_table(
        console,
        "Run summary",
        summary_rows,
        metric_name="summary",
    )
    _render_delta_table(
        console,
        "Stage durations",
        comparison["stages"],
        metric_name="duration_ms",
    )
    _render_delta_table(
        console,
        "Cache hit rates",
        comparison["cache_hit_rates"],
        metric_name="hit_rate",
    )

    audio = comparison["audio_qa"]
    assert isinstance(audio, dict)
    audio_table = Table(title="Audio QA score distribution")
    audio_table.add_column("Metric")
    audio_table.add_column("A", justify="right")
    audio_table.add_column("B", justify="right")
    for metric in (
        "count",
        "mean_similarity",
        "median_similarity",
        "p95_similarity",
        "verdicts",
    ):
        audio_table.add_row(
            metric,
            _display_metric(metric, audio["a"].get(metric)),
            _display_metric(metric, audio["b"].get(metric)),
        )
    console.print(audio_table)
    _render_delta_table(
        console,
        "Evidence yield per source",
        comparison["evidence_yield"],
        metric_name="claim_count",
    )


def _parse_since(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"Invalid date {value!r}, expected e.g. 2026-01-01.") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _render_trace(console: Console, ledger: ObservabilityLedger, trace_id: UUID) -> None:
    nodes = ledger.get_trace(trace_id)
    if not nodes:
        console.print(f"[yellow]Trace {trace_id} has no recorded spans.[/yellow]")
        raise typer.Exit(code=1)
    children: dict[UUID | None, list[TraceNode]] = defaultdict(list)
    for node in nodes:
        children[node.parent_id].append(node)
    console.print(f"[bold]Trace {trace_id}[/bold] · {len(nodes)} nodes")
    tree = Tree("trace")
    for root in sorted(children[None], key=lambda item: item.started_at):
        _add_trace_branch(tree, root, children)
    console.print(tree)


def _add_trace_branch(
    parent_branch: Tree,
    node: TraceNode,
    children: dict[UUID | None, list[TraceNode]],
) -> None:
    status_style = {
        "error": "red",
        "ok": "green",
        "succeeded": "green",
        "blocked": "yellow",
        "interrupted": "yellow",
        "running": "cyan",
    }.get(node.status, "")
    duration = f"{node.duration_ms} ms" if node.duration_ms is not None else "…"
    marker = "🤖" if node.node_source == "model_call" else "▸"
    label = f"{marker} {node.name} [{status_style}]{node.status}[/{status_style}] ({duration})"
    branch = parent_branch.add(label)
    for child in sorted(children.get(node.node_id, []), key=lambda item: item.started_at):
        _add_trace_branch(branch, child, children)


def _print_detail(console: Console, detail: CallDetail) -> None:
    call = detail.call
    console.print_json(
        json.dumps(
            {
                "call": call.model_dump(mode="json"),
                "prompt_id": detail.prompt_id,
                "prompt_version": detail.prompt_version,
                "workflow_run_id": detail.workflow_run_id,
                "parent_call_id": detail.parent_call_id,
                "timeout_ms": detail.timeout_ms,
                "grounding_mode": detail.grounding_mode,
                "retry_scheduled": detail.retry_scheduled,
                "retry_reason": detail.retry_reason,
                "backoff_ms": detail.backoff_ms,
                "artifacts": {
                    "request": detail.request_artifact_path,
                    "raw_response": detail.raw_response_artifact_path,
                    "parsed_output": detail.parsed_output_artifact_path,
                },
                "metadata": detail.metadata,
            },
            ensure_ascii=False,
            default=str,
        )
    )
    table = Table(title="Provider attempts")
    table.add_column("#", justify="right")
    table.add_column("Credential")
    table.add_column("Key")
    table.add_column("Status")
    table.add_column("HTTP")
    table.add_column("Latency", justify="right")
    table.add_column("Retry reason")
    table.add_column("Error")
    for attempt in detail.attempts:
        table.add_row(
            str(attempt.provider_attempt),
            attempt.credential_type or "-",
            (
                f"slot {attempt.key_slot} / {attempt.key_fingerprint}"
                if attempt.key_slot
                else attempt.key_fingerprint or "-"
            ),
            attempt.status,
            str(attempt.http_status or "-"),
            f"{attempt.latency_ms} ms",
            attempt.retry_reason or "-",
            attempt.error_type or "-",
        )
    console.print(table)
