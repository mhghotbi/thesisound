from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from thesisound.config import Settings
from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    EvidenceExtraction,
    EvidenceItem,
    Locator,
    Project,
    ProjectState,
    ResearchBrief,
    Script,
    ScriptTurn,
    SourceAccess,
    SourceCandidate,
    SourceDecision,
    SourceRole,
    SupportStatus,
    TopicType,
    EpisodePlan,
    EpisodeSegment,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.script import ScriptCheckReport, ScriptPipelineManifest, VerificationDraft
from thesisound.services.plan_approval import (
    EpisodePlanApproval,
    EpisodePlanApprovalStore,
    episode_plan_hash,
)
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_run import ScriptBuildRun, ScriptBuildRunStore
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    BlockBuildReport,
    BlockEvidenceExtraction,
    ClaimLedger,
    SourceDocumentBlock,
)
from thesisound.web.app import create_app
from thesisound.web.source_manifest import UiSourceManifest, UiSourceManifestStore, UiSourceStatus
from thesisound.web.upload_paths import resolve_uploaded_source_path


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


def _otp_login(client: TestClient) -> None:
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


def _login(client: TestClient) -> None:
    _otp_login(client)
    account = client.app.state.accounts.get_or_create_phone_user("09120000000")
    for project in client.app.state.workspace.list_projects():
        client.app.state.accounts.add_project_member(project.project_id, account.user_id)


def _project(source_id, *, state: ProjectState = ProjectState.SCRIPT_VERIFIED) -> Project:
    return Project(
        raw_input="موضوع",
        state=state,
        brief=ResearchBrief(
            normalized_topic="موضوع",
            topic_type=TopicType.CONCEPT,
            central_question="سؤال؟",
            target_duration_minutes=5,
        ),
        sources=[
            SourceCandidate(
                source_id=source_id,
                title="کتاب اصلی",
                role=SourceRole.PRIMARY,
                source_type="book",
                origin="fixture",
                access=SourceAccess.FULL_TEXT,
                user_decision=SourceDecision.INCLUDE,
            )
        ],
        episode_plan=EpisodePlan(
            title="طرح",
            listener_outcome="نتیجه",
            estimated_duration_minutes=5,
            segments=[
                EpisodeSegment(
                    segment_id="seg-1",
                    title="بخش",
                    purpose="شرح",
                    estimated_minutes=5,
                    claim_ids=["claim-1"],
                    key_question="پرسش؟",
                    speaker_dynamic="explanation",
                )
            ],
        ),
        script=Script(
            title="متن",
            turns=[
                ScriptTurn(
                    turn_id="t1",
                    segment_id="seg-1",
                    speaker="A",
                    spoken_text_fa="گفتهٔ مستند به منبع.",
                    claim_ids=["claim-1"],
                    evidence_ids=["ev-1"],
                )
            ],
        ),
    )


def _seed_verified_script(settings: Settings, project: Project, source_id) -> None:
    workspace = WorkspaceStore(settings.workspace_root)
    workspace.save_project(project)
    approval = EpisodePlanApproval(
        project_id=project.project_id,
        plan_hash=episode_plan_hash(project.episode_plan),
        approved_by="09120000000",
    )
    EpisodePlanApprovalStore(settings.workspace_root).save(approval)
    ScriptBuildRunStore(settings.workspace_root).save(
        ScriptBuildRun(
            project_id=project.project_id,
            approved_plan_hash=approval.plan_hash,
            approved_by=approval.approved_by,
            status="succeeded",
            stage="complete",
        )
    )
    script_store = ScriptArtifactStore(settings.workspace_root)
    script_store.save_script(project.project_id, project.script)
    script_store.save_checks(
        ScriptCheckReport(
            project_id=project.project_id,
            verdict="pass",
            word_count=5,
            estimated_minutes=0.05,
            substantive_turn_count=1,
        )
    )
    script_store.save_verification(
        project.project_id,
        VerificationDraft(verdict="pass", unsupported_claim_ratio=0),
    )
    script_store.save_manifest(
        ScriptPipelineManifest(project_id=project.project_id, status="verified")
    )
    store = SourceArtifactStore(settings.workspace_root)
    block_text = "پیش‌درآمد. عبارت دقیق منبع در میانهٔ پاره‌متن آمده است. ادامه."
    store.save_blocks(
        project.project_id,
        source_id,
        [
            SourceDocumentBlock(
                block_id="block-0",
                source_id=source_id,
                locator=Locator(page_start=11),
                text="پاره‌متن قبل از شاهد برای بافت.",
                estimated_token_count=8,
                source_block_keys=["k0"],
                next_block_id="block-1",
            ),
            SourceDocumentBlock(
                block_id="block-1",
                source_id=source_id,
                locator=Locator(page_start=12),
                text=block_text,
                estimated_token_count=20,
                source_block_keys=["k1"],
                previous_block_id="block-0",
                next_block_id="block-2",
            ),
            SourceDocumentBlock(
                block_id="block-2",
                source_id=source_id,
                locator=Locator(page_start=13),
                text="پاره‌متن بعد از شاهد برای بافت.",
                estimated_token_count=8,
                source_block_keys=["k2"],
                previous_block_id="block-1",
            ),
        ],
        BlockBuildReport(
            source_id=source_id,
            input_block_count=3,
            output_block_count=3,
        ),
    )
    store.save_evidence(
        project.project_id,
        source_id,
        [
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id="block-1",
                extraction=EvidenceExtraction(
                    segment_function="argument",
                    claims=[
                        EvidenceItem(
                            evidence_id="ev-1",
                            source_id=source_id,
                            block_id="block-1",
                            claim="گزاره مستند",
                            claim_type=ClaimType.AUTHOR_POSITION,
                            supporting_excerpt="عبارت دقیق منبع",
                            locator=Locator(page_start=12, page_end=12),
                            support_kind="direct",
                            confidence=0.9,
                        )
                    ],
                ),
            )
        ],
    )
    store.save_claim_ledger(
        project.project_id,
        source_id,
        ClaimLedger(
            source_id=source_id,
            claims=[
                ClaimRecord(
                    claim_id="claim-1",
                    claim="گزاره مستند",
                    claim_type=ClaimType.AUTHOR_POSITION,
                    evidence_ids=["ev-1"],
                    support_status=SupportStatus.STRONG,
                )
            ],
        ),
    )


