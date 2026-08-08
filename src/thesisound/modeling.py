from __future__ import annotations

from datetime import UTC, datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


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


class StructuredModelResponse(BaseModel, Generic[T]):
    output: T
    provider: str
    model: str
    usage: ModelUsage = Field(default_factory=ModelUsage)
    latency_ms: int = Field(ge=0)
    finish_reason: str | None = None


class ModelAttemptRecord(BaseModel):
    attempt: int = Field(ge=1)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    latency_ms: int | None = Field(default=None, ge=0)
    success: bool = False
    error_type: str | None = None
    error_message: str | None = None
    retryable: bool = False
    usage: ModelUsage | None = None
    finish_reason: str | None = None


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
    error_type: str | None = None
    error_message: str | None = None


class ModelExecution(BaseModel, Generic[T]):
    output: T
    record: ModelRunRecord


class ModelError(RuntimeError):
    retryable = False

    def __init__(self, message: str, *, retryable: bool | None = None) -> None:
        super().__init__(message)
        if retryable is not None:
            self.retryable = retryable


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
