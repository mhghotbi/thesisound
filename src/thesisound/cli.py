from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from thesisound.adapters.parsers.docling_adapter import (
    DoclingParser,
    DoclingUnavailableError,
    DocumentParseError,
)
from thesisound.config import Settings
from thesisound.domain import Project
from thesisound.pipeline import WorkspaceStore
from thesisound.services.document_inspector import inspect_document
from thesisound.services.parse_quality import assess_parse_quality

app = typer.Typer(no_args_is_help=True, help="Thesisound local development CLI")
console = Console()

WorkspaceRootOption = Annotated[
    Path | None,
    typer.Option(help="Override workspace directory"),
]
DocumentPathArgument = Annotated[
    Path,
    typer.Argument(help="Path to a local document"),
]
OutputOption = Annotated[
    Path | None,
    typer.Option("--output", "-o", help="Write JSON output to this path"),
]


def _store(workspace_root: Path | None = None) -> WorkspaceStore:
    settings = Settings()
    root = workspace_root or settings.workspace_root
    return WorkspaceStore(root)


def _emit_json(payload: object, output: Path | None) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if output is None:
        console.print_json(rendered)
        return
    resolved = output.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(rendered + "\n", encoding="utf-8")
    console.print(f"Wrote [bold]{resolved}[/bold]")


@app.command()
def init(
    topic: Annotated[
        str,
        typer.Argument(help="Topic, question, author, book, or short text"),
    ],
    workspace_root: WorkspaceRootOption = None,
) -> None:
    """Create a local project workspace without calling external providers."""

    project = Project(raw_input=topic)
    path = _store(workspace_root).save_project(project)
    console.print(f"Created project [bold]{project.project_id}[/bold]")
    console.print(f"State: {project.state}")
    console.print(f"Manifest: {path}")


@app.command()
def status(
    project_id: Annotated[UUID, typer.Argument()],
    workspace_root: WorkspaceRootOption = None,
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
    project_id: Annotated[UUID, typer.Argument()],
    workspace_root: WorkspaceRootOption = None,
) -> None:
    """Print the complete project JSON for debugging and prompt development."""

    project = _store(workspace_root).load_project(project_id)
    console.print_json(json.dumps(project.model_dump(mode="json"), ensure_ascii=False))


@app.command("inspect")
def inspect_source(
    path: DocumentPathArgument,
    output: OutputOption = None,
) -> None:
    """Inspect file identity, PDF text coverage, encryption, and layout signals."""

    inspection = inspect_document(path)
    _emit_json(inspection.model_dump(mode="json"), output)


@app.command("parse")
def parse_source(
    path: DocumentPathArgument,
    parser: Annotated[
        str,
        typer.Option(help="Parser adapter to use; currently only 'docling'"),
    ] = "docling",
    output: OutputOption = None,
) -> None:
    """Parse a document, normalize blocks, and run deterministic quality gates."""

    if parser != "docling":
        raise typer.BadParameter("Only the 'docling' parser is implemented.", param_hint="--parser")

    inspection = inspect_document(path)
    try:
        parsed = DoclingParser().parse(path, inspection)
    except (DoclingUnavailableError, DocumentParseError) as exc:
        console.print(f"[red]{exc}[/red]", stderr=True)
        raise typer.Exit(code=1) from exc

    report = assess_parse_quality(inspection, parsed)
    payload = {
        "inspection": inspection.model_dump(mode="json"),
        "parsed": parsed.model_dump(mode="json"),
        "quality": report.model_dump(mode="json"),
    }
    _emit_json(payload, output)
    if not report.safe_for_claim_extraction:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
