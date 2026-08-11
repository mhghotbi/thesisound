from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

import typer
from rich.console import Console
from rich.table import Table

CommandSafety = Literal["readonly", "writes", "spends"]

_READONLY = {
    "status",
    "dump",
    "inspect",
    "doctor",
    "audio-status",
    "observability",
    "runs",
    "run-summary",
    "model-call",
    "observability-export",
    "trace",
    "trace-show",
    "timeline",
    "pipeline-summary",
    "cost",
    "evidence-tier-report",
    "readiness",
    "commands",
    "models list",
    "models verify",
    "metrics show",
}
_WRITES = {
    "init",
    "parse",
    "compare-parsers",
    "benchmark-parsers",
    "build-blocks",
    "map-document",
    "extract-evidence",
    "build-claims",
    "analyze-source",
    "audit-coverage",
    "prioritize-claims",
    "estimate-episode-budget",
    "build-disagreement-graph",
    "plan-episode",
    "build-evidence-packs",
    "prepare-episode",
    "approve-plan",
    "build-glossary",
    "write-script",
    "check-script",
    "verify-script",
    "revise-script",
    "prepare-script",
    "record-budget-calibration",
    "script-ab-export",
    "prepare-audio",
    "observability-reprice",
    "create-user",
    "set-password",
    "deactivate-user",
    "activate-user",
    "adopt-orphan-projects",
    "build-brief",
    "eval",
    "models provision",
    "models parse",
    "metrics rollup",
}
_SPENDS = {
    "build-brief",
    "map-document",
    "extract-evidence",
    "analyze-source",
    "audit-coverage",
    "prepare-episode",
    "build-glossary",
    "write-script",
    "verify-script",
    "revise-script",
    "prepare-script",
    "prepare-audio",
    "search-web",
    "eval",
}

COMMAND_SAFETY: dict[str, frozenset[CommandSafety]] = {
    name: frozenset(
        flag
        for flag, names in (
            ("readonly", _READONLY),
            ("writes", _WRITES),
            ("spends", _SPENDS),
        )
        if name in names
    )
    for name in sorted(_READONLY | _WRITES | _SPENDS)
}
# Web search writes no workspace artifact, but it can spend provider quota.
COMMAND_SAFETY["search-web"] = frozenset({"spends"})


def command_name(command) -> str:
    if command.name:
        return command.name
    callback = command.callback
    if callback is None:
        raise ValueError("Registered command has neither name nor callback.")
    return callback.__name__.replace("_", "-").strip("-")


def _registered_commands(
    app: typer.Typer,
    *,
    prefix: str = "",
) -> Iterable[tuple[str, object]]:
    for command in app.registered_commands:
        name = command_name(command)
        qualified = f"{prefix} {name}".strip()
        yield qualified, command
    for group in app.registered_groups:
        group_name = group.name or ""
        qualified = f"{prefix} {group_name}".strip()
        yield from _registered_commands(group.typer_instance, prefix=qualified)


def registered_command_names(app: typer.Typer) -> set[str]:
    return {name for name, _ in _registered_commands(app)}


def apply_command_safety(app: typer.Typer) -> None:
    """Append safety badges to help text after all commands are registered."""

    for name, command in _registered_commands(app):
        badges = COMMAND_SAFETY.get(name)
        if badges is None:
            continue
        suffix = " ".join(f"⟦{badge}⟧" for badge in sorted(badges))
        base = command.help or (command.callback.__doc__ if command.callback else "") or ""
        command.help = f"{base.strip()} {suffix}".strip()


def register_safety_commands(app: typer.Typer) -> None:
    @app.command("commands")
    def commands() -> None:
        """List every CLI command and its operational safety badges."""

        table = Table(title="Thesisound command safety")
        table.add_column("Command")
        table.add_column("Badges")
        for name, flags in sorted(COMMAND_SAFETY.items()):
            table.add_row(name, " ".join(f"⟦{flag}⟧" for flag in sorted(flags)))
        Console().print(table)
