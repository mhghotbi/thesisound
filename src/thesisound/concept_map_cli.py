from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from thesisound.config import Settings
from thesisound.modeling import ModelError
from thesisound.services.concept_map_pipeline import (
    build_concept_map_from_path,
    concept_map_summary,
    parse_chapter_selector,
)

console = Console()


def register_concept_map_command(app: typer.Typer) -> None:
    @app.command("concept-map")
    def concept_map(
        path: Annotated[Path, typer.Argument(help="Path to a local document")],
        chapters: Annotated[
            str | None,
            typer.Option(help="Comma-separated 1-based chapter numbers, e.g. 1,3"),
        ] = None,
        rebuild: Annotated[
            bool,
            typer.Option("--rebuild", help="Ignore the cached map and rebuild"),
        ] = False,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Print JSON instead of tables"),
        ] = False,
        workspace_root: Annotated[
            Path | None,
            typer.Option(help="Override workspace directory"),
        ] = None,
    ) -> None:
        """Parse a document, build its concept map, and print a review summary."""

        settings = Settings()
        root = (workspace_root or settings.workspace_root).expanduser().resolve()
        try:
            selected = parse_chapter_selector(chapters)
            result = build_concept_map_from_path(
                path,
                workspace_root=root,
                settings=settings,
                chapters=selected,
                rebuild=rebuild,
            )
        except (FileNotFoundError, ModelError, OSError, RuntimeError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]", stderr=True)
            raise typer.Exit(code=1) from exc

        payload = concept_map_summary(result)
        if as_json:
            console.print_json(json.dumps(payload, ensure_ascii=False))
            return
        _print_tables(payload)


def _print_tables(payload: dict[str, object]) -> None:
    chapters = Table(title="Chapters")
    chapters.add_column("#")
    chapters.add_column("Title")
    chapters.add_column("Agreement")
    chapters.add_column("From")
    chapters.add_column("Minutes")
    for chapter in payload["chapters"]:  # type: ignore[index]
        chapters.add_row(
            str(chapter["number"]),
            str(chapter["title"]),
            str(chapter["detection_agreement"]),
            str(chapter["detected_from"]),
            f"{chapter['estimated_minutes']:.1f}",
        )
    console.print(chapters)

    tiers = Table(title="Cells per tier")
    tiers.add_column("Tier")
    tiers.add_column("Count")
    cells_per_tier = payload["cells_per_tier"]  # type: ignore[assignment]
    for key in sorted(cells_per_tier, key=lambda item: int(item)):
        tiers.add_row(str(key), str(cells_per_tier[key]))
    console.print(tiers)

    promoted = payload["promoted_cell_keys"]
    console.print(f"Promoted cells: {', '.join(promoted) if promoted else 'none'}")

    edges = Table(title="Edges")
    edges.add_column("Source")
    edges.add_column("Target")
    edges.add_column("Type")
    edges.add_column("By")
    for edge in payload["edges"]:  # type: ignore[index]
        edges.add_row(
            str(edge["source_key"]),
            str(edge["target_key"]),
            str(edge["type"]),
            str(edge["created_by"]),
        )
    console.print(edges)

    stats = payload["statistics"]  # type: ignore[assignment]
    console.print(
        "Statistics: "
        f"{stats['cell_count']} cells, "
        f"{stats['cross_chapter_edge_count']} cross-chapter edges, "
        f"{len(stats['orphan_cell_keys'])} orphans, "
        f"{len(stats['needs_review'])} needs_review"
    )
    estimated = payload["estimated_tokens"]  # type: ignore[assignment]
    console.print(
        "Estimated tokens: "
        f"map {estimated['map']}, cells {estimated['cells']} "
        f"(total {estimated['total']})"
    )
    warnings = payload["warnings"]
    if warnings:
        console.print("Warnings:")
        for warning in warnings:  # type: ignore[union-attr]
            console.print(f"- {warning}")
