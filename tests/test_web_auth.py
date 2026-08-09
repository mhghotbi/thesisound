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
        )
