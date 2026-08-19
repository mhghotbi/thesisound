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
from thesisound.services.budget_calibration import BudgetCalibrationRecorder
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.glossary_builder import GlossaryBuilderService
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner
from thesisound.services.persian_script_writer import (
    PersianScriptWriterService,
    SpeakerBalancePolicy,
)
from thesisound.services.plan_approval import EpisodePlanApprovalStore
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_checks import ScriptChecker
from thesisound.services.script_pipeline_service import ScriptPipelineService
from thesisound.services.script_reviser import TargetedScriptReviserService
from thesisound.services.script_verifier import ScriptVerifierService
from thesisound.services.source_artifact_store import SourceArtifactStore

console = Console()
error_console = Console(stderr=True)


def register_script_commands(app: typer.Typer) -> None:
    app.command("approve-plan")(_approve_plan)
    app.command("build-glossary")(_build_glossary)
    app.command("write-script")(_write_script)
    app.command("check-script")(_check_script)
    app.command("verify-script")(_verify_script)
    app.command("revise-script")(_revise_script)
    app.command("prepare-script")(_prepare_script)
    app.command("record-budget-calibration")(_record_budget_calibration)
    app.command("script-ab-export")(_script_ab_export)


def _approve_plan(
    project_id: Annotated[UUID, typer.Argument()],
    approved_by: Annotated[str, typer.Option("--approved-by")] = "cli",
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    root = _root(settings, workspace_root)
    workspace = WorkspaceStore(root)
    try:
        project = workspace.load_project(project_id)
        approval = EpisodePlanApprovalStore(root).approve(
            project,
            approved_by=approved_by,
        )
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc)
    _print_json(approval.model_dump(mode="json"))


