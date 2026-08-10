from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from typer.testing import CliRunner

from thesisound.cli_with_audio import app
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
from thesisound.episode import CoverageReport
from thesisound.pipeline import WorkspaceStore
from thesisound.script import (
    ScriptCheckReport,
    ScriptPipelineManifest,
    ScriptReviewDecision,
    VerificationDraft,
)
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.plan_approval import (
    EpisodePlanApprovalStore,
    episode_plan_hash,
)
from thesisound.services.readiness import project_readiness
from thesisound.services.script_artifact_store import ScriptArtifactStore


def _project(state: ProjectState = ProjectState.EPISODE_PLANNED) -> Project:
    return Project(
        raw_input="topic",
        state=state,
        brief=ResearchBrief(
            normalized_topic="topic",
            topic_type=TopicType.CONCEPT,
            central_question="What is the argument?",
            target_duration_minutes=10,
        ),
        episode_plan=EpisodePlan(
            title="Plan",
            listener_outcome="Understand the argument",
            estimated_duration_minutes=10,
            segments=[
                EpisodeSegment(
                    segment_id="seg-1",
                    title="Argument",
                    purpose="Explain",
                    estimated_minutes=10,
                    claim_ids=["claim-1"],
                    key_question="Why?",
                    speaker_dynamic="explanation",
                )
            ],
        ),
    )


def _result(results, code: str):
    return next(result for result in results if result.code == code)


