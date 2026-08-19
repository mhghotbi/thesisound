from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl

from thesisound import tracing
from thesisound.adapters.fetch.trafilatura import UrlFetchError, fetch_and_extract_url
from thesisound.adapters.models.gemini import GeminiStructuredModel
from thesisound.adapters.search.gemini import GeminiWebSearchPort
from thesisound.config import Settings
from thesisound.domain import Project, SearchQuery, SourceRole
from thesisound.pipeline import WorkspaceStore
from thesisound.prompt_loader import PromptLoader
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner
from thesisound.services.url_probe import probe_url
from thesisound.services.web_search_cache import WebSearchCache
from thesisound.web.source_ingestion import ingest_uploaded_source
from thesisound.web.source_manifest import UiSourceManifest, UiSourceStatus


class WebSourceCandidate(BaseModel):
    candidate_id: UUID = Field(default_factory=uuid4)
    query: str
    title: str
    url: HttpUrl
    snippet: str | None = None
    provider: str = "gemini_google_search"
    status: Literal["candidate", "added", "failed"] = "candidate"
    source_id: UUID | None = None
    issue_summary: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WebSourceCandidateStore:
    def __init__(self, project_directory: Path) -> None:
        self._path = project_directory / "web-search-candidates.json"

    def load(self) -> list[WebSourceCandidate]:
        if not self._path.exists():
            return []
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return [WebSourceCandidate.model_validate(item) for item in payload]

    def save(self, candidates: list[WebSourceCandidate]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                [candidate.model_dump(mode="json") for candidate in candidates],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self._path)

    def replace_results(self, candidates: list[WebSourceCandidate]) -> None:
        self.save(candidates)

    def get(self, candidate_id: UUID) -> WebSourceCandidate:
        candidate = next(
            (item for item in self.load() if item.candidate_id == candidate_id),
            None,
        )
        if candidate is None:
            raise FileNotFoundError(f"Web source candidate not found: {candidate_id}")
        return candidate

    def replace(self, candidate: WebSourceCandidate) -> None:
        candidates = self.load()
        for index, current in enumerate(candidates):
            if current.candidate_id == candidate.candidate_id:
                candidates[index] = candidate
                self.save(candidates)
                return
        raise FileNotFoundError(f"Web source candidate not found: {candidate.candidate_id}")


class WebSourceSectionDraft(BaseModel):
    heading: str | None = None
    paragraphs: list[str] = Field(default_factory=list)


class WebSourceCaptureDraft(BaseModel):
    title: str = Field(min_length=1)
    canonical_url: HttpUrl
    access: Literal["full_text", "partial_text", "metadata_only", "unavailable"]
    complete_for_declared_scope: bool = False
    sections: list[WebSourceSectionDraft] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @property
    def text_characters(self) -> int:
        return sum(len(paragraph) for section in self.sections for paragraph in section.paragraphs)


CAPTURE_DIVERGENCE_RATIO = 0.20
RAW_TRAFILATURA_FILENAME = "raw-trafilatura.md"


def capture_text_diverges(
    raw_characters: int,
    model_characters: int,
    *,
    ratio: float = CAPTURE_DIVERGENCE_RATIO,
) -> bool:
    """True when model and Trafilatura lengths differ by more than ``ratio``."""

    if raw_characters <= 0 and model_characters <= 0:
        return False
    baseline = max(raw_characters, 1)
    return abs(model_characters - raw_characters) / baseline > ratio


