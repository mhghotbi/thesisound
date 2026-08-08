from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Any, TypeVar

from thesisound.modeling import ModelConfigurationError

T = TypeVar("T")


class GeminiKeyPoolExhausted(RuntimeError):
    """Raised when every configured key is temporarily quota-blocked."""

    status_code = 429


@dataclass(slots=True)
class _KeyState:
    api_key: str
    client: Any | None = None
    blocked_until: float = 0.0


class GeminiKeyPool:
    """Sticky failover pool for independently authorized Gemini API keys.

    A key remains active until Gemini returns a quota/rate-limit response. The pool
    then blocks that key for a cooldown and moves to the next configured key. Other
    provider errors are surfaced immediately and never hidden by key rotation.
    """

    def __init__(
        self,
        api_keys: Sequence[str],
        *,
        client_factory: Callable[[str], Any] | None = None,
        cooldown_seconds: float = 60,
        daily_cooldown_seconds: float = 24 * 60 * 60,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        keys = _normalize_keys(api_keys)
        if not keys:
            raise ModelConfigurationError(
                "GEMINI_API_KEY or GEMINI_API_KEYS is required for live Gemini calls."
            )
        if cooldown_seconds < 0 or daily_cooldown_seconds < 0:
            raise ValueError("Gemini key cooldowns must be non-negative.")
        self._states = [_KeyState(api_key=key) for key in keys]
        self._current_index = 0
        self._cooldown_seconds = cooldown_seconds
        self._daily_cooldown_seconds = daily_cooldown_seconds
        self._clock = clock
        self._client_factory = client_factory or _default_client_factory
        self._lock = RLock()

    @property
    def size(self) -> int:
        return len(self._states)

    def call(self, operation: Callable[[Any], T]) -> T:
        last_quota_error: Exception | None = None
        now = self._clock()
        order = self._candidate_order()
        attempted = False

        for index in order:
            with self._lock:
                state = self._states[index]
                if state.blocked_until > now:
                    continue
                client = self._client(index)
            attempted = True
            try:
                result = operation(client)
            except Exception as exc:
                if not is_gemini_quota_error(exc):
                    raise
                last_quota_error = exc
                with self._lock:
                    duration = (
                        self._daily_cooldown_seconds
                        if is_daily_quota_error(exc)
                        else self._cooldown_seconds
                    )
                    state.blocked_until = self._clock() + duration
                    self._current_index = (index + 1) % len(self._states)
                continue

            with self._lock:
                self._current_index = index
            return result

        if last_quota_error is not None:
            raise last_quota_error
        if not attempted:
            wait_seconds = max(
                0,
                min(state.blocked_until for state in self._states) - self._clock(),
            )
            raise GeminiKeyPoolExhausted(
                "All configured Gemini API keys are temporarily quota-blocked; "
                f"retry in approximately {wait_seconds:.0f} seconds."
            )
        raise GeminiKeyPoolExhausted("No Gemini API key was available.")

    def _candidate_order(self) -> list[int]:
        with self._lock:
            count = len(self._states)
            return [(self._current_index + offset) % count for offset in range(count)]

    def _client(self, index: int) -> Any:
        state = self._states[index]
        if state.client is None:
            state.client = self._client_factory(state.api_key)
        return state.client


_SHARED_POOLS: dict[tuple[str, ...], GeminiKeyPool] = {}
_SHARED_POOLS_LOCK = RLock()


def shared_gemini_key_pool(api_keys: Sequence[str]) -> GeminiKeyPool:
    normalized = tuple(_normalize_keys(api_keys))
    with _SHARED_POOLS_LOCK:
        pool = _SHARED_POOLS.get(normalized)
        if pool is None:
            pool = GeminiKeyPool(normalized)
            _SHARED_POOLS[normalized] = pool
        return pool


def is_gemini_quota_error(exc: Exception) -> bool:
    status = _status_code(exc)
    name = type(exc).__name__.casefold()
    message = str(exc).casefold()
    return status == 429 or any(
        token in name or token in message
        for token in (
            "resourceexhausted",
            "resource_exhausted",
            "rate_limit_exceeded",
            "ratelimit",
            "quota_exceeded",
            "too many requests",
        )
    )


def is_daily_quota_error(exc: Exception) -> bool:
    message = str(exc).casefold()
    return any(
        token in message
        for token in (
            "daily quota",
            "requests per day",
            "request per day",
            "rpd",
            "per-day",
            "per day",
            "quota_exceeded",
        )
    )


def _normalize_keys(api_keys: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in api_keys:
        key = value.strip()
        if not key or key in seen:
            continue
        normalized.append(key)
        seen.add(key)
    return normalized


def _default_client_factory(api_key: str) -> Any:
    try:
        from google import genai
    except ImportError as exc:
        raise ModelConfigurationError(
            "Install the Gemini extra with: uv sync --extra gemini"
        ) from exc
    return genai.Client(api_key=api_key)


def _status_code(exc: Exception) -> int | None:
    for attribute in ("status_code", "code"):
        value = getattr(exc, attribute, None)
        if callable(value):
            value = value()
        if isinstance(value, int):
            return value
        enum_value = getattr(value, "value", None)
        if isinstance(enum_value, int):
            return enum_value
    return None
