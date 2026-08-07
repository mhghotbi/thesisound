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

    enable_firecrawl_parse: bool = False
    allow_provider_uploads: bool = True
    keep_raw_provider_responses: bool = False

    def ensure_workspace_root(self) -> Path:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        return self.workspace_root
