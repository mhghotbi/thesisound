from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Any

from thesisound.modeling import ModelConfigurationError


_GEMINI_OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/generative-language.retriever",
)


class GeminiKeyPoolExhausted(RuntimeError):
    """Raised when every configured key is temporarily quota-blocked."""

    status_code = 429


class GeminiAuthenticationError(RuntimeError):
    """Raised when API-key authentication fails and OAuth/ADC cannot recover."""

    status_code = 401


@dataclass(slots=True)
class _KeyState:
    api_key: str
    client: Any | None = None
    blocked_until: float = 0.0
    authentication_failed: bool = False


class GeminiKeyPool:
    """Sticky failover pool for independently authorized Gemini API keys.

    A key remains active until Gemini returns a quota/rate-limit response. The pool
    then blocks that key for a cooldown and moves to the next configured key. When
    Gemini rejects an authorization key with ACCESS_TOKEN_TYPE_UNSUPPORTED, that key
    is disabled for the process and the pool tries the remaining keys, then a valid
    OAuth Application Default Credential as a final fallback.
    """

    def __init__(
        self,
        api_keys: Sequence[str],
        *,
        client_factory: Callable[[str], Any] | None = None,
        adc_client_factory: Callable[[], Any] | None = None,
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
        self._adc_client_factory = adc_client_factory or _default_adc_client_factory
        self._adc_client_instance: Any | None = None
        self._lock = RLock()

    @property
    def size(self) -> int:
        return len(self._states)

    def call[T](self, operation: Callable[[Any], T]) -> T:
        last_quota_error: Exception | None = None
        last_auth_error: Exception | None = None
        now = self._clock()
        order = self._candidate_order()
        attempted = False

        for index in order:
            with self._lock:
                state = self._states[index]
                if state.authentication_failed or state.blocked_until > now:
                    continue
                client = self._client(index)
            attempted = True
            try:
                result = operation(client)
            except Exception as exc:
                if is_unsupported_auth_credential_error(exc):
                    last_auth_error = exc
                    with self._lock:
                        state.authentication_failed = True
                        self._current_index = (index + 1) % len(self._states)
                    continue
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

        if last_auth_error is not None or self._has_authentication_failures():
            return self._call_with_adc(operation, last_auth_error)
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

    def _has_authentication_failures(self) -> bool:
        with self._lock:
            return any(state.authentication_failed for state in self._states)

    def _adc_client(self) -> Any:
        with self._lock:
            if self._adc_client_instance is None:
                self._adc_client_instance = self._adc_client_factory()
            return self._adc_client_instance

    def _call_with_adc[T](
        self,
        operation: Callable[[Any], T],
        original_error: Exception | None,
    ) -> T:
        try:
            client = self._adc_client()
        except Exception as adc_error:
            raise GeminiAuthenticationError(
                _authentication_failure_message(original_error, adc_error)
            ) from (original_error or adc_error)

        try:
            return operation(client)
        except Exception as adc_error:
            if _status_code(adc_error) in {401, 403} or is_unsupported_auth_credential_error(
                adc_error
            ):
                raise GeminiAuthenticationError(
                    _authentication_failure_message(original_error, adc_error)
                ) from adc_error
            raise


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


def is_unsupported_auth_credential_error(exc: Exception) -> bool:
    if _status_code(exc) != 401:
        return False
    message = str(exc).casefold()
    return (
        "access_token_type_unsupported" in message
        or "expected oauth 2 access token" in message
    )


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
    return genai.Client(api_key=api_key, vertexai=False)


def _default_adc_client_factory() -> Any:
    try:
        import google.auth
        from google import genai
        from google.auth.exceptions import DefaultCredentialsError
    except ImportError as exc:
        raise ModelConfigurationError(
            "Install the Gemini extra with: uv sync --extra gemini"
        ) from exc

    try:
        credentials, _ = google.auth.default(scopes=list(_GEMINI_OAUTH_SCOPES))
    except DefaultCredentialsError as exc:
        raise ModelConfigurationError(
            "Application Default Credentials are unavailable. Configure OAuth/ADC with "
            "`gcloud auth application-default login` or another supported ADC source."
        ) from exc
    return genai.Client(credentials=credentials, vertexai=False)


def _authentication_failure_message(
    original_error: Exception | None,
    adc_error: Exception,
) -> str:
    original = str(original_error) if original_error is not None else "unknown API-key error"
    return (
        "Gemini rejected the configured API key with "
        "ACCESS_TOKEN_TYPE_UNSUPPORTED. This is commonly reported for some AQ. "
        "authorization keys and is not a quota or model-selection error. Thesisound "
        "tried OAuth/Application Default Credentials as a fallback, but that path also "
        f"failed: {adc_error}. Verify the key is restricted to the Gemini API and its "
        "service-account binding is valid, or configure ADC. Original API-key error: "
        f"{original}"
    )


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
