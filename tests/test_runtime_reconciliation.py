from pathlib import Path
from uuid import uuid4

from thesisound.config import Settings
from thesisound.domain import (
    EpisodePlan,
    EpisodeSegment,
    Project,
    ProjectState,
    ResearchBrief,
    TopicType,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.services.corpus_building import (
    CorpusBuildRun,
    CorpusBuildRunStore,
    CorpusSourceRun,
)
from thesisound.services.episode_planning_run import (
    EpisodePlanningRun,
    EpisodePlanningRunStore,
)
from thesisound.web.corpus_runtime import create_corpus_builder
from thesisound.web.episode_runtime import create_episode_planner


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        ingestion_artifact_root=tmp_path / "artifacts",
        web_session_secret="test-secret-that-is-long-enough",
        allow_test_otp=True,
        ui_demo_mode=False,
    )


def test_startup_reconciles_ready_project_with_running_corpus_pointer(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = Project(raw_input="topic", state=ProjectState.CORPUS_READY)
    workspace.save_project(project)
    run_store = CorpusBuildRunStore(workspace.root)
    run_store.save(
        CorpusBuildRun(
            project_id=project.project_id,
            status="running",
            sources=[
                CorpusSourceRun(
                    source_id=uuid4(),
                    filename="source.txt",
                    ingestion_path=tmp_path / "source.json",
                    status="succeeded",
                    stage="complete",
                )
            ],
        )
    )

    create_corpus_builder(settings, workspace)

    recovered = run_store.load(project.project_id)
    assert recovered.status == "succeeded"
    assert recovered.last_error is None
    assert workspace.load_project(project.project_id).state == ProjectState.CORPUS_READY


def test_startup_reconciles_planned_project_with_running_planning_pointer(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    workspace = WorkspaceStore(settings.workspace_root)
    project = Project(
        raw_input="topic",
        state=ProjectState.EPISODE_PLANNED,
        brief=ResearchBrief(
            normalized_topic="topic",
            topic_type=TopicType.CONCEPT,
            central_question="Question?",
            target_duration_minutes=10,
        ),
        episode_plan=EpisodePlan(
            title="Plan",
            listener_outcome="Understand",
            estimated_duration_minutes=10,
            segments=[
                EpisodeSegment(
                    segment_id="seg-1",
                    title="Segment",
                    purpose="Explain",
                    estimated_minutes=10,
                    claim_ids=["claim-1"],
                    key_question="Question?",
                    speaker_dynamic="explanation",
                )
            ],
        ),
    )
    workspace.save_project(project)
    run_store = EpisodePlanningRunStore(workspace.root)
    run_store.save(
        EpisodePlanningRun(
            project_id=project.project_id,
            status="running",
            stage="building_evidence_packs",
            target_duration_minutes=10,
        )
    )

    create_episode_planner(settings, workspace)

    recovered = run_store.load(project.project_id)
    assert recovered.status == "succeeded"
    assert recovered.stage == "complete"
    assert recovered.last_error is None
    assert workspace.load_project(project.project_id).state == ProjectState.EPISODE_PLANNED
