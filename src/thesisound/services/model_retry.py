from __future__ import annotations

from dataclasses import dataclass

from thesisound.modeling import ModelError, StructuredOutputError


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    delay_seconds: float = 0
    repair_instruction: str | None = None


def decide_retry(
    error: ModelError,
    *,
    attempt: int,
    max_attempts: int,
    retry_schema_errors: bool,
    base_delay_seconds: float,
) -> RetryDecision:
    if attempt >= max_attempts or not error.retryable:
        return RetryDecision(should_retry=False)
    if isinstance(error, StructuredOutputError):
        if not retry_schema_errors:
            return RetryDecision(should_retry=False)
        return RetryDecision(
            should_retry=True,
            repair_instruction=(
                "The previous response failed the required output contract. "
                f"Correct this problem without changing the task: {error}"
            ),
        )
    delay = base_delay_seconds * (2 ** (attempt - 1))
    return RetryDecision(should_retry=True, delay_seconds=delay)
