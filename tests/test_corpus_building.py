from pathlib import Path
from uuid import UUID, uuid4

import pytest

from thesisound.domain import Project, ProjectState
from thesisound.pipeline import WorkspaceStore, transition
from thesisound.services.corpus_building import (
    CorpusBuildingService,
    CorpusBuildRun,
    CorpusBuildRunStore,
    CorpusSourceInput,
)
from thesisound.source_analysis import ClaimLedger, SourceAnalysisManifest


class FakeSourceStore:
    @staticmethod
    def load_ingestion(path: Path):
        return path


class FailingRunStore(CorpusBuildRunStore):
    def save(self, run: CorpusBuildRun) -> Path:
        del run
        raise RuntimeError("simulated persistence failure")


class FakeAnalysisService:
    def __init__(self, workspace: WorkspaceStore, *, fail_source: UUID | None = None) -> None:
        self.workspace = workspace
        self.fail_source = fail_source
        self.states_seen: list[ProjectState] = []

    def build_blocks(self, project_id, ingestion, *, source_id):
        del ingestion
        self.states_seen.append(self.workspace.load_project(project_id).state)
        return (
            source_id,
            [object()],
            SourceAnalysisManifest(
                project_id=project_id,
                source_id=source_id,
                source_sha256="a" * 64,
                status="blocks_ready",
                block_count=1,
            ),
        )

    def map_document(self, project_id, source_id, *, model):
        del model
        if source_id == self.fail_source:
            raise ValueError("mapping failed")
        return SourceAnalysisManifest(
            project_id=project_id,
            source_id=source_id,
            source_sha256="a" * 64,
            status="document_mapped",
            block_count=1,
        )

    def extract_evidence(self, project_id, source_id, *, model):
        del model
        return SourceAnalysisManifest(
            project_id=project_id,
            source_id=source_id,
            source_sha256="a" * 64,
            status="evidence_ready",
            block_count=1,
            evidence_count=1,
        )

    def build_claims(
        self,
        project_id,
        source_id,
        *,
        model,
        finalize_project,
    ):
        del model
        assert not finalize_project
        self.states_seen.append(self.workspace.load_project(project_id).state)
        ledger = ClaimLedger(source_id=source_id)
        manifest = SourceAnalysisManifest(
            project_id=project_id,
            source_id=source_id,
            source_sha256="a" * 64,
            status="claims_ready",
            block_count=1,
        )
        return ledger, manifest


def _service(
    tmp_path: Path,
    project: Project,
    fake: FakeAnalysisService,
    *,
    run_store: CorpusBuildRunStore | None = None,
) -> CorpusBuildingService:
    workspace = fake.workspace
    workspace.save_project(project)
    return CorpusBuildingService(
        workspace_store=workspace,
        run_store=run_store or CorpusBuildRunStore(workspace.root),
        source_store=FakeSourceStore(),  # type: ignore[arg-type]
        analysis_service_factory=lambda: fake,  # type: ignore[return-value]
        fast_model="fake-fast",
        strong_model="fake-strong",
    )


def test_multi_source_run_promotes_only_after_every_source(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(raw_input="topic", state=ProjectState.CORPUS_BUILDING)
    fake = FakeAnalysisService(workspace)
    service = _service(tmp_path, project, fake)
    source_ids = [uuid4(), uuid4()]

    service.queue(
        project.project_id,
        [
            CorpusSourceInput(
                source_id=source_id,
                filename=f"source-{index}.txt",
                ingestion_path=tmp_path / f"source-{index}.json",
            )
            for index, source_id in enumerate(source_ids, start=1)
        ],
    )
    run = service.run(project.project_id)

    assert run.status == "succeeded"
    assert run.completed_source_count == 2
    assert all(source.stage == "complete" for source in run.sources)
    assert workspace.load_project(project.project_id).state == ProjectState.CORPUS_READY
    assert fake.states_seen
    assert set(fake.states_seen) == {ProjectState.CORPUS_BUILDING}
    assert [item.run_id for item in service.run_store.load_history(project.project_id)] == [
        run.run_id
    ]


def test_failed_source_keeps_completed_source_and_creates_new_retry_attempt(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(raw_input="topic", state=ProjectState.CORPUS_BUILDING)
    failed_source = uuid4()
    fake = FakeAnalysisService(workspace, fail_source=failed_source)
    service = _service(tmp_path, project, fake)
    first_source = uuid4()

    service.queue(
        project.project_id,
        [
            CorpusSourceInput(
                source_id=first_source,
                filename="first.txt",
                ingestion_path=tmp_path / "first.json",
            ),
            CorpusSourceInput(
                source_id=failed_source,
                filename="second.txt",
                ingestion_path=tmp_path / "second.json",
            ),
        ],
    )
    failed = service.run(project.project_id)

    assert failed.status == "failed"
    assert failed.sources[0].status == "succeeded"
    assert failed.sources[1].status == "failed"
    assert workspace.load_project(project.project_id).state == ProjectState.FAILED_RETRYABLE

    retried = service.retry(project.project_id)
    assert retried.run_id != failed.run_id
    assert retried.previous_run_id == failed.run_id
    assert retried.status == "queued"
    assert retried.sources[0].status == "succeeded"
    assert retried.sources[1].status == "queued"
    history = service.run_store.load_history(project.project_id)
    assert [item.run_id for item in history] == [failed.run_id, retried.run_id]


def test_restart_recovery_turns_running_work_into_retryable_failure(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(raw_input="topic", state=ProjectState.CORPUS_BUILDING)
    fake = FakeAnalysisService(workspace)
    service = _service(tmp_path, project, fake)
    source_id = uuid4()
    run = service.queue(
        project.project_id,
        [
            CorpusSourceInput(
                source_id=source_id,
                filename="source.txt",
                ingestion_path=tmp_path / "source.json",
            )
        ],
    )
    run.status = "running"
    run.sources[0].status = "running"
    run.sources[0].stage = "extracting_evidence"
    service.run_store.save(run)

    recovered = service.recover_interrupted_runs()

    assert recovered == [project.project_id]
    restored = service.run_store.load(project.project_id)
    assert restored.status == "failed"
    assert restored.sources[0].status == "failed"
    assert restored.sources[0].stage == "failed"
    assert "restart" in restored.last_error.lower()
    failed_project = workspace.load_project(project.project_id)
    assert failed_project.state == ProjectState.FAILED_RETRYABLE

    retried = service.retry(project.project_id)
    assert retried.run_id != restored.run_id
    assert retried.previous_run_id == restored.run_id
    assert retried.status == "queued"
    assert retried.sources[0].status == "queued"


def test_confirmation_rolls_project_back_when_run_persistence_fails(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    original = Project(raw_input="topic", state=ProjectState.SOURCE_SELECTION_REQUIRED)
    fake = FakeAnalysisService(workspace)
    service = _service(
        tmp_path,
        original,
        fake,
        run_store=FailingRunStore(workspace.root),
    )
    confirmed = original.model_copy(deep=True)
    transition(confirmed, ProjectState.CORPUS_BUILDING)

    with pytest.raises(RuntimeError, match="persistence failure"):
        service.confirm_project(
            original,
            confirmed,
            [
                CorpusSourceInput(
                    source_id=uuid4(),
                    filename="source.txt",
                    ingestion_path=tmp_path / "source.json",
                )
            ],
        )

    assert workspace.load_project(original.project_id) == original
    assert service.run_store.load_optional(original.project_id) is None
