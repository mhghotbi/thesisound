from __future__ import annotations

from thesisound.script import ScriptCheckReport, VerificationDraft

_VERDICT_RANK = {"reject": 0, "revise": 1, "pass": 2}


def comparison_key(
    checks: ScriptCheckReport,
    verification: VerificationDraft,
) -> tuple[int, float, float, int, int]:
    """Return a lexicographic quality key; higher is better."""

    issues = [*checks.issues, *verification.issues]
    return (
        min(_VERDICT_RANK[checks.verdict], _VERDICT_RANK[verification.verdict]),
        -verification.unsupported_claim_ratio,
        verification.quality.overall if verification.quality is not None else 0.0,
        -sum(issue.severity == "blocking" for issue in issues),
        -len(issues),
    )


def is_better(
    candidate: tuple[ScriptCheckReport, VerificationDraft],
    incumbent: tuple[ScriptCheckReport, VerificationDraft],
) -> bool:
    """Return true only when candidate strictly outranks incumbent.

    A tie keeps the original because the revision bought no measurable benefit.
    """

    return comparison_key(*candidate) > comparison_key(*incumbent)