class WebSourceDiscoveryService:
    """Discover candidates, then capture selected URLs through an auditable gate."""

    def __init__(self, settings: Settings, workspace: WorkspaceStore) -> None:
        self.settings = settings
        self.workspace = workspace

    def search(self, project: Project, query: str) -> list[WebSourceCandidate]:
        if not self.settings.web_source_discovery_enabled:
            raise ValueError(
                "جست‌وجوی وب فعلاً در دسترس نیست. فایل منبع را بارگذاری کنید."
            )
        if project.brief is None:
            raise ValueError("برای جست‌وجوی وب ابتدا برداشت پژوهش را تأیید کنید.")
        normalized = query.strip() or project.brief.central_question
        search_query = SearchQuery(
            query=normalized,
            provider="web",
            source_role=SourceRole.REFERENCE,
            language=project.brief.output_language,
            purpose=(
                "Find credible sources that can materially support the project's "
                "central question and declared scope."
            ),
            priority=3,
        )
        cache = WebSearchCache(self.workspace.root, self.settings)
        results = cache.load(project.project_id, search_query)
        if results is None:
            model_port = GeminiStructuredModel(
                api_keys=self.settings.gemini_api_keys,
                settings=self.settings,
            )
            search_port = GeminiWebSearchPort(
                model_port,
                model=self.settings.model_fast,
                project_id=project.project_id,
                timeout_ms=self.settings.search_timeout_seconds * 1000,
                max_provider_attempts=self.settings.provider_max_attempts,
                provider_retry_base_seconds=self.settings.provider_retry_base_seconds,
            )
            results = search_port.search(search_query)
            cache.save(search_query, results)
        candidates: list[WebSourceCandidate] = []
        seen_urls: set[str] = set()
        for result in results:
            if not result.url or result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            candidates.append(
                WebSourceCandidate(
                    query=normalized,
                    title=result.title,
                    url=result.url,
                    snippet=result.snippet_or_abstract,
                    provider=result.provider,
                )
            )
        return candidates[:12]

    def import_candidate(
        self,
        project_id: UUID,
        candidate: WebSourceCandidate,
    ) -> UiSourceManifest:
        if self.settings.url_probe_enabled:
            probe = probe_url(str(candidate.url), settings=self.settings)
            if probe.outcome == "dead":
                tracing.event(
                    "source.probe_blocked",
                    component="source",
                    project_id=project_id,
                    level="warn",
                    reason=probe.reason,
                    http_status=probe.http_status,
                )
                return UiSourceManifest(
                    source_id=uuid4(),
                    filename=_web_filename(candidate.title),
                    display_title=candidate.title,
                    content_type="text/markdown",
                    size_bytes=0,
                    status=UiSourceStatus.BLOCKED,
                    issue_summary=(
                        "نشانی منبع به‌طور قطعی در دسترس نیست و پیش از مصرف مدل "
                        "مسدود شد."
                    ),
                    origin="gemini_web_search",
                    canonical_url=str(candidate.url),
                    retrieval_scope="unavailable",
                    quality_issues=[probe.reason],
                )
        source_id = uuid4()
        runner = ModelRunner(
            GeminiStructuredModel(
                api_keys=self.settings.gemini_api_keys,
                settings=self.settings,
            ),
            PromptLoader(),
            WorkspaceModelRunStore(
                self.workspace.root,
                keep_prompts=self.settings.keep_rendered_prompts,
            ),
            base_retry_delay_seconds=self.settings.model_retry_base_seconds,
        )
        execution = runner.run(
            project_id=project_id,
            stage="web_source_capture",
            prompt_name="web_source_capture",
            variables={
                "candidate_title": candidate.title,
                "candidate_url": str(candidate.url),
                "candidate_snippet": candidate.snippet,
            },
            output_type=WebSourceCaptureDraft,
            model=self.settings.model_fast,
            grounding_mode="url_context",
            grounding_urls=[str(candidate.url)],
            validator=_validate_capture,
        )
        capture = execution.output
        if capture.access in {"metadata_only", "unavailable"} or not capture.sections:
            return UiSourceManifest(
                source_id=source_id,
                filename=_web_filename(capture.title),
                display_title=capture.title,
                content_type="text/markdown",
                size_bytes=0,
                status=UiSourceStatus.BLOCKED,
                issue_summary=(
                    "متن منبع از URL بازیابی نشد؛ این نتیجه فقط یک پیشنهاد جست‌وجو است "
                    "و نمی‌تواند وارد شاهدها شود."
                ),
                origin="gemini_web_search",
                canonical_url=str(candidate.url),
                retrieval_scope=capture.access,
                quality_issues=capture.limitations,
            )

        raw_fetch = None
        try:
            raw_fetch = fetch_and_extract_url(str(candidate.url), settings=self.settings)
        except UrlFetchError as error:
            tracing.event(
                "source.trafilatura_fetch_failed",
                component="source",
                project_id=project_id,
                level="warn",
                reason=str(error),
            )

        markdown = _render_capture(capture)
        upload_root = self.workspace.project_dir(project_id) / "uploads" / "web" / str(source_id)
        upload_root.mkdir(parents=True, exist_ok=True)
        filename = _web_filename(capture.title)
        path = upload_root / filename
        path.write_text(markdown, encoding="utf-8")
        if raw_fetch is not None:
            (upload_root / RAW_TRAFILATURA_FILENAME).write_text(
                raw_fetch.markdown, encoding="utf-8"
            )
        size_bytes = path.stat().st_size
        artifact_root = (
            self.settings.ensure_ingestion_artifact_root() / str(project_id) / str(source_id)
        )
        manifest = ingest_uploaded_source(
            path,
            source_id=source_id,
            filename=filename,
            content_type="text/markdown",
            size_bytes=size_bytes,
            settings=self.settings,
            artifact_root=artifact_root,
        )
        manifest.display_title = capture.title
        manifest.origin = "gemini_web_search"
        manifest.canonical_url = str(candidate.url)
        manifest.retrieval_scope = capture.access
        manifest.quality_issues = [
            *manifest.quality_issues,
            *capture.limitations,
        ]
        if capture.access != "full_text" or not capture.complete_for_declared_scope:
            manifest.status = UiSourceStatus.REVIEW
            manifest.safe_for_claim_extraction = False
            manifest.selected = False
            manifest.issue_summary = (
                "بخشی از متن بازیابی شد، اما کامل‌بودن محدوده منبع تأیید نشد. "
                "برای جلوگیری از استناد ناقص، این نتیجه خودکار وارد شاهدها نمی‌شود."
            )
        elif manifest.status == UiSourceStatus.READY:
            manifest.selected = True
            if capture.limitations:
                manifest.issue_summary = _append_message(
                    manifest.issue_summary,
                    "محدودیت بازیابی: " + "؛ ".join(capture.limitations[:3]),
                )
        if raw_fetch is not None and capture_text_diverges(
            raw_fetch.text_characters, capture.text_characters
        ):
            manifest.capture_divergence = True
            manifest.quality_issues = [
                *manifest.quality_issues,
                (
                    "capture_divergence: model capture text length differs from "
                    "the raw Trafilatura fetch by more than 20%."
                ),
            ]
        return manifest


def _validate_capture(capture: WebSourceCaptureDraft) -> None:
    if capture.access == "full_text" and not capture.complete_for_declared_scope:
        raise ValueError("full_text capture must be complete for its declared scope")
    if capture.access in {"full_text", "partial_text"}:
        if capture.text_characters < 400:
            raise ValueError("retrieved source text is too short to be auditable")
        if not any(section.paragraphs for section in capture.sections):
            raise ValueError("retrieved source has no paragraphs")


def _render_capture(capture: WebSourceCaptureDraft) -> str:
    lines = [f"# {capture.title}", ""]
    for section in capture.sections:
        if section.heading:
            lines.extend([f"## {section.heading}", ""])
        for paragraph in section.paragraphs:
            cleaned = " ".join(paragraph.split())
            if cleaned:
                lines.extend([cleaned, ""])
    return "\n".join(lines).strip() + "\n"


def _web_filename(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u0600-\u06ff_-]+", "-", title).strip("-")
    if not slug:
        slug = hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]
    return f"{slug[:100]}.web.md"


def _append_message(current: str | None, extra: str) -> str:
    return f"{current} {extra}".strip() if current else extra


def canonical_host(url: str) -> str:
    return (urlparse(url).hostname or "").casefold()
