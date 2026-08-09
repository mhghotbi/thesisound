import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from thesisound.config import Settings
from thesisound.web.app import create_app


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "workspace_root": tmp_path / "workspaces",
        "ingestion_artifact_root": tmp_path / "artifacts",
        "web_session_secret": "test-secret-that-is-long-enough",
        "allow_test_otp": True,
        "test_otp_phone": "09120000000",
        "test_otp_code": "999999",
        "otp_resend_cooldown_seconds": 5,
        "ui_demo_mode": True,
    }
    values.update(overrides)
    return Settings(**values)


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _login(client: TestClient) -> None:
    login = client.get("/login")
    response = client.post(
        "/login/request-code",
        data={
            "phone": "09120000000",
            "csrf_token": _csrf(login.text),
            "next_path": "/projects",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    verify = client.get("/login/verify")
    response = client.post(
        "/login/verify",
        data={"code": "999999", "csrf_token": _csrf(verify.text)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/projects"


def test_protected_page_redirects_to_login(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/projects", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


def test_development_otp_logs_in(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        _login(client)
        response = client.get("/projects")

    assert response.status_code == 200
    assert "گفتارهای شما" in response.text


def test_wrong_otp_is_rejected(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        login = client.get("/login")
        client.post(
            "/login/request-code",
            data={
                "phone": "09120000000",
                "csrf_token": _csrf(login.text),
                "next_path": "/projects",
            },
        )
        verify = client.get("/login/verify")
        response = client.post(
            "/login/verify",
            data={"code": "111111", "csrf_token": _csrf(verify.text)},
        )

    assert response.status_code == 422
    assert "درست نیست" in response.text


def test_production_rejects_test_otp(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="Test OTP"):
        _settings(
            tmp_path,
            environment="production",
            allow_test_otp=True,
            ui_demo_mode=False,
            web_secure_cookies=True,
            web_session_secret="unique-production-secret",
            **{
                "KAVENEGAR_API_KEY": "prod-key",
                "KAVENEGAR_TEMPLATE_NAME": "aist",
            },
        )


def test_production_requires_kavenegar(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="KAVENEGAR_API_KEY"):
        _settings(
            tmp_path,
            environment="production",
            allow_test_otp=False,
            ui_demo_mode=False,
            web_secure_cookies=True,
            web_session_secret="unique-production-secret",
        )


def _login_with_password(
    client: TestClient,
    username: str,
    password: str,
    *,
    next_path: str = "/projects",
):
    page = client.get(f"/login/password?next={next_path}")
    return client.post(
        "/login/password",
        data={
            "username": username,
            "password": password,
            "csrf_token": _csrf(page.text),
            "next_path": next_path,
        },
        follow_redirects=False,
    )


def test_password_login_succeeds(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    app.state.accounts.create_password_user("operator", "correct-password")

    with TestClient(app) as client:
        response = _login_with_password(client, "operator", "correct-password")
        projects = client.get("/projects")

    assert response.status_code == 303
    assert response.headers["location"] == "/projects"
    assert projects.status_code == 200
    assert "operator" in projects.text


def test_password_login_rejects_wrong_password(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    app.state.accounts.create_password_user("operator", "correct-password")

    with TestClient(app) as client:
        response = _login_with_password(client, "operator", "wrong-password")

    assert response.status_code == 422
    assert "نام کاربری یا رمز عبور درست نیست" in response.text


def test_password_login_locks_after_configured_attempts(tmp_path: Path) -> None:
    app = create_app(
        _settings(
            tmp_path,
            password_login_max_attempts=2,
            password_login_lockout_seconds=60,
        )
    )
    app.state.accounts.create_password_user("operator", "correct-password")

    with TestClient(app) as client:
        first = _login_with_password(client, "operator", "wrong-password")
        second = _login_with_password(client, "operator", "wrong-password")
        correct_during_lockout = _login_with_password(
            client,
            "operator",
            "correct-password",
        )

    assert first.status_code == 422
    assert "نام کاربری یا رمز عبور درست نیست" in first.text
    assert second.status_code == 422
    assert "تعداد تلاش‌ها بیش از حد مجاز است" in second.text
    assert correct_during_lockout.status_code == 422
    assert "تعداد تلاش‌ها بیش از حد مجاز است" in correct_during_lockout.text


def test_otp_login_auto_provisions_one_member_account(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    with TestClient(create_app(settings)) as client:
        _login(client)

    with TestClient(create_app(settings)) as client:
        _login(client)

    with sqlite3.connect(settings.resolved_accounts_database_path) as connection:
        rows = connection.execute(
            "SELECT role, phone FROM users WHERE phone = ?",
            ("09120000000",),
        ).fetchall()

    assert rows == [("member", "09120000000")]
