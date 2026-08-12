from __future__ import annotations

from uuid import UUID, uuid4

from test_episode_planning_run import FakePreparationService
from test_episode_planning_run import _brief as _episode_brief

from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    EvidenceExtraction,
    EvidenceItem,
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
from thesisound.modeling import (
    DeterministicValidationError,
    ModelExecution,
    ModelProviderError,
    ModelRunRecord,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.services.analysis_profile import build_analysis_profile
from thesisound.services.block_builder import BlockBuilder
from thesisound.services.claim_prioritizer import ClaimPrioritizer
from thesisound.services.claim_reconciler import ClaimReconcilerService
from thesisound.services.coverage_auditor import CoverageAuditorService
from thesisound.services.disagreement_graph import DisagreementGraphBuilder
from thesisound.services.document_mapper import DocumentMapperService
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.episode_budget import EpisodeBudgetEstimator
from thesisound.services.episode_planner import EpisodePlannerService
from thesisound.services.episode_planning_run import (
    EpisodePlanningRunService,
    EpisodePlanningRunStore,
)
from thesisound.services.episode_preparation_service import EpisodePreparationService
from thesisound.services.evidence_extractor import EvidenceExtractorService
from thesisound.services.evidence_pack_builder import EvidencePackBuilder
from thesisound.services.evidence_scope import (
    extraction_profiles_compatible,
    scope_claims_and_evidence,
)
from thesisound.services.source_analysis_service import SourceAnalysisService
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.services.sqlite_block_retriever import SQLiteBlockRetriever
from thesisound.source_analysis import (
    AnalysisProfile,
    BlockBuildReport,
    BlockEvidenceExtraction,
    ClaimDraft,
    ClaimLedger,
    ClaimReconciliationDraft,
    CrossSectionThreadDraft,
    DocumentMapDraft,
    DocumentMapDraftSection,
    EvidenceClaimDraft,
    EvidenceExtractionDraft,
    EvidenceExtractionPlan,
    SourceAnalysisManifest,
    SourceDocumentBlock,
)


class FakeRunner:
    def run(
        self,
        *,
        project_id: UUID,
        stage: str,
        variables: dict[str, object],
        output_type,
        model: str,
        validator=None,
        **_: object,
    ):
        if output_type is DocumentMapDraft:
            blocks = variables["blocks"]
            assert isinstance(blocks, list)
            sections = [
                DocumentMapDraftSection(
                    section_id=f"sec-{index:03d}",
                    source_block_ids=[item["block_id"]],
                    title=f"Section {index}",
                    function="argument",
                    key_concepts=["action"],
                    required_for_global_understanding=index == 1,
                )
                for index, item in enumerate(blocks, start=1)
            ]
            output = DocumentMapDraft(
                working_thesis="The chapter distinguishes action from fabrication.",
                sections=sections,
                cross_section_threads=[
                    CrossSectionThreadDraft(
                        label="action",
                        section_ids=[sections[0].section_id],
                        description="The central conceptual thread.",
                    )
                ],
            )
        elif output_type is EvidenceExtractionDraft:
            block = variables["block"]
            assert isinstance(block, dict)
            excerpt = str(block["text"]).split(".")[0].strip()
            output = EvidenceExtractionDraft(
                segment_function="argument",
                claims=[
                    EvidenceClaimDraft(
                        claim="Action occurs directly between persons.",
                        claim_type=ClaimType.AUTHOR_POSITION,
                        supporting_excerpt=excerpt,
                        support_kind="direct",
                        confidence=0.95,
                    )
                ],
                must_not_be_lost=["The distinction from fabrication."],
            )
        elif output_type is ClaimReconciliationDraft:
            evidence = variables["evidence_items"]
            assert isinstance(evidence, list)
            output = ClaimReconciliationDraft(
                claims=[
                    ClaimDraft(
                        claim="Action occurs directly between persons.",
                        claim_type=ClaimType.AUTHOR_POSITION,
                        evidence_ids=[item["evidence_id"] for item in evidence],
                        support_status=SupportStatus.STRONG,
                    )
                ]
            )
        else:
            raise AssertionError(f"Unexpected output type: {output_type}")
        if validator is not None:
            last_error: Exception | None = None
            for _ in range(5):
                try:
                    validator(output)
                    last_error = None
                    break
                except DeterministicValidationError as exc:
                    last_error = exc
            if last_error is not None:
                raise last_error
        record = ModelRunRecord(
            project_id=project_id,
            stage=stage,
            prompt_id=stage,
            prompt_version="test",
            prompt_hash="test",
            input_hash="test",
            provider="fake",
            model=model,
            output_model=output_type.__name__,
            status="succeeded",
        )
        return ModelExecution(output=output, record=record)


def _brief(duration: int = 30) -> ResearchBrief:
    return ResearchBrief(
        normalized_topic="Arendt and action",
        topic_type=TopicType.CONCEPT,
        central_question="What distinguishes action from fabrication?",
        target_duration_minutes=duration,
        learning_objectives=[
            "Distinguish action from fabrication.",
            "Explain why plurality matters.",
        ],
    )


def _profile(*, depth: str = "brief") -> AnalysisProfile:
    return AnalysisProfile(
        depth=depth,  # type: ignore[arg-type]
        target_duration_minutes=10 if depth == "brief" else 60,
        block_coverage_target=0.35,
        evidence_input_token_budget=18_000,
        max_claims_per_block=2 if depth == "brief" else 7,
        neighbor_context_blocks=0 if depth == "brief" else 2,
        include_examples=False,
        include_objections_and_responses=False,
        second_pass_for_core_sections=depth != "brief",
        rationale=["test"],
    )


def _prepare_equal_blocks_source(
    tmp_path,
    *,
    duration: int,
    block_count: int,
    tokens_per_block: int,
) -> tuple[SourceAnalysisService, UUID, UUID]:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = Project(
        raw_input="Arendt and action",
        state=ProjectState.BRIEF_READY,
        brief=_brief(duration),
    )
    workspace.save_project(project)
    store = SourceArtifactStore(tmp_path / "workspaces")
    source_id = uuid4()
    blocks = [
        SourceDocumentBlock(
            block_id=f"block-{index:02d}",
            source_id=source_id,
            locator=Locator(page_start=index, page_end=index),
            heading_path=["Body"],
            block_type="other",
            text=(
                f"Action occurs directly between persons in block {index}. "
                "It cannot be reduced to the fabrication of an object."
            ),
            estimated_token_count=tokens_per_block,
            source_block_keys=[f"source-{index}"],
        )
        for index in range(1, block_count + 1)
    ]
    store.save_blocks(
        project.project_id,
        source_id,
        blocks,
        BlockBuildReport(
            source_id=source_id,
            input_block_count=block_count,
            output_block_count=block_count,
        ),
    )
    store.save_manifest(
        SourceAnalysisManifest(
            project_id=project.project_id,
            source_id=source_id,
            source_sha256="b" * 64,
            status="blocks_ready",
            block_count=block_count,
        )
    )
    runner = FakeRunner()
    service = SourceAnalysisService(
        workspace_store=workspace,
        artifact_store=store,
        block_builder=BlockBuilder(),
        document_mapper=DocumentMapperService(runner),
        evidence_extractor=EvidenceExtractorService(runner),
        claim_reconciler=ClaimReconcilerService(runner),
    )
    service.map_document(project.project_id, source_id, model="fake")
    return service, project.project_id, source_id


def test_extraction_profiles_compatible_ignores_budget_and_rationale() -> None:
    base = build_analysis_profile(_brief(10))
    nudged = base.model_copy(
        update={
            "target_duration_minutes": 12,
            "evidence_input_token_budget": base.evidence_input_token_budget + 1_000,
            "block_coverage_target": min(1.0, base.block_coverage_target + 0.05),
            "rationale": ["different wording"],
        }
    )
    deeper = build_analysis_profile(_brief(60))
    flag_only = base.model_copy(update={"second_pass_for_core_sections": True})

    assert extraction_profiles_compatible(base, nudged)
    assert not extraction_profiles_compatible(base, deeper)
    assert not extraction_profiles_compatible(base, flag_only)


def test_scope_claims_and_evidence_drops_deferred_block_support() -> None:
    source_id = uuid4()
    in_scope = EvidenceItem(
        evidence_id="ev-keep",
        source_id=source_id,
        block_id="block-keep",
        claim="In scope",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt="keep",
        locator=Locator(page_start=1, page_end=1),
        support_kind="direct",
        confidence=0.9,
    )
    deferred = EvidenceItem(
        evidence_id="ev-drop",
        source_id=source_id,
        block_id="block-drop",
        claim="Deferred",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt="drop",
        locator=Locator(page_start=2, page_end=2),
        support_kind="direct",
        confidence=0.9,
    )
    claims = [
        ClaimRecord(
            claim_id="c-keep",
            claim="Keep me",
            claim_type=ClaimType.AUTHOR_POSITION,
            evidence_ids=["ev-keep"],
            support_status=SupportStatus.STRONG,
        ),
        ClaimRecord(
            claim_id="c-drop",
            claim="Drop me",
            claim_type=ClaimType.AUTHOR_POSITION,
            evidence_ids=["ev-drop"],
            support_status=SupportStatus.STRONG,
        ),
        ClaimRecord(
            claim_id="c-mixed",
            claim="Mixed support",
            claim_type=ClaimType.AUTHOR_POSITION,
            evidence_ids=["ev-keep", "ev-drop"],
            support_status=SupportStatus.MODERATE,
        ),
        ClaimRecord(
            claim_id="c-editorial",
            claim="Bridge",
            claim_type=ClaimType.EDITORIAL_EXPLANATION,
            evidence_ids=[],
            support_status=SupportStatus.UNCERTAIN,
        ),
    ]

    scoped_claims, scoped_evidence = scope_claims_and_evidence(
        claims,
        [in_scope, deferred],
        {"block-keep"},
    )

    assert [item.evidence_id for item in scoped_evidence] == ["ev-keep"]
    assert [claim.claim_id for claim in scoped_claims] == ["c-keep", "c-editorial"]


def test_extract_evidence_skips_only_compatible_selected_blocks(tmp_path) -> None:
    service, project_id, source_id = _prepare_equal_blocks_source(
        tmp_path,
        duration=10,
        block_count=18,
        tokens_per_block=100,
    )
    store = service.artifact_store
    service.extract_evidence(project_id, source_id, model="fake")

    skip_snapshots: list[set[str]] = []
    original = service.evidence_extractor.extract_source

    def wrapped(**kwargs):
        skip_snapshots.append(set(kwargs.get("skip_block_ids") or set()))
        return original(**kwargs)

    service.evidence_extractor.extract_source = wrapped  # type: ignore[method-assign]

    service.extract_evidence(project_id, source_id, model="fake")
    plan = store.load_extraction_plan(project_id, source_id)
    assert skip_snapshots[0] == set(plan.selected_block_ids)

    project = service.workspace_store.load_project(project_id)
    assert project.brief is not None
    project.brief.target_duration_minutes = 60
    service.workspace_store.save_project(project)
    service.extract_evidence(project_id, source_id, model="fake")
    deeper = store.load_extraction_plan(project_id, source_id)
    assert skip_snapshots[1] == set()
    assert set(plan.selected_block_ids).issubset(set(deeper.selected_block_ids))
    assert len(deeper.selected_block_ids) > len(plan.selected_block_ids)


def test_second_pass_deepens_required_section_block_once(tmp_path) -> None:
    service, project_id, source_id = _prepare_equal_blocks_source(
        tmp_path,
        duration=60,
        block_count=18,
        tokens_per_block=100,
    )
    store = service.artifact_store

    plan_snapshots: list[set[str]] = []
    original = service.evidence_extractor.extract_source

    def wrapped(**kwargs):
        plan = kwargs.get("plan")
        plan_snapshots.append(set(plan.selected_block_ids) if plan else set())
        return original(**kwargs)

    service.evidence_extractor.extract_source = wrapped  # type: ignore[method-assign]

    service.extract_evidence(project_id, source_id, model="fake")

    locators = store.load_block_locators(project_id, source_id)
    records = {
        record.block_id: record
        for record in store.load_block_extractions(
            project_id, source_id, block_locators=locators
        )
    }
    # FakeRunner's DocumentMapDraft marks the first block's section required.
    assert records["block-01"].extraction_pass == 2
    assert all(
        record.extraction_pass == 1
        for block_id, record in records.items()
        if block_id != "block-01"
    )
    # The second-pass call is identifiable as the one targeting only block-01;
    # pass-1 always selects every block at this coverage target.
    second_pass_calls = [
        snapshot for snapshot in plan_snapshots if snapshot == {"block-01"}
    ]
    assert len(second_pass_calls) == 1

    aggregate = {
        record.block_id: record
        for record in store.load_extractions(
            project_id, source_id, block_locators=locators
        )
    }
    assert aggregate["block-01"].extraction_pass == 2

    # A no-op re-run must not re-pay for the second pass.
    service.extract_evidence(project_id, source_id, model="fake")
    second_pass_calls_after_rerun = [
        snapshot for snapshot in plan_snapshots if snapshot == {"block-01"}
    ]
    assert len(second_pass_calls_after_rerun) == 1


def test_second_pass_failure_keeps_the_pass_one_record(tmp_path) -> None:
    """A pass-2 provider failure must not regress a good pass-1 extraction."""

    class _FailOnSecondCall(FakeRunner):
        def __init__(self) -> None:
            self._call_count_by_block: dict[str, int] = {}

        def run(self, *, output_type, variables, **kwargs):
            if output_type is EvidenceExtractionDraft:
                block_id = str(variables["block"]["block_id"])
                count = self._call_count_by_block.get(block_id, 0) + 1
                self._call_count_by_block[block_id] = count
                if block_id == "block-01" and count > 1:
                    raise ModelProviderError("Simulated provider failure on the second pass.")
            return super().run(output_type=output_type, variables=variables, **kwargs)

    service, project_id, source_id = _prepare_equal_blocks_source(
        tmp_path,
        duration=60,
        block_count=18,
        tokens_per_block=100,
    )
    store = service.artifact_store
    service.evidence_extractor = EvidenceExtractorService(_FailOnSecondCall())

    service.extract_evidence(project_id, source_id, model="fake")

    record = next(
        record
        for record in store.load_block_extractions(
            project_id,
            source_id,
            block_locators=store.load_block_locators(project_id, source_id),
        )
        if record.block_id == "block-01"
    )
    assert record.status == "extracted"
    assert record.extraction_pass == 1
    assert record.extraction.claims


def test_second_pass_does_not_trigger_below_extended_depth(tmp_path) -> None:
    service, project_id, source_id = _prepare_equal_blocks_source(
        tmp_path,
        duration=10,
        block_count=18,
        tokens_per_block=100,
    )
    store = service.artifact_store
    service.extract_evidence(project_id, source_id, model="fake")
    records = store.load_block_extractions(
        project_id,
        source_id,
        block_locators=store.load_block_locators(project_id, source_id),
    )
    assert records
    assert all(record.extraction_pass == 1 for record in records)


def test_build_claims_and_aggregates_omit_deferred_blocks(tmp_path) -> None:
    service, project_id, source_id = _prepare_equal_blocks_source(
        tmp_path,
        duration=60,
        block_count=18,
        tokens_per_block=100,
    )
    store = service.artifact_store
    service.extract_evidence(project_id, source_id, model="fake")
    long_plan = store.load_extraction_plan(project_id, source_id)
    long_ledger, _ = service.build_claims(
        project_id,
        source_id,
        model="fake",
        finalize_project=False,
    )
    assert long_ledger.claims
    assert len(long_plan.selected_block_ids) > 1

    project = service.workspace_store.load_project(project_id)
    assert project.brief is not None
    project.brief.target_duration_minutes = 5
    service.workspace_store.save_project(project)
    service.extract_evidence(project_id, source_id, model="fake")
    short_plan = store.load_extraction_plan(project_id, source_id)
    short_ledger, _ = service.build_claims(
        project_id,
        source_id,
        model="fake",
        finalize_project=False,
    )

    selected = set(short_plan.selected_block_ids)
    assert selected < set(long_plan.selected_block_ids)
    aggregate_ids = {item.block_id for item in store.load_evidence_items(project_id, source_id)}
    assert aggregate_ids <= selected
    evidence_by_id = {
        item.evidence_id: item for item in store.load_evidence_items(project_id, source_id)
    }
    for claim in short_ledger.claims:
        for evidence_id in claim.evidence_ids:
            assert evidence_by_id[evidence_id].block_id in selected


def test_sync_to_current_profile_noop_and_delta(tmp_path) -> None:
    service, project_id, source_id = _prepare_equal_blocks_source(
        tmp_path,
        duration=10,
        block_count=18,
        tokens_per_block=100,
    )
    store = service.artifact_store
    service.extract_evidence(project_id, source_id, model="fake")
    service.build_claims(project_id, source_id, model="fake", finalize_project=False)

    assert (
        service.sync_to_current_profile(
            project_id,
            source_id,
            fast_model="fake",
            strong_model="fake",
        )
        is False
    )

    project = service.workspace_store.load_project(project_id)
    assert project.brief is not None
    project.brief.target_duration_minutes = 60
    service.workspace_store.save_project(project)
    assert (
        service.sync_to_current_profile(
            project_id,
            source_id,
            fast_model="fake",
            strong_model="fake",
        )
        is True
    )
    plan = store.load_extraction_plan(project_id, source_id)
    assert plan.profile.depth == "extended"
    assert store.load_claim_ledger(project_id, source_id).claims


def test_planning_load_scopes_stale_ledger_claims(tmp_path) -> None:
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    source_id = uuid4()
    keep = SourceDocumentBlock(
        block_id="block-keep",
        source_id=source_id,
        locator=Locator(page_start=1, page_end=1),
        heading_path=["Keep"],
        block_type="argument",
        text="Keep this grounded claim text for the short episode.",
        estimated_token_count=40,
        source_block_keys=["k1"],
    )
    drop = SourceDocumentBlock(
        block_id="block-drop",
        source_id=source_id,
        locator=Locator(page_start=2, page_end=2),
        heading_path=["Drop"],
        block_type="argument",
        text="Drop this deferred claim text after duration shrinks.",
        estimated_token_count=40,
        source_block_keys=["d1"],
    )
    keep_ev = EvidenceItem(
        evidence_id="ev-keep",
        source_id=source_id,
        block_id=keep.block_id,
        claim="Keep claim",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt=keep.text,
        locator=keep.locator,
        support_kind="direct",
        confidence=0.9,
    )
    drop_ev = EvidenceItem(
        evidence_id="ev-drop",
        source_id=source_id,
        block_id=drop.block_id,
        claim="Drop claim",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt=drop.text,
        locator=drop.locator,
        support_kind="direct",
        confidence=0.9,
    )
    store = SourceArtifactStore(root)
    project = Project(
        raw_input="topic",
        state=ProjectState.CORPUS_READY,
        brief=ResearchBrief(
            normalized_topic="topic",
            topic_type=TopicType.CONCEPT,
            central_question="Question?",
            target_duration_minutes=5,
            learning_objectives=["learn"],
        ),
        sources=[
            SourceCandidate(
                source_id=source_id,
                title="source.txt",
                role=SourceRole.USER_CONTEXT,
                source_type="txt",
                origin="local_upload",
                access=SourceAccess.FULL_TEXT,
                user_decision=SourceDecision.INCLUDE,
            )
        ],
    )
    workspace.save_project(project)
    store.save_blocks(
        project.project_id,
        source_id,
        [keep, drop],
        BlockBuildReport(
            source_id=source_id,
            input_block_count=2,
            output_block_count=2,
        ),
    )
    store.save_evidence(
        project.project_id,
        source_id,
        [
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id=keep.block_id,
                extraction=EvidenceExtraction(segment_function="argument", claims=[keep_ev]),
            ),
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id=drop.block_id,
                extraction=EvidenceExtraction(segment_function="argument", claims=[drop_ev]),
            ),
        ],
    )
    store.save_claim_ledger(
        project.project_id,
        source_id,
        ClaimLedger(
            source_id=source_id,
            claims=[
                ClaimRecord(
                    claim_id="c-keep",
                    claim="Keep claim",
                    claim_type=ClaimType.AUTHOR_POSITION,
                    evidence_ids=["ev-keep"],
                    support_status=SupportStatus.STRONG,
                ),
                ClaimRecord(
                    claim_id="c-drop",
                    claim="Drop claim",
                    claim_type=ClaimType.AUTHOR_POSITION,
                    evidence_ids=["ev-drop"],
                    support_status=SupportStatus.STRONG,
                ),
            ],
        ),
    )
    store.save_extraction_plan(
        project.project_id,
        source_id,
        EvidenceExtractionPlan(
            source_id=source_id,
            profile=_profile(depth="brief"),
            selected_block_ids=[keep.block_id],
            deferred_block_ids=[drop.block_id],
            selected_source_tokens=40,
            total_source_tokens=80,
            achieved_token_coverage=0.5,
        ),
    )
    store.save_manifest(
        SourceAnalysisManifest(
            project_id=project.project_id,
            source_id=source_id,
            source_sha256="a" * 64,
            status="claims_ready",
            block_count=2,
            selected_block_count=1,
            deferred_block_count=1,
            evidence_count=2,
            claim_count=2,
        )
    )

    episode_store = EpisodeArtifactStore(root)
    service = EpisodePreparationService(
        workspace_store=workspace,
        source_store=store,
        episode_store=episode_store,
        coverage_auditor=CoverageAuditorService(FakeRunner()),
        claim_prioritizer=ClaimPrioritizer(),
        budget_estimator=EpisodeBudgetEstimator(),
        disagreement_builder=DisagreementGraphBuilder(),
        episode_planner=EpisodePlannerService(FakeRunner()),
        evidence_pack_builder=EvidencePackBuilder(
            SQLiteBlockRetriever(episode_store.retrieval_database_path(project.project_id))
        ),
    )
    corpus = service._load_corpus(project.project_id)
    assert [claim.claim_id for claim in corpus.claims] == ["c-keep"]
    assert [item.evidence_id for item in corpus.evidence_items] == ["ev-keep"]


