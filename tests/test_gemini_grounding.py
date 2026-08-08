from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from thesisound.adapters.models.gemini import GeminiStructuredModel
from thesisound.ports import RunMetadata


class ExampleOutput(BaseModel):
    value: str


class FakeModels:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, response) -> None:
        self.models = FakeModels(response)


def test_gemini_enables_search_and_url_context_and_extracts_metadata() -> None:
    response = SimpleNamespace(
        parsed=ExampleOutput(value="ok"),
        text='{"value":"ok"}',
        candidates=[
            SimpleNamespace(
                finish_reason="STOP",
                grounding_metadata=SimpleNamespace(
                    web_search_queries=["Arendt action primary sources"],
                    grounding_chunks=[
                        SimpleNamespace(
                            web=SimpleNamespace(
                                uri="https://example.org/arendt",
                                title="Arendt archive",
                                domain="example.org",
                            )
                        )
                    ],
                ),
                url_context_metadata=SimpleNamespace(
                    url_metadata=[
                        SimpleNamespace(
                            retrieved_url="https://example.org/input.pdf",
                            url_retrieval_status="URL_RETRIEVAL_STATUS_SUCCESS",
                        )
                    ]
                ),
            )
        ],
        prompt_feedback=None,
        usage_metadata=None,
    )
    client = FakeClient(response)
    adapter = GeminiStructuredModel(client=client)

    result = adapter.generate_structured(
        system_prompt="system",
        user_prompt="Read https://example.org/input.pdf and search for context.",
        output_type=ExampleOutput,
        model="gemini-test",
        metadata=RunMetadata(
            stage="source_discovery",
            model_or_provider="gemini-test",
            grounding_mode="google_search_and_url_context",
            grounding_urls=["https://example.org/input.pdf"],
        ),
    )

    config = client.models.calls[0]["config"]
    assert config["tools"] == [{"google_search": {}}, {"url_context": {}}]
    assert result.grounding.web_search_queries == ["Arendt action primary sources"]
    assert result.grounding.sources[0].uri == "https://example.org/arendt"
    assert result.grounding.url_retrievals[0].url == "https://example.org/input.pdf"


def test_evidence_bound_call_does_not_enable_web_tools() -> None:
    response = SimpleNamespace(
        parsed=ExampleOutput(value="ok"),
        text='{"value":"ok"}',
        candidates=[SimpleNamespace(finish_reason="STOP")],
        prompt_feedback=None,
        usage_metadata=None,
    )
    client = FakeClient(response)
    adapter = GeminiStructuredModel(client=client)

    adapter.generate_structured(
        system_prompt="system",
        user_prompt="Use only the supplied evidence.",
        output_type=ExampleOutput,
        model="gemini-test",
        metadata=RunMetadata(
            stage="evidence_extraction",
            model_or_provider="gemini-test",
        ),
    )

    assert "tools" not in client.models.calls[0]["config"]
