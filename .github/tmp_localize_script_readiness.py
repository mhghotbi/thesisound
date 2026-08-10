from pathlib import Path

path = Path("src/thesisound/services/readiness.py")
text = path.read_text(encoding="utf-8")
old = '''    try:\n        verified_artifacts = store.has_verified_artifacts(project_id, plan_hash=current_hash)\n        reviewable_artifacts = (\n            project.state == ProjectState.SCRIPT_REVIEW_REQUIRED\n            and store.has_reviewable_artifacts(project_id, plan_hash=current_hash)\n        )\n    except (OSError, ValueError) as exc:\n        for code in script_codes:\n            set_result(\n                code,\n                "unknown",\n                f"Script artifact set is unreadable: {exc}",\n                script_dir,\n            )\n        return\n\n    script_artifacts_required = project.state in {\n        ProjectState.SCRIPT_REVIEW_REQUIRED,\n        ProjectState.SCRIPT_VERIFIED,\n        ProjectState.AUDIO_GENERATING,\n        ProjectState.AUDIO_READY,\n        ProjectState.AUDIO_VERIFYING,\n        ProjectState.COMPLETE,\n    }\n    if script_artifacts_required and not (verified_artifacts or reviewable_artifacts):\n        for code in script_codes:\n            set_result(\n                code,\n                "blocked",\n                "The current project state requires a complete current-plan script artifact set.",\n                script_dir,\n            )\n        return\n\n'''
new = '''    artifact_set_error: str | None = None\n    try:\n        verified_artifacts = store.has_verified_artifacts(project_id, plan_hash=current_hash)\n        reviewable_artifacts = (\n            project.state == ProjectState.SCRIPT_REVIEW_REQUIRED\n            and store.has_reviewable_artifacts(project_id, plan_hash=current_hash)\n        )\n    except (OSError, ValueError) as exc:\n        verified_artifacts = False\n        reviewable_artifacts = False\n        artifact_set_error = str(exc)\n\n'''
if text.count(old) != 1:
    raise SystemExit("script aggregate anchor did not match exactly once")
text = text.replace(old, new)

old_verified = '''    try:\n        verification = store.load_latest_verification(project_id)\n        verified_normally = (\n'''
new_verified = '''    verified_normally = False\n    try:\n        verification = store.load_latest_verification(project_id)\n        verified_normally = (\n'''
if text.count(old_verified) != 1:
    raise SystemExit("verification anchor did not match exactly once")
text = text.replace(old_verified, new_verified)

anchor = '''        set_result(\n            "script-review-decision",\n            "pass" if accepted else "blocked",\n            "The named review acceptance is bound to the current plan."\n            if accepted\n            else "The review decision is not an accepted decision for the current plan.",\n            script_dir / "review-decision.json",\n        )\n\n\ndef _audio_results'''
insertion = '''        set_result(\n            "script-review-decision",\n            "pass" if accepted else "blocked",\n            "The named review acceptance is bound to the current plan."\n            if accepted\n            else "The review decision is not an accepted decision for the current plan.",\n            script_dir / "review-decision.json",\n        )\n\n    if project.state == ProjectState.SCRIPT_REVIEW_REQUIRED and not reviewable_artifacts:\n        if artifact_set_error is not None and decision_error is None:\n            set_result(\n                "script-review-decision",\n                "unknown",\n                f"Reviewable script artifact set is unreadable: {artifact_set_error}",\n                script_dir,\n            )\n        elif artifact_set_error is None and decision_error is None:\n            set_result(\n                "script-review-decision",\n                "blocked",\n                "Human review requires a complete current-plan reviewable script artifact set.",\n                script_dir,\n            )\n\n    verified_state = project.state in {\n        ProjectState.SCRIPT_VERIFIED,\n        ProjectState.AUDIO_GENERATING,\n        ProjectState.AUDIO_READY,\n        ProjectState.AUDIO_VERIFYING,\n        ProjectState.COMPLETE,\n    }\n    if verified_state and not verified_artifacts:\n        if artifact_set_error is not None:\n            # A corrupt review decision is reported by its own human gate. When\n            # the independent verifier already passed normally, do not let that\n            # unrelated optional artifact erase the machine-verification result.\n            if not (decision_error is not None and verified_normally):\n                set_result(\n                    "independent-verification",\n                    "unknown",\n                    f"Verified script artifact set is unreadable: {artifact_set_error}",\n                    script_dir,\n                )\n        else:\n            set_result(\n                "independent-verification",\n                "blocked",\n                "The current state requires a complete current-plan verified script artifact set.",\n                script_dir,\n            )\n\n\ndef _audio_results'''
if text.count(anchor) != 1:
    raise SystemExit("script review tail anchor did not match exactly once")
text = text.replace(anchor, insertion)
path.write_text(text, encoding="utf-8")

test_path = Path("tests/test_readiness.py")
tests = test_path.read_text(encoding="utf-8")
old_asserts = '''    assert _result(results, "independent-verification").status == "unknown"\n    assert _result(results, "script-review-decision").status == "unknown"\n'''
new_asserts = '''    assert _result(results, "script-checks").status == "pass"\n    assert _result(results, "independent-verification").status == "unknown"\n    assert _result(results, "script-review-decision").status == "unknown"\n'''
if tests.count(old_asserts) != 1:
    raise SystemExit("corrupt review assertion anchor did not match exactly once")
tests = tests.replace(old_asserts, new_asserts)

old_incomplete = '''    assert _result(results, "script-checks").status == "blocked"\n    assert _result(results, "independent-verification").status == "blocked"\n    assert _result(results, "script-review-decision").status == "blocked"\n'''
new_incomplete = '''    assert _result(results, "script-checks").status == "pass"\n    assert _result(results, "independent-verification").status == "blocked"\n    assert _result(results, "script-review-decision").status == "not_reached"\n'''
# Only replace the final incomplete-artifact test occurrence, not stale-plan tests.
pos = tests.rfind(old_incomplete)
if pos == -1:
    raise SystemExit("incomplete artifact assertion anchor not found")
tests = tests[:pos] + new_incomplete + tests[pos + len(old_incomplete):]

test_path.write_text(tests, encoding="utf-8")
