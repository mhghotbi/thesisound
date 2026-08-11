from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import ValidationError

from thesisound.config import Settings
from thesisound.domain import (
    ClaimRecord,
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
    SupportStatus,
    TopicType,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.product_metrics.events import EpisodeEvidenceJudged, ProductEvent
from thesisound.script import ScriptCheckReport, ScriptPipelineManifest, VerificationDraft
from thesisound.services.plan_approval import (
    EpisodePlanApproval,
    EpisodePlanApprovalStore,
    episode_plan_hash,
)
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_run import ScriptBuildRun, ScriptBuildRunStore
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import BlockEvidenceExtraction, ClaimLedger
from thesisound.web.app import create_app
from thesisound.web.evidence_judgement_store import (
    EvidenceJudgementRecord,
    EvidenceJudgementStore,
    judgement_key,
)

TEMPLATES_ROOT = Path(__file__).parents[1] / "src" / "thesisound" / "web" / "templates"


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


def _seed_project(settings: Settings) -> tuple[Project, UUID]:
    workspace = WorkspaceStore(settings.workspace_root)
    source_id = uuid4()
    project = Project(
        raw_input="موضوع",
        state=ProjectState.SCRIPT_VERIFIED,
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
                    spoken_text_fa="گفتهٔ مستند.",
                    claim_ids=["claim-1"],
                    evidence_ids=["ev-1"],
                )
            ],
        ),
    )
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
            word_count=3,
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
                            claim="گزاره",
                            claim_type=ClaimType.AUTHOR_POSITION,
                            supporting_excerpt="عبارت شاهد",
                            locator=Locator(page_start=4, page_end=4, chapter="۱"),
                            support_kind="direct",
                            confidence=0.9,
                        )
                    ],
                ),
                extraction_identity={"model": "test-model", "prompt_version": "1"},
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
                    claim="متن مدعا",
                    claim_type=ClaimType.AUTHOR_POSITION,
                    evidence_ids=["ev-1"],
                    support_status=SupportStatus.STRONG,
                )
            ],
            reconciler_identity={"model": "reconciler", "prompt_version": "1"},
        ),
    )
    return project, source_id


def test_judgement_store_last_wins_and_clear(tmp_path: Path) -> None:
    store = EvidenceJudgementStore(tmp_path)
    project_id = uuid4()
    first = EvidenceJudgementRecord(
        project_id=project_id,
        turn_id="t1",
        claim_id="c1",
        evidence_id="e1",
        verdict="incorrect",
        reason="wrong_locator",
        user_id=7,
        excerpt="a",
    )
    second = first.model_copy(update={"verdict": "correct", "reason": None})
    store.append(first)
    store.append(second)
    latest = store.latest_by_key()
    key = judgement_key(second)
    assert latest[key].verdict == "correct"
    cleared = second.model_copy(update={"verdict": "cleared"})
    store.append(cleared)
    assert store.latest_by_key()[key].verdict == "cleared"


def test_judgement_record_rejects_long_note_and_invalid_reason() -> None:
    project_id = uuid4()
    with pytest.raises(ValidationError):
        EvidenceJudgementRecord(
            project_id=project_id,
            turn_id="t1",
            claim_id="c1",
            evidence_id="e1",
            verdict="incorrect",
            reason="wrong_locator",
            note="x" * 501,
            user_id=1,
        )
    with pytest.raises(ValidationError):
        EvidenceJudgementRecord(
            project_id=project_id,
            turn_id="t1",
            claim_id="c1",
            evidence_id="e1",
            verdict="incorrect",
            reason="not_a_reason",  # type: ignore[arg-type]
            user_id=1,
        )
    with pytest.raises(ValidationError):
        EvidenceJudgementRecord(
            project_id=project_id,
            turn_id="t1",
            claim_id="c1",
            evidence_id="e1",
            verdict="incorrect",
            user_id=1,
        )


def test_episode_evidence_judged_payload_has_no_ids_or_free_text() -> None:
    payload = EpisodeEvidenceJudged(verdict="incorrect", reason="claim_mismatch")
    dumped = payload.model_dump()
    assert set(dumped) == {"verdict", "reason"}
    with pytest.raises(ValidationError):
        EpisodeEvidenceJudged.model_validate(
            {"verdict": "correct", "evidence_id": "ev-1"}
        )


