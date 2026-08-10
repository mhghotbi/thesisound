from __future__ import annotations

import base64
import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import SplitResult, unquote, urlsplit, urlunsplit
from urllib.request import OpenerDirector, Request

from thesisound.config import Settings
from thesisound.http_proxy import normalize_proxy_url

_DEAD_STATUSES = {404, 410, 451}
_MAX_CONNECT_RESPONSE_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True)
class UrlProbeResult:
    url: str
    outcome: Literal["reachable", "dead", "unknown"]
    http_status: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class _ResolvedEndpoint:
    family: int
    socktype: int
    proto: int
    sockaddr: tuple[Any, ...]
    ip: str


def probe_url(
    url: str,
    *,
    settings: Settings,
    opener: OpenerDirector | None = None,
) -> UrlProbeResult:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return UrlProbeResult(url, "dead", None, "unsupported URL scheme")
    try:
        _ = parsed.port
    except ValueError:
        return UrlProbeResult(url, "dead", None, "invalid URL port")

    try:
        endpoints = _resolve_public_endpoints(parsed)
    except socket.gaierror as exc:
        return UrlProbeResult(url, "unknown", None, type(exc).__name__)
    except OSError as exc:
        return UrlProbeResult(url, "unknown", None, type(exc).__name__)
    if endpoints is None:
        return UrlProbeResult(url, "dead", None, "non-public host")

    proxy_url = normalize_proxy_url(settings.http_proxy)
    try:
        head_status = _request_status(
            parsed,
            endpoints,
            method="HEAD",
            timeout=settings.url_probe_timeout_seconds,
            proxy_url=proxy_url,
            opener=opener,
        )
        mapped = _map_status(url, head_status)
        if mapped is not None:
            return mapped
        get_status = _request_status(
            parsed,
            endpoints,
            method="GET",
            timeout=settings.url_probe_timeout_seconds,
            proxy_url=proxy_url,
            opener=opener,
        )
        mapped = _map_status(url, get_status)
        if mapped is not None:
            return mapped
        return UrlProbeResult(url, "unknown", get_status, f"HTTP {get_status}")
    except (URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        return UrlProbeResult(url, "unknown", None, type(exc).__name__)


def _resolve_public_endpoints(parsed: SplitResult) -> tuple[_ResolvedEndpoint, ...] | None:
    assert parsed.hostname is not None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = socket.getaddrinfo(
        parsed.hostname,
        port,
        type=socket.SOCK_STREAM,
    )
    endpoints: list[_ResolvedEndpoint] = []
    seen: set[tuple[int, str]] = set()
    for family, socktype, proto, _canonname, sockaddr in addresses:
        address = str(sockaddr[0]).split("%", 1)[0]
        try:
            resolved = ipaddress.ip_address(address)
        except ValueError as exc:
            raise OSError("invalid resolved address") from exc
        if (
            resolved.is_loopback
            or resolved.is_private
            or resolved.is_link_local
            or resolved.is_reserved
            or resolved.is_multicast
        ):
            return None
        key = (family, address)
        if key in seen:
            continue
        seen.add(key)
        endpoints.append(
            _ResolvedEndpoint(
                family=family,
                socktype=socktype,
                proto=proto,
                sockaddr=sockaddr,
                ip=address,
            )
        )
    if not endpoints:
        raise OSError("no resolved address")
    return tuple(endpoints)


def _request_status(
    parsed: SplitResult,
    endpoints: tuple[_ResolvedEndpoint, ...],
    *,
    method: Literal["HEAD", "GET"],
    timeout: int,
    proxy_url: str | None,
    opener: OpenerDirector | None,
) -> int:
    if opener is not None:
        return _request_status_with_opener(
            opener,
            urlunsplit(parsed),
            method=method,
            timeout=timeout,
        )
    return _request_status_pinned(
        parsed,
        endpoints,
        method=method,
        timeout=timeout,
        proxy_url=proxy_url,
    )


def _request_status_with_opener(
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


def _request_status_pinned(
    parsed: SplitResult,
    endpoints: tuple[_ResolvedEndpoint, ...],
    *,
    method: Literal["HEAD", "GET"],
    timeout: int,
    proxy_url: str | None,
) -> int:
    last_error: OSError | ssl.SSLError | None = None
    for endpoint in endpoints:
        try:
            if proxy_url is None:
                return _request_direct(parsed, endpoint, method=method, timeout=timeout)
            return _request_via_proxy(
                parsed,
                endpoint,
                method=method,
                timeout=timeout,
                proxy_url=proxy_url,
            )
        except (OSError, ssl.SSLError) as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise OSError("no validated endpoint was available")


def _request_direct(
    parsed: SplitResult,
    endpoint: _ResolvedEndpoint,
    *,
    method: Literal["HEAD", "GET"],
    timeout: int,
) -> int:
    sock = _connect_endpoint(endpoint, timeout)
    try:
        if parsed.scheme == "https":
            assert parsed.hostname is not None
            sock = ssl.create_default_context().wrap_socket(
                sock,
                server_hostname=parsed.hostname,
            )
        return _exchange(
            sock,
            method=method,
            request_target=_origin_form(parsed),
            host_header=_host_header(parsed),
        )
    finally:
        sock.close()


def _request_via_proxy(
    parsed: SplitResult,
    endpoint: _ResolvedEndpoint,
    *,
    method: Literal["HEAD", "GET"],
    timeout: int,
    proxy_url: str,
) -> int:
    proxy = urlsplit(proxy_url)
    if proxy.scheme != "http" or not proxy.hostname:
        raise OSError("URL probe supports HTTP proxies only")
    proxy_port = proxy.port or 80
    sock = socket.create_connection((proxy.hostname, proxy_port), timeout=timeout)
    try:
        proxy_auth = _proxy_authorization(proxy)
        if parsed.scheme == "http":
            return _exchange(
                sock,
                method=method,
                request_target=_absolute_ip_url(parsed, endpoint.ip),
                host_header=_host_header(parsed),
                proxy_authorization=proxy_auth,
            )

        target_port = parsed.port or 443
        authority = _ip_authority(endpoint.ip, target_port)
        connect_status = _connect_tunnel(sock, authority, proxy_auth)
        if not 200 <= connect_status < 300:
            return connect_status
        assert parsed.hostname is not None
        sock = ssl.create_default_context().wrap_socket(
            sock,
            server_hostname=parsed.hostname,
        )
        return _exchange(
            sock,
            method=method,
            request_target=_origin_form(parsed),
            host_header=_host_header(parsed),
        )
    finally:
        sock.close()


def _connect_endpoint(endpoint: _ResolvedEndpoint, timeout: int) -> socket.socket:
    sock = socket.socket(endpoint.family, endpoint.socktype, endpoint.proto)
    sock.settimeout(timeout)
    try:
        sock.connect(endpoint.sockaddr)
    except Exception:
        sock.close()
        raise
    return sock


def _exchange(
    sock: socket.socket,
    *,
    method: Literal["HEAD", "GET"],
    request_target: str,
    host_header: str,
    proxy_authorization: str | None = None,
) -> int:
    headers = [
        f"{method} {request_target} HTTP/1.1",
        f"Host: {host_header}",
        "User-Agent: thesisound-url-probe/1",
        "Accept: */*",
        "Connection: close",
    ]
    if method == "GET":
        headers.append("Range: bytes=0-0")
    if proxy_authorization is not None:
        headers.append(f"Proxy-Authorization: {proxy_authorization}")
    sock.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("ascii"))
    response = http.client.HTTPResponse(sock)
    response.begin()
    try:
        if method == "GET":
            response.read(16)
        return int(response.status)
    finally:
        response.close()


def _connect_tunnel(
    sock: socket.socket,
    authority: str,
    proxy_authorization: str | None,
) -> int:
    headers = [
        f"CONNECT {authority} HTTP/1.1",
        f"Host: {authority}",
    ]
    if proxy_authorization is not None:
        headers.append(f"Proxy-Authorization: {proxy_authorization}")
    sock.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("ascii"))
    payload = bytearray()
    while not payload.endswith(b"\r\n\r\n"):
        chunk = sock.recv(1)
        if not chunk:
            raise OSError("proxy closed CONNECT response")
        payload.extend(chunk)
        if len(payload) > _MAX_CONNECT_RESPONSE_BYTES:
            raise OSError("proxy CONNECT response headers too large")
    status_line = bytes(payload).split(b"\r\n", 1)[0].decode("iso-8859-1")
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        raise OSError("invalid proxy CONNECT response")
    return int(parts[1])


