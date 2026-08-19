from __future__ import annotations

import pytest

from thesisound.domain import VerificationIssue
from thesisound.modeling import DeterministicValidationError
from thesisound.prompt_loader import PromptLoader
from thesisound.script import (
    _QUALITY_WEIGHTS,
    ScriptCheckIssue,
    ScriptCheckReport,
    ScriptQualityScore,
    VerificationDraft,
)
from thesisound.services.script_quality import comparison_key, is_better
from thesisound.services.script_verifier import _validate_verification


def _quality(**overrides: float | str) -> ScriptQualityScore:
    values: dict[str, float | str] = {
        "evidence_fidelity": 0.8,
        "qualification_preservation": 0.7,
        "stance_and_disagreement": 0.6,
        "terminology_consistency": 0.9,
        "listenability": 1.0,
        "actionable_feedback": "Fix the highest-impact issue.",
    }
    values.update(overrides)
    return ScriptQualityScore.model_validate(values)


def _issue() -> VerificationIssue:
    return VerificationIssue(
        turn_id="turn-1",
        severity="high",
        issue_type="lost_qualification",
        explanation="A qualification was lost.",
        required_revision="Restore the qualification.",
    )


def test_quality_overall_uses_documented_weighted_sum() -> None:
    quality = _quality()

    assert quality.overall == round(
        0.8 * 0.30 + 0.7 * 0.25 + 0.6 * 0.20 + 0.9 * 0.15 + 1.0 * 0.10,
        4,
    )
    assert _quality(
        evidence_fidelity=1.0,
        qualification_preservation=1.0,
        stance_and_disagreement=1.0,
        terminology_consistency=1.0,
        listenability=1.0,
    ).overall == 1.0
    assert _quality(
        evidence_fidelity=0.0,
        qualification_preservation=0.0,
        stance_and_disagreement=0.0,
        terminology_consistency=0.0,
        listenability=0.0,
    ).overall == 0.0


def test_quality_weights_sum_to_one() -> None:
    assert sum(_QUALITY_WEIGHTS.values()) == pytest.approx(1.0)


def test_legacy_verification_without_quality_remains_loadable() -> None:
    draft = VerificationDraft.model_validate(
        {"verdict": "pass", "issues": [], "unsupported_claim_ratio": 0}
    )

    assert draft.quality is None


def test_missing_quality_is_rejected_by_current_verifier() -> None:
    draft = VerificationDraft(
        verdict="pass", issues=[], unsupported_claim_ratio=0
    )

    with pytest.raises(
        DeterministicValidationError,
        match="Verification must include quality scores",
    ):
        _validate_verification(draft, {"turn-1"})


def test_non_pass_requires_actionable_feedback() -> None:
    draft = VerificationDraft(
        verdict="revise",
        issues=[_issue()],
        unsupported_claim_ratio=0,
        quality=_quality(actionable_feedback=" "),
    )

    with pytest.raises(DeterministicValidationError, match="actionable feedback"):
        _validate_verification(draft, {"turn-1"})


def test_unsupported_claims_cannot_have_perfect_evidence_fidelity() -> None:
    issue = VerificationIssue(
        turn_id="turn-1",
        severity="high",
        issue_type="unsupported_claim",
        explanation="Unsupported.",
        required_revision="Remove it.",
    )
    draft = VerificationDraft(
        verdict="revise",
        issues=[issue],
        unsupported_claim_ratio=0.2,
        quality=_quality(evidence_fidelity=1.0),
    )

    with pytest.raises(DeterministicValidationError, match="evidence fidelity"):
        _validate_verification(draft, {"turn-1"})


def test_well_formed_current_verification_is_accepted() -> None:
    draft = VerificationDraft(
        verdict="revise",
        issues=[_issue()],
        unsupported_claim_ratio=0,
        quality=_quality(),
    )

    _validate_verification(draft, {"turn-1"})


def test_latest_script_verifier_contract_is_1_2_0() -> None:
    contract = PromptLoader().load_contract("script_verifier")

    assert contract.version == "1.2.0"
    assert contract.output_model == "VerificationDraft"


def _checks(
    verdict: str = "pass",
    *,
    blocking: int = 0,
    other: int = 0,
) -> ScriptCheckReport:
    issues = [
        ScriptCheckIssue(
            severity="blocking", issue_type="other", explanation="blocking"
        )
        for _ in range(blocking)
    ] + [
        ScriptCheckIssue(severity="high", issue_type="other", explanation="other")
        for _ in range(other)
    ]
    return ScriptCheckReport(
        project_id=__import__("uuid").uuid4(),
        verdict=verdict,
        issues=issues,
        word_count=1,
        estimated_minutes=1,
        substantive_turn_count=1,
    )


def _verification(
    verdict: str = "pass",
    *,
    ratio: float = 0,
    score: float = 0.8,
    blocking: int = 0,
    other: int = 0,
) -> VerificationDraft:
    issues = [
        VerificationIssue(
            turn_id="turn-1",
            severity="blocking",
            issue_type="other",
            explanation="blocking",
            required_revision="fix",
        )
        for _ in range(blocking)
    ] + [
        VerificationIssue(
            turn_id="turn-1",
            severity="high",
            issue_type="other",
            explanation="other",
            required_revision="fix",
        )
        for _ in range(other)
    ]
    return VerificationDraft(
        verdict=verdict,
        issues=issues,
        unsupported_claim_ratio=ratio,
        quality=_quality(
            evidence_fidelity=score,
            qualification_preservation=score,
            stance_and_disagreement=score,
            terminology_consistency=score,
            listenability=score,
        ),
    )


def test_comparison_key_orders_each_boundary() -> None:
    assert comparison_key(_checks(), _verification("pass")) > comparison_key(
        _checks(), _verification("revise")
    )
    assert comparison_key(_checks(), _verification(ratio=0.1)) > comparison_key(
        _checks(), _verification(ratio=0.2)
    )
    assert comparison_key(_checks(), _verification(score=0.9)) > comparison_key(
        _checks(), _verification(score=0.8)
    )
    assert comparison_key(
        _checks(), _verification(blocking=0, other=1)
    ) > comparison_key(_checks(), _verification(blocking=1))
    assert comparison_key(_checks(), _verification(other=1)) > comparison_key(
        _checks(), _verification(other=2)
    )


def test_is_better_is_strict_and_ties_keep_incumbent() -> None:
    candidate = (_checks(), _verification())
    assert is_better(candidate, candidate) is False
