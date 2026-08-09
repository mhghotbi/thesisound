from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from thesisound import tracing
from thesisound.domain import SearchQuery
from thesisound.modeling import GroundingMode, StructuredModelResponse


def _ambient_trace_id() -> UUID | None:
    context = tracing.current_context()
    return context.trace_id if context else None


def _ambient_span_id() -> UUID | None:
    context = tracing.current_context()
    return context.span_id if context else None


class RunMetadata(BaseModel):
    stage: str
    prompt_version: str | None = None
    model_or_provider: str
    provider: str | None = None
    model_profile: str | None = None
    attempt: int = Field(default=1, ge=1)
    input_artifact_hashes: list[str] = Field(default_factory=list)
    grounding_mode: GroundingMode = "none"
    grounding_urls: list[str] = Field(default_factory=list)
    call_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID | None = None
    parent_call_id: UUID | None = None
    # Populated from the ambient span (see thesisound.tracing) whenever a
    # caller does not supply one explicitly. This is what lets a model call
    # made from inside e.g. `with tracing.span("corpus.extract_evidence")`
    # attach to that span without every call site having to read
    # tracing.current_context() itself.
    pipeline_trace_id: UUID | None = Field(default_factory=_ambient_trace_id)
    parent_span_id: UUID | None = Field(default_factory=_ambient_span_id)
    project_id: UUID | None = None
    workflow_run_id: UUID | None = None
    operation: str = "structured_text"
    prompt_id: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    timeout_ms: int | None = Field(default=None, ge=1)
    max_provider_attempts: int = Field(default=1, ge=1, le=5)
    provider_retry_base_seconds: float = Field(default=1, ge=0, le=60)


class DocumentInspection(BaseModel):
    path: Path
    mime_type: str
    extension: str
    file_size_bytes: int = Field(ge=0)
    sha256: str
    page_count: int | None = Field(default=None, ge=0)
    encrypted: bool = False
    sampled_text_characters: int = Field(default=0, ge=0)
    image_only_ratio: float | None = Field(default=None, ge=0, le=1)
    likely_complex_layout: bool = False
    warnings: list[str] = Field(default_factory=list)


class ParsedBlock(BaseModel):
    source_block_key: str
    text: str
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = Field(default_factory=list)
    kind: str = "other"


class ParsedDocument(BaseModel):
    parser_name: str
    parser_version: str
    blocks: list[ParsedBlock]
    warnings: list[str] = Field(default_factory=list)
    raw_artifact_ref: str | None = None


class RawSearchResult(BaseModel):
    provider: str
    provider_id: str | None = None
    title: str
    url: str | None = None
    snippet_or_abstract: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TtsSegment(BaseModel):
    segment_id: str
    transcript: str
    speaker_a_voice: str
    speaker_b_voice: str
    director_notes: str
    pronunciation_notes: list[str] = Field(default_factory=list)
    idempotency_hash: str


class AudioArtifact(BaseModel):
    segment_id: str
    path: Path
    provider: str
    model: str
    duration_seconds: float = Field(gt=0)
    sample_rate_hz: int = Field(gt=0)
    transcript_hash: str


class ArtifactRef(BaseModel):
    key: str
    path: Path
    sha256: str


class TextModelPort(Protocol):
    provider: str

    def generate_structured[T: BaseModel](
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_type: type[T],
        model: str,
        metadata: RunMetadata,
    ) -> StructuredModelResponse[T]: ...


class SearchPort(Protocol):
    def search(self, query: SearchQuery) -> list[RawSearchResult]: ...


class DocumentParserPort(Protocol):
    name: str

    def supports(self, inspection: DocumentInspection) -> bool: ...

    def parse(self, path: Path, inspection: DocumentInspection) -> ParsedDocument: ...


class TtsPort(Protocol):
    def synthesize(self, segment: TtsSegment) -> AudioArtifact: ...


class AsrPort(Protocol):
    def transcribe(self, audio_path: Path) -> str: ...


class ArtifactStorePort(Protocol):
    def put_json(self, key: str, value: BaseModel) -> ArtifactRef: ...

    def put_file(self, key: str, path: Path) -> ArtifactRef: ...
