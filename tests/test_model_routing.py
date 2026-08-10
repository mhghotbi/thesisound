from __future__ import annotations

from pathlib import Path

import pytest

from thesisound.config import Settings
from thesisound.model_routing import load_model_router
from thesisound.modeling import ModelConfigurationError


def test_checked_in_routing_file_resolves_script_and_map_prompt_ids() -> None:
    settings = Settings(
        _env_file=None,
        model_reviewer="gemini-reviewer-test",
        model_routing_file=Path("config/model-routing.toml"),
    )
    router = load_model_router(settings)

    assert (
        router.resolve(
            stage="document_map",
            requested_model=settings.model_fast,
            model_tier="fast",
        ).provider
        == "gemini"
    )
    script_route = router.resolve(
        stage="persian_script_segment",
        requested_model=settings.model_strong,
        model_tier="strong",
    )
    assert script_route.provider == "gemini"
    assert script_route.profile == "gemini_strong"
    verifier_route = router.resolve(
        stage="script_verifier",
        requested_model=settings.model_strong,
        model_tier="strong",
    )
    assert verifier_route.profile == "gemini_reviewer"
    # Observability stages like script_segment:{id} are not route keys; ModelRunner
    # must resolve via the prompt contract id instead.
    assert (
        router.resolve(
            stage="script_segment:seg-001",
            requested_model=settings.model_strong,
            model_tier="strong",
        ).provider
        == "gemini"
    )


def test_okian_profile_can_be_routed_without_changing_prompt_contracts(
    tmp_path: Path,
) -> None:
    routing_file = tmp_path / "routing.toml"
    routing_file.write_text(
        """
version = 1

[profiles.gemini_fast]
provider = "gemini"
model_setting = "model_fast"

[profiles.okian_qwen]
provider = "okian"
model = "qwen-private-id"

[routes]
document_map = "okian_qwen"
""".strip(),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        model_routing_file=routing_file,
    )
    route = load_model_router(settings).resolve(
        stage="document_map",
        requested_model=settings.model_fast,
        model_tier="fast",
    )

    assert route.provider == "okian"
    assert route.model == "qwen-private-id"
    assert route.profile == "okian_qwen"


def test_explicit_model_override_remains_a_direct_gemini_override(
    tmp_path: Path,
) -> None:
    routing_file = tmp_path / "routing.toml"
    routing_file.write_text(
        """
version = 1

[profiles.okian_qwen]
provider = "okian"
model = "qwen-private-id"

[routes]
document_map = "okian_qwen"
""".strip(),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        model_routing_file=routing_file,
    )
    route = load_model_router(settings).resolve(
        stage="document_map",
        requested_model="gemini-manual-override",
        model_tier="fast",
    )

    assert route.provider == "gemini"
    assert route.model == "gemini-manual-override"
    assert route.profile is None


def test_unset_reviewer_model_falls_back_to_strong() -> None:
    settings = Settings(_env_file=None)

    assert settings.model_reviewer == settings.model_strong


def test_reviewer_route_uses_the_configured_reviewer_model() -> None:
    settings = Settings(
        _env_file=None,
        model_reviewer="gemini-reviewer-test",
        model_routing_file=Path("config/model-routing.toml"),
    )
    router = load_model_router(settings)
    reviewer = router.resolve(
        stage="script_verifier",
        requested_model=settings.model_strong,
        model_tier="strong",
    )
    writer = router.resolve(
        stage="persian_script_segment",
        requested_model=settings.model_strong,
        model_tier="strong",
    )

    assert reviewer.model == "gemini-reviewer-test"
    assert reviewer.model != writer.model


def test_self_grading_pairs_flags_identical_models_behind_distinct_profiles(
    tmp_path: Path,
) -> None:
    routing_file = tmp_path / "routing.toml"
    routing_file.write_text(
        """
version = 1

[profiles.writer]
provider = "gemini"
model_setting = "model_strong"

[profiles.reviewer]
provider = "gemini"
model_setting = "model_strong"

[routes]
persian_script_segment = "writer"
script_verifier = "reviewer"
""".strip(),
        encoding="utf-8",
    )
    settings = Settings(_env_file=None, model_routing_file=routing_file)

    assert (
        "script_verifier",
        "persian_script_segment",
        f"gemini/{settings.model_strong}",
    ) in load_model_router(settings).self_grading_pairs()


