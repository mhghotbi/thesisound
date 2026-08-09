from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from thesisound.accounts import AccountError, accounts_store_from_settings
from thesisound.config import Settings
from thesisound.pipeline import WorkspaceStore

console = Console()


def register_accounts_commands(app: typer.Typer) -> None:
    app.command("create-user")(_create_user)
    app.command("set-password")(_set_password)
    app.command("deactivate-user")(_deactivate_user)
    app.command("activate-user")(_activate_user)
    app.command("adopt-orphan-projects")(_adopt_orphan_projects)


def _create_user(
    username: Annotated[str, typer.Argument(help="Unique operator username")],
) -> None:
    password = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    try:
        account = accounts_store_from_settings(Settings()).create_password_user(
            username,
            password,
        )
    except (AccountError, OSError, RuntimeError) as exc:
        _fail(exc)
    console.print(f"Created operator [bold]{account.username}[/bold] (id={account.user_id}).")


def _set_password(
    username: Annotated[str, typer.Argument(help="Existing operator username")],
) -> None:
    password = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    try:
        accounts_store_from_settings(Settings()).set_password(username, password)
    except (AccountError, OSError, RuntimeError) as exc:
        _fail(exc)
    console.print(f"Password updated for [bold]{username.strip()}[/bold].")


def _deactivate_user(
    username: Annotated[str, typer.Argument(help="Existing operator username")],
) -> None:
    try:
        accounts_store_from_settings(Settings()).set_active(username, False)
    except (AccountError, OSError, RuntimeError) as exc:
        _fail(exc)
    console.print(f"Deactivated [bold]{username.strip()}[/bold].")


def _activate_user(
    username: Annotated[str, typer.Argument(help="Existing operator username")],
) -> None:
    try:
        accounts_store_from_settings(Settings()).set_active(username, True)
    except (AccountError, OSError, RuntimeError) as exc:
        _fail(exc)
    console.print(f"Activated [bold]{username.strip()}[/bold].")


def _adopt_orphan_projects(
    username: Annotated[str, typer.Argument(help="Operator who will own legacy projects")],
) -> None:
    settings = Settings()
    accounts = accounts_store_from_settings(settings)
    workspace = WorkspaceStore(settings.ensure_workspace_root())
    try:
        account = accounts.get_user_by_username(username)
        if account is None:
            raise AccountError("حساب کاربری پیدا نشد.")
        adopted = 0
        for project in workspace.list_projects():
            if accounts.has_any_member(project.project_id):
                continue
            accounts.add_project_member(project.project_id, account.user_id, role="owner")
            adopted += 1
    except (AccountError, OSError, RuntimeError) as exc:
        _fail(exc)
    console.print(f"Adopted {adopted} orphan project(s) for [bold]{account.label}[/bold].")


def _fail(exc: Exception) -> None:
    console.print(f"[red]{exc}[/red]", stderr=True)
    raise typer.Exit(code=1) from exc
