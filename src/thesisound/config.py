from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="THESISOUND_",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"

    workspace_root: Path = Path("./workspaces")
    ingestion_artifact_root: Path = Path("./artifacts/ingestion")
    log_level: str = "INFO"

    model_fast: str = "gemini-3.5-flash-lite"
    model_strong: str = "gemini-3.6-flash"
    model_tts: str = "gemini-3.1-flash-tts-preview"
    model_retry_base_seconds: float = Field(default=1, ge=0, le=60)
    keep_rendered_prompts: bool = False

    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    firecrawl_api_key: str | None = Field(default=None, validation_alias="FIRECRAWL_API_KEY")
    openalex_api_key: str | None = Field(default=None, validation_alias="OPENALEX_API_KEY")
    semantic_scholar_api_key: str | None = Field(
        default=None,
        validation_alias="SEMANTIC_SCHOLAR_API_KEY",
    )

    mineru_command: str = "mineru"
    mineru_timeout_seconds: int = Field(default=1_800, ge=30)
    mineru_backend: str | None = None
    mineru_model_source: str | None = None

    enable_firecrawl_parse: bool = False
    allow_provider_uploads: bool = True
    keep_raw_provider_responses: bool = False

    web_session_secret: str = "development-only-session-key"
    web_secure_cookies: bool = False
    web_upload_limit_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)
    allow_test_otp: bool = True
    test_otp_phone: str = "0912" + "000000"
    test_otp_code: str = "999" + "999"
    otp_ttl_seconds: int = Field(default=300, ge=60, le=900)
    otp_resend_cooldown_seconds: int = Field(default=30, ge=5, le=300)
    otp_max_attempts: int = Field(default=5, ge=1, le=10)
    ui_demo_mode: bool = True

    @model_validator(mode="after")
    def protect_production_auth(self) -> "Settings":
        if self.environment == "production":
            if self.allow_test_otp:
                raise ValueError("Test OTP must be disabled in production")
            if self.ui_demo_mode:
                raise ValueError("UI demo mode must be disabled in production")
            if self.web_session_secret == "development-only-session-key":
                raise ValueError("A unique web session secret is required in production")
            if not self.web_secure_cookies:
                raise ValueError("Secure cookies are required in production")
        return self

    def ensure_workspace_root(self) -> Path:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        return self.workspace_root

    def ensure_ingestion_artifact_root(self) -> Path:
        self.ingestion_artifact_root.mkdir(parents=True, exist_ok=True)
        return self.ingestion_artifact_root
