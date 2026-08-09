from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from thesisound.domain import (
    ClaimType,
    DocumentMap,
    DocumentMapSection,
    Locator,
    Project,
    ProjectState,
    ResearchBrief,
    SourceAccess,
    SourceCandidate,
    SourceDecision,
    SourceRole,
    SupportStatus,
    TopicType,
)
from thesisound.pipeline import WorkspaceStore, transition
from thesisound.services.analysis_profile import plan_evidence_extraction
from thesisound.services.corpus_building import (
    CorpusBuildingService,
    CorpusBuildRun,
    CorpusBuildRunStore,
    CorpusSourceInput,
)
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    BlockBuildReport,
    ClaimLedger,
    ClaimRecord,
    SourceAnalysisManifest,
    SourceDocumentBlock,
)

_INGESTION_SHA256 = "b" * 64


class FakeSourceStore(SourceArtifactStore):
    """Real artifact store with a stand-in for the ingestion file itself."""

    ingestion_sha256 = _INGESTION_SHA256

    def load_ingestion(self, path: Path):  # type: ignore[override]
        del path
        return SimpleNamespace(inspection=SimpleNamespace(sha256=self.ingestion_sha256))


class FailingRunStore(CorpusBuildRunStore):
    def save(self, run: CorpusBuildRun) -> Path:
        del run
        raise RuntimeError("simulated persistence failure")


class FakeAnalysisService:
    def __init__(self, workspace: WorkspaceStore, *, fail_source: UUID | None = None) -> None:
        self.workspace = workspace
        self.fail_source = fail_source
        self.states_seen: list[ProjectState] = []
        self.built: list[UUID] = []

    def build_blocks(self, project_id, ingestion, *, source_id):
        del ingestion
        self.built.append(source_id)
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

    def has_reusable_document_map(self, project_id, source_id):
        del project_id, source_id
        return False

    def extract_evidence(self, project_id, source_id, *, model):
        del model
        return (
            SourceAnalysisManifest(
                project_id=project_id,
                source_id=source_id,
                source_sha256="a" * 64,
                status="evidence_ready",
                block_count=1,
                evidence_count=1,
            ),
            [],
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
        source_store=FakeSourceStore(workspace.root),
        analysis_service_factory=lambda: fake,  # type: ignore[return-value]
        fast_model="fake-fast",
        strong_model="fake-strong",
    )


def _source_input(tmp_path: Path, source_id: UUID, name: str) -> CorpusSourceInput:
    return CorpusSourceInput(
        source_id=source_id,
        filename=f"{name}.txt",
        ingestion_path=tmp_path / f"{name}.json",
    )


def _brief_project() -> Project:
    return Project(
        raw_input="اخلاق کانت",
        state=ProjectState.CORPUS_BUILDING,
        brief=ResearchBrief(
            normalized_topic="اخلاق کانت",
            topic_type=TopicType.CONCEPT,
            central_question="اخلاق کانت چگونه کار می‌کند؟",
            target_duration_minutes=20,
        ),
    )


def _confirmed_source(source_id: UUID, title: str) -> SourceCandidate:
    return SourceCandidate(
        source_id=source_id,
        title=title,
        role=SourceRole.USER_CONTEXT,
        source_type="txt",
        origin="user_upload",
        access=SourceAccess.FULL_TEXT,
        user_decision=SourceDecision.INCLUDE,
    )


