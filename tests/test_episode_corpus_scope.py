from pathlib import Path
from uuid import UUID, uuid4

from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    EvidenceExtraction,
    EvidenceItem,
    ExtractedDefinition,
    Locator,
    MustNotBeLostPoint,
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
from thesisound.pipeline import WorkspaceStore
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.episode_preparation_service import EpisodePreparationService
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    AnalysisProfile,
    BlockBuildReport,
    BlockEvidenceExtraction,
    ClaimLedger,
    EvidenceExtractionPlan,
    SourceAnalysisManifest,
    SourceDocumentBlock,
)


def _seed_claim_ready_source(
    root: Path,
    project_id: UUID,
    source_id: UUID,
    label: str,
) -> None:
    store = SourceArtifactStore(root)
    block = SourceDocumentBlock(
        block_id=f"block-{label}",
        source_id=source_id,
        locator=Locator(page_start=1, page_end=1),
        heading_path=[label],
        block_type="argument",
        text=f"Grounded text for {label}.",
        estimated_token_count=20,
        source_block_keys=[f"source-{label}"],
    )
    store.save_blocks(
        project_id,
        source_id,
        [block],
        BlockBuildReport(
            source_id=source_id,
            input_block_count=1,
            output_block_count=1,
        ),
    )
    evidence = EvidenceItem(
        evidence_id=f"evidence-{label}",
        source_id=source_id,
        block_id=block.block_id,
        claim=f"Claim from {label}",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt=block.text,
        locator=block.locator,
        support_kind="direct",
        confidence=0.9,
    )
    store.save_evidence(
        project_id,
        source_id,
        [
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id=block.block_id,
                extraction=EvidenceExtraction(
                    segment_function="argument",
                    claims=[evidence],
                ),
            )
        ],
    )
    store.save_claim_ledger(
        project_id,
        source_id,
        ClaimLedger(
            source_id=source_id,
            claims=[
                ClaimRecord(
                    claim_id=f"claim-{label}",
                    claim=evidence.claim,
                    claim_type=ClaimType.AUTHOR_POSITION,
                    evidence_ids=[evidence.evidence_id],
                    support_status=SupportStatus.STRONG,
                )
            ],
        ),
    )
    store.save_extraction_plan(
        project_id,
        source_id,
        EvidenceExtractionPlan(
            source_id=source_id,
            profile=AnalysisProfile(
                depth="brief",
                target_duration_minutes=5,
                block_coverage_target=1,
                evidence_input_token_budget=1_000,
                max_claims_per_block=2,
                neighbor_context_blocks=0,
                include_examples=False,
                second_pass_for_core_sections=False,
            ),
            selected_block_ids=[block.block_id],
            selected_source_tokens=20,
            total_source_tokens=20,
            achieved_token_coverage=1,
        ),
    )
    store.save_manifest(
        SourceAnalysisManifest(
            project_id=project_id,
            source_id=source_id,
            source_sha256=label * 64,
            status="claims_ready",
            block_count=1,
            selected_block_count=1,
            evidence_count=1,
            claim_count=1,
        )
    )