def test_episode_run_syncs_claim_ready_sources(tmp_path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    source_id = uuid4()
    project = Project(
        raw_input="موضوع",
        state=ProjectState.CORPUS_READY,
        brief=_episode_brief(20),
        sources=[
            SourceCandidate(
                source_id=source_id,
                title="source.txt",
                role=SourceRole.USER_CONTEXT,
                source_type="txt",
                origin="local_upload",
                access=SourceAccess.FULL_TEXT,
                user_decision=SourceDecision.INCLUDE,
            )
        ],
    )
    workspace.save_project(project)
    store = SourceArtifactStore(workspace.root)
    block = SourceDocumentBlock(
        block_id="block-1",
        source_id=source_id,
        locator=Locator(page_start=1, page_end=1),
        heading_path=["One"],
        block_type="argument",
        text="Enough grounded text for a claim-ready source fixture.",
        estimated_token_count=30,
        source_block_keys=["s1"],
    )
    evidence = EvidenceItem(
        evidence_id="ev-1",
        source_id=source_id,
        block_id=block.block_id,
        claim="Claim",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt=block.text,
        locator=block.locator,
        support_kind="direct",
        confidence=0.9,
    )
    store.save_blocks(
        project.project_id,
        source_id,
        [block],
        BlockBuildReport(source_id=source_id, input_block_count=1, output_block_count=1),
    )
    store.save_evidence(
        project.project_id,
        source_id,
        [
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id=block.block_id,
                extraction=EvidenceExtraction(segment_function="argument", claims=[evidence]),
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
                    claim_id="c-1",
                    claim="Claim",
                    claim_type=ClaimType.AUTHOR_POSITION,
                    evidence_ids=["ev-1"],
                    support_status=SupportStatus.STRONG,
                )
            ],
        ),
    )
    store.save_extraction_plan(
        project.project_id,
        source_id,
        EvidenceExtractionPlan(
            source_id=source_id,
            profile=_profile(depth="standard"),
            selected_block_ids=[block.block_id],
            selected_source_tokens=30,
            total_source_tokens=30,
            achieved_token_coverage=1.0,
        ),
    )
    store.save_manifest(
        SourceAnalysisManifest(
            project_id=project.project_id,
            source_id=source_id,
            source_sha256="b" * 64,
            status="claims_ready",
            block_count=1,
            selected_block_count=1,
            evidence_count=1,
            claim_count=1,
        )
    )

    class RecordingAnalysis:
        def __init__(self) -> None:
            self.synced: list[tuple] = []

        def sync_to_current_profile(self, project_id, sid, *, fast_model, strong_model):
            self.synced.append((project_id, sid, fast_model, strong_model))
            return False

    fake = FakePreparationService(workspace)
    analysis = RecordingAnalysis()
    service = EpisodePlanningRunService(
        workspace_store=workspace,
        run_store=EpisodePlanningRunStore(workspace.root),
        episode_store=EpisodeArtifactStore(workspace.root),
        preparation_service_factory=lambda _: fake,  # type: ignore[return-value]
        source_analysis_service_factory=lambda: analysis,  # type: ignore[return-value]
        coverage_model="fake",
        planning_model="fake",
        fast_model="fast",
        strong_model="strong",
    )
    service.queue(project.project_id)
    run = service.run(project.project_id)

    assert run.status == "succeeded"
    assert analysis.synced == [(project.project_id, source_id, "fast", "strong")]
    assert fake.calls[0] == "coverage"


