from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    if new in content:
        return
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one anchor in {path!r}, found {count}")
    write(path, content.replace(old, new, 1))


replace_once(
    "src/thesisound/script.py",
    "\n\nclass RevisedTurnDraft(BaseModel):\n",
    '''\n\nclass RevisionDecision(BaseModel):\n    project_id: UUID\n    accepted: bool\n    reason: str\n    original_verdict: str\n    revised_verdict: str | None\n    original_overall: float | None\n    revised_overall: float | None\n    delta: float | None\n    original_issue_count: int\n    revised_issue_count: int | None\n    changed_turn_count: int\n    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))\n\n\nclass RevisedTurnDraft(BaseModel):\n''',
)

write(
    "src/thesisound/services/script_quality.py",
    '''from __future__ import annotations\n\nfrom thesisound.script import ScriptCheckReport, VerificationDraft\n\n_VERDICT_RANK = {"reject": 0, "revise": 1, "pass": 2}\n\n\ndef comparison_key(\n    checks: ScriptCheckReport,\n    verification: VerificationDraft,\n) -> tuple[int, float, float, int, int]:\n    """Return a lexicographic quality key; higher is better."""\n\n    issues = [*checks.issues, *verification.issues]\n    return (\n        min(_VERDICT_RANK[checks.verdict], _VERDICT_RANK[verification.verdict]),\n        -verification.unsupported_claim_ratio,\n        verification.quality.overall if verification.quality is not None else 0.0,\n        -sum(issue.severity == "blocking" for issue in issues),\n        -len(issues),\n    )\n\n\ndef is_better(\n    candidate: tuple[ScriptCheckReport, VerificationDraft],\n    incumbent: tuple[ScriptCheckReport, VerificationDraft],\n) -> bool:\n    """Return true only when candidate strictly outranks incumbent.\n\n    A tie keeps the original because the revision bought no measurable benefit.\n    """\n\n    return comparison_key(*candidate) > comparison_key(*incumbent)\n''',
)

replace_once(
    "src/thesisound/services/script_artifact_store.py",
    "    ScriptPipelineManifest,\n",
    "    RevisionDecision,\n    ScriptPipelineManifest,\n",
)
replace_once(
    "src/thesisound/services/script_artifact_store.py",
    '''    def has_revised_script(self, project_id: UUID) -> bool:\n        return (self.script_dir(project_id, create=False) / "script-revised.json").exists()\n''',
    '''    def save_revision_decision(self, decision: RevisionDecision) -> None:\n        self._write_json(\n            self.script_dir(decision.project_id) / "revision-decision.json",\n            decision,\n        )\n\n    def load_revision_decision_optional(\n        self, project_id: UUID\n    ) -> RevisionDecision | None:\n        path = self.script_dir(project_id, create=False) / "revision-decision.json"\n        try:\n            return RevisionDecision.model_validate_json(path.read_text(encoding="utf-8"))\n        except FileNotFoundError:\n            return None\n\n    def has_revised_script(self, project_id: UUID) -> bool:\n        if not (\n            self.script_dir(project_id, create=False) / "script-revised.json"\n        ).exists():\n            return False\n        decision = self.load_revision_decision_optional(project_id)\n        # Artifacts written before revision decisions existed have no file; keep\n        # the old "a revision exists, so use it" behaviour for them.\n        return True if decision is None else decision.accepted\n''',
)

