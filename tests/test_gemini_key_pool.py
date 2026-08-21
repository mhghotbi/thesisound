from __future__ import annotations

from dataclasses import dataclass

import pytest

from thesisound.config import Settings
from thesisound.gemini_key_pool import (
    GeminiAuthenticationError,
    GeminiKeyPool,
    GeminiKeyPoolExhausted,
)


class QuotaError(RuntimeError):
    status_code = 429


class AuthError(RuntimeError):
    status_code = 401


class UnsupportedAuthError(RuntimeError):
    status_code = 401


@dataclass
class FakeClient:
    key_name: str
    calls: int = 0


def test_pool_rotates_on_quota_and_sticks_to_next_key() -> None:
    clients: dict[str, FakeClient] = {}

    def factory(key: str) -> FakeClient:
        client = FakeClient(key_name=key)
        clients[key] = client
        return client

    pool = GeminiKeyPool(
        ["key-a", "key-b"],
        client_factory=factory,
        cooldown_seconds=60,
    )

    def first_operation(client: FakeClient) -> str:
        client.calls += 1
        if client.key_name == "key-a":
            raise QuotaError("429 RESOURCE_EXHAUSTED")
        return client.key_name

    assert pool.call(first_operation) == "key-b"
    assert pool.call(lambda client: client.key_name) == "key-b"
    assert clients["key-a"].calls == 1


class ConnectError(RuntimeError):
    """No status_code -- shaped like httpx.ConnectError, not a provider response."""


def test_pool_tries_the_next_key_after_a_transient_connection_error() -> None:
    """A reset/timeout on one key must not starve out the rest of the pool.

    Found live (2026-08-20): every non-quota, non-auth error -- including a
    plain connection reset that says nothing about a *specific* key -- aborted
    the whole call on the first candidate key, even with six other configured
    keys confirmed reachable seconds earlier by a direct probe.
    """

    attempted: list[str] = []
    pool = GeminiKeyPool(
        ["flaky-key", "good-key"],
        client_factory=lambda key: FakeClient(key_name=key),
    )

    def operation(client: FakeClient) -> str:
        attempted.append(client.key_name)
        if client.key_name == "flaky-key":
            raise ConnectError("[WinError 10054] An existing connection was forcibly closed")
        return client.key_name

    assert pool.call(operation) == "good-key"
    assert attempted == ["flaky-key", "good-key"]


def test_pool_raises_the_transient_error_when_every_key_fails_that_way() -> None:
    pool = GeminiKeyPool(
        ["key-a", "key-b"],
        client_factory=lambda key: FakeClient(key_name=key),
    )

    def operation(client: FakeClient) -> str:
        raise ConnectError("The read operation timed out")

    with pytest.raises(ConnectError, match="timed out"):
        pool.call(operation)


def test_pool_does_not_hide_auth_or_input_errors() -> None:
    attempted: list[str] = []
    pool = GeminiKeyPool(
        ["bad-key", "other-key"],
        client_factory=lambda key: FakeClient(key_name=key),
    )

    def operation(client: FakeClient) -> str:
        attempted.append(client.key_name)
        raise AuthError("invalid API key")

    with pytest.raises(AuthError, match="invalid API key"):
        pool.call(operation)
    assert attempted == ["bad-key"]


def test_pool_falls_back_to_adc_for_unsupported_auth_keys() -> None:
    attempted: list[str] = []
    pool = GeminiKeyPool(
        ["AQ.key-a", "AQ.key-b"],
        client_factory=lambda key: FakeClient(key_name=key),
        adc_client_factory=lambda: FakeClient(key_name="adc"),
    )

    def operation(client: FakeClient) -> str:
        attempted.append(client.key_name)
        if client.key_name.startswith("AQ."):
            raise UnsupportedAuthError(
                "401 UNAUTHENTICATED: ACCESS_TOKEN_TYPE_UNSUPPORTED; "
                "Expected OAuth 2 access token"
            )
        return client.key_name

    assert pool.call(operation) == "adc"
    assert pool.call(operation) == "adc"
    assert attempted == ["AQ.key-a", "AQ.key-b", "adc", "adc"]


def test_pool_prefers_quota_error_over_adc_when_keys_mixed() -> None:
    attempted: list[str] = []
    pool = GeminiKeyPool(
        ["AQ.bad", "key-ok"],
        client_factory=lambda key: FakeClient(key_name=key),
        adc_client_factory=lambda: FakeClient(key_name="adc"),
    )

    def operation(client: FakeClient) -> str:
        attempted.append(client.key_name)
        if client.key_name.startswith("AQ."):
            raise UnsupportedAuthError(
                "401 UNAUTHENTICATED: ACCESS_TOKEN_TYPE_UNSUPPORTED; "
                "Expected OAuth 2 access token"
            )
        raise QuotaError("429 RESOURCE_EXHAUSTED")

    with pytest.raises(QuotaError, match="RESOURCE_EXHAUSTED"):
        pool.call(operation)
    assert attempted == ["AQ.bad", "key-ok"]
    assert "adc" not in attempted


def test_pool_reports_actionable_error_when_adc_is_unavailable() -> None:
    def missing_adc() -> FakeClient:
        raise RuntimeError("ADC missing")

    pool = GeminiKeyPool(
        ["AQ.bad"],
        client_factory=lambda key: FakeClient(key_name=key),
        adc_client_factory=missing_adc,
    )

    with pytest.raises(
        GeminiAuthenticationError,
        match="ACCESS_TOKEN_TYPE_UNSUPPORTED",
    ):
        pool.call(
            lambda _: (_ for _ in ()).throw(
                UnsupportedAuthError("401 ACCESS_TOKEN_TYPE_UNSUPPORTED")
            )
        )


def test_pool_reports_when_all_keys_are_temporarily_blocked() -> None:
    now = [100.0]
    pool = GeminiKeyPool(
        ["key-a"],
        client_factory=lambda key: FakeClient(key_name=key),
        cooldown_seconds=30,
        clock=lambda: now[0],
    )

    with pytest.raises(QuotaError):
        pool.call(lambda _: (_ for _ in ()).throw(QuotaError("rate limit")))
    with pytest.raises(GeminiKeyPoolExhausted, match="30 seconds") as raised:
        pool.call(lambda _: "not reached")
    assert raised.value.retry_after_seconds == pytest.approx(30.0, abs=1.0)


def test_settings_accept_json_or_comma_separated_key_pool() -> None:
    json_settings = Settings(
        GEMINI_API_KEYS='["key-a", "key-b", "key-a"]',
        THESISOUND_ENVIRONMENT="test",
    )
    assert json_settings.gemini_api_keys == ("key-a", "key-b")
    assert json_settings.gemini_api_key == "key-a"

    csv_settings = Settings(
        GEMINI_API_KEYS="key-a, key-b",
        GEMINI_API_KEY="legacy-key",
        THESISOUND_ENVIRONMENT="test",
    )
    assert csv_settings.gemini_api_keys == ("key-a", "key-b", "legacy-key")
