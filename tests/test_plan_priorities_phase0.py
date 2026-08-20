"""Phase 0 plan-priorities: duration cost, MNBL UI views, and plan.* events."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from thesisound.config import Settings
from thesisound.domain import (
    EpisodePlan,
    EpisodeSegment,
    Project,
    ProjectState,
    ResearchBrief,
    TopicType,
)
from thesisound.episode import MustNotBeLostReview, MustNotBeLostReviewItem
from thesisound.observability import ObservabilityLedger
from thesisound.pipeline import WorkspaceStore
from thesisound.product_metrics import (
    ProductEvent,
    configure_product_metrics,
    reset_product_metrics,
)
from thesisound.product_metrics.events import PlanDurationChanged, PlanReviewed
from thesisound.product_metrics.store import ProductEventStore
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.episode_duration_cost import (
    DURATION_COST_EXPENSIVE,
    reextraction_required_for_duration,
    source_needs_reextraction,
)
from thesisound.services.episode_planning_run import (
    EpisodePlanningRun,
    EpisodePlanningRunStore,
)
from thesisound.source_analysis import AnalysisProfile, EvidenceExtractionPlan
from thesisound.web.app import create_app
from thesisound.web.evidence_views import (
    must_not_be_lost_review_views,
    unused_must_not_be_lost_views,
)


def _brief(duration: int = 10) -> ResearchBrief:
    return ResearchBrief(
        normalized_topic="موضوع",
        topic_type=TopicType.CONCEPT,
        central_question="سؤال؟",
        target_duration_minutes=duration,
        learning_objectives=["فهم"],
    )


def _profile(*, depth: str = "brief", duration: int = 10) -> AnalysisProfile:
    return AnalysisProfile(
        depth=depth,  # type: ignore[arg-type]
        target_duration_minutes=duration,
        block_coverage_target=0.35,
        evidence_input_token_budget=18_000,
        max_claims_per_block=2 if depth == "brief" else 7,
        neighbor_context_blocks=0 if depth == "brief" else 2,
        include_examples=depth != "brief",
        second_pass_for_core_sections=depth == "extended",
        rationale=["test"],
    )


def _plan(
    source_id: UUID,
    *,
    profile: AnalysisProfile,
    selected: list[str],
) -> EvidenceExtractionPlan:
    return EvidenceExtractionPlan(
        source_id=source_id,
        profile=profile,
        selected_block_ids=selected,
        deferred_block_ids=[],
        selected_source_tokens=100,
        total_source_tokens=100,
        achieved_token_coverage=1.0,
    )


def test_source_needs_reextraction_false_when_compatible_and_same_blocks() -> None:
    source_id = uuid4()
    profile = _profile(depth="brief")
    stored = _plan(source_id, profile=profile, selected=["a", "b"])
    planned = _plan(source_id, profile=profile, selected=["a", "b"])
    assert source_needs_reextraction(stored, planned) is False


def test_source_needs_reextraction_true_when_depth_changes() -> None:
    source_id = uuid4()
    stored = _plan(source_id, profile=_profile(depth="brief"), selected=["a"])
    planned = _plan(source_id, profile=_profile(depth="standard", duration=20), selected=["a"])
    assert source_needs_reextraction(stored, planned) is True


def test_source_needs_reextraction_true_when_selected_blocks_differ() -> None:
    source_id = uuid4()
    profile = _profile(depth="brief")
    stored = _plan(source_id, profile=profile, selected=["a"])
    planned = _plan(source_id, profile=profile, selected=["a", "b"])
    assert source_needs_reextraction(stored, planned) is True


def test_source_needs_reextraction_true_when_stored_missing() -> None:
    source_id = uuid4()
    planned = _plan(source_id, profile=_profile(), selected=["a"])
    assert source_needs_reextraction(None, planned) is True


def test_reextraction_required_false_with_no_claim_ready_sources(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(
        raw_input="موضوع",
        state=ProjectState.EPISODE_PLANNED,
        brief=_brief(10),
    )
    workspace.save_project(project)
    from thesisound.services.source_artifact_store import SourceArtifactStore

    store = SourceArtifactStore(workspace.root)
    assert reextraction_required_for_duration(project, store, 10) is False


def test_unused_must_not_be_lost_views_empty_when_missing() -> None:
    assert unused_must_not_be_lost_views(None, claims={}, evidence_by_id={}) == []


def test_unused_must_not_be_lost_views_filters_used_and_keeps_text() -> None:
    used = MustNotBeLostReviewItem(
        claim_id="c1",
        claim="Used note",
        used_in_plan=True,
    )
    unused = MustNotBeLostReviewItem(
        claim_id="c2",
        claim="Unused note that matters",
        used_in_plan=False,
    )
    review = MustNotBeLostReview(
        project_id=uuid4(),
        items=[used, unused],
        unused_count=1,
    )
    rows = unused_must_not_be_lost_views(review, claims={}, evidence_by_id={})
    assert len(rows) == 1
    assert rows[0]["text"] == "Unused note that matters"
    assert rows[0]["claim_ids"] == ["c2"]


def test_must_not_be_lost_review_views_includes_used_and_candidates() -> None:
    used = MustNotBeLostReviewItem(
        claim_id="c1",
        claim="Used note",
        used_in_plan=True,
    )
    unused = MustNotBeLostReviewItem(
        claim_id="c2",
        claim="Unused note that matters",
        used_in_plan=False,
    )
    review = MustNotBeLostReview(
        project_id=uuid4(),
        items=[used, unused],
        unused_count=1,
    )
    rows = must_not_be_lost_review_views(review, claims={}, evidence_by_id={})
    assert [row["text"] for row in rows] == ["Used note", "Unused note that matters"]
    assert rows[0]["used_in_plan"] is True
    assert rows[0]["claim_ids"] == ["c1"]
    assert rows[1]["used_in_plan"] is False
    assert rows[1]["claim_ids"] == ["c2"]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        ingestion_artifact_root=tmp_path / "artifacts",
        web_session_secret="test-secret-that-is-long-enough",
        allow_test_otp=True,
        test_otp_phone="09120000000",
        test_otp_code="999999",
        otp_resend_cooldown_seconds=5,
        ui_demo_mode=False,
        observability_database_path=tmp_path / "obs.sqlite3",
        observability_artifact_root=tmp_path / "obs-artifacts",
    )


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _login(client: TestClient) -> None:
    page = client.get("/login")
    client.post(
        "/login/request-code",
        data={
            "phone": "09120000000",
            "csrf_token": _csrf(page.text),
            "next_path": "/projects",
        },
    )
    page = client.get("/login/verify")
    client.post(
        "/login/verify",
        data={"code": "999999", "csrf_token": _csrf(page.text)},
    )
    account = client.app.state.accounts.get_or_create_phone_user("09120000000")
    for project in client.app.state.workspace.list_projects():
        client.app.state.accounts.add_project_member(project.project_id, account.user_id)


def _client(app) -> TestClient:
    # Secure session cookies require https; httpx sets domain to testserver.local.
    return TestClient(app, base_url="https://testserver.local")


def test_blocked_page_uses_bidirectional_duration_language(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = Project(
        raw_input="موضوع",
        state=ProjectState.EPISODE_PLANNING,
        brief=_brief(20),
    )
    workspace.save_project(project)
    EpisodePlanningRunStore(settings.workspace_root).save(
        EpisodePlanningRun(
            project_id=project.project_id,
            status="blocked",
            stage="blocked",
            target_duration_minutes=20,
            max_supported_minutes=12,
            last_error="ناکافی",
        )
    )
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )
    with _client(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/episode")
    assert "مدت کوتاه‌تر" not in page.text
    assert "کاهش مدت و سنجش دوباره" not in page.text
    assert "مدت گفتار" in page.text
    assert "تغییر مدت و سنجش دوباره" in page.text


def test_planned_page_shows_mnbl_and_emits_plan_reviewed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = Project(
        raw_input="موضوع",
        state=ProjectState.EPISODE_PLANNED,
        brief=_brief(15),
        episode_plan=EpisodePlan(
            title="طرح نمونه",
            listener_outcome="شنونده می‌فهمد",
            estimated_duration_minutes=15,
            segments=[
                EpisodeSegment(
                    segment_id="seg-001",
                    title="بخش",
                    purpose="هدف",
                    estimated_minutes=15,
                    claim_ids=["c1"],
                    key_question="؟",
                    speaker_dynamic="explanation",
                )
            ],
        ),
    )
    workspace.save_project(project)
    EpisodePlanningRunStore(settings.workspace_root).save(
        EpisodePlanningRun(
            project_id=project.project_id,
            status="succeeded",
            stage="complete",
            target_duration_minutes=15,
            max_supported_minutes=22,
            effective_supported_minutes=22.0,
        )
    )
    episode_store = EpisodeArtifactStore(workspace.root)
    episode_store.save_must_not_be_lost_review(
        MustNotBeLostReview(
            project_id=project.project_id,
            items=[
                MustNotBeLostReviewItem(
                    claim_id="claim-x",
                    claim="این نکته مهم نیامده",
                    used_in_plan=False,
                )
            ],
            unused_count=1,
        )
    )
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )
    with _client(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/episode")
    assert "نکته‌هایی که نباید گم شوند" in page.text
    assert "این نکته مهم نیامده" in page.text
    assert "۱ نکته در طرح نیامده" in page.text
    assert "در طرح نیامده" in page.text
    assert "هر مدتی تا" in page.text
    assert 'data-plan-list-open="must_not_be_lost"' in page.text
    store = ProductEventStore(settings.resolved_observability_database_path)
    events = store.list_events(name=ProductEvent.PLAN_REVIEWED.value)
    assert len(events) >= 1
    assert events[-1].properties["has_unused_must_not_be_lost"] is True


def test_episode_page_renders_full_must_not_be_lost_review(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = Project(
        raw_input="موضوع",
        state=ProjectState.EPISODE_PLANNED,
        brief=_brief(15),
        episode_plan=EpisodePlan(
            title="طرح نمونه",
            listener_outcome="شنونده می‌فهمد",
            estimated_duration_minutes=15,
            segments=[
                EpisodeSegment(
                    segment_id="seg-001",
                    title="بخش",
                    purpose="هدف",
                    estimated_minutes=15,
                    claim_ids=["claim-candidate"],
                    key_question="؟",
                    speaker_dynamic="explanation",
                )
            ],
        ),
    )
    workspace.save_project(project)
    EpisodePlanningRunStore(settings.workspace_root).save(
        EpisodePlanningRun(
            project_id=project.project_id,
            status="succeeded",
            stage="complete",
            target_duration_minutes=15,
            max_supported_minutes=22,
            effective_supported_minutes=22.0,
        )
    )
    episode_store = EpisodeArtifactStore(workspace.root)
    episode_store.save_must_not_be_lost_review(
        MustNotBeLostReview(
            project_id=project.project_id,
            items=[
                MustNotBeLostReviewItem(
                    claim_id="claim-candidate",
                    claim="نکتهٔ آمده در طرح",
                    used_in_plan=True,
                ),
                MustNotBeLostReviewItem(
                    claim_id="claim-other",
                    claim="نکتهٔ نیامده در طرح",
                    used_in_plan=False,
                ),
            ],
            unused_count=1,
        )
    )
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )
    with _client(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/episode")
    assert page.status_code == 200
    assert "نکته‌هایی که نباید گم شوند" in page.text
    assert "نکتهٔ آمده در طرح" in page.text
    assert "نکتهٔ نیامده در طرح" in page.text
    assert "در طرح آمده" in page.text
    assert "در طرح نیامده" in page.text
    assert "۱ نکته در طرح نیامده" in page.text
    assert "claim-candidate" in page.text
    assert "claim-other" in page.text
    assert "مدعاهای نامزد" in page.text


def test_duration_cost_endpoint_returns_hint(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = Project(
        raw_input="موضوع",
        state=ProjectState.EPISODE_PLANNED,
        brief=_brief(10),
    )
    workspace.save_project(project)
    EpisodePlanningRunStore(settings.workspace_root).save(
        EpisodePlanningRun(
            project_id=project.project_id,
            status="succeeded",
            stage="complete",
            target_duration_minutes=10,
            max_supported_minutes=40,
            effective_supported_minutes=40.0,
        )
    )
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )
    with _client(app) as client:
        _login(client)
        response = client.get(
            f"/projects/{project.project_id}/episode/duration-cost",
            params={"minutes": 10},
        )
    assert response.status_code == 200
    assert "تحلیل منابع" in response.text or DURATION_COST_EXPENSIVE in response.text


def test_requeue_emits_plan_duration_changed(tmp_path: Path) -> None:
    from test_episode_planning_run import FakePreparationService, _service

    settings = _settings(tmp_path)
    ObservabilityLedger(
        settings.resolved_observability_database_path,
        settings.resolved_observability_artifact_root,
        store_payloads=False,
    )
    store = ProductEventStore(settings.resolved_observability_database_path)
    configure_product_metrics(settings, store)
    try:
        workspace = WorkspaceStore(tmp_path / "workspaces")
        project = Project(
            raw_input="موضوع",
            state=ProjectState.CORPUS_READY,
            brief=_brief(20),
        )
        fake = FakePreparationService(workspace, can_plan=False, supported_minutes=10)
        service = _service(tmp_path, project, fake)
        service.queue(project.project_id)
        service.run(project.project_id)
        service.requeue_with_duration(project.project_id, 10)
        events = store.list_events(name=ProductEvent.PLAN_DURATION_CHANGED.value)
        assert len(events) == 1
        assert events[0].properties["direction"] == "down"
        assert events[0].properties["from_blocked"] is True
        assert "reextraction_required" in events[0].properties
        assert "claim_id" not in PlanDurationChanged.model_fields
        assert "claim_id" not in PlanReviewed.model_fields
    finally:
        reset_product_metrics()

def test_missing_mnbl_review_does_not_break_episode_page(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = Project(
        raw_input="موضوع",
        state=ProjectState.EPISODE_PLANNED,
        brief=_brief(12),
        episode_plan=EpisodePlan(
            title="طرح",
            listener_outcome="نتیجه",
            estimated_duration_minutes=12,
            segments=[
                EpisodeSegment(
                    segment_id="seg-001",
                    title="بخش",
                    purpose="هدف",
                    estimated_minutes=12,
                    claim_ids=[],
                    key_question="؟",
                    speaker_dynamic="explanation",
                )
            ],
        ),
    )
    workspace.save_project(project)
    EpisodePlanningRunStore(settings.workspace_root).save(
        EpisodePlanningRun(
            project_id=project.project_id,
            status="succeeded",
            stage="complete",
            target_duration_minutes=12,
            max_supported_minutes=20,
            effective_supported_minutes=20.0,
        )
    )
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )
    with _client(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/episode")
    assert page.status_code == 200
    assert "نکته‌هایی که نباید گم شوند" not in page.text


def test_list_opened_emits_event(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = Project(
        raw_input="موضوع",
        state=ProjectState.EPISODE_PLANNED,
        brief=_brief(10),
    )
    workspace.save_project(project)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
    )
    with _client(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/episode")
        response = client.post(
            f"/projects/{project.project_id}/episode/list-opened",
            data={
                "csrf_token": _csrf(page.text),
                "origin": "omitted",
            },
        )
    assert response.status_code == 204
    store = ProductEventStore(settings.resolved_observability_database_path)
    events = store.list_events(name=ProductEvent.PLAN_OMITTED_LIST_OPENED.value)
    assert len(events) == 1
    assert events[0].properties["origin"] == "omitted"