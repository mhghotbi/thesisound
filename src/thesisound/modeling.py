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
    # Sampling. `None` leaves the provider default alone, which is what every
    # creative stage wants. An analytical stage that must answer the same way
    # twice pins `temperature: 0` and a `seed`; see `sampling_for_attempt`.
    temperature: float | None = Field(default=None, ge=0, le=2)
    seed: int | None = None
    # How much temperature each retry adds on top of `temperature`. A pinned
    # stage that repeated itself verbatim would defeat contract repair, since
    # `model_retry` stops early on an identical answer.
    retry_temperature_step: float = Field(default=0.3, ge=0, le=1)
    system_file: str = "system.md"
    user_file: str = "user.md"


def sampling_for_attempt(
    contract: PromptContract,
    attempt: int,
) -> tuple[float | None, int | None]:
    """Resolve ``(temperature, seed)`` for one attempt of ``contract``.

    An unpinned contract stays unpinned: the provider default is left alone and
    nothing about today's behaviour changes. A pinned one answers the same way
    on attempt 1 every run, which is the point -- but each retry adds
    ``retry_temperature_step``, because `model_retry` treats an identical repair
    as a reason to stop, so a stage frozen at temperature 0 would burn its
    repair budget re-sending one wrong answer.

    The seed is deliberately *not* varied across attempts: with the temperature
    moving, holding the seed keeps a rerun of the whole ladder reproducible.
    """

    if contract.temperature is None:
        return None, contract.seed
    temperature = contract.temperature + contract.retry_temperature_step * (attempt - 1)
    return min(2.0, temperature), contract.seed


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
    retry_stop_reason: str | None = None
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
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        if retryable is not None:
            self.retryable = retryable
        # Tokens the provider billed before the call was rejected. None means
        # nothing was billed (or we never found out) -- never coerce it to zero.
        self.usage = usage
        self.retry_after_seconds = retry_after_seconds


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


StopReason = Literal[
    "information_asymmetry",
    "changeable_input",
    "consent",
    "integrity_breach",
]


class DeterministicValidationError(StructuredOutputError):
    def __init__(
        self,
        message: str,
        *,
        stop_reason: StopReason | None = None,
        retryable: bool | None = None,
        usage: ModelUsage | None = None,
    ) -> None:
        super().__init__(message, retryable=retryable, usage=usage)
        self.stop_reason = stop_reason


class ModelConfigurationError(ModelError):
    pass
