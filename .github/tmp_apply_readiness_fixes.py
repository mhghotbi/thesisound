from pathlib import Path

readiness_path = Path("src/thesisound/services/readiness.py")
text = readiness_path.read_text(encoding="utf-8")

old_project = '''    project_path = root / str(project_id) / "project.json"\n    if not project_path.exists():\n        raise FileNotFoundError(f"Project not found: {project_id}")\n    project = Project.model_validate_json(project_path.read_text(encoding="utf-8"))\n    definitions = {gate.code: gate for gate in GATE_REGISTRY}\n    if project.state == ProjectState.DRAFT:\n'''
new_project = '''    project_path = root / str(project_id) / "project.json"\n    if not project_path.exists():\n        raise FileNotFoundError(f"Project not found: {project_id}")\n    definitions = {gate.code: gate for gate in GATE_REGISTRY}\n    try:\n        project = Project.model_validate_json(project_path.read_text(encoding="utf-8"))\n    except (OSError, ValueError) as exc:\n        detail = f"Project artifact is unreadable: {exc}"\n        return [\n            GateResult(\n                code=gate.code,\n                label=gate.label_en,\n                actor=gate.actor,\n                status="unknown",\n                detail=detail,\n                evidence=str(project_path),\n            )\n            for gate in GATE_REGISTRY\n        ]\n    if project.state == ProjectState.DRAFT:\n'''
if text.count(old_project) != 1:
    raise SystemExit("project load anchor did not match exactly once")
text = text.replace(old_project, new_project)

old_script = '''    except (OSError, ValueError) as exc:\n        for code in script_codes:\n            set_result(\n                code,\n                "unknown",\n                f"Script plan binding is unreadable: {exc}",\n                script_dir,\n            )\n        return\n\n    try:\n        checks = store.load_latest_checks(project_id)\n'''
new_script = '''    except (OSError, ValueError) as exc:\n        for code in script_codes:\n            set_result(\n                code,\n                "unknown",\n                f"Script plan binding is unreadable: {exc}",\n                script_dir,\n            )\n        return\n\n    try:\n        verified_artifacts = store.has_verified_artifacts(project_id, plan_hash=current_hash)\n        reviewable_artifacts = (\n            project.state == ProjectState.SCRIPT_REVIEW_REQUIRED\n            and store.has_reviewable_artifacts(project_id, plan_hash=current_hash)\n        )\n    except (OSError, ValueError) as exc:\n        for code in script_codes:\n            set_result(\n                code,\n                "unknown",\n                f"Script artifact set is unreadable: {exc}",\n                script_dir,\n            )\n        return\n\n    script_artifacts_required = project.state in {\n        ProjectState.SCRIPT_REVIEW_REQUIRED,\n        ProjectState.SCRIPT_VERIFIED,\n        ProjectState.AUDIO_GENERATING,\n        ProjectState.AUDIO_READY,\n        ProjectState.AUDIO_VERIFYING,\n        ProjectState.COMPLETE,\n    }\n    if script_artifacts_required and not (verified_artifacts or reviewable_artifacts):\n        for code in script_codes:\n            set_result(\n                code,\n                "blocked",\n                "The current project state requires a complete current-plan script artifact set.",\n                script_dir,\n            )\n        return\n\n    try:\n        checks = store.load_latest_checks(project_id)\n'''
if text.count(old_script) != 1:
    raise SystemExit("script readiness anchor did not match exactly once")
text = text.replace(old_script, new_script)
readiness_path.write_text(text, encoding="utf-8")

test_path = Path("tests/test_readiness.py")
tests = test_path.read_text(encoding="utf-8")
old_domain_import = '''    ResearchBrief,\n    TopicType,\n)\n'''
new_domain_import = '''    ResearchBrief,\n    Script,\n    ScriptTurn,\n    TopicType,\n)\n'''
if tests.count(old_domain_import) != 1:
    raise SystemExit("domain import anchor did not match exactly once")
tests = tests.replace(old_domain_import, new_domain_import)
old_script_import = '''from thesisound.script import ScriptCheckReport, ScriptReviewDecision, VerificationDraft\n'''
new_script_import = '''from thesisound.script import (\n    ScriptCheckReport,\n    ScriptPipelineManifest,\n    ScriptReviewDecision,\n    VerificationDraft,\n)\n'''
if tests.count(old_script_import) != 1:
    raise SystemExit("script import anchor did not match exactly once")
tests = tests.replace(old_script_import, new_script_import)
old_fixture = '''    store.save_verification(\n        project.project_id,\n        VerificationDraft(verdict="revise", unsupported_claim_ratio=0.1),\n    )\n    plan_hash = current_hash\n'''
new_fixture = '''    store.save_verification(\n        project.project_id,\n        VerificationDraft(verdict="revise", unsupported_claim_ratio=0.1),\n    )\n    store.save_script(\n        project.project_id,\n        Script(\n            title="Reviewed script",\n            turns=[\n                ScriptTurn(\n                    turn_id="turn-1",\n                    segment_id="seg-1",\n                    speaker="A",\n                    spoken_text_fa="متن بازبینی‌شده",\n                    editorial_only=True,\n                )\n            ],\n        ),\n    )\n    store.save_manifest(\n        ScriptPipelineManifest(\n            project_id=project.project_id,\n            status="verified",\n            segment_count=1,\n            turn_count=1,\n        )\n    )\n    plan_hash = current_hash\n'''
if tests.count(old_fixture) != 1:
    raise SystemExit("reviewed fixture anchor did not match exactly once")
tests = tests.replace(old_fixture, new_fixture)
append = '''\n\ndef test_corrupt_project_artifact_yields_unknown_for_every_gate(tmp_path: Path) -> None:\n    root = tmp_path / "workspaces"\n    project = _project()\n    WorkspaceStore(root).save_project(project)\n    project_path = root / str(project.project_id) / "project.json"\n    project_path.write_text('{"project_id":', encoding="utf-8")\n\n    results = project_readiness(project_id=project.project_id, workspace_root=root)\n\n    assert results\n    assert all(result.status == "unknown" for result in results)\n    assert all(result.evidence == str(project_path) for result in results)\n\n\ndef test_verified_state_requires_complete_verified_script_artifacts(tmp_path: Path) -> None:\n    root = tmp_path / "workspaces"\n    project = _project(ProjectState.SCRIPT_VERIFIED)\n    WorkspaceStore(root).save_project(project)\n    assert project.episode_plan is not None\n    store = ScriptArtifactStore(root)\n    current_hash = episode_plan_hash(project.episode_plan)\n    store.prepare_for_plan(project.project_id, current_hash)\n    store.save_checks(\n        ScriptCheckReport(\n            project_id=project.project_id,\n            verdict="pass",\n            word_count=100,\n            estimated_minutes=1,\n            substantive_turn_count=2,\n        )\n    )\n    store.save_verification(\n        project.project_id,\n        VerificationDraft(verdict="pass", unsupported_claim_ratio=0),\n    )\n    # Deliberately omit the script and manifest. The individual reports pass,\n    # but the plan requires readiness to verify the complete artifact set.\n\n    results = project_readiness(project_id=project.project_id, workspace_root=root)\n\n    assert _result(results, "script-checks").status == "blocked"\n    assert _result(results, "independent-verification").status == "blocked"\n    assert _result(results, "script-review-decision").status == "blocked"\n'''
if "test_corrupt_project_artifact_yields_unknown_for_every_gate" in tests:
    raise SystemExit("tests already appended")
test_path.write_text(tests.rstrip() + append + "\n", encoding="utf-8")
