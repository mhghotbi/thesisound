from __future__ import annotations

import socket
from urllib.request import Request

import pytest

from thesisound.config import Settings
from thesisound.services import url_probe
from thesisound.services.url_probe import probe_url


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status
        self.read_bytes = 0

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self, size: int) -> bytes:
        self.read_bytes = size
        return b"x"


class FakeOpener:
    def __init__(self, outcomes: list[int | BaseException]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[Request] = []

    def open(self, request: Request, *, timeout: int):
        assert timeout > 0
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeResponse(outcome)


class FakeSocket:
    def __init__(self) -> None:
        self.timeout: int | None = None
        self.connected_to: tuple[object, ...] | None = None
        self.closed = False

    def settimeout(self, timeout: int) -> None:
        self.timeout = timeout

    def connect(self, sockaddr: tuple[object, ...]) -> None:
        self.connected_to = sockaddr

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(
        url_probe.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )


def _settings(**overrides: object) -> Settings:
    values = {"http_proxy": "none", **overrides}
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize("status", [200, 301])
def test_reachable_head_statuses(public_dns, status: int) -> None:
    result = probe_url(
        "https://example.com/a",
        settings=_settings(),
        opener=FakeOpener([status]),
    )
    assert result.outcome == "reachable"
    assert result.http_status == status


@pytest.mark.parametrize("status", [404, 410, 451])
def test_definitive_negative_statuses_are_dead(public_dns, status: int) -> None:
    result = probe_url(
        "https://example.com/a",
        settings=_settings(),
        opener=FakeOpener([status]),
    )
    assert result.outcome == "dead"
    assert result.http_status == status


@pytest.mark.parametrize("status", [403, 500])
def test_non_definitive_statuses_are_unknown(public_dns, status: int) -> None:
    result = probe_url(
        "https://example.com/a",
        settings=_settings(),
        opener=FakeOpener([status, status]),
    )
    assert result.outcome == "unknown"
    assert result.http_status == status


def test_head_405_falls_back_to_ranged_get(public_dns) -> None:
    opener = FakeOpener([405, 206])
    result = probe_url(
        "https://example.com/a",
        settings=_settings(),
        opener=opener,
    )
    assert result.outcome == "reachable"
    assert [request.get_method() for request in opener.requests] == ["HEAD", "GET"]
    assert opener.requests[1].get_header("Range") == "bytes=0-0"


def test_timeout_is_unknown(public_dns) -> None:
    result = probe_url(
        "https://example.com/a",
        settings=_settings(),
        opener=FakeOpener([TimeoutError()]),
    )
    assert result.outcome == "unknown"
    assert result.reason == "TimeoutError"


def test_dns_failure_is_unknown(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise socket.gaierror("no dns")

    monkeypatch.setattr(url_probe.socket, "getaddrinfo", fail)
    result = probe_url("https://example.com/a", settings=_settings())
    assert result.outcome == "unknown"
    assert result.reason == "gaierror"


@pytest.mark.parametrize(
    "url,address",
    [
        ("http://127.0.0.1:8000/", "127.0.0.1"),
        ("http://169.254.169.254/latest/meta-data/", "169.254.169.254"),
    ],
)
def test_non_public_hosts_are_dead(monkeypatch, url: str, address: str) -> None:
    monkeypatch.setattr(
        url_probe.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80))
        ],
    )
    result = probe_url(url, settings=_settings())
    assert result.outcome == "dead"
    assert result.reason == "non-public host"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/a"])
def test_unsupported_schemes_are_dead(url: str) -> None:
    result = probe_url(url, settings=_settings())
    assert result.outcome == "dead"
    assert result.reason == "unsupported URL scheme"


