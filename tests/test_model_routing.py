from __future__ import annotations

from pathlib import Path

from thesisound.config import Settings
from thesisound.model_routing import load_model_router


def test_checked_in_routing_file_resolves_script_and_map_prompt_ids() -> None:
    settings = Settings(
        _env_file=None,
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
    assert script_route.provider == "okian"
    assert script_route.profile == "okian_gemma"
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