def test_judgement_route_writes_snapshot_and_emits(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    project, _source_id = _seed_project(settings)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/script")
        assert "درست است" in page.text
        assert "نادرست است" in page.text
        assert "data-evidence-judgement" in page.text
        csrf = _csrf(page.text)
        response = client.post(
            f"/projects/{project.project_id}/script/evidence/ev-1/judgement",
            data={
                "csrf_token": csrf,
                "turn_id": "t1",
                "claim_id": "claim-1",
                "verdict": "incorrect",
                "reason": "excerpt_does_not_support",
                "note": "کوتاه",
            },
        )
    assert response.status_code == 204
    store = EvidenceJudgementStore(settings.workspace_root)
    rows = store.read_all()
    assert len(rows) == 1
    assert rows[0].excerpt == "عبارت شاهد"
    assert rows[0].claim_text == "متن مدعا"
    assert rows[0].extraction_identity is not None
    assert rows[0].reconciler_identity is not None


def test_judgement_unknown_evidence_is_silent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    project, _ = _seed_project(settings)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/script")
        response = client.post(
            f"/projects/{project.project_id}/script/evidence/missing/judgement",
            data={
                "csrf_token": _csrf(page.text),
                "turn_id": "t1",
                "claim_id": "claim-1",
                "verdict": "correct",
            },
        )
    assert response.status_code == 204
    assert EvidenceJudgementStore(settings.workspace_root).read_all() == []


def test_judgement_bad_csrf_is_403(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    project, _ = _seed_project(settings)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        _login(client)
        response = client.post(
            f"/projects/{project.project_id}/script/evidence/ev-1/judgement",
            data={
                "csrf_token": "not-the-token",
                "turn_id": "t1",
                "claim_id": "claim-1",
                "verdict": "correct",
            },
        )
    assert response.status_code == 403


def test_judgement_requires_auth(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    project, _ = _seed_project(settings)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
    )
    with TestClient(app) as client:
        response = client.post(
            f"/projects/{project.project_id}/script/evidence/ev-1/judgement",
            data={"turn_id": "t1", "claim_id": "claim-1", "verdict": "correct"},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert "/login" in response.headers["location"]


def test_judgement_write_failure_still_204(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    project, _ = _seed_project(settings)
    app = create_app(
        settings,
        corpus_executor=lambda _: None,
        episode_executor=lambda _: None,
        script_executor=lambda _: None,
    )

    def boom(self, record):  # noqa: ANN001
        raise OSError("disk full")

    monkeypatch.setattr(EvidenceJudgementStore, "append", boom)
    with TestClient(app) as client:
        _login(client)
        page = client.get(f"/projects/{project.project_id}/script")
        response = client.post(
            f"/projects/{project.project_id}/script/evidence/ev-1/judgement",
            data={
                "csrf_token": _csrf(page.text),
                "turn_id": "t1",
                "claim_id": "claim-1",
                "verdict": "correct",
            },
        )
    assert response.status_code == 204


def test_macro_judgement_only_with_turn_id() -> None:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATES_ROOT),
        autoescape=True,
        undefined=StrictUndefined,
    )
    environment.filters["fa_num"] = str
    template = environment.from_string(
        "{% from 'components.html' import evidence_claim_groups %}"
        "{{ evidence_claim_groups(claim_groups, 'proj', drawer, turn_id) }}"
    )
    groups = [
        {
            "claim_id": "c1",
            "claim_text": "مدعا",
            "support_status": "strong",
            "support_status_label": "پشتوانه قوی",
            "availability": "ok",
            "evidence": [
                {
                    "evidence_id": "ev-1",
                    "status": "ok",
                    "availability": "ok",
                    "source_id": str(uuid4()),
                    "source_title": "کتاب",
                    "locator": "صفحه 1",
                    "locator_label": "صفحه 1",
                    "page_start": 1,
                    "excerpt": "عبارت",
                    "support_kind": "direct",
                    "support_kind_label": "شاهد صریح",
                }
            ],
        }
    ]
    with_turn = template.render(claim_groups=groups, drawer=True, turn_id="t1")
    assert "درست است" in with_turn
    assert "excerpt_does_not_support" in with_turn
    without = template.render(claim_groups=groups, drawer=False, turn_id="t1")
    assert "درست است" not in without
    assert ProductEvent.EPISODE_EVIDENCE_JUDGED.value
