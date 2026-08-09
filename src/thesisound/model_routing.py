from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from thesisound.config import Settings
from thesisound.modeling import ModelConfigurationError

ProviderName = Literal["gemini", "okian"]
ModelSettingName = Literal["model_fast", "model_strong", "model_reviewer"]

# (reviewer route key, reviewed route key, tier). Route keys are prompt
# contract ids -- see model_runner.py.
REVIEWER_PAIRS: tuple[tuple[str, str, Literal["fast", "strong"]], ...] = (
    ("script_verifier", "persian_script_segment", "strong"),
    ("coverage_audit", "claim_reconciliation", "strong"),
)


class ModelProfile(BaseModel):
    provider: ProviderName
    model: str | None = None
    model_setting: ModelSettingName | None = None

    @model_validator(mode="after")
    def validate_model_source(self) -> ModelProfile:
        configured = int(bool(self.model and self.model.strip())) + int(
            self.model_setting is not None
        )
        if configured != 1:
            raise ValueError("A model profile must set exactly one of model or model_setting")
        return self

    def resolve_model(self, settings: Settings) -> str:
        if self.model_setting is not None:
            return str(getattr(settings, self.model_setting))
        assert self.model is not None
        return self.model.strip()


class ModelRoutingDocument(BaseModel):
    version: int = Field(default=1, ge=1)
    profiles: dict[str, ModelProfile] = Field(default_factory=dict)
    routes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_routes(self) -> ModelRoutingDocument:
        missing = sorted(set(self.routes.values()) - set(self.profiles))
        if missing:
            raise ValueError("Model routes reference undefined profiles: " + ", ".join(missing))
        return self


@dataclass(frozen=True, slots=True)
class ResolvedModelRoute:
    provider: ProviderName
    model: str
    profile: str | None = None


class ModelRouter:
    """Resolve a pipeline stage to a provider/model without changing prompt contracts."""

    def __init__(
        self,
        settings: Settings,
        document: ModelRoutingDocument,
    ) -> None:
        self.settings = settings
        self.document = document

    def resolve(
        self,
        *,
        stage: str,
        requested_model: str,
        model_tier: Literal["fast", "strong"],
    ) -> ResolvedModelRoute:
        default_model = (
            self.settings.model_fast if model_tier == "fast" else self.settings.model_strong
        )
        if requested_model != default_model:
            return ResolvedModelRoute(provider="gemini", model=requested_model)

        profile_name = self.settings.model_route_overrides.get(stage) or self.document.routes.get(
            stage
        )
        if profile_name is None:
            return ResolvedModelRoute(provider="gemini", model=requested_model)

        profile = self.document.profiles.get(profile_name)
        if profile is None:
            raise ModelConfigurationError(
                f"Model route for stage {stage!r} references undefined profile {profile_name!r}."
            )
        return ResolvedModelRoute(
            provider=profile.provider,
            model=profile.resolve_model(self.settings),
            profile=profile_name,
        )

    def self_grading_pairs(self) -> list[tuple[str, str, str]]:
        """Reviewer/reviewed pairs that resolve to the same provider and model.

        Compares the resolved (provider, model), not the profile name: two
        distinct profiles can still point at the same model.
        Returns (reviewer, reviewed, "provider/model").
        """

        collisions: list[tuple[str, str, str]] = []
        for reviewer, reviewed, tier in REVIEWER_PAIRS:
            requested_model = (
                self.settings.model_fast
                if tier == "fast"
                else self.settings.model_strong
            )
            reviewer_route = self.resolve(
                stage=reviewer,
                requested_model=requested_model,
                model_tier=tier,
            )
            reviewed_route = self.resolve(
                stage=reviewed,
                requested_model=requested_model,
                model_tier=tier,
            )
            if (reviewer_route.provider, reviewer_route.model) == (
                reviewed_route.provider,
                reviewed_route.model,
            ):
                collisions.append(
                    (
                        reviewer,
                        reviewed,
                        f"{reviewer_route.provider}/{reviewer_route.model}",
                    )
                )
        return collisions

    def uses_provider(self, provider: ProviderName) -> bool:
        profile_names = set(self.document.routes.values()) | set(
            self.settings.model_route_overrides.values()
        )
        return any(
            self.document.profiles.get(name) and self.document.profiles[name].provider == provider
            for name in profile_names
        )


def load_model_router(settings: Settings) -> ModelRouter:
    path = settings.model_routing_file.expanduser()
    if not path.exists():
        return ModelRouter(settings, _fallback_document(settings))
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
        document = ModelRoutingDocument.model_validate(payload)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        raise ModelConfigurationError(f"Invalid model routing file at {path}: {exc}") from exc
    return ModelRouter(settings, document)


def _fallback_document(settings: Settings) -> ModelRoutingDocument:
    return ModelRoutingDocument(
        profiles={
            "gemini_fast": ModelProfile(
                provider="gemini",
                model_setting="model_fast",
            ),
            "gemini_strong": ModelProfile(
                provider="gemini",
                model_setting="model_strong",
            ),
        },
        routes={},
    )
