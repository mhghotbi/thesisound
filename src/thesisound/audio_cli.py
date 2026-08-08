from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from rich.console import Console

from thesisound.audio_runtime import create_audio_builder
from thesisound.config import Settings
from thesisound.pipeline import WorkspaceStore
from thesisound.services.audio_run import AudioBuildRunStore

console = Console()


def register_audio_commands(app: typer.Typer) -> None:
    @app.command("prepare-audio")
    def prepare_audio(
        project_id: Annotated[
            UUID,
            typer.Argument(help="Project with SCRIPT_VERIFIED state"),
        ],
        workspace_root: Annotated[
            Path | None,
            typer.Option(help="Override workspace directory"),
        ] = None,
    ) -> None:
        """Synthesize, transcribe, verify, normalize, and assemble final audio."""

        settings = Settings()
        workspace = WorkspaceStore(workspace_root or settings.workspace_root)
        builder = create_audio_builder(settings, workspace)
        try:
            builder.queue(project_id)
            run = builder.run(project_id)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]", stderr=True)
            raise typer.Exit(code=1) from exc
        if run.status != "succeeded":
            message = run.last_error or "Audio generation failed."
            console.print(f"[red]{message}[/red]", stderr=True)
            raise typer.Exit(code=1)
        console.print(f"Audio verified for [bold]{project_id}[/bold]")

    @app.command("audio-status")
    def audio_status(
        project_id: Annotated[UUID, typer.Argument()],
        workspace_root: Annotated[
            Path | None,
            typer.Option(help="Override workspace directory"),
        ] = None,
    ) -> None:
        settings = Settings()
        workspace = WorkspaceStore(workspace_root or settings.workspace_root)
        run = AudioBuildRunStore(workspace.root).load(project_id)
        console.print_json(run.model_dump_json(indent=2))