replace_once(
    "src/thesisound/services/script_pipeline_service.py",
    "    ScriptPipelineManifest,\n",
    "    RevisionDecision,\n    ScriptPipelineManifest,\n",
)
replace_once(
    "src/thesisound/services/script_pipeline_service.py",
    "from thesisound.services.script_reviser import TargetedScriptReviserService\n",
    "from thesisound.services.script_quality import is_better\n"
    "from thesisound.services.script_reviser import TargetedScriptReviserService\n",
)
replace_once(
    "src/thesisound/services/script_pipeline_service.py",
    '''                if revised_checks.verdict != "pass":\n                    raise ValueError("Revised script failed deterministic checks.")\n\n                revised_verification = self.script_store.load_verification_optional(\n''',
    '''                original_script = self.script_store.load_script(project_id)\n                changed_turn_count = sum(\n                    1\n                    for before, after in zip(\n                        original_script.turns, revised.turns, strict=True\n                    )\n                    if before.spoken_text_fa != after.spoken_text_fa\n                )\n                original_overall = (\n                    verification.quality.overall\n                    if verification.quality is not None\n                    else None\n                )\n                original_issue_count = len(checks.issues) + len(verification.issues)\n                if revised_checks.verdict != "pass":\n                    decision = RevisionDecision(\n                        project_id=project_id,\n                        accepted=False,\n                        reason="Revised script failed deterministic checks.",\n                        original_verdict=verification.verdict,\n                        revised_verdict=None,\n                        original_overall=original_overall,\n                        revised_overall=None,\n                        delta=None,\n                        original_issue_count=original_issue_count,\n                        revised_issue_count=None,\n                        changed_turn_count=changed_turn_count,\n                    )\n                    self.script_store.save_revision_decision(decision)\n                    raise ValueError(\n                        "Revised script failed deterministic checks; "\n                        "the original script was kept."\n                    )\n\n                revised_verification = self.script_store.load_verification_optional(\n''',
)
replace_once(
    "src/thesisound/services/script_pipeline_service.py",
    '''                        if revised_verification.quality is not None:\n                            span.measure(\n                                quality_overall=revised_verification.quality.overall\n                            )\n                script = revised\n                checks = revised_checks\n                verification = revised_verification\n\n            if verification.verdict != "pass" or verification.unsupported_claim_ratio != 0:\n                raise ValueError("Script failed verification after one targeted revision.")\n''',
    '''                        if revised_verification.quality is not None:\n                            span.measure(\n                                quality_overall=revised_verification.quality.overall\n                            )\n                revised_overall = (\n                    revised_verification.quality.overall\n                    if revised_verification.quality is not None\n                    else None\n                )\n                delta = (\n                    round(revised_overall - original_overall, 4)\n                    if original_overall is not None and revised_overall is not None\n                    else None\n                )\n                accepted = is_better(\n                    (revised_checks, revised_verification),\n                    (checks, verification),\n                )\n                decision = RevisionDecision(\n                    project_id=project_id,\n                    accepted=accepted,\n                    reason=(\n                        "The revision ranked higher than the original."\n                        if accepted\n                        else "The original ranked equal to or higher than the revision."\n                    ),\n                    original_verdict=verification.verdict,\n                    revised_verdict=revised_verification.verdict,\n                    original_overall=original_overall,\n                    revised_overall=revised_overall,\n                    delta=delta,\n                    original_issue_count=original_issue_count,\n                    revised_issue_count=(\n                        len(revised_checks.issues) + len(revised_verification.issues)\n                    ),\n                    changed_turn_count=changed_turn_count,\n                )\n                self.script_store.save_revision_decision(decision)\n                if decision.accepted:\n                    script = revised\n                    checks = revised_checks\n                    verification = revised_verification\n\n            if verification.verdict != "pass" or verification.unsupported_claim_ratio != 0:\n                kept = "revision" if decision.accepted else "original"\n                before = (\n                    f"{decision.original_overall:.2f}"\n                    if decision.original_overall is not None\n                    else "n/a"\n                )\n                after = (\n                    f"{decision.revised_overall:.2f}"\n                    if decision.revised_overall is not None\n                    else "n/a"\n                )\n                raise ValueError(\n                    "Script failed verification after one targeted revision "\n                    f"(kept the {kept}; quality {before} -> {after})."\n                )\n''',
)

replace_once(
    "src/thesisound/web/script_routes.py",
    '''            "verification": verification,\n            "manifest": manifest,\n''',
    '''            "verification": verification,\n            "revision_decision": (\n                script_store.load_revision_decision_optional(project_id)\n                if artifacts_current\n                else None\n            ),\n            "manifest": manifest,\n''',
)

