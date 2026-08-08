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
from thesisound.services.claim_prioritizer import ClaimPrioritizer
from thesisound.services.coverage_auditor import CoverageAuditorService
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.episode_planner import EpisodePlannerService
from thesisound.services.episode_preparation_service import EpisodePreparationService
from thesisound.services.evidence_pack_builder import EvidencePackBuilder
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner
from thesisound.services.source_artifact_store import SourceArtifactStore

console = Console()


def register_episode_commands(app: typer.Typer) -> None:
    app.command("audit-coverage")(_audit_coverage)
    app.command("prioritize-claims")(_prioritize_claims)
    app.command("plan-episode")(_plan_episode)
    app.command("build-evidence-packs")(_build_evidence_packs)
    app.command("prepare-episode")(_prepare_episode)


def _audit_coverage(
    project_id: Annotated[UUID, typer.Argument()],
    model: Annotated[str | None, typer.Option(help="Override strong model")] = None,
    prompt_version: Annotated[str | None, typer.Option()] = None,
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    service = _service(settings, _root(settings, workspace_root))
    try:
        report = service.audit_coverage(
            project_id,
            model=model or settings.model_strong,
            prompt_version=prompt_version,
        )
    except (FileNotFoundError, ModelError, ValueError) as exc:
        _fail(exc)
    _print_json(report.model_dump(mode="json"))


def _prioritize_claims(
    project_id: Annotated[UUID, typer.Argument()],
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    service = _service(settings, _root(settings, workspace_root))
    try:
        report = service.prioritize_claims(project_id)
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc)
    _print_json(report.model_dump(mode="json"))


def _plan_episode(
    project_id: Annotated[UUID, typer.Argument()],
    model: Annotated[str | None, typer.Option(help="Override strong model")] = None,
    prompt_version: Annotated[str | None, typer.Option()] = None,
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    service = _service(settings, _root(settings, workspace_root))
    try:
        plan = service.plan_episode(
            project_id,
            model=model or settings.model_strong,
            prompt_version=prompt_version,
        )
    except (FileNotFoundError, ModelError, ValueError) as exc:
        _fail(exc)
    _print_json(plan.model_dump(mode="json"))


def _build_evidence_packs(
    project_id: Annotated[UUID, typer.Argument()],
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    service = _service(settings, _root(settings, workspace_root))
    try:
        packs = service.build_evidence_packs(project_id)
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc)
    _print_json([pack.model_dump(mode="json") for pack in packs])


def _prepare_episode(
    project_id: Annotated[UUID, typer.Argument()],
    coverage_model: Annotated[
        str | None,
        typer.Option(help="Override coverage-audit model"),
    ] = None,
    planning_model: Annotated[
        str | None,
        typer.Option(help="Override episode-planning model"),
    ] = None,
    prompt_version: Annotated[str | None, typer.Option()] = None,
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    service = _service(settings, _root(settings, workspace_root))
    try:
        coverage, priorities, plan, packs = service.prepare_episode(
            project_id,
            coverage_model=coverage_model or settings.model_strong,
            planning_model=planning_model or settings.model_strong,
            prompt_version=prompt_version,
        )
    except (FileNotFoundError, ModelError, ValueError) as exc:
        _fail(exc)
    _print_json(
        {
            "coverage": coverage.model_dump(mode="json"),
            "priorities": priorities.model_dump(mode="json"),
            "episode_plan": plan.model_dump(mode="json"),
            "evidence_packs": [pack.model_dump(mode="json") for pack in packs],
        }
    )


def _service(settings: Settings, root: Path) -> EpisodePreparationService:
    model_port = GeminiStructuredModel(api_key=settings.gemini_api_key)
    runner = ModelRunner(
        model_port,
        PromptLoader(),
        WorkspaceModelRunStore(root, keep_prompts=settings.keep_rendered_prompts),
        base_retry_delay_seconds=settings.model_retry_base_seconds,
    )
    return EpisodePreparationService(
        workspace_store=WorkspaceStore(root),
        source_store=SourceArtifactStore(root),
        episode_store=EpisodeArtifactStore(root),
        coverage_auditor=CoverageAuditorService(runner),
        claim_prioritizer=ClaimPrioritizer(),
        episode_planner=EpisodePlannerService(runner),
        evidence_pack_builder=EvidencePackBuilder(),
    )


def _root(settings: Settings, override: Path | None) -> Path:
    return (override or settings.workspace_root).expanduser().resolve()


def _print_json(payload: object) -> None:
    console.print_json(json.dumps(payload, ensure_ascii=False))


def _fail(exc: Exception) -> None:
    console.print(f"[red]{exc}[/red]", stderr=True)
    raise typer.Exit(code=1) from exc
