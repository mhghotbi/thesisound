from __future__ import annotations

from typer.testing import CliRunner

from thesisound.cli_safety import COMMAND_SAFETY, registered_command_names
from thesisound.cli_with_audio import app


def test_every_registered_command_has_a_safety_classification() -> None:
    assert registered_command_names(app) == set(COMMAND_SAFETY)


def test_spending_commands_are_also_marked_writes_or_readonly() -> None:
    for name, flags in COMMAND_SAFETY.items():
        if "spends" in flags and name != "search-web":
            assert flags & {"writes", "readonly"}, name


def test_commands_table_renders_badges() -> None:
    result = CliRunner().invoke(app, ["commands"])

    assert result.exit_code == 0
    assert "⟦readonly⟧" in result.output
    assert "⟦writes⟧" in result.output
    assert "⟦spends⟧" in result.output


def test_help_renders_safety_badge() -> None:
    result = CliRunner().invoke(app, ["readiness", "--help"])

    assert result.exit_code == 0
    assert "⟦readonly⟧" in result.output
