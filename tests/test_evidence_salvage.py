from __future__ import annotations

import pytest

from thesisound.domain import ClaimType
from thesisound.modeling import DeterministicValidationError, StructuredOutputError
from thesisound.services.evidence_extractor import ExcerptNotFoundError, _validate_claim_excerpt
from thesisound.services.model_retry import decide_retry, error_fingerprint
from thesisound.source_analysis import EvidenceClaimDraft


def _claim(excerpt: str) -> EvidenceClaimDraft:
    return EvidenceClaimDraft(
        claim="A test claim.",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt=excerpt,
        support_kind="direct",
        confidence=0.9,
    )


def test_excerpt_not_found_has_a_distinct_retryable_error_type() -> None:
    with pytest.raises(ExcerptNotFoundError) as missing:
        _validate_claim_excerpt(_claim("This excerpt is absent."), "A real source block.")
    with pytest.raises(DeterministicValidationError) as short:
        _validate_claim_excerpt(_claim("too short"), "A real source block.")

    assert isinstance(missing.value, StructuredOutputError)
    assert not isinstance(short.value, ExcerptNotFoundError)
    for error in (missing.value, short.value):
        assert decide_retry(
            error,
            attempt=1,
            max_attempts=3,
            prompt_id="evidence_extraction",
            retry_schema_errors=True,
            base_delay_seconds=0,
        ).should_retry


def test_excerpt_not_found_fingerprint_distinguishes_which_excerpt_failed() -> None:
    """A bare constant message collides on the retry loop's identical_repair guard.

    Observed in production (source 2bb3ca40, block dc0fd1d5fdfb): two attempts
    raised ExcerptNotFoundError for two different, genuinely different bad
    excerpts, but decide_retry saw one identical fingerprint and stopped after
    2 of the configured 3 attempts -- burning the retry budget that
    evidence_extraction's stage policy (max_contract_repairs=None) exists to
    grant this exact error class.
    """

    with pytest.raises(ExcerptNotFoundError) as first:
        _validate_claim_excerpt(_claim("This excerpt is absent."), "A real source block.")
    with pytest.raises(ExcerptNotFoundError) as second:
        _validate_claim_excerpt(_claim("A different missing excerpt text."), "A real source block.")
    with pytest.raises(ExcerptNotFoundError) as repeat_of_first:
        _validate_claim_excerpt(_claim("This excerpt is absent."), "A real source block.")

    assert error_fingerprint(first.value) != error_fingerprint(second.value)
    # A genuinely repeated mistake must still collide, or identical_repair can
    # never fire and a truly stuck model retries to no purpose every time.
    assert error_fingerprint(first.value) == error_fingerprint(repeat_of_first.value)

    decision = decide_retry(
        second.value,
        attempt=2,
        max_attempts=3,
        prompt_id="evidence_extraction",
        retry_schema_errors=True,
        base_delay_seconds=0,
        previous_fingerprint=error_fingerprint(first.value),
    )
    assert decision.should_retry
    assert decision.stop_reason is None