# Extend the pipeline fake so revision outcomes can be exercised deterministically.
replace_once(
    "tests/test_script_pipeline.py",
    '''class FakeScriptRunner:\n    def __init__(self) -> None:\n        self.verification_calls = 0\n        self.segment_calls = 0\n''',
    '''class FakeScriptRunner:\n    def __init__(\n        self,\n        *,\n        revision_verdict: str = "pass",\n        revision_quality: ScriptQualityScore | None = None,\n        revision_text_prefix: str = "اصلاح",\n    ) -> None:\n        self.verification_calls = 0\n        self.segment_calls = 0\n        self.revision_verdict = revision_verdict\n        self.revision_quality = revision_quality\n        self.revision_text_prefix = revision_text_prefix\n''',
)
replace_once(
    "tests/test_script_pipeline.py",
    '''            else:\n                output = VerificationDraft(\n                    verdict="pass",\n                    issues=[],\n                    unsupported_claim_ratio=0,\n                    quality=ScriptQualityScore(\n                        evidence_fidelity=0.95,\n                        qualification_preservation=0.90,\n                        stance_and_disagreement=0.90,\n                        terminology_consistency=0.90,\n                        listenability=0.90,\n                        actionable_feedback="",\n                    ),\n                )\n''',
    '''            else:\n                quality = self.revision_quality or ScriptQualityScore(\n                    evidence_fidelity=0.95,\n                    qualification_preservation=0.90,\n                    stance_and_disagreement=0.90,\n                    terminology_consistency=0.90,\n                    listenability=0.90,\n                    actionable_feedback=(\n                        ""\n                        if self.revision_verdict == "pass"\n                        else "The revision still needs work."\n                    ),\n                )\n                output = VerificationDraft(\n                    verdict=self.revision_verdict,\n                    issues=(\n                        []\n                        if self.revision_verdict == "pass"\n                        else [\n                            VerificationIssue(\n                                turn_id=turn_id,\n                                severity="high",\n                                issue_type="lost_qualification",\n                                explanation="The revision still drops a qualification.",\n                                required_revision="Restore the qualification.",\n                            )\n                        ]\n                    ),\n                    unsupported_claim_ratio=0,\n                    quality=quality,\n                )\n''',
)
replace_once(
    "tests/test_script_pipeline.py",
    '                        spoken_text_fa=_spoken("اصلاح", 50),\n',
    '                        spoken_text_fa=_spoken(self.revision_text_prefix, 50),\n',
)
replace_once(
    "tests/test_script_pipeline.py",
    '''    assert (script_dir / "verification-revised.json").exists()\n''',
    '''    assert (script_dir / "verification-revised.json").exists()\n    decision = ScriptArtifactStore(root).load_revision_decision_optional(project_id)\n    assert decision is not None\n    assert decision.accepted is True\n    assert decision.delta is not None and decision.delta > 0\n''',
)

# Add focused pipeline and migration-compatibility tests.
path = "tests/test_script_pipeline.py"
content = read(path)
if "test_worse_revision_is_kept_on_disk_but_the_original_is_used" not in content:
    content += '''\n\ndef _quality_score(value: float, feedback: str) -> ScriptQualityScore:\n    return ScriptQualityScore(\n        evidence_fidelity=value,\n        qualification_preservation=value,\n        stance_and_disagreement=value,\n        terminology_consistency=value,\n        listenability=value,\n        actionable_feedback=feedback,\n    )\n\n\ndef test_worse_revision_is_kept_on_disk_but_the_original_is_used(\n    tmp_path: Path,\n) -> None:\n    root = tmp_path / "workspaces"\n    project_id, _, _ = _seed(root)\n    _approve(root, project_id)\n    runner = FakeScriptRunner(\n        revision_verdict="revise",\n        revision_quality=_quality_score(0.20, "The revision is worse."),\n    )\n\n    with pytest.raises(ValueError, match="kept the original"):\n        _service(root, runner).run(\n            project_id,\n            glossary_model="fake",\n            writer_model="fake",\n            verifier_model="fake",\n            reviser_model="fake",\n        )\n\n    store = ScriptArtifactStore(root)\n    decision = store.load_revision_decision_optional(project_id)\n    assert decision is not None and decision.accepted is False\n    assert (store.script_dir(project_id) / "script-revised.json").exists()\n    assert store.load_latest_script(project_id).turns[0].spoken_text_fa.startswith("الف0")\n\n\ndef test_tied_revision_keeps_the_original(tmp_path: Path) -> None:\n    root = tmp_path / "workspaces"\n    project_id, _, _ = _seed(root)\n    _approve(root, project_id)\n    runner = FakeScriptRunner(\n        revision_verdict="revise",\n        revision_quality=ScriptQualityScore(\n            evidence_fidelity=0.55,\n            qualification_preservation=0.50,\n            stance_and_disagreement=0.70,\n            terminology_consistency=0.80,\n            listenability=0.85,\n            actionable_feedback="Restore the dropped qualification.",\n        ),\n    )\n\n    with pytest.raises(ValueError, match="kept the original"):\n        _service(root, runner).run(\n            project_id,\n            glossary_model="fake",\n            writer_model="fake",\n            verifier_model="fake",\n            reviser_model="fake",\n        )\n\n    decision = ScriptArtifactStore(root).load_revision_decision_optional(project_id)\n    assert decision is not None and decision.accepted is False\n    assert decision.delta == 0\n\n\ndef test_revision_failing_deterministic_checks_records_a_rejected_decision(\n    tmp_path: Path,\n) -> None:\n    root = tmp_path / "workspaces"\n    project_id, _, _ = _seed(root)\n    _approve(root, project_id)\n    runner = FakeScriptRunner(revision_text_prefix="system prompt")\n\n    with pytest.raises(ValueError, match="deterministic checks; the original"):\n        _service(root, runner).run(\n            project_id,\n            glossary_model="fake",\n            writer_model="fake",\n            verifier_model="fake",\n            reviser_model="fake",\n        )\n\n    decision = ScriptArtifactStore(root).load_revision_decision_optional(project_id)\n    assert decision is not None\n    assert decision.accepted is False\n    assert decision.revised_verdict is None\n\n\ndef test_artifacts_without_a_decision_file_still_use_the_revision(\n    tmp_path: Path,\n) -> None:\n    root = tmp_path / "workspaces"\n    project_id, _, _ = _seed(root)\n    _approve(root, project_id)\n    _service(root, FakeScriptRunner()).run(\n        project_id,\n        glossary_model="fake",\n        writer_model="fake",\n        verifier_model="fake",\n        reviser_model="fake",\n    )\n    store = ScriptArtifactStore(root)\n    (store.script_dir(project_id) / "revision-decision.json").unlink()\n\n    assert store.has_revised_script(project_id) is True\n    assert store.load_latest_script(project_id).turns[0].spoken_text_fa.startswith("اصلاح")\n'''
