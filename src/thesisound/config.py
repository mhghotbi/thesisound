from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from thesisound.http_proxy import DEFAULT_HTTP_PROXY, configure_gemini_http_proxy


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
    # A shared parse store under <ingestion_artifact_root>/_shared. Turning this
    # off is the first thing to try when a parse looks wrong: it answers "is this
    # the cache or the parser?" without deleting anything.
    parsed_document_cache_enabled: bool = True
    log_level: str = "INFO"

    # Gemini-only proxy (local Xray HTTP inbound). Okian and OpenAI always connect directly.
    # Set to "none" / empty to disable Gemini proxying.
    http_proxy: str | None = DEFAULT_HTTP_PROXY

    model_fast: str = "gemini-3.5-flash-lite"
    model_strong: str = "gemini-3.6-flash"
    # Independent reviewer model. Unset falls back to model_strong, which makes
    # the writer grade its own script -- script_verifier then refuses to resolve
    # a route at all (ModelRouter._require_reviewer_independence). The fallback
    # is deliberate: a blank model id would reach the provider instead.
    model_reviewer: str = ""
    model_tts: str = "gemini-3.1-flash-tts-preview"
    model_asr: str = "gemini-3.6-flash"
    # Used only when Gemini TTS hits key-pool exhaustion / rate-limit.
    model_tts_fallback: str = "gpt-4o-mini-tts"
    model_routing_file: Path = Path("./config/model-routing.toml")
    model_route_overrides: dict[str, str] = Field(default_factory=dict)

    okian_base_url: str | None = Field(
        default=None,
        validation_alias="OKIAN_BASE_URL",
    )
    okian_api_key: str | None = Field(
        default=None,
        validation_alias="OKIAN_API_KEY",
        exclude=True,
        repr=False,
    )
    okian_timeout_seconds: int = Field(default=180, ge=5, le=3_600)

    openai_api_key: str | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
        exclude=True,
        repr=False,
    )
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias="OPENAI_BASE_URL",
    )
    openai_tts_voice_a: str = "coral"
    openai_tts_voice_b: str = "ash"

    model_retry_base_seconds: float = Field(default=1, ge=0, le=60)
    model_timeout_seconds: int = Field(default=180, ge=5, le=3_600)
    search_timeout_seconds: int = Field(default=120, ge=5, le=3_600)
    url_probe_enabled: bool = True
    url_probe_timeout_seconds: int = Field(default=10, ge=1, le=60)
    web_search_cache_ttl_hours: int = Field(default=24, ge=1, le=720)
    # Direct URL paste on Sources: Trafilatura fetch + extract. Independent of
    # Gemini web search so paste works without a model key.
    url_source_fetch_enabled: bool = True
    url_fetch_timeout_seconds: int = Field(default=30, ge=5, le=120)
    url_fetch_min_characters: int = Field(default=400, ge=50, le=10_000)
    # Product surface for "find sources on the web". Off by default: code and
    # tests stay, but the UI and routes do not offer discovery until we bring
    # search back as a deliberate feature.
    web_source_discovery_enabled: bool = False
    tts_timeout_seconds: int = Field(default=240, ge=5, le=3_600)
    asr_timeout_seconds: int = Field(default=180, ge=5, le=3_600)
    provider_max_attempts: int = Field(default=2, ge=1, le=5)
    provider_retry_base_seconds: float = Field(default=1, ge=0, le=60)
    # Evidence extraction is one independent model call per selected block and dominates
    # corpus-build wall clock. Kept modest so a build does not spend its time in the key
    # pool's quota cooldown; set to 1 to restore the fully sequential behaviour.
    evidence_extraction_workers: int = Field(default=4, ge=1, le=16)
    # document_map_part is the largest call class in the pipeline (60% of input tokens,
    # 28% of provider time on the 2026-08-09 run) and partitions are independent, so
    # this is where fan-out buys the most wall clock. One partition is probed first: a
    # partition failure aborts the whole map, so a dead provider must not be paid for
    # once per partition. Set to 1 to restore the fully sequential behaviour.
    document_map_workers: int = Field(default=4, ge=1, le=16)
    # Blocks per evidence_extraction call. 1 preserves the audited one-block,
    # one-call behaviour; larger values use the separate batch prompt.
    evidence_extraction_batch_size: int = Field(default=1, ge=1, le=8)
    keep_rendered_prompts: bool = False
    gemini_google_search_enabled: bool = True
    gemini_url_context_enabled: bool = True

    observability_store_payloads: bool = True
    observability_database_path: Path | None = None
    observability_retention_days: int = Field(default=90, ge=1)
    accounts_database_path: Path | None = None
    password_login_max_attempts: int = Field(default=5, ge=1, le=20)
    password_login_lockout_seconds: int = Field(default=900, ge=60, le=3_600)

    # Pipeline-wide tracing: spans and events for every operation, not just
    # model calls. See src/thesisound/tracing.py. Off entirely disables span
    # recording; "detail" controls how fine-grained the recorded spans are
    # once tracing is on -- "stage" records only the coarse per-stage spans,
    # "operation" (the default) adds the step-level spans this codebase's
    # services open directly, "verbose" additionally allows per-block/
    # per-page/per-segment spans that can reach into the thousands on a
    # large corpus.
    tracing_enabled: bool = True
    tracing_detail: Literal["stage", "operation", "verbose"] = "operation"

    # Structured logging. Activates the log_level setting above, which
    # otherwise nothing reads. "json" is one JSON object per line, suitable
    # for machine ingestion; "text" is the human-readable default for local
    # development.
    log_format: Literal["text", "json"] = "text"
    log_file: Path | None = None

    pricing_file: Path = Path("./config/model-pricing.toml")
    observability_artifact_root: Path | None = None

    tts_voice_a: str = "Kore"
    tts_voice_b: str = "Puck"
    tts_style_prompt: str = (
        "فارسی معیار و طبیعی، دقیق، آرام و مناسب پادکست آموزشی بخوان. "
        "هیچ دستور، برچسب، توضیح یا متن اضافه‌ای نخوان."
    )
    tts_chunk_max_characters: int = Field(default=900, ge=120, le=4_000)
    tts_words_per_minute: int = Field(default=135, ge=80, le=220)
    # TTS chunks are independent Gemini calls. Kept modest so an audio build does
    # not pile concurrent requests into the key pool's quota cooldown; set to 1
    # to restore fully sequential synthesis.
    tts_workers: int = Field(default=4, ge=1, le=16)
    # Deterministic episode-budget assumptions (recorded in budget-report.json).
    # Separate from tts_words_per_minute: this paces planned speech density;
    # TTS WPM paces synthesis timing.
    episode_budget_words_per_minute: int = Field(default=130, ge=80, le=220)
    episode_budget_explanation_expansion_factor: float = Field(
        default=4.0, ge=1.0, le=10.0
    )
    episode_budget_evidence_tokens_per_output_minute: float = Field(
        default=20.0, ge=1.0, le=500.0
    )
    audio_sample_rate_hz: int = Field(default=24_000, ge=8_000, le=48_000)
    audio_qa_pass_threshold: float = Field(default=0.90, ge=0.5, le=1)
    audio_qa_review_threshold: float = Field(default=0.78, ge=0.4, le=1)
    # Separation measured on the 2026-08-09 production run: genuine deletions
    # score <= 0.79, correct reads >= 0.95. 0.85 sits in the gap.
    audio_qa_missing_sentence_threshold: float = Field(default=0.85, ge=0.5, le=1)
    # Off until the frozen golden-set evaluation provides evidence for a threshold.
    script_quality_gate_enabled: bool = False
    script_quality_min_overall: float = Field(default=0.70, ge=0, le=1)
    # Audit R10: the deterministic floor under speaker B. On, because the shipped prompt
    # already asked for an interlocutor in prose and got 10 filler turns out of 11 -- the
    # prompt half alone is the configuration we have evidence fails. Off restores the
    # pre-R10 validator exactly and is how the control arm of the blind A/B is run.
    script_speaker_balance_enabled: bool = True
    # Temporary for live e2e: keep scoring manual_review, but do not block assembly on it.
    audio_qa_accept_manual_review: bool = True
    # ASR + transcript QA are expensive for MVP. Off skips transcription, QA
    # verdicts, and ASR-driven regeneration; WAV validation during TTS and
    # final assembly still run. Set true to restore the full audio QA loop.
    audio_asr_enabled: bool = False
    audio_max_regeneration_attempts: int = Field(default=1, ge=0, le=1)
    audio_silence_milliseconds: int = Field(default=220, ge=0, le=2_000)
    ffmpeg_command: str = "ffmpeg"

    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_api_keys_value: str | None = Field(
        default=None,
        validation_alias="GEMINI_API_KEYS",
        exclude=True,
        repr=False,
    )

    mineru_command: str = "mineru"
    mineru_timeout_seconds: int = Field(default=1_800, ge=30)
    mineru_backend: str | None = None
    mineru_model_source: str | None = None
    docling_timeout_seconds: int = Field(default=360, ge=30)

    allow_provider_uploads: bool = True
    keep_raw_provider_responses: bool = False

    web_session_secret: str = "development-only-session-key"
    web_secure_cookies: bool = False
    web_upload_limit_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)
    allow_test_otp: bool = True
    test_otp_phone: str = "0912" + "0000000"
    test_otp_code: str = "999" + "999"
    otp_ttl_seconds: int = Field(default=300, ge=60, le=900)
    otp_resend_cooldown_seconds: int = Field(default=30, ge=5, le=300)
    otp_max_attempts: int = Field(default=5, ge=1, le=10)

    kavenegar_api_key: str | None = Field(
        default=None,
        validation_alias="KAVENEGAR_API_KEY",
        exclude=True,
        repr=False,
    )
    kavenegar_otp_template: str | None = Field(
        default=None,
        validation_alias="KAVENEGAR_TEMPLATE_NAME",
    )

    ui_demo_mode: bool = True

    @property
    def gemini_api_keys(self) -> tuple[str, ...]:
        values = _parse_gemini_api_keys(self.gemini_api_keys_value)
        if self.gemini_api_key:
            values.append(self.gemini_api_key)
        return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))

    @property
    def resolved_observability_database_path(self) -> Path:
        configured = self.observability_database_path
        return configured or self.workspace_root / "_observability" / "ledger.sqlite3"

    @property
    def resolved_observability_artifact_root(self) -> Path:
        configured = self.observability_artifact_root
        return configured or self.workspace_root / "_observability" / "artifacts"

    @property
    def resolved_accounts_database_path(self) -> Path:
        configured = self.accounts_database_path
        return configured or self.workspace_root / "_accounts" / "accounts.sqlite3"

    @model_validator(mode="after")
    def validate_runtime(self) -> Settings:
        pooled_keys = _parse_gemini_api_keys(self.gemini_api_keys_value)
        if not self.gemini_api_key and pooled_keys:
            self.gemini_api_key = pooled_keys[0]
        if self.audio_qa_review_threshold >= self.audio_qa_pass_threshold:
            raise ValueError("Audio QA review threshold must be below the pass threshold")
        if self.tts_voice_a == self.tts_voice_b:
            raise ValueError("TTS speakers A and B must use different voices")
        if self.openai_tts_voice_a == self.openai_tts_voice_b:
            raise ValueError("OpenAI TTS speakers A and B must use different voices")
        if self.environment == "production":
            if self.allow_test_otp:
                raise ValueError("Test OTP must be disabled in production")
            if self.ui_demo_mode:
                raise ValueError("UI demo mode must be disabled in production")
            if self.web_session_secret == "development-only-session-key":
                raise ValueError("A unique web session secret is required in production")
            if not self.web_secure_cookies:
                raise ValueError("Secure cookies are required in production")
            if not (self.kavenegar_api_key and self.kavenegar_api_key.strip()):
                raise ValueError("KAVENEGAR_API_KEY is required in production")
            if not (self.kavenegar_otp_template and self.kavenegar_otp_template.strip()):
                raise ValueError("KAVENEGAR_TEMPLATE_NAME is required in production")
        if not self.model_reviewer.strip():
            self.model_reviewer = self.model_strong
        configure_gemini_http_proxy(self.http_proxy)
        return self

    def ensure_workspace_root(self) -> Path:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        return self.workspace_root

    def ensure_ingestion_artifact_root(self) -> Path:
        self.ingestion_artifact_root.mkdir(parents=True, exist_ok=True)
        return self.ingestion_artifact_root


def _parse_gemini_api_keys(raw: str | None) -> list[str]:
    if not raw or not raw.strip():
        return []
    value = raw.strip()
    if value.startswith("["):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "GEMINI_API_KEYS must be a JSON list or comma-separated string"
            ) from exc
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError("GEMINI_API_KEYS JSON value must be a list of strings")
        return parsed
    return [item.strip() for item in value.split(",") if item.strip()]
