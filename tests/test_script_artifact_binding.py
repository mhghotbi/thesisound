from pathlib import Path
from uuid import uuid4

from thesisound.domain import (
    EpisodePlan,
    EpisodeSegment,
    Project,
    ProjectState,
    ResearchBrief,
    TopicType,
)
from thesisound.pipeline import WorkspaceStore, mark_failed
from thesisound.script import Glossary, ScriptTurnDraft, SegmentScriptDraft
from thesisound.services.plan_approval import (
    EpisodePlanApprovalStore,
    episode_plan_hash,
)
from thesisound.services.script_artifact_store import ScriptArtifactStore


def _project() -> Project:
    return Project(
        raw_input="موضوع",
        state=ProjectState.EPISODE_PLANNED,
        brief=ResearchBrief(
            normalized_topic="موضوع",
            topic_type=TopicType.CONCEPT,
            central_question="سؤال؟",
            target_duration_minutes=5,
        ),
        episode_plan=EpisodePlan(
            title="طرح اول",
            listener_outcome="فهم موضوع",
            estimated_duration_minutes=5,
            segments=[
                EpisodeSegment(
                    segment_id="seg-1",
                    title="بخش اول",
                    purpose="توضیح",
                    estimated_minutes=5,
                    claim_ids=["claim-1"],
                    key_question="سؤال؟",
                    speaker_dynamic="explanation",
                )
            ],
        ),
    )


def test_reapproving_changed_plan_discards_resumable_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    project = _project()
    workspace.save_project(project)
    approvals = EpisodePlanApprovalStore(root)
    artifacts = ScriptArtifactStore(root)

    first = approvals.approve(project, approved_by="operator")
    artifacts.save_segment_draft(
        project.project_id,
        "seg-1",
        SegmentScriptDraft(
            turns=[
                ScriptTurnDraft(
                    speaker="A",
                    spoken_text_fa="متن مستند",
                    claim_ids=["claim-1"],
                    evidence_ids=["evidence-1"],
                )
            ]
        ),
    )
    assert artifacts.load_segment_draft_optional(project.project_id, "seg-1") is not None

    changed = workspace.load_project(project.project_id)
    assert changed.episode_plan is not None
    changed.episode_plan.title = "طرح دوم"
    workspace.save_project(changed)
    second = approvals.approve(changed, approved_by="operator")

    assert first.plan_hash != second.plan_hash
    assert second.plan_hash == episode_plan_hash(changed.episode_plan)
    assert artifacts.artifacts_match_plan(project.project_id, second.plan_hash)
    assert artifacts.load_segment_draft_optional(project.project_id, "seg-1") is None


def test_glossary_without_manifest_is_not_resumable(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = _project()
    WorkspaceStore(root).save_project(project)
    EpisodePlanApprovalStore(root).approve(project, approved_by="operator")
    artifacts = ScriptArtifactStore(root)
    artifacts.save_glossary(
        Glossary(
            project_id=project.project_id,
            model_run_id=uuid4(),
        )
    )

    assert artifacts.load_glossary(project.project_id).project_id == project.project_id
    assert artifacts.load_glossary_optional(project.project_id) is None


def test_verified_script_can_enter_retryable_recovery() -> None:
    project = _project()
    project.state = ProjectState.SCRIPT_VERIFIED

    mark_failed(project, "verified artifact is missing")

    assert project.state == ProjectState.FAILED_RETRYABLE
    assert project.last_error == "verified artifact is missing"