def test_sync_evidence_scope_falls_back_when_registered_sources_unusable(tmp_path) -> None:
    """Claim-ready sync must run when sources exist but none are usable as evidence."""
    workspace = WorkspaceStore(tmp_path / "workspaces")
    claim_ready_id = uuid4()
    unusable_id = uuid4()
    project = Project(
        raw_input="موضوع",
        state=ProjectState.CORPUS_READY,
        brief=_episode_brief(20),
        sources=[
            SourceCandidate(
                source_id=unusable_id,
                title="pending.txt",
                role=SourceRole.USER_CONTEXT,
                source_type="txt",
                origin="local_upload",
                access=SourceAccess.METADATA_ONLY,
                user_decision=SourceDecision.PENDING,
            )
        ],
    )
    workspace.save_project(project)
    store = SourceArtifactStore(workspace.root)
    store.save_manifest(
        SourceAnalysisManifest(
            project_id=project.project_id,
            source_id=claim_ready_id,
            source_sha256="c" * 64,
            status="claims_ready",
            block_count=1,
            selected_block_count=1,
            evidence_count=1,
            claim_count=1,
        )
    )

    class RecordingAnalysis:
        def __init__(self) -> None:
            self.synced: list[UUID] = []

        def sync_to_current_profile(self, project_id, sid, *, fast_model, strong_model):
            del project_id, fast_model, strong_model
            self.synced.append(sid)
            return False

    analysis = RecordingAnalysis()
    service = EpisodePlanningRunService(
        workspace_store=workspace,
        run_store=EpisodePlanningRunStore(workspace.root),
        episode_store=EpisodeArtifactStore(workspace.root),
        preparation_service_factory=lambda _: FakePreparationService(workspace),  # type: ignore[return-value]
        source_analysis_service_factory=lambda: analysis,  # type: ignore[return-value]
        coverage_model="fake",
        planning_model="fake",
        fast_model="fast",
        strong_model="strong",
    )
    service._sync_evidence_scope(project.project_id)

    assert analysis.synced == [claim_ready_id]
