from __future__ import annotations

import json
from collections import defaultdict
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from thesisound.config import Settings
from thesisound.observability import (
    CallDetail,
    ObservabilityLedger,
    TraceNode,
    ledger_from_settings,
)


def register_observability_commands(app: typer.Typer) -> None:
    @app.command("observability")
    def project_observability(
        project_id: UUID,
        stage: str | None = typer.Option(None, help="Filter by pipeline stage."),
        status: str | None = typer.Option(None, help="Filter by call status."),
        limit: int = typer.Option(100, min=1, max=2_000),
    ) -> None:
        """Show model calls, attempts, token use, latency, and failures for one project."""

        settings = Settings()
        ledger = ledger_from_settings(settings)
        summary = ledger.project_summary(project_id)
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
        for call in ledger.list_calls(project_id, stage=stage, status=status, limit=limit):
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

    @app.command("trace")
    def trace(project_id: UUID) -> None:
        """Show the most recent trace for a project as a span tree, model
        calls inline as leaves."""

        settings = Settings()
        ledger = ledger_from_settings(settings)
        console = Console()
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
            level_style = "red" if event.level == "error" else (
                "yellow" if event.level == "warn" else ""
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
    def pipeline_summary(project_id: UUID) -> None:
        """Rank every recorded span name by total time spent, across every
        trace for a project -- where the wall clock actually goes."""

        settings = Settings()
        ledger = ledger_from_settings(settings)
        console = Console()
        rows = ledger.stage_summary(project_id)
        if not rows:
            console.print(f"[yellow]No recorded spans for project {project_id}.[/yellow]")
            return
        table = Table(title=f"Stage summary for {project_id}")
        table.add_column("Name")
        table.add_column("Component")
        table.add_column("Calls", justify="right")
        table.add_column("Total", justify="right")
        table.add_column("Avg", justify="right")
        table.add_column("Errors", justify="right")
        for row in rows:
            table.add_row(
                row.name,
                row.component,
                str(row.call_count),
                f"{row.total_ms} ms",
                f"{row.avg_ms} ms",
                str(row.error_count) if row.error_count == 0 else f"[red]{row.error_count}[/red]",
            )
        console.print(table)


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
