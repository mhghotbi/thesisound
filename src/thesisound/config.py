from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="THESISOUND_",
        extra="ignore",
    )

    workspace_root: Path = Path("./workspaces")
    ingestion_artifact_root: Path = Path("./artifacts/ingestion")
    log_level: str = "INFO"

    model_fast: str = "gemini-3.5-flash-lite"
    model_strong: str = "gemini-3.6-flash"
    model_tts: str = "gemini-3.1-flash-tts-preview"

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

    def ensure_workspace_root(self) -> Path:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        return self.workspace_root

    def ensure_ingestion_artifact_root(self) -> Path:
        self.ingestion_artifact_root.mkdir(parents=True, exist_ok=True)
        return self.ingestion_artifact_root
