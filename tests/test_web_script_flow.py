from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from thesisound.config import Settings
from thesisound.domain import (
    ClaimType,
    EpisodePlan,
    EpisodeSegment,
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
    TopicType,
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
from thesisound.source_analysis import BlockEvidenceExtraction
from thesisound.web.app import create_app


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        ingestion_artifact_root=tmp_path / "artifacts",
        web_session_secret="test-secret-that-is-long-enough",
        allow_test_otp=True,
        test_otp_phone="0912000000",
        test_otp_code="999999",
        otp_resend_cooldown_seconds=5,
        ui_demo_mode=False,
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
            "phone": "0912000000",
            "csrf_token": _csrf(page.text),
            "next_path": "/projects",
        },
    )
    page = client.get("/login/verify")
    client.post(
        "/login/verify",
        data={"code": "999999", "csrf_token": _csrf(page.text)},
    )


def _project(state: ProjectState = ProjectState.EPISODE_PLANNED) -> Project:
    return Project(
        raw_input="موضوع",
        state=state,
        brief=ResearchBrief(
            normalized_topic="موضوع",
            topic_type=TopicType.CONCEPT,
            central_question="سؤال مرکزی چیست؟",
            target_duration_minutes=5,
        ),
        episode_plan=EpisodePlan(
            title="طرح آزمون",
            listener_outcome="فهم موضوع",
            estimated_duration_minutes=5,
            segments=[
                EpisodeSegment(
                    segment_id="seg-1",
                    title="بخش اول",
                    purpose="شرح موضوع",
                    estimated_minutes=5,
                    claim_ids=["claim-1"],
                    key_question="سؤال؟",
                    speaker_dynamic="explanation",
                )
            ],
        ),
    )


def test_get_has_no_side_effect_and_post_approval_queues_exact_plan(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()
    workspace.save_project(project)
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
        assert "تأیید همین طرح و ساخت سناریو" in page.text
        assert EpisodePlanApprovalStore(settings.workspace_root).load_optional(
            project.project_id
        ) is None
        assert ScriptBuildRunStore(settings.workspace_root).load_optional(
            project.project_id
        ) is None
        assert not (workspace.project_dir(project.project_id) / "script").exists()

        response = client.post(
            f"/projects/{project.project_id}/script/approve",
            data={"csrf_token": _csrf(page.text)},
            follow_redirects=False,
        )

    assert response.status_code == 303
    approval = EpisodePlanApprovalStore(settings.workspace_root).load(project.project_id)
    run = ScriptBuildRunStore(settings.workspace_root).load(project.project_id)
    assert approval.approved_by == "0912000000"
    assert approval.plan_hash == episode_plan_hash(project.episode_plan)
    assert run.approved_plan_hash == approval.plan_hash
    assert run.status == "queued"
    assert workspace.load_project(project.project_id).state == ProjectState.EPISODE_PLANNED


def test_episode_page_exposes_explicit_plan_approval_gate(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = _project()
    workspace.save_project(project)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
    )

    with TestClient(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/episode")

    assert page.status_code == 200
    assert "تأیید طرح و ساخت سناریو" in page.text
    assert f"/projects/{project.project_id}/script/approve" in page.text


def test_verified_script_page_shows_quality_and_source_trace(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    source_id = uuid4()
    project = _project(ProjectState.SCRIPT_VERIFIED)
    project.sources = [
        SourceCandidate(
            source_id=source_id,
            title="کتاب اصلی",
            role=SourceRole.PRIMARY,
            source_type="book",
            origin="fixture",
            access=SourceAccess.FULL_TEXT,
            user_decision=SourceDecision.INCLUDE,
        )
    ]
    project.script = Script(
        title="سناریوی آزمون",
        turns=[
            ScriptTurn(
                turn_id="seg-1-turn-001",
                segment_id="seg-1",
                speaker="A",
                spoken_text_fa="این گزاره به منبع متصل است.",
                claim_ids=["claim-1"],
                evidence_ids=["evidence-1"],
            )
        ],
    )
    workspace.save_project(project)
    approval = EpisodePlanApproval(
        project_id=project.project_id,
        plan_hash=episode_plan_hash(project.episode_plan),
        approved_by="0912000000",
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
            word_count=7,
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
    SourceArtifactStore(settings.workspace_root).save_evidence(
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
                            evidence_id="evidence-1",
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
    assert "سناریوی آزمون" in page.text
    assert "کنترل قطعی" in page.text
    assert "Verifier مستقل" in page.text
    assert "کتاب اصلی" in page.text
    assert "صفحه 12" in page.text
    assert "عبارت دقیق منبع" in page.text
    assert "SCRIPT_VERIFIED" in page.text
