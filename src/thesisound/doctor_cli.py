from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from thesisound.config import Settings
from thesisound.services.runtime_preflight import RuntimePreflight


def register_doctor_command(app: typer.Typer) -> None:
    @app.command("doctor")
    def doctor() -> None:
        """Check local prerequisites before running the live end-to-end pipeline."""

        checks = RuntimePreflight(Settings()).run("full")
        table = Table(title="Thesisound runtime preflight")
        table.add_column("Status")
        table.add_column("Check")
        table.add_column("Details")
        labels = {"pass": "PASS", "warning": "WARN", "fail": "FAIL"}
        styles = {"pass": "green", "warning": "yellow", "fail": "red"}
        for check in checks:
            table.add_row(
                f"[{styles[check.status]}]{labels[check.status]}[/]",
                check.label,
                check.detail,
            )
        console = Console()
        console.print(table)
        if any(check.blocking for check in checks):
            raise typer.Exit(code=1)
