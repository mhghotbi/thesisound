from __future__ import annotations

from typing import Literal

from thesisound.script import ScriptCheckReport, VerificationDraft

ScriptOutcome = Literal["verified", "review_required", "rejected"]


def script_outcome(
    checks: ScriptCheckReport,
    verification: VerificationDraft,
    *,
    min_overall: float | None = None,
) -> tuple[ScriptOutcome, str]:
    """Classify a completed script attempt without weakening deterministic blocks."""

    blocking = [
        issue.explanation
        for issue in [*checks.issues, *verification.issues]
        if issue.severity == "blocking"
    ]
    if checks.verdict == "reject" or blocking:
        return "rejected", blocking[0] if blocking else "Deterministic checks rejected the script."
    if (
        checks.verdict == "pass"
        and verification.verdict == "pass"
        and verification.unsupported_claim_ratio == 0
    ):
        overall = verification.quality.overall if verification.quality is not None else None
        if min_overall is not None and (overall is None or overall < min_overall):
            return "review_required", (
                "Script passed verification but did not meet the enabled quality threshold."
            )
        return "verified", "Script passed deterministic checks and independent verification."
    return "review_required", (
        "Script has no deterministic blocking violation but independent verification "
        "left issues for a named human decision."
    )
