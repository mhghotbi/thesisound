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
    """Build google-genai HttpOptions kwargs that force the Gemini proxy.

    Returns None only when proxying is explicitly disabled. Callers that send
    GEMINI_API_KEYS traffic must treat a missing proxy as a configuration error.
    """
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


def require_gemini_http_options(proxy: str | None = None) -> dict[str, object]:
    """HttpOptions for Gemini API-key clients; proxy is mandatory."""
    options = gemini_http_options(proxy)
    if options is None:
        raise RuntimeError(
            "Gemini API key requests require THESISOUND_HTTP_PROXY "
            f"(default {DEFAULT_HTTP_PROXY}). Unproxied GEMINI_API_KEYS traffic "
            "is not allowed; set the proxy or use 'none' only for non-key clients."
        )
    return options
