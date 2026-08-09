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
    if content.count(old) != 1:
        raise RuntimeError(f"Expected one anchor in {path!r}, found {content.count(old)}")
    write(path, content.replace(old, new, 1))


# Item 1: independent reviewer routing and doctor warning.
replace_once(
    "src/thesisound/config.py",
    '    model_strong: str = "gemini-3.6-flash"\n',
    '    model_strong: str = "gemini-3.6-flash"\n'
    '    # Independent reviewer model. Unset falls back to model_strong, which makes\n'
    '    # the writer grade its own work -- `doctor` warns when that happens.\n'
    '    model_reviewer: str = ""\n',
)
replace_once(
    "src/thesisound/config.py",
    "        configure_gemini_http_proxy(self.http_proxy)\n",
    "        if not self.model_reviewer.strip():\n"
    "            self.model_reviewer = self.model_strong\n"
    "        configure_gemini_http_proxy(self.http_proxy)\n",
)

replace_once(
    "src/thesisound/model_routing.py",
    'ModelSettingName = Literal["model_fast", "model_strong"]\n',
    'ModelSettingName = Literal["model_fast", "model_strong", "model_reviewer"]\n\n'
    '# (reviewer route key, reviewed route key, tier). Route keys are prompt\n'
    '# contract ids -- see model_runner.py.\n'
    'REVIEWER_PAIRS: tuple[tuple[str, str, Literal["fast", "strong"]], ...] = (\n'
    '    ("script_verifier", "persian_script_segment", "strong"),\n'
    '    ("coverage_audit", "claim_reconciliation", "strong"),\n'
    ')\n',
)
replace_once(
    "src/thesisound/model_routing.py",
    "    def uses_provider(self, provider: ProviderName) -> bool:\n",
    "    def self_grading_pairs(self) -> list[tuple[str, str, str]]:\n"
    "        \"\"\"Reviewer/reviewed pairs that resolve to the same provider and model.\n\n"
    "        Compares the resolved (provider, model), not the profile name: two\n"
    "        distinct profiles can still point at the same model.\n"
    "        Returns (reviewer, reviewed, \"provider/model\").\n"
    "        \"\"\"\n\n"
    "        collisions: list[tuple[str, str, str]] = []\n"
    "        for reviewer, reviewed, tier in REVIEWER_PAIRS:\n"
    "            requested_model = (\n"
    "                self.settings.model_fast\n"
    "                if tier == \"fast\"\n"
    "                else self.settings.model_strong\n"
    "            )\n"
    "            reviewer_route = self.resolve(\n"
    "                stage=reviewer,\n"
    "                requested_model=requested_model,\n"
    "                model_tier=tier,\n"
    "            )\n"
    "            reviewed_route = self.resolve(\n"
    "                stage=reviewed,\n"
    "                requested_model=requested_model,\n"
    "                model_tier=tier,\n"
    "            )\n"
    "            if (reviewer_route.provider, reviewer_route.model) == (\n"
    "                reviewed_route.provider,\n"
    "                reviewed_route.model,\n"
    "            ):\n"
    "                collisions.append(\n"
    "                    (\n"
    "                        reviewer,\n"
    "                        reviewed,\n"
    "                        f\"{reviewer_route.provider}/{reviewer_route.model}\",\n"
    "                    )\n"
    "                )\n"
    "        return collisions\n\n"
    "    def uses_provider(self, provider: ProviderName) -> bool:\n",
)

replace_once(
    "config/model-routing.toml",
    '[profiles.gemini_strong]\nprovider = "gemini"\nmodel_setting = "model_strong"\n',
    '[profiles.gemini_strong]\nprovider = "gemini"\nmodel_setting = "model_strong"\n\n'
    '# Independent reviewer. Reads THESISOUND_MODEL_REVIEWER; when that is unset it\n'
    '# falls back to THESISOUND_MODEL_STRONG and `doctor` warns about self-grading.\n'
    '[profiles.gemini_reviewer]\nprovider = "gemini"\nmodel_setting = "model_reviewer"\n',
)
replace_once(
    "config/model-routing.toml",
    'script_verifier = "gemini_strong"\n',
    'script_verifier = "gemini_reviewer"\n',
)

