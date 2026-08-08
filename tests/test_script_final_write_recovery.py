from pathlib import Path

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
from thesisound.services.plan_approval import (
    EpisodePlanApproval,
    EpisodePlanApprovalStore,
    episode_plan_hash,
)
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_run import (
    ScriptBuildRun,
    ScriptBuildRunService,
    ScriptBuildRunStore,
)


def test_failed_pointer_reconciles_when_verified_artifacts_are_complete(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    project = Project(
        raw_input="موضوع",
        state=ProjectState.SCRIPT_VERIFIED,
        brief=ResearchBrief(
            normalized_topic="موضوع",
            topic_type=TopicType.CONCEPT,
            central_question="سؤال؟",
            target_duration_minutes=5,
        ),
        episode_plan=EpisodePlan(
            title="طرح",
            listener_outcome="فهم موضوع",
            estimated_duration_minutes=5,
            segments=[
                EpisodeSegment(
                    segment_id="seg-1",
                    title="بخش",
                    purpose="توضیح",
                    estimated_minutes=5,
                    claim_ids=["claim-1"],
                    key_question="سؤال؟",
                    speaker_dynamic="explanation",
                )
            ],
        ),
    )
    workspace.save_project(project)
    assert project.episode_plan is not None
    plan_hash = episode_plan_hash(project.episode_plan)
    EpisodePlanApprovalStore(root).save(
        EpisodePlanApproval(
            project_id=project.project_id,
            plan_hash=plan_hash,
            approved_by="operator",
        )
    )
    run_store = ScriptBuildRunStore(root)
    run_store.save(
        ScriptBuildRun(
            project_id=project.project_id,
            approved_plan_hash=plan_hash,
            approved_by="operator",
            status="failed",
            stage="failed",
            last_error="final run write failed",
        )
    )
    artifacts = ScriptArtifactStore(root)
    artifacts.save_script(
        project.project_id,
        Script(
            title="سناریو",
            turns=[
                ScriptTurn(
                    turn_id="seg-1-turn-001",
                    segment_id="seg-1",
                    speaker="A",
                    spoken_text_fa="متن مستند",
                    claim_ids=["claim-1"],
                    evidence_ids=["evidence-1"],
                )
            ],
        ),
    )
    artifacts.save_checks(
        ScriptCheckReport(
            project_id=project.project_id,
            verdict="pass",
            word_count=2,
            estimated_minutes=0.02,
            substantive_turn_count=1,
        )
    )
    artifacts.save_verification(
        project.project_id,
        VerificationDraft(verdict="pass", unsupported_claim_ratio=0),
    )
    artifacts.save_manifest(
        ScriptPipelineManifest(project_id=project.project_id, status="verified")
    )
    service = ScriptBuildRunService(
        workspace_store=workspace,
        run_store=run_store,
        approval_store=EpisodePlanApprovalStore(root),
        script_store=artifacts,
        pipeline_factory=lambda _: None,  # type: ignore[return-value]
        glossary_model="fake",
        writer_model="fake",
        verifier_model="fake",
        reviser_model="fake",
    )

    recovered = service.recover_interrupted_runs()

    assert recovered == [project.project_id]
    current = run_store.load(project.project_id)
    assert current.status == "succeeded"
    assert current.stage == "complete"
    assert current.last_error is None