def test_registered_corpus_excludes_unselected_claim_ready_artifacts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    selected_id = uuid4()
    stale_id = uuid4()
    project = Project(
        raw_input="topic",
        state=ProjectState.CORPUS_READY,
        brief=ResearchBrief(
            normalized_topic="topic",
            topic_type=TopicType.CONCEPT,
            central_question="Question?",
            target_duration_minutes=10,
        ),
        sources=[
            SourceCandidate(
                source_id=selected_id,
                title="selected.txt",
                role=SourceRole.USER_CONTEXT,
                source_type="txt",
                origin="local_upload",
                access=SourceAccess.FULL_TEXT,
                user_decision=SourceDecision.INCLUDE,
            ),
            SourceCandidate(
                source_id=stale_id,
                title="stale.txt",
                role=SourceRole.USER_CONTEXT,
                source_type="txt",
                origin="local_upload",
                access=SourceAccess.FULL_TEXT,
                user_decision=SourceDecision.EXCLUDE,
            ),
        ],
    )
    workspace.save_project(project)
    _seed_claim_ready_source(root, project.project_id, selected_id, "a")
    _seed_claim_ready_source(root, project.project_id, stale_id, "b")

    service = EpisodePreparationService(
        workspace_store=workspace,
        source_store=SourceArtifactStore(root),
        episode_store=EpisodeArtifactStore(root),
        coverage_auditor=None,  # type: ignore[arg-type]
        claim_prioritizer=None,  # type: ignore[arg-type]
        budget_estimator=None,  # type: ignore[arg-type]
        disagreement_builder=None,  # type: ignore[arg-type]
        episode_planner=None,  # type: ignore[arg-type]
        evidence_pack_builder=None,  # type: ignore[arg-type]
    )

    corpus = service._load_corpus(project.project_id)

    assert corpus.source_ids == [selected_id]
    assert [claim.claim_id for claim in corpus.claims] == ["claim-a"]
    assert [item.evidence_id for item in corpus.evidence_items] == ["evidence-a"]


def _seed_source_with_auxiliary_evidence(
    root: Path,
    project_id: UUID,
    source_id: UUID,
    label: str,
) -> None:
    """Two blocks per source: one selected, one deferred, both carrying aux evidence."""

    store = SourceArtifactStore(root)
    selected_block = SourceDocumentBlock(
        block_id=f"block-{label}-selected",
        source_id=source_id,
        locator=Locator(page_start=1, page_end=1),
        heading_path=[label],
        block_type="argument",
        text=f"Selected grounded text for {label}.",
        estimated_token_count=20,
        source_block_keys=[f"source-{label}-selected"],
    )
    deferred_block = SourceDocumentBlock(
        block_id=f"block-{label}-deferred",
        source_id=source_id,
        locator=Locator(page_start=2, page_end=2),
        heading_path=[label],
        block_type="argument",
        text=f"Deferred grounded text for {label}.",
        estimated_token_count=20,
        source_block_keys=[f"source-{label}-deferred"],
    )
    store.save_blocks(
        project_id,
        source_id,
        [selected_block, deferred_block],
        BlockBuildReport(source_id=source_id, input_block_count=2, output_block_count=2),
    )

    def _evidence(block: SourceDocumentBlock) -> EvidenceItem:
        return EvidenceItem(
            evidence_id=f"evidence-{block.block_id}",
            source_id=source_id,
            block_id=block.block_id,
            claim=f"Claim from {block.block_id}",
            claim_type=ClaimType.AUTHOR_POSITION,
            supporting_excerpt=block.text,
            locator=block.locator,
            support_kind="direct",
            confidence=0.9,
        )

    def _definition(block: SourceDocumentBlock) -> ExtractedDefinition:
        return ExtractedDefinition(
            term=f"Term-{block.block_id}",
            definition=f"Definition from {block.block_id}.",
            source_id=source_id,
            block_id=block.block_id,
            locator=block.locator,
        )

    def _must_not_be_lost(block: SourceDocumentBlock) -> MustNotBeLostPoint:
        return MustNotBeLostPoint(
            text=f"Flag from {block.block_id}.",
            source_id=source_id,
            block_id=block.block_id,
            locator=block.locator,
        )

    selected_evidence = _evidence(selected_block)
    deferred_evidence = _evidence(deferred_block)
    store.save_evidence(
        project_id,
        source_id,
        [
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id=selected_block.block_id,
                extraction=EvidenceExtraction(
                    segment_function="argument",
                    claims=[selected_evidence],
                    definitions=[_definition(selected_block)],
                    must_not_be_lost=[_must_not_be_lost(selected_block)],
                ),
            ),
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id=deferred_block.block_id,
                extraction=EvidenceExtraction(
                    segment_function="argument",
                    claims=[deferred_evidence],
                    definitions=[_definition(deferred_block)],
                    must_not_be_lost=[_must_not_be_lost(deferred_block)],
                ),
            ),
        ],
    )
    store.save_claim_ledger(
        project_id,
        source_id,
        ClaimLedger(
            source_id=source_id,
            claims=[
                ClaimRecord(
                    claim_id=f"claim-{selected_block.block_id}",
                    claim=selected_evidence.claim,
                    claim_type=ClaimType.AUTHOR_POSITION,
                    evidence_ids=[selected_evidence.evidence_id],
                    support_status=SupportStatus.STRONG,
                ),
                ClaimRecord(
                    claim_id=f"claim-{deferred_block.block_id}",
                    claim=deferred_evidence.claim,
                    claim_type=ClaimType.AUTHOR_POSITION,
                    evidence_ids=[deferred_evidence.evidence_id],
                    support_status=SupportStatus.STRONG,
                ),
            ],
            # Un-scoped: the ledger holds both blocks' aux evidence; _load_corpus is
            # responsible for scoping it down to the currently selected block.
            definitions=[_definition(selected_block), _definition(deferred_block)],
            must_not_be_lost=[
                _must_not_be_lost(selected_block),
                _must_not_be_lost(deferred_block),
            ],
        ),
    )
    store.save_extraction_plan(
        project_id,
        source_id,
        EvidenceExtractionPlan(
            source_id=source_id,
            profile=AnalysisProfile(
                depth="brief",
                target_duration_minutes=5,
                block_coverage_target=0.5,
                evidence_input_token_budget=1_000,
                max_claims_per_block=2,
                neighbor_context_blocks=0,
                include_examples=False,
                second_pass_for_core_sections=False,
            ),
            selected_block_ids=[selected_block.block_id],
            deferred_block_ids=[deferred_block.block_id],
            selected_source_tokens=20,
            total_source_tokens=40,
            achieved_token_coverage=0.5,
        ),
    )
    store.save_manifest(
        SourceAnalysisManifest(
            project_id=project_id,
            source_id=source_id,
            source_sha256=(label * 64)[:64],
            status="claims_ready",
            block_count=2,
            selected_block_count=1,
            deferred_block_count=1,
            evidence_count=2,
            claim_count=2,
        )
    )