replace_once(
    ".env.example",
    "THESISOUND_MODEL_STRONG=gemini-3.6-flash\n",
    "THESISOUND_MODEL_STRONG=gemini-3.6-flash\n"
    "# Independent reviewer used by script_verifier. Leave empty to fall back to\n"
    "# THESISOUND_MODEL_STRONG -- `doctor` warns while it is empty, because the\n"
    "# writer then grades its own script.\n"
    "THESISOUND_MODEL_REVIEWER=\n",
)

replace_once(
    "src/thesisound/services/runtime_preflight.py",
    "            self._model_routing(),\n            self._okian_provider(),\n",
    "            self._model_routing(),\n"
    "            self._reviewer_independence(),\n"
    "            self._okian_provider(),\n",
)
replace_once(
    "src/thesisound/services/runtime_preflight.py",
    "    def _okian_provider(self) -> RuntimeCheck:\n",
    "    def _reviewer_independence(self) -> RuntimeCheck:\n"
    "        try:\n"
    "            router = load_model_router(self.settings)\n"
    "        except ModelConfigurationError:\n"
    "            return RuntimeCheck(\n"
    "                code=\"reviewer-independence\",\n"
    "                label=\"Reviewer independence\",\n"
    "                status=\"pass\",\n"
    "                detail=\"Skipped: model routing did not load.\",\n"
    "            )\n"
    "        collisions = router.self_grading_pairs()\n"
    "        if not collisions:\n"
    "            route = router.resolve(\n"
    "                stage=\"script_verifier\",\n"
    "                requested_model=self.settings.model_strong,\n"
    "                model_tier=\"strong\",\n"
    "            )\n"
    "            return RuntimeCheck(\n"
    "                code=\"reviewer-independence\",\n"
    "                label=\"Reviewer independence\",\n"
    "                status=\"pass\",\n"
    "                detail=(\n"
    "                    f\"script_verifier runs on `{route.model}`, distinct from the writer.\"\n"
    "                ),\n"
    "            )\n"
    "        detail = \" \".join(\n"
    "            f\"{reviewer} and {reviewed} both resolve to `{resolved}`.\"\n"
    "            for reviewer, reviewed, resolved in collisions\n"
    "        )\n"
    "        return RuntimeCheck(\n"
    "            code=\"reviewer-independence\",\n"
    "            label=\"Reviewer independence\",\n"
    "            status=\"warning\",\n"
    "            detail=detail + \" Set THESISOUND_MODEL_REVIEWER.\",\n"
    "        )\n\n"
    "    def _okian_provider(self) -> RuntimeCheck:\n",
)

