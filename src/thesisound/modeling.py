from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

type GroundingMode = Literal[
    "none",
    "google_search",
    "url_context",
    "google_search_and_url_context",
]


class PromptContract(BaseModel):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    model_tier: Literal["fast", "strong"]
    output_model: str = Field(min_length=1)
    max_attempts: int = Field(default=2, ge=1, le=5)
    retry_schema_errors: bool = True
    system_file: str = "system.md"
    user_file: str = "user.md"


class PromptBundle(BaseModel):
    contract: PromptContract
    system_prompt: str
    user_prompt: str
    content_hash: str


class ModelUsage(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    thinking_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)


class GroundingSource(BaseModel):
    uri: str
    title: str | None = None
    domain: str | None = None


class UrlRetrieval(BaseModel):
    url: str
    status: str | None = None


class GroundingMetadata(BaseModel):
    mode: GroundingMode = "none"
    web_search_queries: list[str] = Field(default_factory=list)
    sources: list[GroundingSource] = Field(default_factory=list)
    url_retrievals: list[UrlRetrieval] = Field(default_factory=list)


class StructuredModelResponse[T: BaseModel](BaseModel):
    output: T
    provider: str
    model: str
    usage: ModelUsage = Field(default_factory=ModelUsage)
    latency_ms: int = Field(ge=0)
    finish_reason: str | None = None
    grounding: GroundingMetadata = Field(default_factory=GroundingMetadata)
    call_id: UUID | None = None


class ModelAttemptRecord(BaseModel):
    attempt: int = Field(ge=1)
    # Wall-clock start of the attempt. The runner passes this explicitly; relying on
    # the default here records the attempt's *end* time, because the record is built
    # after the provider call returns.
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    latency_ms: int | None = Field(default=None, ge=0)
    success: bool = False
    error_type: str | None = None
    error_message: str | None = None
    retryable: bool = False
    retry_delay_ms: int | None = Field(default=None, ge=0)
    usage: ModelUsage | None = None
    finish_reason: str | None = None
    grounding_source_count: int = Field(default=0, ge=0)
    web_search_queries: list[str] = Field(default_factory=list)
    call_id: UUID | None = None


class ModelRunRecord(BaseModel):
    run_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    stage: str
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    input_hash: str
    provider: str
    model: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    status: Literal["running", "succeeded", "failed"] = "running"
    attempts: list[ModelAttemptRecord] = Field(default_factory=list)
    output_model: str
    grounding_mode: GroundingMode = "none"
    grounding_urls: list[str] = Field(default_factory=list)
    grounding_source_count: int = Field(default=0, ge=0)
    web_search_queries: list[str] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None


class ModelExecution[T: BaseModel](BaseModel):
    output: T
    record: ModelRunRecord


class ModelError(RuntimeError):
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        retryable: bool | None = None,
        usage: ModelUsage | None = None,
    ) -> None:
        super().__init__(message)
        if retryable is not None:
            self.retryable = retryable
        # Tokens the provider billed before the call was rejected. None means
        # nothing was billed (or we never found out) -- never coerce it to zero.
        self.usage = usage


class ModelProviderError(ModelError):
    retryable = True


class ModelRateLimitError(ModelProviderError):
    pass


class ModelTimeoutError(ModelProviderError):
    pass


class ModelSafetyError(ModelError):
    pass


class StructuredOutputError(ModelError):
    retryable = True


class SchemaValidationError(StructuredOutputError):
    pass


class DeterministicValidationError(StructuredOutputError):
    pass


class ModelConfigurationError(ModelError):
    pass
