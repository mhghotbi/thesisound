"""`/projects/{id}/report` (`10c` P3 Step 12)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from thesisound.concepts import ConceptCell, ConceptMapStatistics, SourceChapter, SourceConceptMap
from thesisound.config import Settings
from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    Compression,
    EvidenceExtraction,
    EvidenceItem,
    LessonIntent,
    Locator,
    Project,
    ProjectScope,
    ProjectState,
    ResearchBrief,
    SourceAccess,
    SourceCandidate,
    SourceDecision,
    SourceRole,
    SupportStatus,
    TopicType,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import BlockEvidenceExtraction, ClaimLedger
from thesisound.web.app import create_app

_FINGERPRINT = "b" * 64


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        workspace_root=tmp_path / "workspaces",
        ingestion_artifact_root=tmp_path / "artifacts",
        web_session_secret="test-secret-that-is-long-enough",
        allow_test_otp=True,
        test_otp_phone="09120000000",
        test_otp_code="999999",
        otp_resend_cooldown_seconds=5,
        ui_demo_mode=False,
        gemini_api_key="test-api-key",
    )


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _login(client: TestClient) -> None:
    page = client.get("/login")
    client.post(
        "/login/request-code",
        data={"phone": "09120000000", "csrf_token": _csrf(page.text), "next_path": "/projects"},
    )
    page = client.get("/login/verify")
    client.post("/login/verify", data={"code": "999999", "csrf_token": _csrf(page.text)})
    account = client.app.state.accounts.get_or_create_phone_user("09120000000")
    for project in client.app.state.workspace.list_projects():
        client.app.state.accounts.add_project_member(project.project_id, account.user_id)


def test_focused_question_project_shows_the_not_applicable_state(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = Project(
        raw_input="موضوع",
        state=ProjectState.CORPUS_READY,
        brief=ResearchBrief(
            normalized_topic="موضوع",
            topic_type=TopicType.CONCEPT,
            central_question="سؤال؟",
            target_duration_minutes=10,
        ),
    )
    workspace.save_project(project)
    app = create_app(
        settings, corpus_executor=lambda _: None,
        episode_executor=lambda _: None, script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/report")
    assert page.status_code == 200
    assert "فقط برای گفتارهای" in page.text


def test_source_coverage_project_report_renders_parts_and_coverage(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    source_store = SourceArtifactStore(settings.workspace_root)
    source_id = uuid4()
    project = Project(
        raw_input="کتاب",
        state=ProjectState.CORPUS_READY,
        brief=ResearchBrief(
            normalized_topic="کتاب آزمون",
            topic_type=TopicType.WORK,
            central_question="کتاب چه می‌گوید؟",
            target_duration_minutes=10,
        ),
        lesson_intent=LessonIntent.SOURCE_COVERAGE,
        compression=Compression.STANDARD,
        episode_target_minutes=10,
        scope=ProjectScope(source_id=source_id),
        sources=[
            SourceCandidate(
                source_id=source_id,
                title="منبع آزمون",
                role=SourceRole.USER_CONTEXT,
                source_type="pdf",
                origin="user_upload",
                access=SourceAccess.FULL_TEXT,
                user_decision=SourceDecision.INCLUDE,
            )
        ],
    )
    workspace.save_project(project)

    cell = ConceptCell(
        cell_key="ch00-c001",
        label_fa="برچسب",
        kind="argument",
        tier=1,
        chapter_index=0,
        section_ids=["section-1"],
        block_ids=["block-1"],
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=4.0,
    )
    source_store.save_concept_map(
        project.project_id,
        source_id,
        SourceConceptMap(
            source_fingerprint=_FINGERPRINT,
            builder_version=1,
            chapters=[
                SourceChapter(
                    chapter_index=0,
                    title="فصل ۰",
                    heading_path=["فصل ۰"],
                    block_ids=["block-1"],
                    estimated_minutes=4.0,
                    detected_from="heading",
                    detection_agreement="agreed",
                )
            ],
            cells=[cell],
            edges=[],
            statistics=ConceptMapStatistics(cell_count=1),
            created_at=datetime.now(UTC),
        ),
    )
    claim = ClaimRecord(
        claim_id="clm-1",
        claim="مدعا",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=["ev-1"],
        support_status=SupportStatus.STRONG,
    )
    evidence_item = EvidenceItem(
        evidence_id="ev-1",
        source_id=source_id,
        block_id="block-1",
        claim="مدعا",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt="نقل قول",
        locator=Locator(page_start=1, page_end=1),
        support_kind="direct",
        confidence=0.9,
    )
    source_store.save_evidence(
        project.project_id,
        source_id,
        [
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id="block-1",
                extraction=EvidenceExtraction(segment_function="argument", claims=[evidence_item]),
            )
        ],
    )
    source_store.save_claim_ledger(
        project.project_id, source_id, ClaimLedger(source_id=source_id, claims=[claim])
    )

    app = create_app(
        settings, corpus_executor=lambda _: None,
        episode_executor=lambda _: None, script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/report")
    assert page.status_code == 200
    assert "برچسب" in page.text


def test_overview_shows_source_coverage_scope_and_cost(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    source_store = SourceArtifactStore(settings.workspace_root)
    source_id = uuid4()
    project = Project(
        raw_input="کتاب",
        state=ProjectState.CORPUS_READY,
        brief=ResearchBrief(
            normalized_topic="کتاب آزمون",
            topic_type=TopicType.WORK,
            central_question="کتاب چه می‌گوید؟",
            target_duration_minutes=10,
        ),
        lesson_intent=LessonIntent.SOURCE_COVERAGE,
        compression=Compression.CONCISE,
        episode_target_minutes=15,
        scope=ProjectScope(source_id=source_id, chapter_indexes=[0]),
        sources=[
            SourceCandidate(
                source_id=source_id,
                title="منبع آزمون",
                role=SourceRole.USER_CONTEXT,
                source_type="pdf",
                origin="user_upload",
                access=SourceAccess.FULL_TEXT,
                user_decision=SourceDecision.INCLUDE,
            )
        ],
    )
    workspace.save_project(project)

    cell = ConceptCell(
        cell_key="ch00-c001",
        label_fa="برچسب",
        kind="argument",
        tier=1,
        chapter_index=0,
        section_ids=["section-1"],
        block_ids=["block-1"],
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=4.0,
    )
    source_store.save_concept_map(
        project.project_id,
        source_id,
        SourceConceptMap(
            source_fingerprint=_FINGERPRINT,
            builder_version=1,
            chapters=[
                SourceChapter(
                    chapter_index=0,
                    title="فصل ۰",
                    heading_path=["فصل ۰"],
                    block_ids=["block-1"],
                    estimated_minutes=4.0,
                    detected_from="heading",
                    detection_agreement="agreed",
                )
            ],
            cells=[cell],
            edges=[],
            statistics=ConceptMapStatistics(cell_count=1),
            created_at=datetime.now(UTC),
        ),
    )
    claim = ClaimRecord(
        claim_id="clm-1",
        claim="مدعا",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=["ev-1"],
        support_status=SupportStatus.STRONG,
    )
    evidence_item = EvidenceItem(
        evidence_id="ev-1",
        source_id=source_id,
        block_id="block-1",
        claim="مدعا",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt="نقل قول",
        locator=Locator(page_start=1, page_end=1),
        support_kind="direct",
        confidence=0.9,
    )
    source_store.save_evidence(
        project.project_id,
        source_id,
        [
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id="block-1",
                extraction=EvidenceExtraction(segment_function="argument", claims=[evidence_item]),
            )
        ],
    )
    source_store.save_claim_ledger(
        project.project_id, source_id, ClaimLedger(source_id=source_id, claims=[claim])
    )

    app = create_app(
        settings, corpus_executor=lambda _: None,
        episode_executor=lambda _: None, script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}")
    assert page.status_code == 200
    assert "یادگیری کامل یک منبع" in page.text
    assert "فشرده — فقط مفاهیم اصلی" in page.text
    assert "۱۵ دقیقه" in page.text
    assert "۱ فصل منتخب از این منبع" in page.text
    assert f"/projects/{project.project_id}/report" in page.text
