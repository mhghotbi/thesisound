from __future__ import annotations

import pytest

from thesisound.domain import ClaimType
from thesisound.modeling import DeterministicValidationError, StructuredOutputError
from thesisound.services.evidence_extractor import ExcerptNotFoundError, _validate_claim_excerpt
from thesisound.services.model_retry import decide_retry
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
            retry_schema_errors=True,
            base_delay_seconds=0,
        ).should_retry