# Replace the stale checked-in routing assertions and add item-specific coverage.
path = "tests/test_model_routing.py"
content = read(path)
content = content.replace(
    '    assert script_route.provider == "okian"\n    assert script_route.profile == "okian_gemma"\n',
    '    assert script_route.provider == "gemini"\n'
    '    assert script_route.profile == "gemini_strong"\n'
    '    verifier_route = router.resolve(\n'
    '        stage="script_verifier",\n'
    '        requested_model=settings.model_strong,\n'
    '        model_tier="strong",\n'
    '    )\n'
    '    assert verifier_route.profile == "gemini_reviewer"\n',
)
if "test_unset_reviewer_model_falls_back_to_strong" not in content:
    content += '''\n\ndef test_unset_reviewer_model_falls_back_to_strong() -> None:\n    settings = Settings(_env_file=None)\n\n    assert settings.model_reviewer == settings.model_strong\n\n\ndef test_reviewer_route_uses_the_configured_reviewer_model() -> None:\n    settings = Settings(\n        _env_file=None,\n        model_reviewer="gemini-reviewer-test",\n        model_routing_file=Path("config/model-routing.toml"),\n    )\n    router = load_model_router(settings)\n    reviewer = router.resolve(\n        stage="script_verifier",\n        requested_model=settings.model_strong,\n        model_tier="strong",\n    )\n    writer = router.resolve(\n        stage="persian_script_segment",\n        requested_model=settings.model_strong,\n        model_tier="strong",\n    )\n\n    assert reviewer.model == "gemini-reviewer-test"\n    assert reviewer.model != writer.model\n\n\ndef test_self_grading_pairs_flags_identical_models_behind_distinct_profiles(\n    tmp_path: Path,\n) -> None:\n    routing_file = tmp_path / "routing.toml"\n    routing_file.write_text(\n        """\nversion = 1\n\n[profiles.writer]\nprovider = "gemini"\nmodel_setting = "model_strong"\n\n[profiles.reviewer]\nprovider = "gemini"\nmodel_setting = "model_strong"\n\n[routes]\npersian_script_segment = "writer"\nscript_verifier = "reviewer"\n""".strip(),\n        encoding="utf-8",\n    )\n    settings = Settings(_env_file=None, model_routing_file=routing_file)\n\n    assert (\n        "script_verifier",\n        "persian_script_segment",\n        f"gemini/{settings.model_strong}",\n    ) in load_model_router(settings).self_grading_pairs()\n\n\ndef test_self_grading_pairs_is_empty_when_the_reviewer_model_differs(\n    tmp_path: Path,\n) -> None:\n    routing_file = tmp_path / "routing.toml"\n    routing_file.write_text(\n        """\nversion = 1\n\n[profiles.writer]\nprovider = "gemini"\nmodel_setting = "model_strong"\n\n[profiles.reviewer]\nprovider = "gemini"\nmodel_setting = "model_reviewer"\n\n[routes]\npersian_script_segment = "writer"\nscript_verifier = "reviewer"\nclaim_reconciliation = "writer"\ncoverage_audit = "reviewer"\n""".strip(),\n        encoding="utf-8",\n    )\n    settings = Settings(\n        _env_file=None,\n        model_reviewer="gemini-reviewer-test",\n        model_routing_file=routing_file,\n    )\n\n    assert load_model_router(settings).self_grading_pairs() == []\n'''
write(path, content)

write(
    "tests/test_runtime_preflight.py",
    '''from __future__ import annotations\n\nfrom pathlib import Path\n\nfrom thesisound.config import Settings\nfrom thesisound.services.runtime_preflight import RuntimePreflight\n\n\ndef test_doctor_warns_when_the_verifier_shares_the_writer_model() -> None:\n    settings = Settings(\n        _env_file=None,\n        model_routing_file=Path("config/model-routing.toml"),\n    )\n\n    check = RuntimePreflight(settings)._reviewer_independence()\n\n    assert check.status == "warning"\n    assert check.blocking is False\n    assert "script_verifier" in check.detail\n\n\ndef test_doctor_passes_when_the_reviewer_model_is_distinct(tmp_path: Path) -> None:\n    routing_file = tmp_path / "routing.toml"\n    routing_file.write_text(\n        """\nversion = 1\n\n[profiles.writer]\nprovider = "gemini"\nmodel_setting = "model_strong"\n\n[profiles.reviewer]\nprovider = "gemini"\nmodel_setting = "model_reviewer"\n\n[routes]\npersian_script_segment = "writer"\nscript_verifier = "reviewer"\nclaim_reconciliation = "writer"\ncoverage_audit = "reviewer"\n""".strip(),\n        encoding="utf-8",\n    )\n    settings = Settings(\n        _env_file=None,\n        model_reviewer="gemini-reviewer-test",\n        model_routing_file=routing_file,\n    )\n\n    check = RuntimePreflight(settings)._reviewer_independence()\n\n    assert check.status == "pass"\n    assert check.blocking is False\n\n\ndef test_reviewer_check_is_skipped_when_routing_fails_to_load(tmp_path: Path) -> None:\n    routing_file = tmp_path / "routing.toml"\n    routing_file.write_text("not = [valid", encoding="utf-8")\n    settings = Settings(_env_file=None, model_routing_file=routing_file)\n    checks = {check.code: check for check in RuntimePreflight(settings).run("full")}\n\n    assert checks["model-routing"].status == "fail"\n    assert checks["reviewer-independence"].status == "pass"\n    assert checks["reviewer-independence"].detail == "Skipped: model routing did not load."\n''',
)
