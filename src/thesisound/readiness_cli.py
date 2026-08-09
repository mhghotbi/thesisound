from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from thesisound.config import Settings
from thesisound.services.readiness import project_readiness


def register_readiness_command(app: typer.Typer) -> None:
    @app.command("readiness")
    def readiness(
        project_id: Annotated[UUID, typer.Argument(help="Project UUID")],
        workspace_root: Annotated[
            Path | None, typer.Option(help="Override workspace directory")
        ] = None,
        as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON")] = False,
    ) -> None:
        """Slowly re-run the real stored-input gate logic; this is not a status ping."""

        root = (workspace_root or Settings().workspace_root).expanduser().resolve()
        results = project_readiness(project_id=project_id, workspace_root=root)
        if as_json:
            typer.echo(
                json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2)
            )
        else:
            table = Table(title=f"Readiness · {project_id}")
            table.add_column("Status")
            table.add_column("Gate")
            table.add_column("Actor")
            table.add_column("Detail")
            styles = {"blocked": "red", "unknown": "yellow", "not_reached": "dim", "pass": "green"}
            for result in results:
                table.add_row(
                    result.status,
                    result.label,
                    result.actor,
                    result.detail,
                    style=styles[result.status],
                )
            Console().print(table)
        if any(result.status == "blocked" for result in results):
            raise typer.Exit(code=1)
