from __future__ import annotations

from pathlib import Path

from thesisound.config import Settings
from thesisound.services.runtime_preflight import RuntimePreflight


def test_doctor_warns_when_the_verifier_shares_the_writer_model() -> None:
    settings = Settings(
        _env_file=None,
        model_routing_file=Path("config/model-routing.toml"),
    )

    check = RuntimePreflight(settings)._reviewer_independence()

    assert check.status == "warning"
    assert check.blocking is False
    assert "script_verifier" in check.detail


def test_doctor_passes_when_the_reviewer_model_is_distinct(tmp_path: Path) -> None:
    routing_file = tmp_path / "routing.toml"
    routing_file.write_text(
        """
version = 1

[profiles.writer]
provider = "gemini"
model_setting = "model_strong"

[profiles.reviewer]
provider = "gemini"
model_setting = "model_reviewer"

[routes]
persian_script_segment = "writer"
script_verifier = "reviewer"
claim_reconciliation = "writer"
coverage_audit = "reviewer"
""".strip(),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        model_reviewer="gemini-reviewer-test",
        model_routing_file=routing_file,
    )

    check = RuntimePreflight(settings)._reviewer_independence()

    assert check.status == "pass"
    assert check.blocking is False


def test_reviewer_check_is_skipped_when_routing_fails_to_load(tmp_path: Path) -> None:
    routing_file = tmp_path / "routing.toml"
    routing_file.write_text("not = [valid", encoding="utf-8")
    settings = Settings(_env_file=None, model_routing_file=routing_file)
    checks = {check.code: check for check in RuntimePreflight(settings).run("full")}

    assert checks["model-routing"].status == "fail"
    assert checks["reviewer-independence"].status == "pass"
    assert checks["reviewer-independence"].detail == "Skipped: model routing did not load."
