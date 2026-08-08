from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from rich.console import Console

from thesisound.adapters.models.gemini import GeminiStructuredModel
from thesisound.config import Settings
from thesisound.modeling import ModelError
from thesisound.pipeline import WorkspaceStore
from thesisound.prompt_loader import PromptLoader
from thesisound.services.block_builder import BlockBuilder
from thesisound.services.claim_reconciler import ClaimReconcilerService
from thesisound.services.document_mapper import DocumentMapperService
from thesisound.services.evidence_extractor import EvidenceExtractorService
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner
from thesisound.services.source_analysis_service import SourceAnalysisService
from thesisound.services.source_artifact_store import SourceArtifactStore

console = Console()


def register_source_commands(app: typer.Typer) -> None:
    app.command("build-blocks")(_build_blocks)
    app.command("map-document")(_map_document)
    app.command("extract-evidence")(_extract_evidence)
    app.command("build-claims")(_build_claims)
    app.command("analyze-source")(_analyze_source)


def _build_blocks(
    project_id: Annotated[UUID, typer.Argument(help="Existing project UUID")],
    ingestion_result: Annotated[
        Path,
        typer.Argument(help="JSON output produced by thesisound parse"),
    ],
    source_id: Annotated[
        UUID | None,
        typer.Option(help="Optional stable source UUID"),
    ] = None,
    workspace_root: Annotated[
        Path | None,
        typer.Option(help="Override workspace directory"),
    ] = None,
) -> None:
    settings = Settings()
    root = _root(settings, workspace_root)
    service = SourceAnalysisService(
        workspace_store=WorkspaceStore(root),
        artifact_store=SourceArtifactStore(root),
        block_builder=BlockBuilder(),
        document_mapper=None,  # type: ignore[arg-type]
        evidence_extractor=None,  # type: ignore[arg-type]
        claim_reconciler=None,  # type: ignore[arg-type]
    )
    try:
        ingestion = SourceArtifactStore.load_ingestion(ingestion_result)
        resolved_source_id, blocks, manifest = service.build_blocks(
            project_id,
            ingestion,
            source_id=source_id,
        )
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc)
    _print_json(
        {
            "source_id": str(resolved_source_id),
            "block_count": len(blocks),
            "manifest": manifest.model_dump(mode="json"),
        }
    )


def _map_document(
    project_id: Annotated[UUID, typer.Argument()],
    source_id: Annotated[UUID, typer.Argument()],
    model: Annotated[str | None, typer.Option(help="Override fast model")] = None,
    prompt_version: Annotated[str | None, typer.Option()] = None,
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    service = _model_service(settings, _root(settings, workspace_root))
    try:
        manifest = service.map_document(
            project_id,
            source_id,
            model=model or settings.model_fast,
            prompt_version=prompt_version,
        )
    except (FileNotFoundError, ModelError, ValueError) as exc:
        _fail(exc)
    _print_json(manifest.model_dump(mode="json"))


def _extract_evidence(
    project_id: Annotated[UUID, typer.Argument()],
    source_id: Annotated[UUID, typer.Argument()],
    model: Annotated[str | None, typer.Option(help="Override fast model")] = None,
    prompt_version: Annotated[str | None, typer.Option()] = None,
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    service = _model_service(settings, _root(settings, workspace_root))
    try:
        manifest = service.extract_evidence(
            project_id,
            source_id,
            model=model or settings.model_fast,
            prompt_version=prompt_version,
        )
    except (FileNotFoundError, ModelError, ValueError) as exc:
        _fail(exc)
    _print_json(manifest.model_dump(mode="json"))


def _build_claims(
    project_id: Annotated[UUID, typer.Argument()],
    source_id: Annotated[UUID, typer.Argument()],
    model: Annotated[str | None, typer.Option(help="Override strong model")] = None,
    prompt_version: Annotated[str | None, typer.Option()] = None,
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    service = _model_service(settings, _root(settings, workspace_root))
    try:
        ledger, manifest = service.build_claims(
            project_id,
            source_id,
            model=model or settings.model_strong,
            prompt_version=prompt_version,
        )
    except (FileNotFoundError, ModelError, ValueError) as exc:
        _fail(exc)
    _print_json(
        {
            "ledger": ledger.model_dump(mode="json"),
            "manifest": manifest.model_dump(mode="json"),
        }
    )


def _analyze_source(
    project_id: Annotated[UUID, typer.Argument()],
    ingestion_result: Annotated[
        Path,
        typer.Argument(help="JSON output produced by thesisound parse"),
    ],
    source_id: Annotated[UUID | None, typer.Option()] = None,
    fast_model: Annotated[str | None, typer.Option()] = None,
    strong_model: Annotated[str | None, typer.Option()] = None,
    prompt_version: Annotated[str | None, typer.Option()] = None,
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    service = _model_service(settings, _root(settings, workspace_root))
    try:
        ledger, manifest = service.analyze_source(
            project_id,
            ingestion_result,
            fast_model=fast_model or settings.model_fast,
            strong_model=strong_model or settings.model_strong,
            source_id=source_id,
            prompt_version=prompt_version,
        )
    except (FileNotFoundError, ModelError, ValueError) as exc:
        _fail(exc)
    _print_json(
        {
            "ledger": ledger.model_dump(mode="json"),
            "manifest": manifest.model_dump(mode="json"),
        }
    )


def _model_service(settings: Settings, root: Path) -> SourceAnalysisService:
    model_port = GeminiStructuredModel(api_key=settings.gemini_api_key)
    runner = ModelRunner(
        model_port,
        PromptLoader(),
        WorkspaceModelRunStore(root, keep_prompts=settings.keep_rendered_prompts),
        base_retry_delay_seconds=settings.model_retry_base_seconds,
    )
    return SourceAnalysisService(
        workspace_store=WorkspaceStore(root),
        artifact_store=SourceArtifactStore(root),
        block_builder=BlockBuilder(),
        document_mapper=DocumentMapperService(runner),
        evidence_extractor=EvidenceExtractorService(runner),
        claim_reconciler=ClaimReconcilerService(runner),
    )


def _root(settings: Settings, override: Path | None) -> Path:
    return (override or settings.workspace_root).expanduser().resolve()


def _print_json(payload: object) -> None:
    console.print_json(json.dumps(payload, ensure_ascii=False))


def _fail(exc: Exception) -> None:
    console.print(f"[red]{exc}[/red]", stderr=True)
    raise typer.Exit(code=1) from exc
