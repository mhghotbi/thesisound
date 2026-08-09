from __future__ import annotations

import ipaddress
import socket
import ssl
from dataclasses import dataclass
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener

from thesisound.config import Settings
from thesisound.http_proxy import normalize_proxy_url

_DEAD_STATUSES = {404, 410, 451}


@dataclass(frozen=True, slots=True)
class UrlProbeResult:
    url: str
    outcome: Literal["reachable", "dead", "unknown"]
    http_status: int | None
    reason: str


def probe_url(
    url: str,
    *,
    settings: Settings,
    opener: OpenerDirector | None = None,
) -> UrlProbeResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return UrlProbeResult(url, "dead", None, "unsupported URL scheme")

    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        return UrlProbeResult(url, "unknown", None, type(exc).__name__)
    except OSError as exc:
        return UrlProbeResult(url, "unknown", None, type(exc).__name__)

    for entry in addresses:
        address = entry[4][0].split("%", 1)[0]
        try:
            resolved = ipaddress.ip_address(address)
        except ValueError:
            return UrlProbeResult(url, "unknown", None, "invalid resolved address")
        if (
            resolved.is_loopback
            or resolved.is_private
            or resolved.is_link_local
            or resolved.is_reserved
            or resolved.is_multicast
        ):
            return UrlProbeResult(url, "dead", None, "non-public host")

    active_opener = opener or _build_opener(settings)
    try:
        head_status = _request_status(
            active_opener,
            url,
            method="HEAD",
            timeout=settings.url_probe_timeout_seconds,
        )
        mapped = _map_status(url, head_status)
        if mapped is not None:
            return mapped
        get_status = _request_status(
            active_opener,
            url,
            method="GET",
            timeout=settings.url_probe_timeout_seconds,
        )
        mapped = _map_status(url, get_status)
        if mapped is not None:
            return mapped
        return UrlProbeResult(url, "unknown", get_status, f"HTTP {get_status}")
    except (URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        return UrlProbeResult(url, "unknown", None, type(exc).__name__)


def _build_opener(settings: Settings) -> OpenerDirector:
    proxy = normalize_proxy_url(settings.http_proxy)
    proxies = {"http": proxy, "https": proxy} if proxy is not None else {}
    return build_opener(ProxyHandler(proxies))


def _request_status(
    opener: OpenerDirector,
    url: str,
    *,
    method: Literal["HEAD", "GET"],
    timeout: int,
) -> int:
    headers = {"Range": "bytes=0-0"} if method == "GET" else {}
    request = Request(url, method=method, headers=headers)
    try:
        with opener.open(request, timeout=timeout) as response:
            if method == "GET":
                response.read(16)
            return int(getattr(response, "status", response.getcode()))
    except HTTPError as exc:
        return int(exc.code)


def _map_status(url: str, status: int) -> UrlProbeResult | None:
    if status in _DEAD_STATUSES:
        return UrlProbeResult(url, "dead", status, f"HTTP {status}")
    if 200 <= status < 400:
        return UrlProbeResult(url, "reachable", status, f"HTTP {status}")
    return None