def test_load_corpus_scopes_and_aggregates_auxiliary_evidence(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    source_a, source_b = uuid4(), uuid4()
    project = Project(
        raw_input="topic",
        state=ProjectState.CORPUS_READY,
        brief=ResearchBrief(
            normalized_topic="topic",
            topic_type=TopicType.CONCEPT,
            central_question="Question?",
            target_duration_minutes=10,
        ),
        sources=[
            SourceCandidate(
                source_id=source_id,
                title=f"{label}.txt",
                role=SourceRole.USER_CONTEXT,
                source_type="txt",
                origin="local_upload",
                access=SourceAccess.FULL_TEXT,
                user_decision=SourceDecision.INCLUDE,
            )
            for source_id, label in [(source_a, "a"), (source_b, "b")]
        ],
    )
    workspace.save_project(project)
    _seed_source_with_auxiliary_evidence(root, project.project_id, source_a, "a")
    _seed_source_with_auxiliary_evidence(root, project.project_id, source_b, "b")

    service = EpisodePreparationService(
        workspace_store=workspace,
        source_store=SourceArtifactStore(root),
        episode_store=EpisodeArtifactStore(root),
        coverage_auditor=None,  # type: ignore[arg-type]
        claim_prioritizer=None,  # type: ignore[arg-type]
        budget_estimator=None,  # type: ignore[arg-type]
        disagreement_builder=None,  # type: ignore[arg-type]
        episode_planner=None,  # type: ignore[arg-type]
        evidence_pack_builder=None,  # type: ignore[arg-type]
    )

    corpus = service._load_corpus(project.project_id)

    # Only the selected block from each source contributes; the deferred block's
    # auxiliary evidence must not leak into the corpus, and both sources aggregate.
    assert {item.block_id for item in corpus.definitions} == {
        "block-a-selected",
        "block-b-selected",
    }
    assert {item.block_id for item in corpus.must_not_be_lost} == {
        "block-a-selected",
        "block-b-selected",
    }
    assert len(corpus.definitions) == 2
    assert len(corpus.must_not_be_lost) == 2
