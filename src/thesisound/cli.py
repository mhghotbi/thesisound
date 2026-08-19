from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from thesisound import tracing
from thesisound.adapters.models.gemini import GeminiStructuredModel
from thesisound.adapters.parsers.docling_adapter import DoclingParser
from thesisound.adapters.parsers.epub_adapter import EpubDocumentParser
from thesisound.adapters.parsers.mineru_adapter import MineruParser
from thesisound.adapters.parsers.native_adapter import NativeDocumentParser
from thesisound.concept_map_cli import register_concept_map_command
from thesisound.config import Settings
from thesisound.domain import Project
from thesisound.episode_cli import register_episode_commands
from thesisound.migrate_cli import register_migrate_commands
from thesisound.modeling import ModelError
from thesisound.observability import tracer_from_settings
from thesisound.pipeline import WorkspaceStore
from thesisound.ports import DocumentParserPort
from thesisound.prompt_loader import PromptLoader
from thesisound.script_cli import register_script_commands
from thesisound.services.artifact_writer import IngestionArtifactWriter
from thesisound.services.document_ingestion import ingest_document
from thesisound.services.document_inspector import inspect_document
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner
from thesisound.services.parsed_document_cache import ParsedDocumentCache
from thesisound.services.parser_benchmark import benchmark_directory, benchmark_document
from thesisound.services.research_brief import ResearchBriefService
from thesisound.source_cli import register_source_commands

app = typer.Typer(no_args_is_help=True, help="Thesisound local development CLI")
console = Console()
error_console = Console(stderr=True)
register_source_commands(app)
register_episode_commands(app)
register_script_commands(app)
register_migrate_commands(app)
register_concept_map_command(app)


@app.callback()
def _install_observability() -> None:
    """Install the ambient tracer once per CLI invocation, before any command
    runs. The composition-root counterpart of tracing.install_tracer() in
    web.app.create_app -- every thesisound/thesisound-web entry point gets
    one, whichever process starts first."""

    tracing.install_tracer(tracer_from_settings())