def test_direct_https_pins_validated_ip_and_preserves_original_sni(
    public_dns,
    monkeypatch,
) -> None:
    sock = FakeSocket()
    seen: dict[str, object] = {}

    class FakeTlsContext:
        def wrap_socket(self, raw_sock: FakeSocket, *, server_hostname: str):
            seen["sni"] = server_hostname
            return raw_sock

    monkeypatch.setattr(url_probe.socket, "socket", lambda *_args: sock)
    monkeypatch.setattr(url_probe.ssl, "create_default_context", FakeTlsContext)

    def exchange(_sock: FakeSocket, **kwargs: object) -> int:
        seen.update(kwargs)
        return 200

    monkeypatch.setattr(url_probe, "_exchange", exchange)

    result = probe_url("https://example.com/a?q=1", settings=_settings())

    assert result.outcome == "reachable"
    assert sock.connected_to == ("93.184.216.34", 443)
    assert seen["sni"] == "example.com"
    assert seen["request_target"] == "/a?q=1"
    assert seen["host_header"] == "example.com"


def test_https_proxy_tunnels_to_validated_ip_and_preserves_original_sni(
    public_dns,
    monkeypatch,
) -> None:
    proxy_sock = FakeSocket()
    seen: dict[str, object] = {}

    def create_connection(address: tuple[str, int], *, timeout: int):
        seen["proxy_address"] = address
        seen["proxy_timeout"] = timeout
        return proxy_sock

    class FakeTlsContext:
        def wrap_socket(self, raw_sock: FakeSocket, *, server_hostname: str):
            seen["sni"] = server_hostname
            return raw_sock

    def connect_tunnel(
        _sock: FakeSocket,
        authority: str,
        proxy_authorization: str | None,
    ) -> int:
        seen["connect_authority"] = authority
        seen["proxy_authorization"] = proxy_authorization
        return 200

    def exchange(_sock: FakeSocket, **kwargs: object) -> int:
        seen.update(kwargs)
        return 200

    monkeypatch.setattr(url_probe.socket, "create_connection", create_connection)
    monkeypatch.setattr(url_probe.ssl, "create_default_context", FakeTlsContext)
    monkeypatch.setattr(url_probe, "_connect_tunnel", connect_tunnel)
    monkeypatch.setattr(url_probe, "_exchange", exchange)

    result = probe_url(
        "https://example.com/a",
        settings=_settings(http_proxy="http://127.0.0.1:10809"),
    )

    assert result.outcome == "reachable"
    assert seen["proxy_address"] == ("127.0.0.1", 10809)
    assert seen["connect_authority"] == "93.184.216.34:443"
    assert seen["sni"] == "example.com"
    assert seen["host_header"] == "example.com"


def test_http_proxy_absolute_target_uses_validated_ip_not_hostname(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        url_probe.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        ],
    )
    proxy_sock = FakeSocket()
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        url_probe.socket,
        "create_connection",
        lambda *_args, **_kwargs: proxy_sock,
    )

    def exchange(_sock: FakeSocket, **kwargs: object) -> int:
        seen.update(kwargs)
        return 200

    monkeypatch.setattr(url_probe, "_exchange", exchange)

    result = probe_url(
        "http://example.com/a",
        settings=_settings(http_proxy="http://127.0.0.1:10809"),
    )

    assert result.outcome == "reachable"
    assert seen["request_target"] == "http://93.184.216.34/a"
    assert seen["host_header"] == "example.com"


def test_resolver_output_is_the_only_target_input_for_direct_transport(
    monkeypatch,
) -> None:
    dns_calls = 0
    sock = FakeSocket()

    def resolve(*_args, **_kwargs):
        nonlocal dns_calls
        dns_calls += 1
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]

    monkeypatch.setattr(url_probe.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(url_probe.socket, "socket", lambda *_args: sock)
    monkeypatch.setattr(url_probe, "_exchange", lambda *_args, **_kwargs: 200)

    class FakeTlsContext:
        def wrap_socket(self, raw_sock: FakeSocket, *, server_hostname: str):
            assert server_hostname == "example.com"
            return raw_sock

    monkeypatch.setattr(url_probe.ssl, "create_default_context", FakeTlsContext)

    result = probe_url("https://example.com/", settings=_settings())

    assert result.outcome == "reachable"
    assert dns_calls == 1
    assert sock.connected_to == ("93.184.216.34", 443)