def _origin_form(parsed: SplitResult) -> str:
    path = parsed.path or "/"
    return f"{path}?{parsed.query}" if parsed.query else path


def _host_header(parsed: SplitResult) -> str:
    assert parsed.hostname is not None
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    port = parsed.port
    default_port = 443 if parsed.scheme == "https" else 80
    return f"{host}:{port}" if port is not None and port != default_port else host


def _absolute_ip_url(parsed: SplitResult, ip: str) -> str:
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    authority = _ip_authority(ip, port)
    default_port = 443 if parsed.scheme == "https" else 80
    if port == default_port:
        authority = f"[{ip}]" if ":" in ip else ip
    return urlunsplit((parsed.scheme, authority, parsed.path or "/", parsed.query, ""))


def _ip_authority(ip: str, port: int) -> str:
    host = f"[{ip}]" if ":" in ip else ip
    return f"{host}:{port}"


def _proxy_authorization(proxy: SplitResult) -> str | None:
    if proxy.username is None:
        return None
    username = unquote(proxy.username)
    password = unquote(proxy.password or "")
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def _map_status(url: str, status: int) -> UrlProbeResult | None:
    if status in _DEAD_STATUSES:
        return UrlProbeResult(url, "dead", status, f"HTTP {status}")
    if 200 <= status < 400:
        return UrlProbeResult(url, "reachable", status, f"HTTP {status}")
    return None
