from __future__ import annotations

from typing import Annotated, NoReturn

import typer
from rich.console import Console

from thesisound.accounts import (
    AccountError,
    AccountRecord,
    AccountStore,
    accounts_store_from_settings,
    normalize_phone_digits,
)
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
    username: Annotated[str, typer.Argument(help="Unique username for the new account")],
    role: Annotated[
        str,
        typer.Option(
            "--role",
            help=(
                "Account role: 'member' is isolated to their own projects; "
                "'operator' can see and manage every project."
            ),
        ),
    ] = "member",
) -> None:
    password = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    try:
        account = accounts_store_from_settings(Settings()).create_password_user(
            username,
            password,
            role=role,
        )
    except (AccountError, OSError, RuntimeError) as exc:
        _fail(exc)
    console.print(f"Created {account.role} [bold]{account.username}[/bold] (id={account.user_id}).")


def _set_password(
    username: Annotated[str, typer.Argument(help="Existing username")],
) -> None:
    password = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    try:
        accounts_store_from_settings(Settings()).set_password(username, password)
    except (AccountError, OSError, RuntimeError) as exc:
        _fail(exc)
    console.print(f"Password updated for [bold]{username.strip()}[/bold].")


def _deactivate_user(
    username: Annotated[str, typer.Argument(help="Existing username")],
) -> None:
    try:
        accounts_store_from_settings(Settings()).set_active(username, False)
    except (AccountError, OSError, RuntimeError) as exc:
        _fail(exc)
    console.print(f"Deactivated [bold]{username.strip()}[/bold].")


def _activate_user(
    username: Annotated[str, typer.Argument(help="Existing username")],
) -> None:
    try:
        accounts_store_from_settings(Settings()).set_active(username, True)
    except (AccountError, OSError, RuntimeError) as exc:
        _fail(exc)
    console.print(f"Activated [bold]{username.strip()}[/bold].")


def _adopt_orphan_projects(
    account: Annotated[
        str,
        typer.Argument(
            metavar="ACCOUNT",
            help="Username, or phone number for an OTP account, who will own legacy projects",
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--apply",
            help="List what would be adopted without writing, or apply it (default).",
        ),
    ] = False,
) -> None:
    """Give every workspace project with no member row an owner.

    Projects created before the accounts table existed have no ``project_members``
    row, which makes them unreachable for *everyone* rather than private to
    someone. This reconciles the filesystem against the account store.
    """
    settings = Settings()
    accounts = accounts_store_from_settings(settings)
    workspace = WorkspaceStore(settings.ensure_workspace_root())
    try:
        record = _resolve_account(accounts, account)
        orphans = [
            project
            for project in workspace.list_projects()
            if not accounts.has_any_member(project.project_id)
        ]
        if not dry_run:
            for project in orphans:
                accounts.add_project_member(
                    project.project_id, record.user_id, role="owner"
                )
    except (AccountError, OSError, RuntimeError) as exc:
        _fail(exc)

    if not orphans:
        console.print("No orphan projects found; every project already has an owner.")
        return
    verb = "Would adopt" if dry_run else "Adopted"
    console.print(f"{verb} {len(orphans)} orphan project(s) for [bold]{record.label}[/bold]:")
    for project in orphans:
        console.print(f"  · {project.project_id}  {_summarize(project.raw_input)}")
    if dry_run:
        console.print("Nothing was written. Re-run with --apply to make it so.")


def _resolve_account(accounts: AccountStore, identifier: str) -> AccountRecord:
    """Find an existing account by username or phone. Never creates one."""
    found = accounts.get_user_by_username(identifier)
    if found is not None:
        return found
    if normalize_phone_digits(identifier) is not None:
        found = accounts.get_user_by_phone(identifier)
        if found is not None:
            return found
    raise AccountError("حساب کاربری پیدا نشد.")


def _summarize(raw_input: str) -> str:
    single_line = " ".join(raw_input.split())
    return single_line if len(single_line) <= 60 else f"{single_line[:57]}…"


def _fail(exc: Exception) -> NoReturn:
    Console(stderr=True).print(f"[red]{exc}[/red]")
    raise typer.Exit(code=1) from exc
