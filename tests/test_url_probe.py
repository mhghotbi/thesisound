from __future__ import annotations

import socket
from urllib.request import ProxyHandler, Request

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


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (
            "http://127.0.0.1:10809",
            {
                "http": "http://127.0.0.1:10809",
                "https": "http://127.0.0.1:10809",
            },
        ),
        ("none", {}),
    ],
)
def test_opener_uses_only_the_configured_proxy(
    public_dns,
    monkeypatch,
    configured: str,
    expected: dict[str, str],
) -> None:
    captured: list[ProxyHandler] = []
    fake = FakeOpener([200])

    def build(handler: ProxyHandler):
        captured.append(handler)
        return fake

    monkeypatch.setattr(url_probe, "build_opener", build)
    result = probe_url(
        "https://example.com/a",
        settings=_settings(http_proxy=configured),
    )
    assert result.outcome == "reachable"
    assert captured[0].proxies == expected
