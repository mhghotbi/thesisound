"""Gemini-only outbound HTTP(S) proxy helpers.

Okian and other non-Gemini clients must not inherit this proxy.
"""

from __future__ import annotations

DEFAULT_HTTP_PROXY = "http://127.0.0.1:10809"

_gemini_proxy: str | None = DEFAULT_HTTP_PROXY


def normalize_proxy_url(proxy: str | None) -> str | None:
    value = (proxy or "").strip()
    if not value or value.casefold() in {"none", "off", "disable", "disabled"}:
        return None
    return value


def configure_gemini_http_proxy(proxy: str | None) -> str | None:
    """Remember the proxy used only by Gemini clients (not process-wide env)."""
    global _gemini_proxy
    _gemini_proxy = normalize_proxy_url(proxy)
    return _gemini_proxy


def current_http_proxy() -> str | None:
    return _gemini_proxy


def gemini_http_options(proxy: str | None = None) -> dict[str, object] | None:
    """Build google-genai HttpOptions kwargs that force the Gemini proxy."""
    resolved = normalize_proxy_url(proxy)
    if resolved is None:
        resolved = current_http_proxy()
    if resolved is None:
        return None
    return {
        "client_args": {
            "proxy": resolved,
            # Do not inherit process HTTP(S)_PROXY; Gemini proxy is explicit only.
            "trust_env": False,
        },
        "async_client_args": {
            "proxy": resolved,
            "trust_env": False,
        },
    }
