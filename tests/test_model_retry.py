from __future__ import annotations

from thesisound.modeling import (
    DeterministicValidationError,
    ModelRateLimitError,
    ModelTimeoutError,
    SchemaValidationError,
)
from thesisound.services.model_retry import (
    classify_error,
    decide_retry,
    error_fingerprint,
)


def test_classify_error_splits_provider_and_contract_classes() -> None:
    assert classify_error(ModelTimeoutError("timeout")) == "timeout"
    assert classify_error(ModelRateLimitError("429")) == "rate_limit"
    assert classify_error(SchemaValidationError("bad json")) == "schema"
    assert classify_error(DeterministicValidationError("bad claim")) == "deterministic"
    assert classify_error(ModelTimeoutError("blocked", retryable=False)) == "non_retryable"


def test_evidence_allows_contract_repair() -> None:
    decision = decide_retry(
        DeterministicValidationError("excerpt missing"),
        attempt=1,
        max_attempts=3,
        prompt_id="evidence_extraction",
        retry_schema_errors=True,
        base_delay_seconds=0,
    )
    assert decision.should_retry
    assert decision.repair_instruction is not None
    assert decision.stop_reason is None


def test_episode_plan_allows_one_contract_repair_and_provider_retry() -> None:
    """episode_plan gets one repair chance (2026-08-13), unlike glossary/verifier/reviser.

    An invented claim ID is a scoped, nameable mistake a repair instruction can
    fix; see the _STAGE_RETRY_POLICIES comment for the audit-R7 context this
    revises.
    """

    first_attempt = decide_retry(
        DeterministicValidationError("references unknown claim IDs: clm-999"),
        attempt=1,
        max_attempts=2,
        prompt_id="episode_plan",
        retry_schema_errors=True,
        base_delay_seconds=0.5,
    )
    assert first_attempt.should_retry
    assert first_attempt.repair_instruction is not None

    # max_attempts=5 here (vs. the contract's real 2) isolates the stage_policy
    # ceiling from the attempt ceiling -- they coincide at the contract's real
    # max_attempts=2, which would make this assert the wrong stop_reason.
    second_attempt = decide_retry(
        DeterministicValidationError("references unknown claim IDs: clm-999"),
        attempt=2,
        max_attempts=5,
        prompt_id="episode_plan",
        retry_schema_errors=True,
        base_delay_seconds=0.5,
        contract_repairs_used=1,
    )
    assert not second_attempt.should_retry
    assert second_attempt.stop_reason == "stage_policy"

    provider = decide_retry(
        ModelTimeoutError("timeout"),
        attempt=1,
        max_attempts=2,
        prompt_id="episode_plan",
        retry_schema_errors=True,
        base_delay_seconds=0.5,
    )
    assert provider.should_retry
    assert provider.delay_seconds == 0.5
    assert provider.repair_instruction is None


def test_glossary_and_verifier_follow_zero_contract_repair_policy() -> None:
    for prompt_id in ("glossary", "script_verifier", "script_reviser"):
        decision = decide_retry(
            SchemaValidationError("invalid"),
            attempt=1,
            max_attempts=2,
            prompt_id=prompt_id,
            retry_schema_errors=True,
            base_delay_seconds=0,
        )
        assert not decision.should_retry
        assert decision.stop_reason == "stage_policy"


def test_identical_fingerprint_stops_further_contract_repairs() -> None:
    error = DeterministicValidationError("value must equal good")
    fingerprint = error_fingerprint(error)
    decision = decide_retry(
        error,
        attempt=2,
        max_attempts=3,
        prompt_id="evidence_extraction",
        retry_schema_errors=True,
        base_delay_seconds=0,
        previous_fingerprint=fingerprint,
        contract_repairs_used=1,
    )
    assert not decision.should_retry
    assert decision.stop_reason == "identical_repair"


def test_document_map_allows_two_contract_repairs_so_final_attempt_can_drop_key_concepts() -> None:
    first = decide_retry(
        DeterministicValidationError("key_concepts missing from blocks"),
        attempt=1,
        max_attempts=3,
        prompt_id="document_map",
        retry_schema_errors=True,
        base_delay_seconds=0,
        contract_repairs_used=0,
    )
    assert first.should_retry

    repeated = decide_retry(
        DeterministicValidationError("key_concepts missing from blocks"),
        attempt=2,
        max_attempts=3,
        prompt_id="document_map",
        retry_schema_errors=True,
        base_delay_seconds=0,
        previous_fingerprint=error_fingerprint(
            DeterministicValidationError("key_concepts missing from blocks")
        ),
        contract_repairs_used=1,
    )
    assert repeated.should_retry

    third = decide_retry(
        DeterministicValidationError("different problem"),
        attempt=3,
        max_attempts=3,
        prompt_id="document_map",
        retry_schema_errors=True,
        base_delay_seconds=0,
        previous_fingerprint=error_fingerprint(
            DeterministicValidationError("key_concepts missing from blocks")
        ),
        contract_repairs_used=2,
    )
    assert not third.should_retry
    assert third.stop_reason == "max_attempts"


def test_different_fingerprint_can_still_repair_when_budget_remains() -> None:
    decision = decide_retry(
        DeterministicValidationError("second distinct failure"),
        attempt=2,
        max_attempts=3,
        prompt_id="evidence_extraction",
        retry_schema_errors=True,
        base_delay_seconds=0,
        previous_fingerprint=error_fingerprint(DeterministicValidationError("first failure")),
        contract_repairs_used=1,
    )
    assert decision.should_retry
    assert "second distinct failure" in (decision.repair_instruction or "")


def test_retry_schema_errors_false_stops_with_explicit_reason() -> None:
    decision = decide_retry(
        SchemaValidationError("bad"),
        attempt=1,
        max_attempts=3,
        prompt_id="evidence_extraction",
        retry_schema_errors=False,
        base_delay_seconds=0,
    )
    assert not decision.should_retry
    assert decision.stop_reason == "schema_retries_disabled"
