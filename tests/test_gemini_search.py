from __future__ import annotations

from pydantic import BaseModel

from thesisound.adapters.search.gemini import GeminiWebSearchPort, SearchSynthesis
from thesisound.domain import SearchQuery, SourceRole
from thesisound.modeling import (
    GroundingMetadata,
    GroundingSource,
    ModelUsage,
    StructuredModelResponse,
)
from thesisound.ports import RunMetadata


class FakeModel:
    provider = "fake"

    def __init__(self) -> None:
        self.metadata: RunMetadata | None = None

    def generate_structured[T: BaseModel](
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_type: type[T],
        model: str,
        metadata: RunMetadata,
    ) -> StructuredModelResponse[T]:
        _ = system_prompt, user_prompt, model
        self.metadata = metadata
        output = SearchSynthesis(
            overview="Two grounded candidate sources were found.",
            cautions=["Full text must be acquired before evidence use."],
        )
        assert output_type is SearchSynthesis
        return StructuredModelResponse(
            output=output,
            provider="fake",
            model="fake",
            usage=ModelUsage(),
            latency_ms=1,
            grounding=GroundingMetadata(
                mode="google_search",
                web_search_queries=["test query"],
                sources=[
                    GroundingSource(
                        uri="https://example.org/source",
                        title="Example source",
                        domain="example.org",
                    )
                ],
            ),
        )


def test_gemini_search_returns_only_grounded_candidate_urls() -> None:
    model = FakeModel()
    search = GeminiWebSearchPort(model, model="fake")

    results = search.search(
        SearchQuery(
            query="test query",
            provider="web",
            source_role=SourceRole.REFERENCE,
            language="fa",
            purpose="Find a credible source.",
            priority=3,
        )
    )

    assert len(results) == 1
    assert results[0].url == "https://example.org/source"
    assert results[0].metadata["candidate_only"] is True
    assert results[0].metadata["usable_as_evidence"] is False
    assert model.metadata is not None
    assert model.metadata.grounding_mode == "google_search"
