
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from thesisound.adapters.parsers.local_ocr_adapter import LocalOcrParser
from thesisound.services.document_inspector import inspect_document
from thesisound.services.ocr_model_registry import OcrModelRegistry
from thesisound.services.parse_quality import assess_parse_quality

console = Console()
models_app = typer.Typer(no_args_is_help=True, help="Provision and verify offline OCR models")


def register_model_commands(app: typer.Typer) -> None:
    app.add_typer(models_app, name="models")


@models_app.command("list")
def list_models() -> None:
    registry = OcrModelRegistry.from_environment()
    table = Table(title="Thesisound OCR model bundle")
    table.add_column("Model")
    table.add_column("Role")
    table.add_column("Required")
    table.add_column("Revision")
    table.add_column("Status")
    specs = registry.load_lock().by_name()
    for name, spec in specs.items():
        result = registry.verify(name)
        table.add_row(name, spec.role, str(spec.required), spec.revision, result.status)
    console.print(table)


@models_app.command("verify")
def verify_models(
    allow_missing: Annotated[
        bool,
        typer.Option("--allow-missing", help="Treat absent weights as valid in code-only CI."),
    ] = False,
) -> None:
    registry = OcrModelRegistry.from_environment()
    results = registry.verify_all()
    table = Table(title="OCR model integrity")
    table.add_column("Status")
    table.add_column("Model")
    table.add_column("Detail")
    for result in results:
        table.add_row(result.status.upper(), result.name, result.detail)
    console.print(table)
    failing = [
        result
        for result in results
        if result.status in {"corrupt", "invalid_lock"}
        or (result.status == "missing" and not allow_missing)
    ]
    if failing:
        raise typer.Exit(code=1)


@models_app.command("provision")
def provision_models(
    models: Annotated[
        str | None,
        typer.Option("--models", help="Comma-separated model names; default provisions all."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Replace verified local snapshots.")
    ] = False,
) -> None:
    selected = [item.strip() for item in models.split(",") if item.strip()] if models else None
    registry = OcrModelRegistry.from_environment()
    paths = registry.provision(selected, force=force)
    for path in paths:
        console.print(f"Provisioned [bold]{path}[/bold]")
    verify_models(allow_missing=False)


@models_app.command("parse")
def parse_with_local_ocr(
    path: Annotated[Path, typer.Argument(help="PDF or image to process fully offline")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the ingestion result JSON here."),
    ] = None,
    enable_vlm: Annotated[
        bool,
        typer.Option("--enable-vlm/--no-vlm", help="Allow on-demand PaddleOCR-VL fallback."),
    ] = False,
) -> None:
    inspection = inspect_document(path)
    parser = LocalOcrParser(enable_vlm=enable_vlm)
    parsed = parser.parse(path, inspection)
    quality = assess_parse_quality(inspection, parsed)
    payload = {
        "inspection": inspection.model_dump(mode="json"),
        "parsed": parsed.model_dump(mode="json"),
        "quality": quality.model_dump(mode="json"),
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output is None:
        console.print_json(rendered)
    else:
        resolved = output.expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(rendered, encoding="utf-8")
        console.print(f"Wrote [bold]{resolved}[/bold]")
    if not quality.safe_for_claim_extraction:
        raise typer.Exit(code=2)
