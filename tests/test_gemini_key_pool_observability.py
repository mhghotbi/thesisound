from __future__ import annotations

from thesisound.gemini_key_pool import GeminiKeyPool


class QuotaError(RuntimeError):
    status_code = 429


class AuthError(RuntimeError):
    status_code = 401


class Client:
    def __init__(self, name: str) -> None:
        self.name = name


def test_pool_emits_redacted_events_for_quota_rotation() -> None:
    pool = GeminiKeyPool(
        ["AIza-first-secret-key-123456789", "AIza-second-secret-key-987654321"],
        client_factory=Client,
        adc_client_factory=lambda: Client("adc"),
        cooldown_seconds=60,
    )
    events = []

    def operation(client: Client):
        if "first" in client.name:
            raise QuotaError("quota")
        return client.name

    result = pool.call(operation, on_attempt=events.append)

    assert "second" in result
    assert [event["status"] for event in events] == ["quota_failed", "succeeded"]
    assert events[0]["key_slot"] == 1
    assert events[1]["key_slot"] == 2
    assert all("api_key" not in event for event in events)
    assert all("AIza" not in str(event) for event in events)


def test_pool_emits_adc_fallback_attempt() -> None:
    pool = GeminiKeyPool(
        ["AQ.authorization-key"],
        client_factory=Client,
        adc_client_factory=lambda: Client("adc"),
    )
    events = []

    def operation(client: Client):
        if client.name.startswith("AQ."):
            raise AuthError("ACCESS_TOKEN_TYPE_UNSUPPORTED expected OAuth 2 access token")
        return "ok"

    assert pool.call(operation, on_attempt=events.append) == "ok"
    assert [event["credential_type"] for event in events] == ["api_key", "adc"]
    assert [event["status"] for event in events] == ["auth_failed", "succeeded"]
