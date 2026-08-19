from __future__ import annotations

from pathlib import Path
from uuid import UUID

from thesisound.adapters.fetch.trafilatura import UrlFetchResult
from thesisound.config import Settings
from thesisound.domain import Project, ResearchBrief, TopicType
from thesisound.modeling import ModelExecution, ModelRunRecord
from thesisound.pipeline import WorkspaceStore
from thesisound.ports import RawSearchResult
from thesisound.services.url_probe import UrlProbeResult
from thesisound.web import source_discovery
from thesisound.web.source_discovery import (
    RAW_TRAFILATURA_FILENAME,
    WebSourceCandidate,
    WebSourceCaptureDraft,
    WebSourceDiscoveryService,
    WebSourceSectionDraft,
    capture_text_diverges,
)
from thesisound.web.source_manifest import UiSourceStatus


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        ingestion_artifact_root=tmp_path / "artifacts",
        web_session_secret="test-secret-that-is-long-enough",
        allow_test_otp=True,
        ui_demo_mode=False,
        url_probe_enabled=False,
        web_source_discovery_enabled=True,
    )


def _project() -> Project:
    return Project(
        raw_input="اخلاق کانت",
        brief=ResearchBrief(
            normalized_topic="اخلاق کانت",
            topic_type=TopicType.CONCEPT,
            central_question="اخلاق کانت چگونه کار می‌کند؟",
        ),
    )


class FakeRunner:
    def __init__(self, capture: WebSourceCaptureDraft) -> None:
        self.capture = capture
        self.calls = 0

    def run(
        self,
        *,
        project_id: UUID,
        stage: str,
        output_type,
        model: str,
        validator=None,
        **_: object,
    ):
        self.calls += 1
        assert output_type is WebSourceCaptureDraft
        if validator is not None:
            validator(self.capture)
        record = ModelRunRecord(
            project_id=project_id,
            stage=stage,
            prompt_id=stage,
            prompt_version="test",
            prompt_hash="test",
            input_hash="test",
            provider="fake",
            model=model,
            output_model=output_type.__name__,
            status="succeeded",
        )
        return ModelExecution(output=self.capture, record=record)


def _capture(*, full: bool) -> WebSourceCaptureDraft:
    paragraph = (
        "این متن کامل یک منبع وب برای آزمون بازیابی، استخراج، کنترل کیفیت و ردیابی شواهد است. "
    ) * 12
    return WebSourceCaptureDraft(
        title="مقاله آزمون",
        canonical_url="https://example.com/article",
        access="full_text" if full else "partial_text",
        complete_for_declared_scope=full,
        sections=[
            WebSourceSectionDraft(
                heading="بخش اصلی",
                paragraphs=[paragraph],
            )
        ],
        limitations=[] if full else ["Only part of the article was available."],
    )


def _matching_fetch(capture: WebSourceCaptureDraft) -> UrlFetchResult:
    body = "x" * capture.text_characters
    return UrlFetchResult(
        title=capture.title,
        markdown=body,
        canonical_url="https://example.com/article",
        text_characters=len(body),
    )


def _patch_fetch(monkeypatch, result: UrlFetchResult) -> None:
    monkeypatch.setattr(source_discovery, "fetch_and_extract_url", lambda *_a, **_k: result)


