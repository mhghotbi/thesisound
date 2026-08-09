from __future__ import annotations

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from thesisound.accounts import AccountError, AccountStore
from thesisound.accounts_cli import register_accounts_commands
from thesisound.domain import Project

runner = CliRunner()


@pytest.fixture
def cli_app() -> typer.Typer:
    app = typer.Typer()
    register_accounts_commands(app)
    return app


@pytest.fixture
def configured_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace_root = tmp_path / "workspaces"
    accounts_database = tmp_path / "accounts.sqlite3"
    monkeypatch.setenv("THESISOUND_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("THESISOUND_ACCOUNTS_DATABASE_PATH", str(accounts_database))
    return workspace_root, accounts_database


def test_create_set_password_and_activation_round_trip(
    cli_app: typer.Typer,
    configured_paths: tuple[Path, Path],
) -> None:
    _, database = configured_paths

    created = runner.invoke(
        cli_app,
        ["create-user", "Operator"],
        input="first-secret\nfirst-secret\n",
    )
    assert created.exit_code == 0, created.output

    store = AccountStore(database)
    account = store.verify_password("operator", "first-secret")
    assert account.role == "operator"

    changed = runner.invoke(
        cli_app,
        ["set-password", "operator"],
        input="second-secret\nsecond-secret\n",
    )
    assert changed.exit_code == 0, changed.output
    with pytest.raises(AccountError):
        store.verify_password("operator", "first-secret")
    assert store.verify_password("operator", "second-secret") == account

    deactivated = runner.invoke(cli_app, ["deactivate-user", "operator"])
    assert deactivated.exit_code == 0, deactivated.output
    assert store.get_active_user(account.user_id) is None

    activated = runner.invoke(cli_app, ["activate-user", "operator"])
    assert activated.exit_code == 0, activated.output
    assert store.get_active_user(account.user_id) == account


def test_adopt_orphan_projects_is_idempotent(
    cli_app: typer.Typer,
    configured_paths: tuple[Path, Path],
) -> None:
    workspace_root, database = configured_paths
    created = runner.invoke(
        cli_app,
        ["create-user", "operator"],
        input="secret\nsecret\n",
    )
    assert created.exit_code == 0, created.output

    project = Project(raw_input="legacy project")
    project_directory = workspace_root / str(project.project_id)
    project_directory.mkdir(parents=True)
    (project_directory / "project.json").write_text(
        project.model_dump_json(indent=2),
        encoding="utf-8",
    )

    first = runner.invoke(cli_app, ["adopt-orphan-projects", "operator"])
    second = runner.invoke(cli_app, ["adopt-orphan-projects", "operator"])

    assert first.exit_code == 0, first.output
    assert "Adopted 1" in first.output
    assert second.exit_code == 0, second.output
    assert "Adopted 0" in second.output

    store = AccountStore(database)
    account = store.get_user_by_username("operator")
    assert account is not None
    assert store.is_project_member(project.project_id, account.user_id)
