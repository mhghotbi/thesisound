from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from thesisound.config import Settings
from thesisound.domain import Project
from thesisound.pipeline import WorkspaceStore

app = typer.Typer(no_args_is_help=True, help="Thesisound local development CLI")
console = Console()


def _store(workspace_root: Path | None = None) -> WorkspaceStore:
    settings = Settings()
    root = workspace_root or settings.workspace_root
    return WorkspaceStore(root)


@app.command()
def init(
    topic: str = typer.Argument(..., help="Topic, question, author, book, or short text"),
    workspace_root: Path | None = typer.Option(None, help="Override workspace directory"),
) -> None:
    """Create a local project workspace without calling external providers."""

    project = Project(raw_input=topic)
    path = _store(workspace_root).save_project(project)
    console.print(f"Created project [bold]{project.project_id}[/bold]")
    console.print(f"State: {project.state}")
    console.print(f"Manifest: {path}")


@app.command()
def status(
    project_id: UUID = typer.Argument(...),
    workspace_root: Path | None = typer.Option(None),
) -> None:
    """Show the current local project state."""

    project = _store(workspace_root).load_project(project_id)
    table = Table(title=f"Thesisound project {project.project_id}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Input", project.raw_input)
    table.add_row("State", project.state.value)
    table.add_row("Created", project.created_at.isoformat())
    table.add_row("Updated", project.updated_at.isoformat())
    table.add_row("Sources", str(len(project.sources)))
    table.add_row("Has brief", str(project.brief is not None))
    table.add_row("Has episode plan", str(project.episode_plan is not None))
    table.add_row("Has script", str(project.script is not None))
    table.add_row("Last error", project.last_error or "-")
    console.print(table)


@app.command("dump")
def dump_project(
    project_id: UUID = typer.Argument(...),
    workspace_root: Path | None = typer.Option(None),
) -> None:
    """Print the complete project JSON for debugging and prompt development."""

    project = _store(workspace_root).load_project(project_id)
    console.print_json(json.dumps(project.model_dump(mode="json"), ensure_ascii=False))


if __name__ == "__main__":
    app()
