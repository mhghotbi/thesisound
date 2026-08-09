from pathlib import Path

ROOT = Path.cwd()


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one formatting anchor in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "src/thesisound/services/eval_harness.py",
    '''    for gate in report.gates:
        lines.append(
            f"| `{gate.name}` | **{gate.status}** | {gate.observed if gate.observed is not None else 'unknown'} | {gate.comparison} {gate.threshold} |"
        )
''',
    '''    for gate in report.gates:
        observed = gate.observed if gate.observed is not None else "unknown"
        lines.append(
            f"| `{gate.name}` | **{gate.status}** | {observed} | "
            f"{gate.comparison} {gate.threshold} |"
        )
''',
)
replace_once(
    "src/thesisound/services/eval_harness.py",
    '''    for case in report.cases:
        lines.append(
            f"| `{case.case_id}` | {case.script_outcome} | {case.checks_verdict} | {case.verification_verdict} | {case.quality_overall if case.quality_overall is not None else 'unknown'} | {case.unsupported_claim_ratio:.3f} | {case.call_count} | {case.cost_micros if case.cost_micros is not None else 'unknown'} |"
        )
''',
    '''    for case in report.cases:
        quality = case.quality_overall if case.quality_overall is not None else "unknown"
        cost = case.cost_micros if case.cost_micros is not None else "unknown"
        lines.append(
            f"| `{case.case_id}` | {case.script_outcome} | {case.checks_verdict} | "
            f"{case.verification_verdict} | {quality} | "
            f"{case.unsupported_claim_ratio:.3f} | {case.call_count} | {cost} |"
        )
''',
)
replace_once(
    "src/thesisound/services/eval_harness.py",
    '''            "Expectations are recorded in the JSON report for human review and are not asserted by this runner.",
''',
    '''            "Expectations are recorded in the JSON report for human review and are "
            "not asserted by this runner.",
''',
)
replace_once(
    "src/thesisound/services/readiness.py",
    '''            f"Kept {retention:.0%} of planned token mass; minimum is {_MIN_PLANNED_TOKEN_RETENTION:.0%}.",
''',
    '''            (
                f"Kept {retention:.0%} of planned token mass; minimum is "
                f"{_MIN_PLANNED_TOKEN_RETENTION:.0%}."
            ),
''',
)
replace_once(
    "src/thesisound/services/readiness.py",
    '''                "The verifier did not pass, but a named human accepted this exact plan-bound script."
''',
    '''                "The verifier did not pass, but a named human accepted this exact "
                "plan-bound script."
''',
)
replace_once(
    "tests/test_eval_harness.py",
    '''        """sources = ["absent.md"]\\n[brief]\\nnormalized_topic = "x"\\ntopic_type = "concept"\\ncentral_question = "x?"\\ntarget_duration_minutes = 5\\n""",
''',
    '''        """sources = ["absent.md"]
[brief]
normalized_topic = "x"
topic_type = "concept"
central_question = "x?"
target_duration_minutes = 5
""",
''',
)
