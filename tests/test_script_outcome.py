from __future__ import annotations

from uuid import uuid4

from thesisound.domain import VerificationIssue
from thesisound.script import (
    ScriptCheckIssue,
    ScriptCheckReport,
    ScriptQualityScore,
    VerificationDraft,
)
from thesisound.services.script_outcome import script_outcome


def _checks(verdict: str = "pass", issues=None) -> ScriptCheckReport:
    return ScriptCheckReport(
        project_id=uuid4(),
        verdict=verdict,
        issues=issues or [],
        word_count=100,
        estimated_minutes=1,
        substantive_turn_count=2,
    )


def _quality(value: float) -> ScriptQualityScore:
    return ScriptQualityScore(
        evidence_fidelity=value,
        qualification_preservation=value,
        stance_and_disagreement=value,
        terminology_consistency=value,
        listenability=value,
    )


def test_blocking_deterministic_issue_rejects() -> None:
    issue = ScriptCheckIssue(
        severity="blocking",
        issue_type="missing_grounding",
        explanation="Grounding is missing.",
    )
    outcome, _ = script_outcome(
        _checks("reject", [issue]),
        VerificationDraft(verdict="pass", unsupported_claim_ratio=0),
    )
    assert outcome == "rejected"


def test_nonblocking_verifier_failure_requires_review() -> None:
    issue = VerificationIssue(
        turn_id="turn-1",
        severity="high",
        issue_type="lost_qualification",
        explanation="A qualification was lost.",
        required_revision="Restore it.",
    )
    outcome, reason = script_outcome(
        _checks(),
        VerificationDraft(verdict="revise", unsupported_claim_ratio=0.1, issues=[issue]),
    )
    assert outcome == "review_required"
    assert reason


def test_quality_gate_is_off_when_threshold_is_none() -> None:
    outcome, _ = script_outcome(
        _checks(),
        VerificationDraft(
            verdict="pass",
            unsupported_claim_ratio=0,
            quality=_quality(0.2),
        ),
    )
    assert outcome == "verified"


def test_quality_gate_downgrades_when_enabled() -> None:
    outcome, _ = script_outcome(
        _checks(),
        VerificationDraft(
            verdict="pass",
            unsupported_claim_ratio=0,
            quality=_quality(0.2),
        ),
        min_overall=0.7,
    )
    assert outcome == "review_required"
