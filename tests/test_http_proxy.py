from __future__ import annotations

import os

import pytest

from thesisound.config import Settings
from thesisound.http_proxy import (
    configure_gemini_http_proxy,
    current_http_proxy,
    gemini_http_options,
    normalize_proxy_url,
)


def test_normalize_proxy_url_disables_sentinels() -> None:
    assert normalize_proxy_url("none") is None
    assert normalize_proxy_url("OFF") is None
    assert normalize_proxy_url("  ") is None
    assert normalize_proxy_url("http://127.0.0.1:10809") == "http://127.0.0.1:10809"


def test_configure_gemini_proxy_does_not_export_process_env(monkeypatch) -> None:
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(key, raising=False)

    assert configure_gemini_http_proxy("http://127.0.0.1:10809") == "http://127.0.0.1:10809"
    assert current_http_proxy() == "http://127.0.0.1:10809"
    assert os.environ.get("HTTPS_PROXY") is None
    assert os.environ.get("HTTP_PROXY") is None
    options = gemini_http_options()
    assert options is not None
    assert options["client_args"]["proxy"] == "http://127.0.0.1:10809"
    assert options["client_args"]["trust_env"] is False


def test_settings_configures_gemini_proxy_only(tmp_path) -> None:
    Settings(
        _env_file=None,
        workspace_root=tmp_path / "workspaces",
        http_proxy="http://127.0.0.1:10809",
    )
    assert current_http_proxy() == "http://127.0.0.1:10809"
    assert gemini_http_options()["client_args"]["proxy"] == "http://127.0.0.1:10809"


def test_require_gemini_http_options_rejects_unproxied_api_key_traffic(tmp_path) -> None:
    from thesisound.http_proxy import require_gemini_http_options

    configure_gemini_http_proxy("none")
    with pytest.raises(RuntimeError, match="THESISOUND_HTTP_PROXY"):
        require_gemini_http_options()
    configure_gemini_http_proxy("http://127.0.0.1:10809")
    options = require_gemini_http_options()
    assert options["client_args"]["proxy"] == "http://127.0.0.1:10809"
