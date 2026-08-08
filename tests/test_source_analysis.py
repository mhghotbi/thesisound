from __future__ import annotations

from pathlib import Path
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
    SupportStatus,
    TopicType,
)
from thesisound.ingestion import IngestionResult, ParserRoute
from thesisound.modeling import (
    DeterministicValidationError,
    ModelExecution,
    ModelRunRecord,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.ports import DocumentInspection, ParsedBlock, ParsedDocument
from thesisound.quality import ParseReport
from thesisound.services.analysis_profile import (
    build_analysis_profile,
    plan_evidence_extraction,
)
from thesisound.services.block_builder import BlockBuilder
from thesisound.services.claim_reconciler import ClaimReconcilerService
from thesisound.services.document_mapper import DocumentMapperService
from thesisound.services.evidence_extractor import EvidenceExtractorService
from thesisound.services.evidence_validator import validate_evidence_extraction
from thesisound.services.source_analysis_service import SourceAnalysisService
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    ClaimDraft,
    ClaimReconciliationDraft,
    CrossSectionThreadDraft,
    DocumentMapDraft,
    DocumentMapDraftSection,
    EvidenceClaimDraft,
    EvidenceExtractionDraft,
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
            output = DocumentMapDraft(
                working_thesis="The chapter distinguishes action from fabrication.",
                sections=[
                    DocumentMapDraftSection(
                        section_id="sec-001",
                        source_block_ids=[item["block_id"] for item in blocks],
                        title="Action",
                        function="argument",
                        key_concepts=["action"],
                        required_for_global_understanding=True,
                    )
                ],
                cross_section_threads=[
                    CrossSectionThreadDraft(
                        label="action",
                        section_ids=["sec-001"],
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
            validator(output)
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


def _parsed_document() -> ParsedDocument:
    return ParsedDocument(
        parser_name="fixture",
        parser_version="1",
        blocks=[
            ParsedBlock(
                source_block_key="h1",
                text="Action",
                page_start=1,
                page_end=1,
                heading_path=["Action"],
                kind="heading",
            ),
            ParsedBlock(
                source_block_key="p1",
                text=(
                    "Action occurs directly between persons. "
                    "It cannot be reduced to the fabrication of an object."
                ),
                page_start=1,
                page_end=1,
                heading_path=["Action"],
                kind="text",
            ),
            ParsedBlock(
                source_block_key="footer-1",
                text="The Human Condition",
                page_start=1,
                page_end=1,
                kind="page_footer",
            ),
        ],
    )


def _ingestion(path: Path) -> IngestionResult:
    return IngestionResult(
        inspection=DocumentInspection(
            path=path,
            mime_type="application/pdf",
            extension=".pdf",
            file_size_bytes=100,
            sha256="a" * 64,
            page_count=1,
        ),
        route=ParserRoute(primary="fixture"),
        attempts=[],
        selected_parser="fixture",
        parsed=_parsed_document(),
        quality=ParseReport(verdict="pass", safe_for_claim_extraction=True),
        safe_for_claim_extraction=True,
    )


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


def _project() -> Project:
    return Project(
        raw_input="Arendt and action",
        state=ProjectState.BRIEF_READY,
        brief=_brief(),
    )


def _planning_fixture() -> tuple[UUID, list[SourceDocumentBlock], DocumentMap]:
    source_id = uuid4()
    blocks = [
        SourceDocumentBlock(
            block_id=f"block-{index}",
            source_id=source_id,
            locator=Locator(page_start=index, page_end=index),
            heading_path=[f"Section {index}"],
            block_type="other",
            text=f"Semantic content for block {index}." * 10,
            estimated_token_count=100,
            source_block_keys=[f"source-{index}"],
        )
        for index in range(1, 11)
    ]
    sections = [
        DocumentMapSection(
            section_id=f"section-{index}",
            source_block_ids=[f"block-{index * 2 - 1}", f"block-{index * 2}"],
            title=f"Section {index}",
            function="argument" if index < 5 else "conclusion",
            key_concepts=["action" if index == 1 else f"concept-{index}"],
            required_for_global_understanding=index == 1,
        )
        for index in range(1, 6)
    ]
    document_map = DocumentMap(
        source_id=source_id,
        scope_locator=Locator(page_start=1, page_end=10),
        working_thesis="Action differs from fabrication.",
        sections=sections,
    )
    return source_id, blocks, document_map


def test_analysis_profile_scales_with_requested_duration() -> None:
    short = build_analysis_profile(_brief(5))
    long = build_analysis_profile(_brief(60))

    assert short.depth == "brief"
    assert long.depth == "extended"
    assert short.block_coverage_target < long.block_coverage_target
    assert short.max_claims_per_block < long.max_claims_per_block
    assert short.neighbor_context_blocks < long.neighbor_context_blocks
    assert short.evidence_input_token_budget < long.evidence_input_token_budget


def test_extraction_plan_spends_more_source_tokens_for_long_episode() -> None:
    _, blocks, document_map = _planning_fixture()
    short = plan_evidence_extraction(_brief(5), document_map, blocks)
    long = plan_evidence_extraction(_brief(60), document_map, blocks)

    assert len(short.selected_block_ids) < len(long.selected_block_ids)
    assert short.selected_source_tokens < long.selected_source_tokens
    assert short.deferred_block_ids
    assert not long.deferred_block_ids
    assert long.achieved_token_coverage == 1.0


def test_block_builder_removes_margin_and_preserves_traceability() -> None:
    source_id = uuid4()
    blocks, report = BlockBuilder(
        minimum_tokens=20,
        target_tokens=50,
        maximum_tokens=100,
    ).build(
        _parsed_document(),
        source_id=source_id,
    )

    assert len(blocks) == 1
    assert blocks[0].source_block_keys == ["p1"]
    assert blocks[0].heading_path == ["Action"]
    assert blocks[0].previous_block_id is None
    assert blocks[0].next_block_id is None
    assert report.removed_margin_block_keys == ["footer-1"]


def test_evidence_validator_rejects_excerpt_not_in_block() -> None:
    source_id = uuid4()
    block = BlockBuilder().build(_parsed_document(), source_id=source_id)[0][0]
    runner = FakeRunner()
    document_map, _ = DocumentMapperService(runner).map_document(
        project_id=uuid4(),
        source_id=source_id,
        blocks=[block],
        model="fake",
    )
    record = EvidenceExtractorService(runner).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=[block],
        document_map=document_map,
        model="fake",
    )[0][0]
    record.extraction.claims[0].supporting_excerpt = "This sentence is invented."

    with pytest.raises(DeterministicValidationError, match="not present"):
        validate_evidence_extraction(record.extraction, block)


def test_complete_one_source_pipeline_writes_auditable_artifacts(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    workspace.save_project(project)
    ingestion = _ingestion(Path("chapter.pdf"))
    ingestion_path = tmp_path / "ingestion.json"
    ingestion_path.write_text(ingestion.model_dump_json(indent=2), encoding="utf-8")

    runner = FakeRunner()
    service = SourceAnalysisService(
        workspace_store=workspace,
        artifact_store=SourceArtifactStore(tmp_path / "workspaces"),
        block_builder=BlockBuilder(),
        document_mapper=DocumentMapperService(runner),
        evidence_extractor=EvidenceExtractorService(runner),
        claim_reconciler=ClaimReconcilerService(runner),
    )

    ledger, manifest = service.analyze_source(
        project.project_id,
        ingestion_path,
        fast_model="fake-fast",
        strong_model="fake-strong",
    )

    source_dir = (
        tmp_path
        / "workspaces"
        / str(project.project_id)
        / "sources"
        / str(manifest.source_id)
    )
    assert manifest.status == "claims_ready"
    assert manifest.block_count == 1
    assert manifest.selected_block_count == 1
    assert manifest.deferred_block_count == 0
    assert manifest.analysis_depth == "deep"
    assert manifest.evidence_count == 1
    assert manifest.claim_count == 1
    assert len(ledger.claims) == 1
    assert workspace.load_project(project.project_id).state == ProjectState.CORPUS_READY
    assert (source_dir / "document-blocks.jsonl").exists()
    assert (source_dir / "document-map.json").exists()
    assert (source_dir / "evidence-extraction-plan.json").exists()
    assert (source_dir / "evidence-items.jsonl").exists()
    assert (source_dir / "claim-ledger.json").exists()
    assert list((source_dir / "evidence" / "extractions").glob("*.json"))