def _build_glossary(
    project_id: Annotated[UUID, typer.Argument()],
    model: Annotated[str | None, typer.Option()] = None,
    prompt_version: Annotated[str | None, typer.Option()] = None,
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    service = _service(settings, _root(settings, workspace_root))
    try:
        result = service.build_glossary(
            project_id,
            model=model or settings.model_strong,
            prompt_version=prompt_version,
        )
    except (FileNotFoundError, ModelError, ValueError) as exc:
        _fail(exc)
    _print_json(result.model_dump(mode="json"))


def _write_script(
    project_id: Annotated[UUID, typer.Argument()],
    model: Annotated[str | None, typer.Option()] = None,
    prompt_version: Annotated[str | None, typer.Option()] = None,
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    service = _service(settings, _root(settings, workspace_root))
    try:
        result = service.write_script(
            project_id,
            model=model or settings.model_strong,
            prompt_version=prompt_version,
        )
    except (FileNotFoundError, ModelError, ValueError) as exc:
        _fail(exc)
    _print_json(result.model_dump(mode="json"))


def _check_script(
    project_id: Annotated[UUID, typer.Argument()],
    revised: Annotated[bool, typer.Option("--revised/--draft")] = False,
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    service = _service(settings, _root(settings, workspace_root))
    try:
        result = service.run_checks(project_id, revised=revised)
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc)
    _print_json(result.model_dump(mode="json"))


def _verify_script(
    project_id: Annotated[UUID, typer.Argument()],
    model: Annotated[str | None, typer.Option()] = None,
    revised: Annotated[bool, typer.Option("--revised/--draft")] = False,
    prompt_version: Annotated[str | None, typer.Option()] = None,
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    service = _service(settings, _root(settings, workspace_root))
    try:
        result = service.verify_script(
            project_id,
            model=model or settings.model_strong,
            revised=revised,
            prompt_version=prompt_version,
        )
    except (FileNotFoundError, ModelError, ValueError) as exc:
        _fail(exc)
    _print_json(result.model_dump(mode="json"))


def _revise_script(
    project_id: Annotated[UUID, typer.Argument()],
    model: Annotated[str | None, typer.Option()] = None,
    prompt_version: Annotated[str | None, typer.Option()] = None,
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    service = _service(settings, _root(settings, workspace_root))
    try:
        result = service.revise_script(
            project_id,
            model=model or settings.model_strong,
            prompt_version=prompt_version,
        )
    except (FileNotFoundError, ModelError, ValueError) as exc:
        _fail(exc)
    _print_json(result.model_dump(mode="json"))


def _prepare_script(
    project_id: Annotated[UUID, typer.Argument()],
    glossary_model: Annotated[str | None, typer.Option()] = None,
    writer_model: Annotated[str | None, typer.Option()] = None,
    verifier_model: Annotated[str | None, typer.Option()] = None,
    reviser_model: Annotated[str | None, typer.Option()] = None,
    prompt_version: Annotated[str | None, typer.Option()] = None,
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    service = _service(settings, _root(settings, workspace_root))
    try:
        result = service.run(
            project_id,
            glossary_model=glossary_model or settings.model_strong,
            writer_model=writer_model or settings.model_strong,
            verifier_model=verifier_model or settings.model_strong,
            reviser_model=reviser_model or settings.model_strong,
            prompt_version=prompt_version,
        )
    except (FileNotFoundError, ModelError, ValueError) as exc:
        _fail(exc)
    _print_json(result.model_dump(mode="json"))


def _record_budget_calibration(
    project_id: Annotated[UUID, typer.Argument()],
    revised: Annotated[bool, typer.Option("--revised/--draft")] = True,
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    root = _root(settings, workspace_root)
    workspace = WorkspaceStore(root)
    episode_store = EpisodeArtifactStore(root)
    script_store = ScriptArtifactStore(root)
    try:
        project = workspace.load_project(project_id)
        if project.brief is None or project.episode_plan is None:
            raise ValueError("ResearchBrief and EpisodePlan are required for calibration.")
        report = BudgetCalibrationRecorder(root).record(
            project_id=project_id,
            target_duration_minutes=project.brief.target_duration_minutes,
            episode_plan=project.episode_plan,
            evidence_packs=episode_store.load_evidence_packs(project_id),
            checks=script_store.load_checks(project_id, revised=revised),
            verification=script_store.load_verification(project_id, revised=revised),
        )
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc)
    _print_json(report.model_dump(mode="json"))


def _script_ab_export(
    project_a: Annotated[UUID, typer.Argument()],
    project_b: Annotated[UUID, typer.Argument()],
    out: Annotated[Path, typer.Option("--out")],
    workspace_root: Annotated[Path | None, typer.Option()] = None,
) -> None:
    settings = Settings()
    from thesisound.services.script_ab_export import ScriptAbExporter

    try:
        result = ScriptAbExporter(_root(settings, workspace_root)).export(
            project_a,
            project_b,
            out,
        )
    except (FileNotFoundError, ValueError) as exc:
        _fail(exc)
    _print_json(result)


def _service(settings: Settings, root: Path) -> ScriptPipelineService:
    model_port = GeminiStructuredModel(api_key=settings.gemini_api_key)
    runner = ModelRunner(
        model_port,
        PromptLoader(),
        WorkspaceModelRunStore(root, keep_prompts=settings.keep_rendered_prompts),
        base_retry_delay_seconds=settings.model_retry_base_seconds,
    )
    return ScriptPipelineService(
        workspace_store=WorkspaceStore(root),
        source_store=SourceArtifactStore(root),
        episode_store=EpisodeArtifactStore(root),
        script_store=ScriptArtifactStore(root),
        approval_store=EpisodePlanApprovalStore(root),
        glossary_builder=GlossaryBuilderService(runner),
        script_writer=PersianScriptWriterService(
            runner,
            SpeakerBalancePolicy(enabled=settings.script_speaker_balance_enabled),
        ),
        script_checker=ScriptChecker(),
        verifier=ScriptVerifierService(runner),
        reviser=TargetedScriptReviserService(runner),
        quality_gate_enabled=settings.script_quality_gate_enabled,
        min_quality_overall=settings.script_quality_min_overall,
    )


def _root(settings: Settings, override: Path | None) -> Path:
    return (override or settings.workspace_root).expanduser().resolve()


def _print_json(payload: object) -> None:
    console.print_json(json.dumps(payload, ensure_ascii=False))


def _fail(exc: Exception) -> None:
    error_console.print(f"[red]{exc}[/red]")
    raise typer.Exit(code=1) from exc
