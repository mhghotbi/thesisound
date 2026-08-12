from __future__ import annotations

from pathlib import Path

from thesisound.config import Settings
from thesisound.services.runtime_preflight import RuntimePreflight


def test_doctor_fails_when_the_verifier_shares_the_writer_model(tmp_path: Path) -> None:
    routing_file = tmp_path / "routing.toml"
    routing_file.write_text(
        """
version = 1

[profiles.shared]
provider = "gemini"
model_setting = "model_strong"

[routes]
persian_script_segment = "shared"
script_verifier = "shared"
""".strip(),
        encoding="utf-8",
    )
    settings = Settings(_env_file=None, model_routing_file=routing_file)

    check = RuntimePreflight(settings)._reviewer_independence("full")

    assert check.status == "fail"
    assert check.blocking is True
    assert "script_verifier" in check.detail
    assert "THESISOUND_MODEL_REVIEWER" in check.detail


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

    check = RuntimePreflight(settings)._reviewer_independence("full")

    assert check.status == "pass"
    assert check.blocking is False


def test_checked_in_routing_file_keeps_both_reviewer_pairs_independent(
    tmp_path: Path,
) -> None:
    # Both pairs are independent now that the Okian stages split across the two
    # Okian Gemini profiles: script_verifier/persian_script_segment (enforced) and
    # coverage_audit/claim_reconciliation (warn-only) each land on different models.
    # A warning here means a pair collided again -- most likely two stages were
    # pointed at one profile, which puts a model back to grading its own output.
    settings = Settings(
        _env_file=None,
        workspace_root=tmp_path / "workspaces",
        ingestion_artifact_root=tmp_path / "artifacts",
        model_routing_file=Path("config/model-routing.toml"),
    )

    check = RuntimePreflight(settings)._reviewer_independence("full")

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


def test_only_the_script_and_full_scopes_block_on_a_self_grading_verifier(
    tmp_path: Path,
) -> None:
    routing_file = tmp_path / "routing.toml"
    routing_file.write_text(
        """
version = 1

[profiles.shared]
provider = "gemini"
model_setting = "model_strong"

[routes]
persian_script_segment = "shared"
script_verifier = "shared"
""".strip(),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        workspace_root=tmp_path / "workspaces",
        ingestion_artifact_root=tmp_path / "artifacts",
        model_routing_file=routing_file,
    )
    preflight = RuntimePreflight(settings)
    by_scope = {
        scope: {check.code: check for check in preflight.run(scope)}
        for scope in ("model", "script", "audio", "full")
    }

    # Assert on the individual check: unrelated prerequisites may also fail in CI.
    assert by_scope["model"]["reviewer-independence"].blocking is False
    assert by_scope["audio"]["reviewer-independence"].blocking is False
    assert by_scope["script"]["reviewer-independence"].blocking is True
    assert by_scope["full"]["reviewer-independence"].blocking is True


def test_the_script_scope_keeps_every_model_scope_check(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        workspace_root=tmp_path / "workspaces",
        ingestion_artifact_root=tmp_path / "artifacts",
        model_routing_file=Path("config/model-routing.toml"),
    )
    preflight = RuntimePreflight(settings)

    model_codes = {check.code for check in preflight.run("model")}
    script_codes = {check.code for check in preflight.run("script")}

    assert script_codes >= model_codes


def test_script_build_posts_are_gated_on_the_script_preflight_scope() -> None:
    from thesisound.web.app import _PREFLIGHT_POST_SCOPES

    mapping = dict(_PREFLIGHT_POST_SCOPES)

    assert mapping["/script/approve"] == "script"
    assert mapping["/script/retry"] == "script"
    # Stages that never call the verifier retain their existing scopes (R6, D5).
    assert mapping["/corpus/confirm"] == "model"
    assert mapping["/episode/prepare"] == "model"
    assert mapping["/audio/generate"] == "audio"
