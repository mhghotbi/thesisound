from __future__ import annotations

import json
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from thesisound.config import Settings
from thesisound.observability import CallDetail, ledger_from_settings


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