write(path, content)

# Extend quality comparison coverage.
path = "tests/test_script_quality.py"
content = read(path)
content = content.replace(
    "from thesisound.script import (\n",
    "from thesisound.script import (\n    ScriptCheckIssue,\n    ScriptCheckReport,\n",
    1,
)
if "from thesisound.services.script_quality import comparison_key" not in content:
    content = content.replace(
        "from thesisound.services.script_verifier import _validate_verification\n",
        "from thesisound.services.script_quality import comparison_key, is_better\n"
        "from thesisound.services.script_verifier import _validate_verification\n",
        1,
    )
if "test_comparison_key_orders_each_boundary" not in content:
    content += '''\n\ndef _checks(\n    verdict: str = "pass",\n    *,\n    blocking: int = 0,\n    other: int = 0,\n) -> ScriptCheckReport:\n    issues = [\n        ScriptCheckIssue(\n            severity="blocking", issue_type="other", explanation="blocking"\n        )\n        for _ in range(blocking)\n    ] + [\n        ScriptCheckIssue(severity="high", issue_type="other", explanation="other")\n        for _ in range(other)\n    ]\n    return ScriptCheckReport(\n        project_id=__import__("uuid").uuid4(),\n        verdict=verdict,\n        issues=issues,\n        word_count=1,\n        estimated_minutes=1,\n        substantive_turn_count=1,\n    )\n\n\ndef _verification(\n    verdict: str = "pass",\n    *,\n    ratio: float = 0,\n    score: float = 0.8,\n    blocking: int = 0,\n    other: int = 0,\n) -> VerificationDraft:\n    issues = [\n        VerificationIssue(\n            turn_id="turn-1",\n            severity="blocking",\n            issue_type="other",\n            explanation="blocking",\n            required_revision="fix",\n        )\n        for _ in range(blocking)\n    ] + [\n        VerificationIssue(\n            turn_id="turn-1",\n            severity="high",\n            issue_type="other",\n            explanation="other",\n            required_revision="fix",\n        )\n        for _ in range(other)\n    ]\n    return VerificationDraft(\n        verdict=verdict,\n        issues=issues,\n        unsupported_claim_ratio=ratio,\n        quality=_quality(\n            evidence_fidelity=score,\n            qualification_preservation=score,\n            stance_and_disagreement=score,\n            terminology_consistency=score,\n            listenability=score,\n        ),\n    )\n\n\ndef test_comparison_key_orders_each_boundary() -> None:\n    assert comparison_key(_checks(), _verification("pass")) > comparison_key(\n        _checks(), _verification("revise")\n    )\n    assert comparison_key(_checks(), _verification(ratio=0.1)) > comparison_key(\n        _checks(), _verification(ratio=0.2)\n    )\n    assert comparison_key(_checks(), _verification(score=0.9)) > comparison_key(\n        _checks(), _verification(score=0.8)\n    )\n    assert comparison_key(\n        _checks(), _verification(blocking=0, other=1)\n    ) > comparison_key(_checks(), _verification(blocking=1))\n    assert comparison_key(_checks(), _verification(other=1)) > comparison_key(\n        _checks(), _verification(other=2)\n    )\n\n\ndef test_is_better_is_strict_and_ties_keep_incumbent() -> None:\n    candidate = (_checks(), _verification())\n    assert is_better(candidate, candidate) is False\n'''
write(path, content)
