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


def test_episode_plan_rejects_contract_repair_but_allows_provider_retry() -> None:
    contract = decide_retry(
        DeterministicValidationError("bad duration"),
        attempt=1,
        max_attempts=2,
        prompt_id="episode_plan",
        retry_schema_errors=True,
        base_delay_seconds=0.5,
    )
    assert not contract.should_retry
    assert contract.stop_reason == "stage_policy"

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


def test_document_map_allows_one_contract_repair_then_stops() -> None:
    first = decide_retry(
        DeterministicValidationError("section missing"),
        attempt=1,
        max_attempts=3,
        prompt_id="document_map",
        retry_schema_errors=True,
        base_delay_seconds=0,
        contract_repairs_used=0,
    )
    assert first.should_retry

    second = decide_retry(
        DeterministicValidationError("different problem"),
        attempt=2,
        max_attempts=3,
        prompt_id="document_map",
        retry_schema_errors=True,
        base_delay_seconds=0,
        previous_fingerprint=error_fingerprint(DeterministicValidationError("section missing")),
        contract_repairs_used=1,
    )
    assert not second.should_retry
    assert second.stop_reason == "stage_policy"


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
