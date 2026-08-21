"""Gemini-scoped outbound HTTP(S) proxy helpers.

Okian and other non-Gemini clients must not inherit this proxy. The URL probe
deliberately reuses it so local reachability follows the operator's internet path;
Gemini URL Context itself still fetches from Google's network.
"""

from __future__ import annotations

DEFAULT_HTTP_PROXY = "http://127.0.0.1:10809"

_gemini_proxy: str | None = DEFAULT_HTTP_PROXY
_gemini_proxy_required: bool = True


def configure_gemini_proxy_required(required: bool) -> None:
    """Whether API-key Gemini clients must have a working proxy configured.

    Defaults to True (the original policy). Set THESISOUND_GEMINI_PROXY_REQUIRED=false
    (see Settings.gemini_proxy_required) to allow unproxied API-key traffic -- e.g.
    while a local proxy is temporarily broken and direct access to Gemini is confirmed
    to work. This is an operator override for a specific environment, not a statement
    that the proxy is never needed.
    """

    global _gemini_proxy_required
    _gemini_proxy_required = required


def gemini_proxy_required() -> bool:
    return _gemini_proxy_required


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


def require_gemini_http_options(proxy: str | None = None) -> dict[str, object] | None:
    """HttpOptions for Gemini API-key clients; proxy is mandatory unless relaxed.

    Returns None when proxying is unconfigured and gemini_proxy_required() is False
    (THESISOUND_GEMINI_PROXY_REQUIRED=false) -- callers must then build an unproxied
    client, the same way the ADC path already tolerates a None result.
    """
    options = gemini_http_options(proxy)
    if options is None and _gemini_proxy_required:
        raise RuntimeError(
            "Gemini API key requests require THESISOUND_HTTP_PROXY "
            f"(default {DEFAULT_HTTP_PROXY}). Unproxied GEMINI_API_KEYS traffic "
            "is not allowed unless THESISOUND_GEMINI_PROXY_REQUIRED=false is set."
        )
    return options
