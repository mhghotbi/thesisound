from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path
from uuid import uuid4

import typer
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from thesisound.accounts_cli import register_accounts_commands
from thesisound.config import Settings
from thesisound.domain import Project
from thesisound.pipeline import WorkspaceStore
from thesisound.web.app import create_app

runner = CliRunner()


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        observability_database_path=tmp_path / "observability.sqlite3",
        observability_artifact_root=tmp_path / "observability-artifacts",
        accounts_database_path=tmp_path / "accounts.sqlite3",
        web_session_secret="test-secret",
        allow_test_otp=True,
        test_otp_phone="09120000000",
        test_otp_code="999999",
        web_secure_cookies=False,
        **overrides,
    )


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match
    return match.group(1)


def _otp_login(client: TestClient) -> None:
    page = client.get("/login")
    requested = client.post(
        "/login/request-code",
        data={
            "phone": "09120000000",
            "csrf_token": _csrf(page.text),
            "next_path": "/projects",
        },
        follow_redirects=False,
    )
    assert requested.status_code == 303
    page = client.get("/login/verify")
    verified = client.post(
        "/login/verify",
        data={"code": "999999", "csrf_token": _csrf(page.text)},
        follow_redirects=False,
    )
    assert verified.status_code == 303


def _password_login(client: TestClient, username: str, password: str) -> None:
    page = client.get("/login/password")
    response = client.post(
        "/login/password",
        data={
            "username": username,
            "password": password,
            "csrf_token": _csrf(page.text),
            "next_path": "/projects",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _save_projects(workspace: WorkspaceStore) -> tuple[Project, Project]:
    first = Project(raw_input="member-a-private-project")
    second = Project(raw_input="member-b-private-project")
    workspace.save_project(first)
    workspace.save_project(second)
    return first, second


def test_member_cannot_reach_another_users_project_across_all_route_files(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    workspace = app.state.workspace
    project_a, project_b = _save_projects(workspace)
    account_b = app.state.accounts.get_or_create_phone_user("09121111111")
    app.state.accounts.add_project_member(project_b.project_id, account_b.user_id)

    with TestClient(app) as client:
        _otp_login(client)
        account_a = app.state.accounts.get_or_create_phone_user("09120000000")
        app.state.accounts.add_project_member(project_a.project_id, account_a.user_id)
        projects_page = client.get("/projects")
        csrf_token = _csrf(projects_page.text)

        denied_gets = [
            f"/projects/{project_b.project_id}",
            f"/projects/{project_b.project_id}/sources",
            f"/projects/{project_b.project_id}/episode",
            f"/projects/{project_b.project_id}/script",
            f"/projects/{project_b.project_id}/audio",
            f"/projects/{project_b.project_id}/readiness",
            f"/projects/{project_b.project_id}/audio/segments/audio-0.wav",
        ]
        for url in denied_gets:
            response = client.get(url, follow_redirects=False)
            assert response.status_code == 303, url
            assert response.headers["location"] == "/projects", url

        denied_post = client.post(
            f"/projects/{project_b.project_id}/brief",
            data={"csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert denied_post.status_code == 303
        assert denied_post.headers["location"] == "/projects"

        nonexistent = client.get(f"/projects/{uuid4()}", follow_redirects=False)
        existing_but_denied = client.get(
            f"/projects/{project_b.project_id}",
            follow_redirects=False,
        )

    assert nonexistent.status_code == existing_but_denied.status_code
    assert nonexistent.headers["location"] == existing_but_denied.headers["location"]
    assert nonexistent.content == existing_but_denied.content


def test_projects_list_is_filtered_for_members_and_complete_for_operators(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    project_a, project_b = _save_projects(app.state.workspace)
    member_a = app.state.accounts.get_or_create_phone_user("09120000000")
    member_b = app.state.accounts.get_or_create_phone_user("09121111111")
    app.state.accounts.add_project_member(project_a.project_id, member_a.user_id)
    app.state.accounts.add_project_member(project_b.project_id, member_b.user_id)
    app.state.accounts.create_password_user("operator", "secret")

    with TestClient(app) as client:
        _otp_login(client)
        page = client.get("/projects")
        assert project_a.raw_input in page.text
        assert project_b.raw_input not in page.text

    with TestClient(app) as client:
        _password_login(client, "operator", "secret")
        page = client.get("/projects")
        assert project_a.raw_input in page.text
        assert project_b.raw_input in page.text


def test_operator_can_cross_project_boundaries(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    _, project = _save_projects(app.state.workspace)
    app.state.accounts.create_password_user("operator", "secret")

    with TestClient(app) as client:
        _password_login(client, "operator", "secret")
        urls = [
            f"/projects/{project.project_id}",
            f"/projects/{project.project_id}/sources",
            f"/projects/{project.project_id}/episode",
            f"/projects/{project.project_id}/script",
            f"/projects/{project.project_id}/audio",
            f"/projects/{project.project_id}/audio/segments/audio-0.wav",
        ]
        responses = [client.get(url, follow_redirects=False) for url in urls]

    for url, response in zip(urls, responses, strict=True):
        assert not (
            response.status_code == 303 and response.headers.get("location") == "/projects"
        ), url


def test_deactivating_account_invalidates_the_next_request(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    app.state.accounts.create_password_user("operator", "secret")

    with TestClient(app) as client:
        _password_login(client, "operator", "secret")
        assert client.get("/projects").status_code == 200
        app.state.accounts.set_active("operator", False)
        revoked = client.get("/projects", follow_redirects=False)

    assert revoked.status_code == 303
    assert revoked.headers["location"] == "/auth/login?next=/projects"


def test_orphan_is_invisible_until_adopt_command_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    member = app.state.accounts.create_password_user("member", "secret", role="member")
    orphan = Project(raw_input="legacy-orphan-project")
    app.state.workspace.save_project(orphan)

    monkeypatch.setenv("THESISOUND_WORKSPACE_ROOT", str(settings.workspace_root))
    monkeypatch.setenv(
        "THESISOUND_ACCOUNTS_DATABASE_PATH",
        str(settings.resolved_accounts_database_path),
    )
    cli_app = typer.Typer()
    register_accounts_commands(cli_app)

    with TestClient(app) as client:
        _password_login(client, "member", "secret")
        before = client.get("/projects")
        assert orphan.raw_input not in before.text

        adopted = runner.invoke(cli_app, ["adopt-orphan-projects", "member"])
        assert adopted.exit_code == 0, adopted.output

        after = client.get("/projects")
        assert orphan.raw_input in after.text

    assert app.state.accounts.is_project_member(orphan.project_id, member.user_id)


def test_failed_membership_write_rolls_back_new_project_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = create_app(_settings(tmp_path))

    def fail_membership(*_args, **_kwargs) -> None:
        raise sqlite3.OperationalError("accounts database unavailable")

    monkeypatch.setattr(app.state.accounts, "add_project_member", fail_membership)

    with TestClient(app, raise_server_exceptions=False) as client:
        _otp_login(client)
        page = client.get("/projects/new")
        response = client.post(
            "/projects",
            data={
                "csrf_token": _csrf(page.text),
                "topic": "atomic project creation",
            },
            follow_redirects=False,
        )

    assert response.status_code == 500
    assert app.state.workspace.list_projects() == []
    assert not any(app.state.workspace.root.glob("*/project.json"))


def test_every_project_scoped_web_handler_has_an_authorization_guard() -> None:
    web_root = Path(__file__).parents[1] / "src" / "thesisound" / "web"
    missing: list[str] = []
    guard_markers = (
        "_project_redirect(request, project_id)",
        "project_redirect(request, project_id)",
        "require_operator(request, project_id)",
        "authenticated_operator(request)",
    )

    for path in sorted(web_root.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(argument.arg == "project_id" for argument in node.args.args):
                continue
            decorators = [
                ast.get_source_segment(source, item) or "" for item in node.decorator_list
            ]
            if not any(
                item.startswith("app.get(") or item.startswith("app.post(") for item in decorators
            ):
                continue
            body = ast.get_source_segment(source, node) or ""
            if not any(marker in body for marker in guard_markers):
                missing.append(f"{path.name}:{node.lineno}:{node.name}")

    assert missing == []
