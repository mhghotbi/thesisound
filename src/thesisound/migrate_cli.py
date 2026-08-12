from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from thesisound.config import Settings
from thesisound.services.evidence_artifact_migration import migrate_evidence_artifacts

migrate_app = typer.Typer(no_args_is_help=True, help="Rewrite stored artifacts to current schemas")


def register_migrate_commands(app: typer.Typer) -> None:
    app.add_typer(migrate_app, name="migrate")


@migrate_app.command("evidence-artifacts")
def migrate_evidence_artifacts_command(
    project: Annotated[
        UUID | None,
        typer.Option("--project", help="Limit migration to one project UUID"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--apply",
            help="Report changes without writing (default) or rewrite artifacts.",
        ),
    ] = True,
    workspace_root: Annotated[
        Path | None,
        typer.Option(help="Override workspace directory"),
    ] = None,
) -> None:
    """Lift drifted BlockEvidenceExtraction artifacts to schema_version 2."""

    root = (workspace_root or Settings().workspace_root).expanduser().resolve()
    report = migrate_evidence_artifacts(
        workspace_root=root,
        project_id=project,
        dry_run=dry_run,
    )
    table = Table(
        title=(
            "Evidence artifact migration (dry-run)"
            if report.dry_run
            else "Evidence artifact migration (applied)"
        )
    )
    table.add_column("Project")
    table.add_column("Source")
    table.add_column("As-is", justify="right")
    table.add_column("Upgraded", justify="right")
    table.add_column("Unfixable", justify="right")
    for item in report.sources:
        table.add_row(
            str(item.project_id)[:8],
            str(item.source_id)[:8],
            str(item.as_is),
            str(item.upgraded),
            str(item.unfixable),
        )
    table.add_row(
        "TOTAL",
        "",
        str(report.as_is),
        str(report.upgraded),
        str(report.unfixable),
        style="bold",
    )
    Console().print(table)
    if report.unfixable:
        raise typer.Exit(code=1)