def test_full_web_capture_is_parsed_and_selected(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()
    workspace.save_project(project)
    capture = _capture(full=True)
    monkeypatch.setattr(source_discovery, "GeminiStructuredModel", lambda **_: object())
    monkeypatch.setattr(
        source_discovery,
        "ModelRunner",
        lambda *_, **__: FakeRunner(capture),
    )
    _patch_fetch(monkeypatch, _matching_fetch(capture))

    manifest = WebSourceDiscoveryService(settings, workspace).import_candidate(
        project.project_id,
        WebSourceCandidate(
            query="اخلاق کانت",
            title="مقاله آزمون",
            url="https://example.com/article",
        ),
    )

    assert manifest.status == UiSourceStatus.READY
    assert manifest.selected
    assert manifest.safe_for_claim_extraction
    assert manifest.origin == "gemini_web_search"
    assert manifest.canonical_url == "https://example.com/article"
    assert manifest.artifact_ref is not None
    assert not manifest.capture_divergence
    raw_path = (
        settings.workspace_root
        / str(project.project_id)
        / "uploads"
        / "web"
        / str(manifest.source_id)
        / RAW_TRAFILATURA_FILENAME
    )
    assert raw_path.exists()
    assert (
        settings.ingestion_artifact_root
        / str(project.project_id)
        / str(manifest.source_id)
        / manifest.artifact_ref
    ).exists()


def test_partial_web_capture_is_visible_but_not_usable_as_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()
    workspace.save_project(project)
    capture = _capture(full=False)
    monkeypatch.setattr(source_discovery, "GeminiStructuredModel", lambda **_: object())
    monkeypatch.setattr(
        source_discovery,
        "ModelRunner",
        lambda *_, **__: FakeRunner(capture),
    )
    _patch_fetch(monkeypatch, _matching_fetch(capture))

    manifest = WebSourceDiscoveryService(settings, workspace).import_candidate(
        project.project_id,
        WebSourceCandidate(
            query="اخلاق کانت",
            title="مقاله آزمون",
            url="https://example.com/article",
        ),
    )

    assert manifest.status == UiSourceStatus.REVIEW
    assert not manifest.selected
    assert not manifest.safe_for_claim_extraction
    assert "کامل‌بودن" in (manifest.issue_summary or "")


def test_search_returns_deduplicated_candidates(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()

    class FakeSearchPort:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def search(self, _query):
            result = RawSearchResult(
                provider="gemini_google_search",
                title="مقاله آزمون",
                url="https://example.com/article",
                snippet_or_abstract="candidate only",
            )
            return [result, result]

    monkeypatch.setattr(source_discovery, "GeminiStructuredModel", lambda **_: object())
    monkeypatch.setattr(source_discovery, "GeminiWebSearchPort", FakeSearchPort)

    candidates = WebSourceDiscoveryService(settings, workspace).search(project, "")

    assert len(candidates) == 1
    assert candidates[0].query == project.brief.central_question
    assert str(candidates[0].url) == "https://example.com/article"



def test_dead_url_is_blocked_before_any_model_call(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    settings.url_probe_enabled = True
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()
    workspace.save_project(project)
    runner = FakeRunner(_capture(full=True))
    monkeypatch.setattr(
        source_discovery,
        "probe_url",
        lambda *_args, **_kwargs: UrlProbeResult(
            "https://example.com/dead", "dead", 404, "HTTP 404"
        ),
    )
    monkeypatch.setattr(source_discovery, "GeminiStructuredModel", lambda **_: object())
    monkeypatch.setattr(source_discovery, "ModelRunner", lambda *_, **__: runner)

    manifest = WebSourceDiscoveryService(settings, workspace).import_candidate(
        project.project_id,
        WebSourceCandidate(
            query="اخلاق کانت",
            title="Dead",
            url="https://example.com/dead",
        ),
    )

    assert manifest.status == UiSourceStatus.BLOCKED
    assert runner.calls == 0


def test_unknown_probe_outcome_still_attempts_capture(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    settings.url_probe_enabled = True
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()
    workspace.save_project(project)
    runner = FakeRunner(_capture(full=True))
    monkeypatch.setattr(
        source_discovery,
        "probe_url",
        lambda *_args, **_kwargs: UrlProbeResult(
            "https://example.com/article", "unknown", None, "TimeoutError"
        ),
    )
    monkeypatch.setattr(source_discovery, "GeminiStructuredModel", lambda **_: object())
    monkeypatch.setattr(source_discovery, "ModelRunner", lambda *_, **__: runner)
    _patch_fetch(monkeypatch, _matching_fetch(runner.capture))

    manifest = WebSourceDiscoveryService(settings, workspace).import_candidate(
        project.project_id,
        WebSourceCandidate(
            query="اخلاق کانت",
            title="Article",
            url="https://example.com/article",
        ),
    )

    assert manifest.status == UiSourceStatus.READY
    assert runner.calls == 1


def test_repeated_identical_search_uses_the_cache(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()

    class CountingSearchPort:
        calls = 0

        def __init__(self, *_: object, **__: object) -> None:
            pass

        def search(self, _query):
            type(self).calls += 1
            return [
                RawSearchResult(
                    provider="fake",
                    title="Cached",
                    url="https://example.com/cached",
                )
            ]

    monkeypatch.setattr(source_discovery, "GeminiStructuredModel", lambda **_: object())
    monkeypatch.setattr(source_discovery, "GeminiWebSearchPort", CountingSearchPort)
    service = WebSourceDiscoveryService(settings, workspace)

    first = service.search(project, "اخلاق")
    second = service.search(project, "اخلاق")

    assert [(item.title, str(item.url)) for item in first] == [
        (item.title, str(item.url)) for item in second
    ]
    assert CountingSearchPort.calls == 1


def test_capture_text_diverges_at_twenty_percent() -> None:
    assert not capture_text_diverges(100, 120)
    assert capture_text_diverges(100, 121)
    assert capture_text_diverges(100, 50)


def test_web_capture_flags_divergence_when_raw_fetch_length_differs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()
    workspace.save_project(project)
    capture = _capture(full=True)
    short = UrlFetchResult(
        title=capture.title,
        markdown="short",
        canonical_url="https://example.com/article",
        text_characters=5,
    )
    monkeypatch.setattr(source_discovery, "GeminiStructuredModel", lambda **_: object())
    monkeypatch.setattr(
        source_discovery,
        "ModelRunner",
        lambda *_, **__: FakeRunner(capture),
    )
    _patch_fetch(monkeypatch, short)

    manifest = WebSourceDiscoveryService(settings, workspace).import_candidate(
        project.project_id,
        WebSourceCandidate(
            query="اخلاق کانت",
            title="مقاله آزمون",
            url="https://example.com/article",
        ),
    )

    assert manifest.capture_divergence
    assert any("capture_divergence" in issue for issue in manifest.quality_issues)