def test_self_grading_pairs_is_empty_when_the_reviewer_model_differs(
    tmp_path: Path,
) -> None:
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

    assert load_model_router(settings).self_grading_pairs() == []


def test_verifier_route_is_blocked_when_the_reviewer_model_is_unset() -> None:
    settings = Settings(
        _env_file=None,
        model_routing_file=Path("config/model-routing.toml"),
    )

    with pytest.raises(ModelConfigurationError) as excinfo:
        load_model_router(settings).resolve(
            stage="script_verifier",
            requested_model=settings.model_strong,
            model_tier="strong",
        )

    error = str(excinfo.value)
    assert "script_verifier" in error
    assert "persian_script_segment" in error
    assert "THESISOUND_MODEL_REVIEWER" in error


def test_verifier_route_is_blocked_when_the_reviewer_is_explicitly_set_to_the_writer_model(
) -> None:
    # Model identity, not the presence of an environment variable, is the predicate.
    settings = Settings(
        _env_file=None,
        model_reviewer="gemini-3.6-flash",
        model_routing_file=Path("config/model-routing.toml"),
    )

    with pytest.raises(ModelConfigurationError):
        load_model_router(settings).resolve(
            stage="script_verifier",
            requested_model=settings.model_strong,
            model_tier="strong",
        )


def test_verifier_route_is_blocked_when_two_profiles_resolve_to_one_model(
    tmp_path: Path,
) -> None:
    routing_file = tmp_path / "routing.toml"
    routing_file.write_text(
        """
version = 1

[profiles.writer]
provider = "gemini"
model_setting = "model_strong"

[profiles.reviewer]
provider = "gemini"
model_setting = "model_strong"

[routes]
persian_script_segment = "writer"
script_verifier = "reviewer"
""".strip(),
        encoding="utf-8",
    )
    settings = Settings(_env_file=None, model_routing_file=routing_file)

    with pytest.raises(ModelConfigurationError):
        load_model_router(settings).resolve(
            stage="script_verifier",
            requested_model=settings.model_strong,
            model_tier="strong",
        )


def test_verifier_route_resolves_when_the_reviewer_model_differs() -> None:
    settings = Settings(
        _env_file=None,
        model_reviewer="gemini-reviewer-test",
        model_routing_file=Path("config/model-routing.toml"),
    )

    route = load_model_router(settings).resolve(
        stage="script_verifier",
        requested_model=settings.model_strong,
        model_tier="strong",
    )

    assert route.model == "gemini-reviewer-test"
    assert route.profile == "gemini_reviewer"


def test_writer_route_blocks_a_per_run_override_to_the_configured_reviewer_model() -> None:
    settings = Settings(
        _env_file=None,
        model_reviewer="gemini-reviewer-test",
        model_routing_file=Path("config/model-routing.toml"),
    )

    with pytest.raises(ModelConfigurationError) as excinfo:
        load_model_router(settings).resolve(
            stage="persian_script_segment",
            requested_model=settings.model_reviewer,
            model_tier="strong",
        )

    assert "per-run model override" in str(excinfo.value)
    assert "THESISOUND_MODEL_REVIEWER" in str(excinfo.value)


def test_coverage_audit_self_grading_warns_but_still_resolves(tmp_path: Path) -> None:
    routing_file = tmp_path / "routing.toml"
    routing_file.write_text(
        """
version = 1

[profiles.shared]
provider = "gemini"
model_setting = "model_strong"

[profiles.reviewer]
provider = "gemini"
model_setting = "model_reviewer"

[routes]
persian_script_segment = "shared"
script_verifier = "reviewer"
claim_reconciliation = "shared"
coverage_audit = "shared"
""".strip(),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        model_reviewer="gemini-reviewer-test",
        model_routing_file=routing_file,
    )
    router = load_model_router(settings)

    route = router.resolve(
        stage="coverage_audit",
        requested_model=settings.model_strong,
        model_tier="strong",
    )

    assert route.model == settings.model_strong
    assert router.self_grading_pairs()
    assert router.blocked_self_grading_pairs() == []


def test_blocked_self_grading_pairs_reports_only_the_script_verifier() -> None:
    settings = Settings(
        _env_file=None,
        model_routing_file=Path("config/model-routing.toml"),
    )

    blocked = load_model_router(settings).blocked_self_grading_pairs()

    assert len(blocked) == 1
    assert blocked[0][0] == "script_verifier"
