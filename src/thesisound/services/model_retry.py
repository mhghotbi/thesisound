from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from thesisound.modeling import (
    DeterministicValidationError,
    ModelError,
    ModelRateLimitError,
    ModelTimeoutError,
    SchemaValidationError,
    StructuredOutputError,
)

type ErrorClass = Literal[
    "provider",
    "rate_limit",
    "timeout",
    "schema",
    "deterministic",
    "non_retryable",
]
type RetryStopReason = Literal[
    "max_attempts",
    "non_retryable",
    "stage_policy",
    "identical_repair",
    "schema_retries_disabled",
]


@dataclass(frozen=True)
class StageRetryPolicy:
    """Per-prompt contract-repair budget. Provider retries use ``max_attempts``."""

    # None = unlimited within max_attempts; 0 = no contract repairs; 1 = one chance.
    max_contract_repairs: int | None = 1
    # False for stages whose final attempt has its own deterministic repair
    # (concept_cells auto-merges/flags, consolidate/edges auto-fix on the last
    # attempt): a model that repeats the same wrong answer must still reach
    # that final attempt, so an identical fingerprint must not stop it early.
    allow_identical_repair_stop: bool = True


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    delay_seconds: float = 0
    repair_instruction: str | None = None
    stop_reason: RetryStopReason | None = None


# Measured recovery (audit R7): evidence recovers; episode/glossary/verifier
# historically did not. episode_plan is bumped to 1 repair (2026-08-13): that
# measurement predates routing episode_plan onto okian_gemini_strong, and an
# invented claim ID is exactly the kind of scoped, nameable mistake a repair
# instruction is suited to fix. Revert to 0 if it turns out not to recover.
_STAGE_RETRY_POLICIES: dict[str, StageRetryPolicy] = {
    "evidence_extraction": StageRetryPolicy(max_contract_repairs=None),
    "evidence_extraction_batch": StageRetryPolicy(max_contract_repairs=None),
    "document_map": StageRetryPolicy(
        max_contract_repairs=2, allow_identical_repair_stop=False
    ),
    "document_map_merge": StageRetryPolicy(max_contract_repairs=1),
    # Two repairs so attempt 3 can auto-merge duplicates / accept distribution.
    "concept_cells": StageRetryPolicy(
        max_contract_repairs=2, allow_identical_repair_stop=False
    ),
    # Contract max_attempts is 2: one repair, then a strict second attempt.
    "concept_cells_consolidate": StageRetryPolicy(
        max_contract_repairs=1, allow_identical_repair_stop=False
    ),
    # Attempt 1 errors on a cycle; the final attempt drops the weakest cycle edge.
    "concept_edges": StageRetryPolicy(
        max_contract_repairs=1, allow_identical_repair_stop=False
    ),
    "claim_reconciliation": StageRetryPolicy(max_contract_repairs=1),
    "claim_reconciliation_merge": StageRetryPolicy(max_contract_repairs=1),
    "coverage_audit": StageRetryPolicy(max_contract_repairs=1),
    "episode_plan": StageRetryPolicy(max_contract_repairs=1),
    "glossary": StageRetryPolicy(max_contract_repairs=0),
    "script_verifier": StageRetryPolicy(max_contract_repairs=0),
    "script_reviser": StageRetryPolicy(max_contract_repairs=0),
}
_DEFAULT_STAGE_RETRY_POLICY = StageRetryPolicy(max_contract_repairs=1)


def stage_retry_policy(prompt_id: str) -> StageRetryPolicy:
    return _STAGE_RETRY_POLICIES.get(prompt_id, _DEFAULT_STAGE_RETRY_POLICY)


def classify_error(error: ModelError) -> ErrorClass:
    if not error.retryable:
        return "non_retryable"
    if isinstance(error, ModelRateLimitError):
        return "rate_limit"
    if isinstance(error, ModelTimeoutError):
        return "timeout"
    if isinstance(error, DeterministicValidationError):
        return "deterministic"
    if isinstance(error, SchemaValidationError):
        return "schema"
    if isinstance(error, StructuredOutputError):
        return "schema"
    return "provider"


def error_fingerprint(error: ModelError) -> str:
    message = " ".join(str(error).split())
    return f"{type(error).__name__}:{message}"


def decide_retry(
    error: ModelError,
    *,
    attempt: int,
    max_attempts: int,
    prompt_id: str,
    retry_schema_errors: bool,
    base_delay_seconds: float,
    previous_fingerprint: str | None = None,
    contract_repairs_used: int = 0,
) -> RetryDecision:
    if attempt >= max_attempts:
        return RetryDecision(should_retry=False, stop_reason="max_attempts")
    if not error.retryable:
        return RetryDecision(should_retry=False, stop_reason="non_retryable")

    error_class = classify_error(error)
    if error_class in {"provider", "rate_limit", "timeout"}:
        delay = base_delay_seconds * (2 ** (attempt - 1))
        return RetryDecision(should_retry=True, delay_seconds=delay)

    # Contract / structured-output failures.
    if not isinstance(error, StructuredOutputError):
        delay = base_delay_seconds * (2 ** (attempt - 1))
        return RetryDecision(should_retry=True, delay_seconds=delay)

    if not retry_schema_errors:
        return RetryDecision(should_retry=False, stop_reason="schema_retries_disabled")

    policy = stage_retry_policy(prompt_id)
    if policy.max_contract_repairs is not None and contract_repairs_used >= policy.max_contract_repairs:
        return RetryDecision(should_retry=False, stop_reason="stage_policy")

    fingerprint = error_fingerprint(error)
    if (
        policy.allow_identical_repair_stop
        and previous_fingerprint is not None
        and fingerprint == previous_fingerprint
    ):
        return RetryDecision(should_retry=False, stop_reason="identical_repair")

    return RetryDecision(
        should_retry=True,
        repair_instruction=(
            "The previous response failed the required output contract. "
            f"Correct this problem without changing the task: {error}"
        ),
    )