def _snapshot(root: Path) -> dict[str, tuple[int, str]]:
    return {
        str(path.relative_to(root)): (
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in root.rglob("*")
        if path.is_file()
    }


def test_draft_project_reports_every_gate_as_not_reached(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = Project(raw_input="topic")
    WorkspaceStore(root).save_project(project)

    results = project_readiness(project_id=project.project_id, workspace_root=root)

    assert results
    assert all(result.status == "not_reached" for result in results)


def test_plan_edited_after_approval_is_blocked(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = _project()
    workspace = WorkspaceStore(root)
    workspace.save_project(project)
    EpisodePlanApprovalStore(root).approve(project, approved_by="reviewer")
    project.episode_plan.title = "Edited after approval"
    workspace.save_project(project)

    result = _result(
        project_readiness(project_id=project.project_id, workspace_root=root),
        "episode-plan-approval",
    )

    assert result.status == "blocked"
    assert "changed" in result.detail


def test_raising_duration_after_audit_blocks_coverage(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = _project()
    workspace = WorkspaceStore(root)
    workspace.save_project(project)
    EpisodeArtifactStore(root).save_coverage(
        CoverageReport(
            project_id=project.project_id,
            central_question_status="well_covered",
            max_supported_minutes=10,
            recommendation="continue",
            recommendation_reason="Enough for ten minutes.",
            can_plan_episode=True,
            model_run_id=uuid4(),
        )
    )
    project.brief.target_duration_minutes = 20
    workspace.save_project(project)

    result = _result(
        project_readiness(project_id=project.project_id, workspace_root=root),
        "coverage-duration",
    )

    assert result.status == "blocked"


def test_corrupt_artifact_yields_unknown_not_a_crash(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = _project()
    WorkspaceStore(root).save_project(project)
    path = root / str(project.project_id) / "episode" / "coverage-report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"project_id":', encoding="utf-8")

    result = _result(
        project_readiness(project_id=project.project_id, workspace_root=root),
        "coverage-duration",
    )

    assert result.status == "unknown"


def test_readiness_writes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = _project()
    WorkspaceStore(root).save_project(project)
    before = _snapshot(root)

    project_readiness(project_id=project.project_id, workspace_root=root)

    assert _snapshot(root) == before


def test_cli_exits_one_when_any_gate_is_blocked(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = _project(ProjectState.BRIEF_READY)
    WorkspaceStore(root).save_project(project)

    result = CliRunner().invoke(
        app,
        ["readiness", str(project.project_id), "--workspace-root", str(root)],
    )

    assert result.exit_code == 1


def _save_reviewed_script_artifacts(root: Path, project: Project, *, stale: bool = False) -> None:
    assert project.episode_plan is not None
    store = ScriptArtifactStore(root)
    current_hash = episode_plan_hash(project.episode_plan)
    store.prepare_for_plan(project.project_id, current_hash)
    store.save_checks(
        ScriptCheckReport(
            project_id=project.project_id,
            verdict="pass",
            word_count=100,
            estimated_minutes=1,
            substantive_turn_count=2,
        )
    )
    store.save_verification(
        project.project_id,
        VerificationDraft(verdict="revise", unsupported_claim_ratio=0.1),
    )
    store.save_script(
        project.project_id,
        Script(
            title="Reviewed script",
            turns=[
                ScriptTurn(
                    turn_id="turn-1",
                    segment_id="seg-1",
                    speaker="A",
                    spoken_text_fa="متن بازبینی‌شده",
                    editorial_only=True,
                )
            ],
        ),
    )
    store.save_manifest(
        ScriptPipelineManifest(
            project_id=project.project_id,
            status="verified",
            segment_count=1,
            turn_count=1,
        )
    )
    plan_hash = current_hash
    if stale:
        plan_hash = "0" * 64 if plan_hash != "0" * 64 else "1" * 64
    store.save_review_decision(
        ScriptReviewDecision(
            project_id=project.project_id,
            decision="accepted",
            reviewer="reviewer",
            reason="The qualification is acceptable for this edition.",
            plan_hash=plan_hash,
            checks_verdict="pass",
            verification_verdict="revise",
            unsupported_claim_ratio=0.1,
            quality_overall=None,
        )
    )


def test_current_plan_bound_review_acceptance_unblocks_verification(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = _project(ProjectState.SCRIPT_VERIFIED)
    WorkspaceStore(root).save_project(project)
    _save_reviewed_script_artifacts(root, project)

    results = project_readiness(project_id=project.project_id, workspace_root=root)

    assert _result(results, "independent-verification").status == "pass"
    assert _result(results, "script-review-decision").status == "pass"


def test_stale_review_acceptance_does_not_unblock_verification(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = _project(ProjectState.SCRIPT_VERIFIED)
    WorkspaceStore(root).save_project(project)
    _save_reviewed_script_artifacts(root, project, stale=True)

    results = project_readiness(project_id=project.project_id, workspace_root=root)

    assert _result(results, "independent-verification").status == "blocked"
    assert _result(results, "script-review-decision").status == "blocked"


def test_plan_change_blocks_stale_script_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = _project(ProjectState.SCRIPT_VERIFIED)
    workspace = WorkspaceStore(root)
    workspace.save_project(project)
    _save_reviewed_script_artifacts(root, project)

    assert project.episode_plan is not None
    project.episode_plan.title = "Changed but not regenerated"
    workspace.save_project(project)

    results = project_readiness(project_id=project.project_id, workspace_root=root)

    assert _result(results, "script-checks").status == "blocked"
    assert _result(results, "independent-verification").status == "blocked"
    assert _result(results, "script-review-decision").status == "blocked"


def test_corrupt_review_decision_yields_unknown_not_a_crash(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = _project(ProjectState.SCRIPT_VERIFIED)
    WorkspaceStore(root).save_project(project)
    _save_reviewed_script_artifacts(root, project)
    decision_path = root / str(project.project_id) / "script" / "review-decision.json"
    decision_path.write_text('{"decision":', encoding="utf-8")

    results = project_readiness(project_id=project.project_id, workspace_root=root)

    assert _result(results, "independent-verification").status == "unknown"
    assert _result(results, "script-review-decision").status == "unknown"


def test_corrupt_project_artifact_yields_unknown_for_every_gate(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = _project()
    WorkspaceStore(root).save_project(project)
    project_path = root / str(project.project_id) / "project.json"
    project_path.write_text('{"project_id":', encoding="utf-8")

    results = project_readiness(project_id=project.project_id, workspace_root=root)

    assert results
    assert all(result.status == "unknown" for result in results)
    assert all(result.evidence == str(project_path) for result in results)


def test_verified_state_requires_complete_verified_script_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = _project(ProjectState.SCRIPT_VERIFIED)
    WorkspaceStore(root).save_project(project)
    assert project.episode_plan is not None
    store = ScriptArtifactStore(root)
    current_hash = episode_plan_hash(project.episode_plan)
    store.prepare_for_plan(project.project_id, current_hash)
    store.save_checks(
        ScriptCheckReport(
            project_id=project.project_id,
            verdict="pass",
            word_count=100,
            estimated_minutes=1,
            substantive_turn_count=2,
        )
    )
    store.save_verification(
        project.project_id,
        VerificationDraft(verdict="pass", unsupported_claim_ratio=0),
    )
    # Deliberately omit the script and manifest. The individual reports pass,
    # but the plan requires readiness to verify the complete artifact set.

    results = project_readiness(project_id=project.project_id, workspace_root=root)

    assert _result(results, "script-checks").status == "blocked"
    assert _result(results, "independent-verification").status == "blocked"
    assert _result(results, "script-review-decision").status == "blocked"