def _seed_claim_ready_artifacts(
    store: SourceArtifactStore,
    project: Project,
    source_id: UUID,
    *,
    source_sha256: str = _INGESTION_SHA256,
) -> None:
    """Write everything a finished source leaves on disk, the way the pipeline does."""

    assert project.brief is not None
    blocks = [
        SourceDocumentBlock(
            block_id="block-1",
            source_id=source_id,
            locator=Locator(),
            text="متن آزمون برای ساخت دفتر مدعاها.",
            estimated_token_count=120,
            source_block_keys=["key-1"],
        )
    ]
    document_map = DocumentMap(
        source_id=source_id,
        scope_locator=Locator(),
        sections=[
            DocumentMapSection(
                section_id="section-1",
                source_block_ids=["block-1"],
                title="بخش اصلی",
                function="argument",
                required_for_global_understanding=True,
            )
        ],
    )
    store.save_blocks(
        project.project_id,
        source_id,
        blocks,
        BlockBuildReport(source_id=source_id, input_block_count=1, output_block_count=1),
    )
    store.save_document_map(project.project_id, source_id, document_map)
    store.save_extraction_plan(
        project.project_id,
        source_id,
        plan_evidence_extraction(project.brief, document_map, blocks),
    )
    store.save_claim_ledger(
        project.project_id,
        source_id,
        ClaimLedger(
            source_id=source_id,
            claims=[
                ClaimRecord(
                    claim_id="claim-1",
                    claim="مدعای آزمون",
                    claim_type=ClaimType.AUTHOR_POSITION,
                    evidence_ids=["evidence-1"],
                    support_status=SupportStatus.STRONG,
                )
            ],
        ),
    )
    store.save_manifest(
        SourceAnalysisManifest(
            project_id=project.project_id,
            source_id=source_id,
            source_sha256=source_sha256,
            status="claims_ready",
            block_count=1,
            claim_count=1,
        )
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


def test_skipping_a_stopped_source_continues_the_remaining_selection(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    first, stopped, last = uuid4(), uuid4(), uuid4()
    project = Project(raw_input="topic", state=ProjectState.CORPUS_BUILDING)
    project.sources = [
        _confirmed_source(first, "first.txt"),
        _confirmed_source(stopped, "second.txt"),
        _confirmed_source(last, "third.txt"),
    ]
    fake = FakeAnalysisService(workspace, fail_source=stopped)
    service = _service(tmp_path, project, fake)

    service.queue(
        project.project_id,
        [
            _source_input(tmp_path, first, "first"),
            _source_input(tmp_path, stopped, "second"),
            _source_input(tmp_path, last, "third"),
        ],
    )
    failed = service.run(project.project_id)
    assert [source.status for source in failed.sources] == [
        "succeeded",
        "failed",
        "queued",
    ]

    skipped = service.skip_source(project.project_id, stopped)

    assert skipped.run_id != failed.run_id
    assert skipped.previous_run_id == failed.run_id
    assert [source.status for source in skipped.sources] == [
        "succeeded",
        "skipped",
        "queued",
    ]
    assert skipped.sources[1].stage == "skipped"
    assert skipped.sources[1].last_error is not None
    assert skipped.selected_source_count == 2
    assert [source.source_id for source in workspace.load_project(project.project_id).sources] == [
        first,
        last,
    ]

    completed = service.run(project.project_id)

    assert completed.status == "succeeded"
    assert completed.completed_source_count == 2
    assert completed.skipped_source_count == 1
    assert workspace.load_project(project.project_id).state == ProjectState.CORPUS_READY
    assert fake.built.count(stopped) == 1  # only the attempt that failed


def test_skipping_the_only_stopped_source_completes_the_corpus(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    first, stopped = uuid4(), uuid4()
    project = Project(raw_input="topic", state=ProjectState.CORPUS_BUILDING)
    project.sources = [
        _confirmed_source(first, "first.txt"),
        _confirmed_source(stopped, "second.txt"),
    ]
    fake = FakeAnalysisService(workspace, fail_source=stopped)
    factory_calls: list[int] = []

    def factory() -> FakeAnalysisService:
        factory_calls.append(1)
        return fake

    service = CorpusBuildingService(
        workspace_store=workspace,
        run_store=CorpusBuildRunStore(workspace.root),
        source_store=FakeSourceStore(workspace.root),
        analysis_service_factory=factory,  # type: ignore[arg-type]
        fast_model="fake-fast",
        strong_model="fake-strong",
    )
    workspace.save_project(project)
    service.queue(
        project.project_id,
        [
            _source_input(tmp_path, first, "first"),
            _source_input(tmp_path, stopped, "second"),
        ],
    )
    service.run(project.project_id)
    service.skip_source(project.project_id, stopped)

    completed = service.run(project.project_id)

    assert completed.status == "succeeded"
    assert workspace.load_project(project.project_id).state == ProjectState.CORPUS_READY
    assert factory_calls == [1]  # nothing left to build, so no model client is opened


def test_skip_refuses_a_finished_source_and_an_unknown_source(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    first, stopped = uuid4(), uuid4()
    project = Project(raw_input="topic", state=ProjectState.CORPUS_BUILDING)
    fake = FakeAnalysisService(workspace, fail_source=stopped)
    service = _service(tmp_path, project, fake)
    service.queue(
        project.project_id,
        [
            _source_input(tmp_path, first, "first"),
            _source_input(tmp_path, stopped, "second"),
        ],
    )
    service.run(project.project_id)

    with pytest.raises(ValueError, match="cannot be dropped"):
        service.skip_source(project.project_id, first)
    with pytest.raises(ValueError, match="not part of"):
        service.skip_source(project.project_id, uuid4())

    unchanged = service.run_store.load(project.project_id)
    assert [source.status for source in unchanged.sources] == ["succeeded", "failed"]


def test_skip_refuses_to_empty_the_corpus(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    only_source = uuid4()
    project = Project(raw_input="topic", state=ProjectState.CORPUS_BUILDING)
    project.sources = [_confirmed_source(only_source, "only.txt")]
    fake = FakeAnalysisService(workspace, fail_source=only_source)
    service = _service(tmp_path, project, fake)
    service.queue(project.project_id, [_source_input(tmp_path, only_source, "only")])
    service.run(project.project_id)

    with pytest.raises(ValueError, match="At least one source"):
        service.skip_source(project.project_id, only_source)

    assert workspace.load_project(project.project_id).sources[0].source_id == only_source


def test_retry_keeps_a_skipped_source_out_of_the_next_attempt(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    stopped, other = uuid4(), uuid4()
    project = Project(raw_input="topic", state=ProjectState.CORPUS_BUILDING)
    fake = FakeAnalysisService(workspace, fail_source=stopped)
    service = _service(tmp_path, project, fake)
    service.queue(
        project.project_id,
        [
            _source_input(tmp_path, stopped, "first"),
            _source_input(tmp_path, other, "second"),
        ],
    )
    service.run(project.project_id)
    skipped = service.skip_source(project.project_id, stopped)
    skipped.status = "failed"
    service.run_store.save(skipped)

    retried = service.retry(project.project_id)

    assert [source.status for source in retried.sources] == ["skipped", "queued"]


def test_confirming_a_smaller_selection_reuses_a_finished_source(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _brief_project()
    fake = FakeAnalysisService(workspace)
    service = _service(tmp_path, project, fake)
    finished, fresh = uuid4(), uuid4()
    _seed_claim_ready_artifacts(service.source_store, project, finished)

    run = service.queue(
        project.project_id,
        [
            _source_input(tmp_path, finished, "finished"),
            _source_input(tmp_path, fresh, "fresh"),
        ],
    )

    assert run.sources[0].status == "succeeded"
    assert run.sources[0].stage == "complete"
    assert run.sources[0].carried_forward
    assert run.sources[0].claim_count == 1
    assert run.sources[1].status == "queued"
    assert not run.sources[1].carried_forward

    completed = service.run(project.project_id)

    assert completed.status == "succeeded"
    assert fake.built == [fresh]
    assert workspace.load_project(project.project_id).state == ProjectState.CORPUS_READY


def test_reuse_is_refused_when_the_brief_changed(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _brief_project()
    fake = FakeAnalysisService(workspace)
    service = _service(tmp_path, project, fake)
    source_id = uuid4()
    _seed_claim_ready_artifacts(service.source_store, project, source_id)

    assert project.brief is not None
    project.brief.target_duration_minutes = 60  # a deeper profile plans different evidence
    workspace.save_project(project)
    run = service.queue(project.project_id, [_source_input(tmp_path, source_id, "source")])

    assert run.sources[0].status == "queued"

    service.run(project.project_id)

    assert fake.built == [source_id]


def test_reuse_is_refused_when_the_source_file_changed(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _brief_project()
    fake = FakeAnalysisService(workspace)
    service = _service(tmp_path, project, fake)
    source_id = uuid4()
    _seed_claim_ready_artifacts(
        service.source_store,
        project,
        source_id,
        source_sha256="c" * 64,
    )

    run = service.queue(project.project_id, [_source_input(tmp_path, source_id, "source")])

    assert run.sources[0].status == "queued"


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
