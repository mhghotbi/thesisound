"""Audio generate form must accept the common case: empty optional notes."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from thesisound.config import Settings
from thesisound.domain import (
    EpisodePlan,
    EpisodeSegment,
    Project,
    ProjectState,
    ResearchBrief,
    Script,
    ScriptTurn,
    TopicType,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.script import ScriptCheckReport, ScriptPipelineManifest, VerificationDraft
from thesisound.services.audio_run import AudioBuildRunStore
from thesisound.services.plan_approval import (
    EpisodePlanApproval,
    EpisodePlanApprovalStore,
    episode_plan_hash,
)
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_run import ScriptBuildRun, ScriptBuildRunStore
from thesisound.web.app import create_app


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


def _seed_script_verified(settings: Settings) -> Project:
    workspace = WorkspaceStore(settings.workspace_root)
    script = Script(
        title="گفتار آزمون",
        turns=[
            ScriptTurn(
                turn_id="turn-1",
                segment_id="seg-1",
                speaker="A",
                spoken_text_fa="متن آزمون.",
                claim_ids=["claim-1"],
                evidence_ids=["evidence-1"],
            )
        ],
    )
    project = Project(
        raw_input="موضوع",
        state=ProjectState.SCRIPT_VERIFIED,
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
        script=script,
    )
    workspace.save_project(project)
    plan_hash = episode_plan_hash(project.episode_plan)
    EpisodePlanApprovalStore(settings.workspace_root).save(
        EpisodePlanApproval(
            project_id=project.project_id,
            plan_hash=plan_hash,
            approved_by="09120000000",
        )
    )
    ScriptBuildRunStore(settings.workspace_root).save(
        ScriptBuildRun(
            project_id=project.project_id,
            approved_plan_hash=plan_hash,
            approved_by="09120000000",
            status="succeeded",
            stage="complete",
        )
    )
    store = ScriptArtifactStore(settings.workspace_root)
    store.save_script(project.project_id, script)
    store.save_checks(
        ScriptCheckReport(
            project_id=project.project_id,
            verdict="pass",
            word_count=2,
            estimated_minutes=0.05,
            substantive_turn_count=1,
        )
    )
    store.save_verification(
        project.project_id,
        VerificationDraft(verdict="pass", unsupported_claim_ratio=0),
    )
    store.save_manifest(
        ScriptPipelineManifest(project_id=project.project_id, status="verified")
    )
    return project


def test_audio_generate_accepts_empty_optional_notes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    project = _seed_script_verified(settings)
    app = create_app(settings, audio_executor=lambda _: None)

    with TestClient(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/audio")
        assert "ساخت و وارسی نسخهٔ شنیداری" in page.text
        body = urlencode(
            {
                "csrf_token": _csrf(page.text),
                "voice_a": "Kore",
                "voice_b": "Puck",
                "pace": "moderate",
                "tone": "جدی و صمیمی",
                "accent": "تهرانی",
                "speaker_a_notes": "",
                "speaker_b_notes": "",
            }
        )
        response = client.post(
            f"/projects/{project.project_id}/audio/generate",
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/audio")
    run = AudioBuildRunStore(settings.workspace_root).load(project.project_id)
    assert run.status == "queued"
    assert run.direction is not None
    assert run.direction.speaker_a_notes == ""
    assert run.direction.speaker_b_notes == ""