def test_evidence_context_endpoint_highlights_and_neighbors(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source_id = uuid4()
    project = _project(source_id)
    _seed_verified_script(settings, project, source_id)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/script")
        assert page.status_code == 200
        assert 'data-evidence-context' in page.text
        assert "رفتن به نشانی" in page.text
        assert f"/sources/{source_id}/file#page=12" in page.text

        context = client.get(f"/projects/{project.project_id}/script/evidence/ev-1")
        assert context.status_code == 200
        assert "<mark>" in context.text
        assert "عبارت دقیق منبع" in context.text
        assert "پاره‌متن قبل" in context.text
        assert "پاره‌متن بعد" in context.text


def test_evidence_context_unknown_evidence_is_404(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source_id = uuid4()
    project = _project(source_id)
    _seed_verified_script(settings, project, source_id)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        response = client.get(f"/projects/{project.project_id}/script/evidence/missing")
    assert response.status_code == 404


def test_evidence_context_requires_auth(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source_id = uuid4()
    project = _project(source_id)
    _seed_verified_script(settings, project, source_id)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        response = client.get(
            f"/projects/{project.project_id}/script/evidence/ev-1",
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert "/auth/login" in response.headers["location"] or "/login" in response.headers["location"]


def test_evidence_context_foreign_project_redirects(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source_id = uuid4()
    foreign = _project(source_id)
    _seed_verified_script(settings, foreign, source_id)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
    )
    owner = app.state.accounts.get_or_create_phone_user("09121111111")
    app.state.accounts.add_project_member(foreign.project_id, owner.user_id)
    with TestClient(app) as client:
        _otp_login(client)
        # Authenticated caller is not a member of the foreign project.
        response = client.get(
            f"/projects/{foreign.project_id}/script/evidence/ev-1",
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/projects"


def _write_upload(
    workspace: WorkspaceStore,
    project_id,
    source_id,
    *,
    filename: str,
    content: bytes,
    under_web: bool = False,
) -> Path:
    root = workspace.project_dir(project_id) / "uploads"
    if under_web:
        root = root / "web"
    path = root / str(source_id) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_source_file_pdf_inline_with_security_headers(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    source_id = uuid4()
    project = _project(source_id, state=ProjectState.SOURCES_COLLECTING)
    project.script = None
    workspace.save_project(project)
    _write_upload(workspace, project.project_id, source_id, filename="book.pdf", content=b"%PDF-1.4")
    UiSourceManifestStore(workspace.project_dir(project.project_id)).save(
        [
            UiSourceManifest(
                source_id=source_id,
                filename="book.pdf",
                content_type="application/pdf",
                size_bytes=8,
                status=UiSourceStatus.READY,
            )
        ]
    )
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        response = client.get(f"/projects/{project.project_id}/sources/{source_id}/file")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "inline" in response.headers.get("content-disposition", "")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("content-security-policy") == "sandbox"


def test_source_file_non_pdf_forced_attachment(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    source_id = uuid4()
    project = _project(source_id, state=ProjectState.SOURCES_COLLECTING)
    project.script = None
    workspace.save_project(project)
    _write_upload(
        workspace,
        project.project_id,
        source_id,
        filename="page.html",
        content=b"<script>alert(1)</script>",
    )
    UiSourceManifestStore(workspace.project_dir(project.project_id)).save(
        [
            UiSourceManifest(
                source_id=source_id,
                filename="page.html",
                content_type="text/html",
                size_bytes=24,
                status=UiSourceStatus.READY,
            )
        ]
    )
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        response = client.get(f"/projects/{project.project_id}/sources/{source_id}/file")
    assert response.status_code == 200
    assert "attachment" in response.headers.get("content-disposition", "")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert "content-security-policy" not in {k.lower() for k in response.headers.keys()} or (
        response.headers.get("content-security-policy") != "sandbox"
    )


def test_source_file_unknown_source_is_404(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    source_id = uuid4()
    project = _project(source_id, state=ProjectState.SOURCES_COLLECTING)
    project.script = None
    workspace.save_project(project)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        response = client.get(f"/projects/{project.project_id}/sources/{uuid4()}/file")
    assert response.status_code == 404


def test_resolve_uploaded_source_path_rejects_escape(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    source_id = uuid4()
    project = _project(source_id, state=ProjectState.SOURCES_COLLECTING)
    project.script = None
    workspace.save_project(project)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    uploads = workspace.project_dir(project.project_id) / "uploads" / str(source_id)
    uploads.mkdir(parents=True, exist_ok=True)
    link = uploads / "escape.txt"
    link.symlink_to(outside)
    manifest = UiSourceManifest(
        source_id=source_id,
        filename="escape.txt",
        content_type="text/plain",
        size_bytes=6,
        status=UiSourceStatus.READY,
    )
    assert resolve_uploaded_source_path(workspace, project.project_id, manifest) is None
