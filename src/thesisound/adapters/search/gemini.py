from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, Field

from thesisound.domain import SearchQuery
from thesisound.modeling import StructuredModelResponse
from thesisound.ports import RawSearchResult, RunMetadata, TextModelPort

_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")


class SearchSynthesis(BaseModel):
    overview: str
    cautions: list[str] = Field(default_factory=list)


class GeminiWebSearchPort:
    """Discover web candidates through Gemini Google Search grounding.

    Returned items are candidates only. They are not evidence until their full
    text is acquired, parsed, quality-gated, and explicitly included.
    """

    def __init__(self, model_port: TextModelPort, *, model: str) -> None:
        self.model_port = model_port
        self.model = model

    def search(self, query: SearchQuery) -> list[RawSearchResult]:
        prompt = _render_query(query)
        urls = _URL_PATTERN.findall(prompt)
        mode = "google_search_and_url_context" if urls else "google_search"
        response: StructuredModelResponse[SearchSynthesis] = (
            self.model_port.generate_structured(
                system_prompt=(
                    "Use Google Search to find high-quality sources for the requested "
                    "research purpose. Do not invent URLs. Summarize the search space; "
                    "the application will trust only URLs returned in grounding metadata."
                ),
                user_prompt=prompt,
                output_type=SearchSynthesis,
                model=self.model,
                metadata=RunMetadata(
                    stage="source_discovery",
                    model_or_provider=self.model,
                    grounding_mode=mode,
                    grounding_urls=urls[:20],
                ),
            )
        )

        results: list[RawSearchResult] = []
        for source in response.grounding.sources:
            results.append(
                RawSearchResult(
                    provider="gemini_google_search",
                    provider_id=hashlib.sha256(source.uri.encode("utf-8")).hexdigest()[:20],
                    title=source.title or source.domain or source.uri,
                    url=source.uri,
                    snippet_or_abstract=response.output.overview,
                    metadata={
                        "domain": source.domain,
                        "web_search_queries": response.grounding.web_search_queries,
                        "cautions": response.output.cautions,
                        "candidate_only": True,
                        "usable_as_evidence": False,
                    },
                )
            )
        return results


def _render_query(query: SearchQuery) -> str:
    parts = [
        f"Query: {query.query}",
        f"Purpose: {query.purpose}",
        f"Desired source role: {query.source_role.value}",
        f"Language: {query.language}",
    ]
    if query.exact_phrases:
        parts.append("Exact phrases: " + "; ".join(query.exact_phrases))
    if query.include_domains:
        parts.append("Prefer domains: " + ", ".join(query.include_domains))
    if query.exclude_domains:
        parts.append("Exclude domains: " + ", ".join(query.exclude_domains))
    if query.year_from is not None or query.year_to is not None:
        parts.append(
            f"Publication years: {query.year_from or 'open'} to {query.year_to or 'open'}"
        )
    return "\n".join(parts)