WorkspaceRootOption = Annotated[
    Path | None,
    typer.Option(help="Override workspace directory"),
]
ArtifactRootOption = Annotated[
    Path | None,
    typer.Option(help="Override the ingestion artifact directory"),
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


def _artifact_writer(
    settings: Settings,
    artifact_root: Path | None,
) -> IngestionArtifactWriter:
    return IngestionArtifactWriter(artifact_root or settings.ingestion_artifact_root)


def _parse_cache(
    settings: Settings,
    artifact_root: Path | None,
) -> ParsedDocumentCache | None:
    if not settings.parsed_document_cache_enabled:
        return None
    return ParsedDocumentCache(artifact_root or settings.ingestion_artifact_root)


def _parsers(
    settings: Settings,
    writer: IngestionArtifactWriter,
) -> dict[str, DocumentParserPort]:
    return {
        "native": NativeDocumentParser(),
        "epub": EpubDocumentParser(),
        "docling": DoclingParser(timeout_seconds=settings.docling_timeout_seconds),
        "mineru": MineruParser(
            command=settings.mineru_command,
            timeout_seconds=settings.mineru_timeout_seconds,
            backend=settings.mineru_backend,
            model_source=settings.mineru_model_source,
            output_root=writer.root / "raw" / "mineru",
        ),
    }


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


@app.command("build-brief")
def build_brief(
    project_id: Annotated[UUID, typer.Argument(help="Existing project UUID")],
    audience: Annotated[str, typer.Option(help="Intended listener profile")] = (
        "educated general listener"
    ),
    prior_knowledge: Annotated[
        str,
        typer.Option(help="none, introductory, intermediate, or advanced"),
    ] = "introductory",
    target_duration_minutes: Annotated[
        int,
        typer.Option("--duration", min=5, max=120, help="Requested episode duration"),
    ] = 30,
    modes: Annotated[
        str,
        typer.Option(help="Comma-separated: explanatory, critical, comparative, debate"),
    ] = "explanatory",
    output_language: Annotated[
        str,
        typer.Option("--language", help="Output language code"),
    ] = "fa",
    model: Annotated[str | None, typer.Option(help="Override the configured fast model")] = None,
    prompt_version: Annotated[
        str | None,
        typer.Option(help="Pin a specific prompt contract version"),
    ] = None,
    workspace_root: WorkspaceRootOption = None,
    output: OutputOption = None,
) -> None:
    """Create a validated ResearchBrief with Gemini structured output."""

    allowed_knowledge = {"none", "introductory", "intermediate", "advanced"}
    if prior_knowledge not in allowed_knowledge:
        raise typer.BadParameter(
            f"Expected one of: {', '.join(sorted(allowed_knowledge))}.",
            param_hint="--prior-knowledge",
        )
    requested_modes = [item.strip() for item in modes.split(",") if item.strip()]
    allowed_modes = {"explanatory", "critical", "comparative", "debate"}
    invalid_modes = set(requested_modes) - allowed_modes
    if not requested_modes or invalid_modes:
        detail = ", ".join(sorted(invalid_modes)) or "no modes supplied"
        raise typer.BadParameter(f"Invalid mode selection: {detail}", param_hint="--modes")

    settings = Settings()
    root = (workspace_root or settings.workspace_root).expanduser().resolve()
    workspace_store = WorkspaceStore(root)
    try:
        model_port = GeminiStructuredModel(api_keys=settings.gemini_api_keys)
        runner = ModelRunner(
            model_port,
            PromptLoader(),
            WorkspaceModelRunStore(root, keep_prompts=settings.keep_rendered_prompts),
            base_retry_delay_seconds=settings.model_retry_base_seconds,
        )
        execution = ResearchBriefService(workspace_store, runner).build(
            project_id,
            model=model or settings.model_fast,
            audience=audience,
            prior_knowledge=prior_knowledge,
            target_duration_minutes=target_duration_minutes,
            modes=requested_modes,
            output_language=output_language,
            prompt_version=prompt_version,
        )
    except (FileNotFoundError, ModelError, ValueError) as exc:
        error_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    _emit_json(
        {
            "brief": execution.output.model_dump(mode="json"),
            "model_run": execution.record.model_dump(mode="json"),
        },
        output,
    )


@app.command("inspect")
def inspect_source(
    path: DocumentPathArgument,
    output: OutputOption = None,
) -> None:
    """Inspect file identity, text coverage, encryption, and layout signals."""

    inspection = inspect_document(path)
    _emit_json(inspection.model_dump(mode="json"), output)


@app.command("parse")
def parse_source(
    path: DocumentPathArgument,
    parser: Annotated[
        str,
        typer.Option(help="Parser: auto, native, epub, docling, or mineru"),
    ] = "auto",
    artifact_root: ArtifactRootOption = None,
    output: OutputOption = None,
) -> None:
    """Inspect, route, parse, fall back when needed, and run quality gates."""

    allowed_parsers = {"auto", "native", "epub", "docling", "mineru"}
    if parser not in allowed_parsers:
        raise typer.BadParameter(
            f"Expected one of: {', '.join(sorted(allowed_parsers))}.",
            param_hint="--parser",
        )
    settings = Settings()
    writer = _artifact_writer(settings, artifact_root)
    try:
        result = ingest_document(
            path,
            parsers=_parsers(settings, writer),
            parser_name=parser,
            artifact_writer=writer,
            parse_cache=_parse_cache(settings, artifact_root),
        )
    except (OSError, ValueError, RuntimeError) as exc:
        error_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    _emit_json(result.model_dump(mode="json"), output)
    if not result.safe_for_claim_extraction:
        raise typer.Exit(code=2)


@app.command("compare-parsers")
def compare_parsers(
    path: DocumentPathArgument,
    artifact_root: ArtifactRootOption = None,
    output: OutputOption = None,
) -> None:
    """Run every configured parser on one document and compare quality metrics."""

    settings = Settings()
    writer = _artifact_writer(settings, artifact_root)
    benchmark = benchmark_document(
        path,
        parsers=_parsers(settings, writer),
        artifact_writer=writer,
    )
    _emit_json(benchmark.model_dump(mode="json"), output)
    if benchmark.recommended_parser is None:
        raise typer.Exit(code=2)


@app.command("benchmark-parsers")
def benchmark_parsers(
    directory: Annotated[Path, typer.Argument(help="Directory containing benchmark documents")],
    recursive: Annotated[
        bool,
        typer.Option("--recursive/--no-recursive", help="Include nested directories"),
    ] = False,
    artifact_root: ArtifactRootOption = None,
    output: OutputOption = None,
) -> None:
    """Benchmark all configured parsers across a local document corpus."""

    settings = Settings()
    writer = _artifact_writer(settings, artifact_root)
    suite = benchmark_directory(
        directory,
        parsers=_parsers(settings, writer),
        recursive=recursive,
        artifact_writer=writer,
    )
    _emit_json(suite.model_dump(mode="json"), output)
    if not suite.documents:
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
