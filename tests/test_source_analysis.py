from __future__ import annotations

import json
import math
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from thesisound import tracing
from thesisound.domain import (
    ClaimType,
    DocumentMap,
    DocumentMapSection,
    EvidenceExtraction,
    ExtractedAuxiliaryPoint,
    Locator,
    MustNotBeLostPoint,
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
    ModelProviderError,
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
from thesisound.services.document_identity import block_sequence_key
from thesisound.services.document_map_cache import (
    MAP_BUILDER_VERSION,
    CachedDocumentMap,
    CachedMapSection,
    DocumentMapCache,
)
from thesisound.services.document_mapper import DocumentMapperService, scope_locator
from thesisound.services.evidence_extractor import EvidenceExtractorService
from thesisound.services.evidence_validator import validate_evidence_extraction
from thesisound.services.source_analysis_service import (
    SourceAnalysisService,
    evidence_retention_holds,
)
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    BlockBuildReport,
    BlockEvidenceExtraction,
    ClaimDraft,
    ClaimReconciliationDraft,
    CrossSectionThreadDraft,
    DefinitionDraft,
    DistinctionDraft,
    DocumentMapDraft,
    DocumentMapDraftSection,
    EvidenceClaimDraft,
    EvidenceExtractionDraft,
    EvidenceExtractionPlan,
    SourceAnalysisManifest,
    SourceDocumentBlock,
)


class FakeRunner:
    def __init__(self, reject_block_ids: set[str] | frozenset[str] = frozenset()) -> None:
        self.reject_block_ids = set(reject_block_ids)
        self.calls: list[str] = []

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
        self.calls.append(stage)
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
            block_id = str(block["block_id"])
            if block_id in self.reject_block_ids:
                output = EvidenceExtractionDraft(
                    segment_function="argument",
                    claims=[
                        EvidenceClaimDraft(
                            claim="Invented claim.",
                            claim_type=ClaimType.AUTHOR_POSITION,
                            supporting_excerpt="This sentence is invented.",
                            support_kind="direct",
                            confidence=0.5,
                        )
                    ],
                    must_not_be_lost=[],
                )
            else:
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


class ProviderSkippingRunner(FakeRunner):
    def __init__(self, provider_error_block_ids: set[str]) -> None:
        super().__init__()
        self.provider_error_block_ids = provider_error_block_ids

    def run(self, *, output_type, variables: dict[str, object], **kwargs):
        if output_type is EvidenceExtractionDraft:
            block = variables["block"]
            assert isinstance(block, dict)
            if str(block["block_id"]) in self.provider_error_block_ids:
                raise ModelProviderError(f"provider failed for {block['block_id']}")
        return super().run(output_type=output_type, variables=variables, **kwargs)


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


def _many_required_sections_fixture(
    *,
    sections: int = 60,
    blocks_per_section: int = 4,
    tokens_per_block: int = 1_400,
    required: bool = True,
) -> tuple[UUID, list[SourceDocumentBlock], DocumentMap]:
    source_id = uuid4()
    blocks: list[SourceDocumentBlock] = []
    document_map_sections: list[DocumentMapSection] = []
    for section_index in range(sections):
        section_block_ids: list[str] = []
        for block_index in range(blocks_per_section):
            document_index = len(blocks) + 1
            block_id = f"block-{section_index:03d}-{block_index:02d}"
            section_block_ids.append(block_id)
            blocks.append(
                SourceDocumentBlock(
                    block_id=block_id,
                    source_id=source_id,
                    locator=Locator(page_start=document_index, page_end=document_index),
                    heading_path=[f"Section {section_index}"],
                    block_type="other",
                    text=f"Semantic content for section {section_index}, block {block_index}.",
                    estimated_token_count=tokens_per_block,
                    source_block_keys=[f"source-{section_index}-{block_index}"],
                )
            )
        document_map_sections.append(
            DocumentMapSection(
                section_id=f"section-{section_index:03d}",
                source_block_ids=section_block_ids,
                title=f"Unrelated section {section_index}",
                function="argument",
                key_concepts=[f"concept-{section_index}"],
                required_for_global_understanding=required,
            )
        )
    return (
        source_id,
        blocks,
        DocumentMap(
            source_id=source_id,
            scope_locator=Locator(page_start=1, page_end=len(blocks)),
            working_thesis="Action differs from fabrication.",
            sections=document_map_sections,
        ),
    )


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


def test_extraction_plan_measures_selected_vs_deferred_blocks(
    recording_tracer: tracing.Tracer,
) -> None:
    """The single most direct cost lever in the corpus stage: every block not
    selected here is a model call that never happens."""

    _, blocks, document_map = _planning_fixture()

    plan = plan_evidence_extraction(_brief(5), document_map, blocks)

    span = recording_tracer.sink.one("corpus.plan_extraction")
    assert span.metrics["selected_count"] == len(plan.selected_block_ids)
    assert span.metrics["deferred_count"] == len(plan.deferred_block_ids)
    assert span.metrics["deferred_count"] > 0
    assert 0 <= span.metrics["achieved_token_coverage"] <= 1


def test_extraction_plan_keeps_required_seeding_inside_the_budget() -> None:
    _, blocks, document_map = _many_required_sections_fixture()

    plan = plan_evidence_extraction(_brief(10), document_map, blocks)

    assert len(plan.selected_block_ids) == 13
    assert plan.selected_source_tokens == 18_200
    assert plan.seeded_block_count == 8


def test_extraction_plan_ranks_required_sections_by_relevance() -> None:
    _, blocks, document_map = _many_required_sections_fixture()
    relevant = document_map.sections[-1].model_copy(
        update={
            "title": "What distinguishes action from fabrication?",
            "function": "argument",
            "key_concepts": ["action", "fabrication"],
        }
    )
    document_map = document_map.model_copy(
        update={
            "sections": [
                *[
                    section.model_copy(update={"function": "transition"})
                    for section in document_map.sections[:-1]
                ],
                relevant,
            ]
        }
    )

    plan = plan_evidence_extraction(_brief(10), document_map, blocks)

    relevant_seed = document_map.sections[-1].source_block_ids[0]
    lower_scoring_seed = document_map.sections[8].source_block_ids[0]
    assert relevant_seed in plan.selected_block_ids
    assert lower_scoring_seed not in plan.selected_block_ids
    # The point of capping seeds below the full budget: the leftover share lets the
    # ranking deepen the best section instead of buying one lonely block per section.
    selected = set(plan.selected_block_ids)
    per_section = [
        len(selected.intersection(section.source_block_ids))
        for section in document_map.sections
    ]
    assert max(per_section) > 1


def test_extraction_plan_seeds_one_required_block_larger_than_the_allowance() -> None:
    _, blocks, document_map = _many_required_sections_fixture(
        sections=1,
        blocks_per_section=1,
        tokens_per_block=50_000,
    )

    plan = plan_evidence_extraction(_brief(10), document_map, blocks)

    assert plan.selected_block_ids == [blocks[0].block_id]
    assert plan.seeded_block_count == 1


def test_extraction_plan_selects_nothing_extra_without_required_sections() -> None:
    _, blocks, document_map = _many_required_sections_fixture(
        sections=20,
        blocks_per_section=1,
        required=False,
    )

    plan = plan_evidence_extraction(_brief(10), document_map, blocks)

    assert plan.seeded_block_count == 0
    assert plan.selected_block_ids
    assert plan.selected_block_ids == [block.block_id for block in blocks[:8]]


def test_extraction_plan_deduplicates_shared_required_seed_blocks() -> None:
    _, blocks, document_map = _many_required_sections_fixture(sections=2)
    shared_seed = document_map.sections[0].source_block_ids[0]
    document_map = document_map.model_copy(
        update={
            "sections": [
                document_map.sections[0],
                document_map.sections[1].model_copy(
                    update={
                        "source_block_ids": [
                            shared_seed,
                            *document_map.sections[1].source_block_ids,
                        ]
                    }
                ),
            ]
        }
    )

    plan = plan_evidence_extraction(_brief(10), document_map, blocks)

    assert plan.seeded_block_count == 1
    assert shared_seed in plan.selected_block_ids
    assert plan.selected_source_tokens == sum(
        block.estimated_token_count
        for block in blocks
        if block.block_id in set(plan.selected_block_ids)
    )


def test_extraction_plan_records_budget_and_seed_counters() -> None:
    _, blocks, document_map = _many_required_sections_fixture(sections=3, tokens_per_block=5_000)

    plan = plan_evidence_extraction(_brief(10), document_map, blocks)

    expected_target = min(
        plan.total_source_tokens,
        math.ceil(plan.total_source_tokens * plan.profile.block_coverage_target * 1.10),
        plan.profile.evidence_input_token_budget,
    )
    assert plan.target_source_tokens == expected_target
    assert plan.required_section_count == 3
    assert plan.seeded_block_count <= len(plan.selected_block_ids)


def test_extraction_plan_measures_budget_and_seeding(
    recording_tracer: tracing.Tracer,
) -> None:
    _, blocks, document_map = _many_required_sections_fixture()

    plan = plan_evidence_extraction(_brief(10), document_map, blocks)

    span = recording_tracer.sink.one("corpus.plan_extraction")
    assert span.metrics["selected_source_tokens"] == plan.selected_source_tokens
    assert span.metrics["target_source_tokens"] == plan.target_source_tokens
    assert span.metrics["required_section_count"] == plan.required_section_count
    assert span.metrics["seeded_block_count"] == plan.seeded_block_count


def test_extraction_plan_does_not_report_over_budget_when_seeding_is_capped(
    recording_tracer: tracing.Tracer,
) -> None:
    _, blocks, document_map = _many_required_sections_fixture()

    plan_evidence_extraction(_brief(10), document_map, blocks)

    events = [
        event for event in recording_tracer.sink.events if event.name == "corpus.plan_over_budget"
    ]
    assert events == []


def test_extraction_plan_loads_without_the_r5_counters() -> None:
    source_id = uuid4()
    profile = build_analysis_profile(_brief(10))
    payload = {
        "source_id": str(source_id),
        "profile": profile.model_dump(mode="json"),
        "selected_block_ids": ["block-1"],
        "deferred_block_ids": ["block-2"],
        "selected_source_tokens": 100,
        "total_source_tokens": 200,
        "achieved_token_coverage": 0.5,
    }

    plan = EvidenceExtractionPlan.model_validate_json(json.dumps(payload))

    assert plan.target_source_tokens == 0
    assert plan.required_section_count == 0
    assert plan.seeded_block_count == 0


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


def test_extract_source_materializes_auxiliary_evidence_with_provenance() -> None:
    source_id = uuid4()
    block = BlockBuilder().build(_parsed_document(), source_id=source_id)[0][0]

    class RichRunner:
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
                )
            else:
                assert output_type is EvidenceExtractionDraft
                target_block = variables["block"]
                assert isinstance(target_block, dict)
                excerpt = str(target_block["text"]).split(".")[0].strip()
                output = EvidenceExtractionDraft(
                    segment_function="argument",
                    claims=[
                        EvidenceClaimDraft(
                            claim="Action occurs directly between persons.",
                            claim_type=ClaimType.AUTHOR_POSITION,
                            supporting_excerpt=excerpt,
                            support_kind="direct",
                            confidence=0.9,
                        )
                    ],
                    definitions=[
                        DefinitionDraft(
                            term="Action",
                            definition="Direct disclosure between persons.",
                        )
                    ],
                    distinctions=[
                        DistinctionDraft(
                            item_a="Action",
                            item_b="Fabrication",
                            distinction="Action cannot be repeated identically.",
                        )
                    ],
                    examples=["Speech in the assembly."],
                    objections=["Some deny action is distinct from labor."],
                    responses=["The distinction rests on plurality, not effort."],
                    must_not_be_lost=["The link between action and plurality."],
                )
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

    runner = RichRunner()
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

    extraction = record.extraction
    assert extraction.definitions[0].source_id == source_id
    assert extraction.definitions[0].block_id == block.block_id
    assert extraction.definitions[0].locator == block.locator
    assert extraction.distinctions[0].source_id == source_id
    assert extraction.distinctions[0].block_id == block.block_id
    for point in (*extraction.examples, *extraction.objections, *extraction.responses):
        assert isinstance(point, ExtractedAuxiliaryPoint)
        assert point.source_id == source_id
        assert point.block_id == block.block_id
        assert point.locator == block.locator
    assert isinstance(extraction.must_not_be_lost[0], MustNotBeLostPoint)
    assert extraction.must_not_be_lost[0].text == "The link between action and plurality."
    assert extraction.must_not_be_lost[0].source_id == source_id
    assert extraction.must_not_be_lost[0].block_id == block.block_id


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
        tmp_path / "workspaces" / str(project.project_id) / "sources" / str(manifest.source_id)
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


class SalvagingFakeRunner(FakeRunner):
    """Returns one bad claim and one good claim so final-attempt salvage can keep the good one."""

    def run(self, *, project_id, stage, variables, output_type, model, validator=None, **_):
        if output_type is not EvidenceExtractionDraft:
            return super().run(
                project_id=project_id,
                stage=stage,
                variables=variables,
                output_type=output_type,
                model=model,
                validator=validator,
            )
        block = variables["block"]
        assert isinstance(block, dict)
        excerpt = str(block["text"]).split(".")[0].strip()
        output = EvidenceExtractionDraft(
            segment_function="argument",
            claims=[
                EvidenceClaimDraft(
                    claim="Invented claim with a bad excerpt.",
                    claim_type=ClaimType.AUTHOR_POSITION,
                    supporting_excerpt="This sentence is invented and not in the block.",
                    support_kind="direct",
                    confidence=0.5,
                ),
                EvidenceClaimDraft(
                    claim="Action occurs directly between persons.",
                    claim_type=ClaimType.AUTHOR_POSITION,
                    supporting_excerpt=excerpt,
                    support_kind="direct",
                    confidence=0.95,
                ),
            ],
            must_not_be_lost=["The distinction from fabrication."],
        )
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


class AlwaysBadExcerptRunner(FakeRunner):
    def run(self, *, project_id, stage, variables, output_type, model, validator=None, **_):
        if output_type is not EvidenceExtractionDraft:
            return super().run(
                project_id=project_id,
                stage=stage,
                variables=variables,
                output_type=output_type,
                model=model,
                validator=validator,
            )
        output = EvidenceExtractionDraft(
            segment_function="argument",
            claims=[
                EvidenceClaimDraft(
                    claim="Invented claim.",
                    claim_type=ClaimType.AUTHOR_POSITION,
                    supporting_excerpt="This sentence is invented and not in the block.",
                    support_kind="direct",
                    confidence=0.5,
                )
            ],
        )
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


def test_evidence_extractor_keeps_valid_claims_after_salvage(recording_tracer) -> None:
    source_id = uuid4()
    block = BlockBuilder().build(_parsed_document(), source_id=source_id)[0][0]
    mapper_runner = FakeRunner()
    document_map, _ = DocumentMapperService(mapper_runner).map_document(
        project_id=uuid4(),
        source_id=source_id,
        blocks=[block],
        model="fake",
    )
    records, _ = EvidenceExtractorService(SalvagingFakeRunner()).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=[block],
        document_map=document_map,
        model="fake",
    )
    assert len(records) == 1
    assert records[0].status == "extracted"
    assert len(records[0].extraction.claims) == 1
    assert "Action occurs" in records[0].extraction.claims[0].claim
    events = [
        event for event in recording_tracer.sink.events if event.name == "corpus.evidence_attempts"
    ]
    assert len(events) == 1
    assert events[0].attributes == {
        "attempt_count": 3,
        "excerpt_failure_count": 3,
        "salvaged": True,
        "dropped_claim_count": 1,
        "kept_claim_count": 1,
        "status": "extracted",
    }


def test_evidence_extractor_rejects_block_when_nothing_survives(recording_tracer) -> None:
    source_id = uuid4()
    block = BlockBuilder().build(_parsed_document(), source_id=source_id)[0][0]
    mapper_runner = FakeRunner()
    document_map, _ = DocumentMapperService(mapper_runner).map_document(
        project_id=uuid4(),
        source_id=source_id,
        blocks=[block],
        model="fake",
    )
    records, _ = EvidenceExtractorService(AlwaysBadExcerptRunner()).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=[block],
        document_map=document_map,
        model="fake",
    )
    assert len(records) == 1
    assert records[0].status == "rejected"
    assert records[0].extraction.claims == []
    assert records[0].rejection_reason
    events = [
        event for event in recording_tracer.sink.events if event.name == "corpus.evidence_attempts"
    ]
    assert len(events) == 1
    assert events[0].attributes["salvaged"] is True
    assert events[0].attributes["dropped_claim_count"] == 1
    assert events[0].attributes["kept_claim_count"] == 0


def test_extract_evidence_skips_extracted_and_reattempts_rejected(
    tmp_path: Path,
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    workspace.save_project(project)
    ingestion = _ingestion(Path("chapter.pdf"))
    store = SourceArtifactStore(tmp_path / "workspaces")
    runner = FakeRunner()
    service = SourceAnalysisService(
        workspace_store=workspace,
        artifact_store=store,
        block_builder=BlockBuilder(),
        document_mapper=DocumentMapperService(runner),
        evidence_extractor=EvidenceExtractorService(runner),
        claim_reconciler=ClaimReconcilerService(runner),
    )
    source_id, blocks, _ = service.build_blocks(project.project_id, ingestion)
    service.map_document(project.project_id, source_id, model="fake")
    content = next(block for block in blocks if block.block_type != "front_matter")

    store.save_block_extraction(
        project.project_id,
        source_id,
        BlockEvidenceExtraction(
            source_id=source_id,
            block_id=content.block_id,
            extraction=EvidenceExtraction(segment_function="argument", claims=[]),
            status="rejected",
            rejection_reason="supporting_excerpt must be copied from the supplied source block.",
        ),
    )

    skip_snapshots: list[set[str]] = []
    original = service.evidence_extractor.extract_source

    def wrapped(**kwargs):
        skip_snapshots.append(set(kwargs.get("skip_block_ids") or set()))
        return original(**kwargs)

    service.evidence_extractor.extract_source = wrapped  # type: ignore[method-assign]
    manifest, _warnings = service.extract_evidence(
        project.project_id,
        source_id,
        model="fake",
    )
    assert skip_snapshots[0] == set()
    assert manifest.status == "evidence_ready"
    assert manifest.evidence_count >= 1
    saved = store.load_block_extractions(project.project_id, source_id)
    assert any(item.status == "extracted" for item in saved)

    service.extract_evidence(project.project_id, source_id, model="fake")
    assert content.block_id in skip_snapshots[1]


def test_reusable_document_map_skips_remap(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    workspace.save_project(project)
    ingestion = _ingestion(Path("chapter.pdf"))
    store = SourceArtifactStore(tmp_path / "workspaces")
    runner = FakeRunner()
    service = SourceAnalysisService(
        workspace_store=workspace,
        artifact_store=store,
        block_builder=BlockBuilder(),
        document_mapper=DocumentMapperService(runner),
        evidence_extractor=EvidenceExtractorService(runner),
        claim_reconciler=ClaimReconcilerService(runner),
    )
    source_id, _, _ = service.build_blocks(project.project_id, ingestion)
    first = service.map_document(project.project_id, source_id, model="fake")
    assert service.has_reusable_document_map(project.project_id, source_id)
    second = service.map_document(project.project_id, source_id, model="fake")
    assert first.model_run_ids == second.model_run_ids


def test_reusable_document_map_emits_a_project_cache_hit_event(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    workspace.save_project(project)
    ingestion = _ingestion(Path("chapter.pdf"))
    store = SourceArtifactStore(tmp_path / "workspaces")
    runner = FakeRunner()
    service = SourceAnalysisService(
        workspace_store=workspace,
        artifact_store=store,
        block_builder=BlockBuilder(),
        document_mapper=DocumentMapperService(runner),
        evidence_extractor=EvidenceExtractorService(runner),
        claim_reconciler=ClaimReconcilerService(runner),
    )
    source_id, _, _ = service.build_blocks(project.project_id, ingestion)

    service.map_document(project.project_id, source_id, model="fake")
    service.map_document(project.project_id, source_id, model="fake")

    cache_events = [
        event
        for event in recording_tracer.sink.events
        if event.name == "cache.lookup" and event.attributes.get("cache") == "project_document_map"
    ]
    assert [event.attributes["result"] for event in cache_events] == ["miss", "hit"]


def test_document_map_is_shared_between_sources_with_the_same_text(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    first_project, second_project = _project(), _project()
    workspace.save_project(first_project)
    workspace.save_project(second_project)
    ingestion = _ingestion(Path("chapter.pdf"))
    runner = FakeRunner()
    service = SourceAnalysisService(
        workspace_store=workspace,
        artifact_store=SourceArtifactStore(root),
        block_builder=BlockBuilder(),
        document_mapper=DocumentMapperService(runner),
        evidence_extractor=EvidenceExtractorService(runner),
        claim_reconciler=ClaimReconcilerService(runner),
    )

    first_source, _, _ = service.build_blocks(first_project.project_id, ingestion)
    service.map_document(first_project.project_id, first_source, model="fake")
    mapping_calls = list(runner.calls)
    assert mapping_calls

    second_source, _, _ = service.build_blocks(second_project.project_id, ingestion)
    assert second_source != first_source
    assert service.has_reusable_document_map(second_project.project_id, second_source)
    service.map_document(second_project.project_id, second_source, model="fake")

    assert runner.calls == mapping_calls  # the second source cost no model call
    original = SourceArtifactStore(root).load_document_map(
        first_project.project_id,
        first_source,
    )
    reused = SourceArtifactStore(root).load_document_map(
        second_project.project_id,
        second_source,
    )
    assert reused.source_id == second_source
    assert reused.working_thesis == original.working_thesis
    assert [section.title for section in reused.sections] == [
        section.title for section in original.sections
    ]
    reused_blocks = [
        block_id for section in reused.sections for block_id in section.source_block_ids
    ]
    assert reused_blocks
    assert all(block_id.startswith(f"blk-{str(second_source)[:8]}") for block_id in reused_blocks)


def test_shared_document_map_reuse_emits_a_cache_hit_event(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    first_project, second_project = _project(), _project()
    workspace.save_project(first_project)
    workspace.save_project(second_project)
    ingestion = _ingestion(Path("chapter.pdf"))
    runner = FakeRunner()
    service = SourceAnalysisService(
        workspace_store=workspace,
        artifact_store=SourceArtifactStore(root),
        block_builder=BlockBuilder(),
        document_mapper=DocumentMapperService(runner),
        evidence_extractor=EvidenceExtractorService(runner),
        claim_reconciler=ClaimReconcilerService(runner),
    )
    first_source, _, _ = service.build_blocks(first_project.project_id, ingestion)
    service.map_document(first_project.project_id, first_source, model="fake")

    second_source, _, _ = service.build_blocks(second_project.project_id, ingestion)
    service.map_document(second_project.project_id, second_source, model="fake")

    shared_cache_events = [
        event
        for event in recording_tracer.sink.events
        if event.name == "cache.lookup" and event.attributes.get("cache") == "shared_document_map"
    ]
    # First source: no project-level reuse, no shared cache entry yet -> miss.
    # Second source: different project, but the same text -> shared cache hit.
    assert [event.attributes["result"] for event in shared_cache_events] == ["miss", "hit"]

    map_document_spans = recording_tracer.sink.find("corpus.map_document")
    assert [span.attributes["source"] for span in map_document_spans] == ["model", "shared_cache"]


def test_degraded_document_map_is_not_reused_or_shared(tmp_path: Path) -> None:
    class Mapper:
        def __init__(self, warnings: list[str]) -> None:
            self.warnings = warnings
            self.calls = 0

        def map_document(self, *, source_id: UUID, blocks: list[SourceDocumentBlock], **_):
            self.calls += 1
            content_blocks = [block for block in blocks if block.block_type != "front_matter"]
            return (
                DocumentMap(
                    source_id=source_id,
                    scope_locator=scope_locator(blocks),
                    working_thesis="Action differs from fabrication.",
                    sections=[
                        DocumentMapSection(
                            section_id="section-1",
                            source_block_ids=[block.block_id for block in content_blocks],
                            title="Action",
                            function="argument",
                        )
                    ],
                    warnings=self.warnings,
                ),
                SimpleNamespace(run_id=uuid4()),
            )

    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    project = _project()
    workspace.save_project(project)
    store = SourceArtifactStore(root)
    warning = "Cross-partition merge was skipped: the partition payload exceeded the merge budget."
    incomplete_mapper = Mapper([warning])
    service = SourceAnalysisService(
        workspace_store=workspace,
        artifact_store=store,
        block_builder=BlockBuilder(),
        document_mapper=incomplete_mapper,
        evidence_extractor=EvidenceExtractorService(FakeRunner()),
        claim_reconciler=ClaimReconcilerService(FakeRunner()),
    )
    source_id, blocks, _ = service.build_blocks(project.project_id, _ingestion(Path("chapter.pdf")))
    content_key = block_sequence_key(blocks)
    cache = DocumentMapCache(root)

    service.map_document(project.project_id, source_id, model="fake")

    assert incomplete_mapper.calls == 1
    assert not cache.path(content_key).exists()
    assert not service.has_reusable_document_map(project.project_id, source_id)

    # A cache entry written by the prior implementation is ignored for the same reason.
    legacy_cache_entry = CachedDocumentMap(
        content_key=content_key,
        builder_version=MAP_BUILDER_VERSION,
        content_block_count=1,
        working_thesis="Action differs from fabrication.",
        sections=[
            CachedMapSection(
                section_id="section-1",
                content_block_indexes=[0],
                title="Action",
                function="argument",
            )
        ],
        warnings=[warning],
    )
    cache.path(content_key).parent.mkdir(parents=True, exist_ok=True)
    cache.path(content_key).write_text(legacy_cache_entry.model_dump_json(), encoding="utf-8")
    assert cache.load(content_key, blocks, source_id=source_id) is None

    complete_mapper = Mapper([])
    service.document_mapper = complete_mapper
    service.map_document(project.project_id, source_id, model="fake")

    assert complete_mapper.calls == 1
    assert cache.path(content_key).exists()
    assert store.load_document_map(project.project_id, source_id).warnings == []


def test_changed_body_text_does_not_reuse_a_shared_map(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    project = _project()
    workspace.save_project(project)
    runner = FakeRunner()
    service = SourceAnalysisService(
        workspace_store=workspace,
        artifact_store=SourceArtifactStore(root),
        block_builder=BlockBuilder(),
        document_mapper=DocumentMapperService(runner),
        evidence_extractor=EvidenceExtractorService(runner),
        claim_reconciler=ClaimReconcilerService(runner),
    )
    source_id, _, _ = service.build_blocks(project.project_id, _ingestion(Path("chapter.pdf")))
    service.map_document(project.project_id, source_id, model="fake")
    mapping_calls = list(runner.calls)

    edited = _ingestion(Path("chapter.pdf"))
    edited.inspection.sha256 = "b" * 64
    assert edited.parsed is not None
    body = next(block for block in edited.parsed.blocks if block.kind == "text")
    body.text = f"{body.text} An added sentence changes the body of the chapter."
    other_source, _, _ = service.build_blocks(project.project_id, edited)
    service.map_document(project.project_id, other_source, model="fake")

    assert len(runner.calls) > len(mapping_calls)


def test_extract_evidence_fails_when_all_blocks_rejected(tmp_path: Path) -> None:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _project()
    workspace.save_project(project)
    ingestion = _ingestion(Path("chapter.pdf"))
    store = SourceArtifactStore(tmp_path / "workspaces")
    map_runner = FakeRunner()
    service = SourceAnalysisService(
        workspace_store=workspace,
        artifact_store=store,
        block_builder=BlockBuilder(),
        document_mapper=DocumentMapperService(map_runner),
        evidence_extractor=EvidenceExtractorService(AlwaysBadExcerptRunner()),
        claim_reconciler=ClaimReconcilerService(map_runner),
    )
    source_id, _, _ = service.build_blocks(project.project_id, ingestion)
    service.map_document(project.project_id, source_id, model="fake")
    with pytest.raises(ValueError, match="no claim-bearing evidence"):
        service.extract_evidence(project.project_id, source_id, model="fake")
    saved = store.load_block_extractions(project.project_id, source_id)
    assert saved
    assert all(item.status == "rejected" for item in saved)


def _prepare_equal_blocks_source(
    tmp_path: Path,
    *,
    duration: int,
    block_count: int,
    tokens_per_block: int,
    reject_block_ids: set[str] | frozenset[str] = frozenset(),
    provider_error_block_ids: set[str] | frozenset[str] = frozenset(),
    max_workers: int = 4,
) -> tuple[SourceAnalysisService, UUID, UUID, list[SourceDocumentBlock]]:
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
    map_runner = FakeRunner()
    evidence_runner = (
        ProviderSkippingRunner(set(provider_error_block_ids))
        if provider_error_block_ids
        else FakeRunner(reject_block_ids=reject_block_ids)
    )
    service = SourceAnalysisService(
        workspace_store=workspace,
        artifact_store=store,
        block_builder=BlockBuilder(),
        document_mapper=DocumentMapperService(map_runner),
        evidence_extractor=EvidenceExtractorService(evidence_runner, max_workers=max_workers),
        claim_reconciler=ClaimReconcilerService(map_runner),
    )
    service.map_document(project.project_id, source_id, model="fake")
    return service, project.project_id, source_id, blocks


def test_evidence_gate_tolerates_single_block_rejection(tmp_path: Path) -> None:
    # 18×100 tokens, 10-minute brief → ~7 selected; one rejection drops coverage
    # below the 35% profile target but keeps retention above 85%.
    service, project_id, source_id, _blocks = _prepare_equal_blocks_source(
        tmp_path,
        duration=10,
        block_count=18,
        tokens_per_block=100,
        reject_block_ids={"block-01"},
    )
    _manifest, warnings = service.extract_evidence(project_id, source_id, model="fake")
    assert any("coverage" in warning.casefold() for warning in warnings)


@pytest.mark.parametrize("max_workers", [1, 4])
def test_manifest_records_skipped_block_count_and_warning(tmp_path: Path, max_workers: int) -> None:
    service, project_id, source_id, _blocks = _prepare_equal_blocks_source(
        tmp_path,
        duration=10,
        block_count=18,
        tokens_per_block=100,
        provider_error_block_ids={"block-02"},
        max_workers=max_workers,
    )

    manifest, warnings = service.extract_evidence(project_id, source_id, model="fake")

    assert manifest.skipped_block_count == 1
    assert any("1 skipped after provider errors" in warning for warning in warnings)


@pytest.mark.parametrize("max_workers", [1, 4])
def test_low_retention_after_skips_names_rejected_and_skipped_counts(
    tmp_path: Path,
    max_workers: int,
) -> None:
    service, project_id, source_id, _blocks = _prepare_equal_blocks_source(
        tmp_path,
        duration=10,
        block_count=18,
        tokens_per_block=100,
        provider_error_block_ids={"block-02", "block-03"},
        max_workers=max_workers,
    )

    with pytest.raises(ValueError, match=r"0 rejected and 2 skipped"):
        service.extract_evidence(project_id, source_id, model="fake")


def test_evidence_gate_fails_when_most_blocks_rejected(tmp_path: Path) -> None:
    service, project_id, source_id, _blocks = _prepare_equal_blocks_source(
        tmp_path,
        duration=10,
        block_count=18,
        tokens_per_block=100,
        reject_block_ids={
            "block-01",
            "block-02",
            "block-03",
            "block-04",
        },
    )
    with pytest.raises(ValueError, match="planned source tokens"):
        service.extract_evidence(project_id, source_id, model="fake")


def test_evidence_gate_passes_when_budget_caps_planned_coverage(tmp_path: Path) -> None:
    # 20×3000 = 60k tokens; 10-minute budget is 18k → planned coverage ~30% < 35%.
    service, project_id, source_id, _blocks = _prepare_equal_blocks_source(
        tmp_path,
        duration=10,
        block_count=20,
        tokens_per_block=3_000,
    )
    manifest, warnings = service.extract_evidence(project_id, source_id, model="fake")
    assert manifest.status == "evidence_ready"
    assert any("coverage" in warning.casefold() for warning in warnings)
    assert any("analysis budget" in warning for warning in warnings)


def test_coverage_warning_omits_the_budget_cause_when_the_source_is_simply_small(
    tmp_path: Path,
) -> None:
    # 18×100 = 1.8k tokens, far under the 18k budget: coverage is short because one
    # planned block was rejected, not because the budget capped the plan.
    service, project_id, source_id, _blocks = _prepare_equal_blocks_source(
        tmp_path,
        duration=10,
        block_count=18,
        tokens_per_block=100,
        reject_block_ids={"block-01"},
    )
    _manifest, warnings = service.extract_evidence(project_id, source_id, model="fake")
    assert any("coverage" in warning.casefold() for warning in warnings)
    assert not any("analysis budget" in warning for warning in warnings)


def test_evidence_gate_forgives_one_lost_block_in_a_budget_capped_plan(tmp_path: Path) -> None:
    # 40×1400 = 56k tokens against an 18k budget selects 13 blocks / 18,200 tokens, the
    # shape R5 produces on a real book. Two rejections cost 15.4% of planned mass, which
    # the bare 85% rule would fail even though 11 of 13 blocks extracted cleanly.
    service, project_id, source_id, _blocks = _prepare_equal_blocks_source(
        tmp_path,
        duration=10,
        block_count=40,
        tokens_per_block=1_400,
        reject_block_ids={"block-01", "block-02"},
    )

    manifest, warnings = service.extract_evidence(project_id, source_id, model="fake")

    assert manifest.status == "evidence_ready"
    assert manifest.selected_block_count == 13
    assert any("Kept 85% of planned tokens" in warning for warning in warnings)


def test_evidence_gate_still_fails_a_budget_capped_plan_losing_three_blocks(
    tmp_path: Path,
) -> None:
    service, project_id, source_id, _blocks = _prepare_equal_blocks_source(
        tmp_path,
        duration=10,
        block_count=40,
        tokens_per_block=1_400,
        reject_block_ids={"block-01", "block-02", "block-03"},
    )

    with pytest.raises(ValueError, match="planned source tokens"):
        service.extract_evidence(project_id, source_id, model="fake")


def test_evidence_retention_rule_forgives_only_the_largest_single_loss() -> None:
    # 13 planned blocks of 1,400 tokens: the shape a budget-capped plan produces.
    planned = 13 * 1_400
    assert evidence_retention_holds(
        planned_tokens=planned, kept_tokens=planned, largest_lost_tokens=0
    )
    assert evidence_retention_holds(
        planned_tokens=planned, kept_tokens=planned - 2_800, largest_lost_tokens=1_400
    )
    # A third loss puts the forgiven retention under 85% as well.
    assert not evidence_retention_holds(
        planned_tokens=planned, kept_tokens=planned - 4_200, largest_lost_tokens=1_400
    )
    # One enormous block cannot buy its way past the absolute floor.
    assert not evidence_retention_holds(
        planned_tokens=planned, kept_tokens=1_400, largest_lost_tokens=planned - 1_400
    )


def test_extraction_plan_adds_headroom_above_coverage_target() -> None:
    source_id = uuid4()
    blocks = [
        SourceDocumentBlock(
            block_id=f"block-{index}",
            source_id=source_id,
            locator=Locator(page_start=index, page_end=index),
            heading_path=["Body"],
            block_type="other",
            text=f"Semantic content for block {index}." * 2,
            estimated_token_count=10,
            source_block_keys=[f"source-{index}"],
        )
        for index in range(1, 101)
    ]
    document_map = DocumentMap(
        source_id=source_id,
        scope_locator=Locator(page_start=1, page_end=100),
        working_thesis="Action differs from fabrication.",
        sections=[
            DocumentMapSection(
                section_id="sec-1",
                source_block_ids=[block.block_id for block in blocks],
                title="Body",
                function="argument",
                key_concepts=["action"],
                required_for_global_understanding=True,
            )
        ],
    )
    plan = plan_evidence_extraction(_brief(10), document_map, blocks)
    total_tokens = 1_000
    headroom_target = math.ceil(total_tokens * plan.profile.block_coverage_target * 1.10)
    assert plan.achieved_token_coverage > plan.profile.block_coverage_target
    assert plan.selected_source_tokens >= headroom_target


def test_planner_defers_endnote_blocks() -> None:
    source_id = uuid4()
    body = SourceDocumentBlock(
        block_id="block-body",
        source_id=source_id,
        locator=Locator(page_start=1, page_end=1),
        heading_path=["Chapter"],
        block_type="other",
        text="Action occurs directly between persons." * 20,
        estimated_token_count=200,
        source_block_keys=["body"],
    )
    notes = SourceDocumentBlock(
        block_id="block-notes",
        source_id=source_id,
        locator=Locator(page_start=2, page_end=2),
        heading_path=["Notes"],
        block_type="other",
        text="1. See Arendt, The Human Condition." * 20,
        estimated_token_count=200,
        source_block_keys=["notes"],
    )
    document_map = DocumentMap(
        source_id=source_id,
        scope_locator=Locator(page_start=1, page_end=2),
        working_thesis="Action differs from fabrication.",
        sections=[
            DocumentMapSection(
                section_id="sec-body",
                source_block_ids=["block-body"],
                title="Chapter",
                function="argument",
                key_concepts=["action"],
                required_for_global_understanding=True,
            ),
            DocumentMapSection(
                section_id="sec-notes",
                source_block_ids=["block-notes"],
                title="Notes",
                function="other",
                key_concepts=[],
                required_for_global_understanding=False,
            ),
        ],
    )
    plan = plan_evidence_extraction(_brief(60), document_map, [body, notes])
    assert "block-notes" in plan.deferred_block_ids
    assert "block-notes" not in plan.selected_block_ids
    assert "block-body" in plan.selected_block_ids


def test_planner_keeps_all_blocks_when_every_block_looks_like_notes() -> None:
    source_id = uuid4()
    blocks = [
        SourceDocumentBlock(
            block_id=f"block-{index}",
            source_id=source_id,
            locator=Locator(page_start=index, page_end=index),
            heading_path=["Notes"],
            block_type="other",
            text=f"{index}. Bibliographic note about action and plurality." * 10,
            estimated_token_count=100,
            source_block_keys=[f"source-{index}"],
        )
        for index in range(1, 6)
    ]
    document_map = DocumentMap(
        source_id=source_id,
        scope_locator=Locator(page_start=1, page_end=5),
        working_thesis="Notes-only source.",
        sections=[
            DocumentMapSection(
                section_id="sec-notes",
                source_block_ids=[block.block_id for block in blocks],
                title="Notes",
                function="other",
                key_concepts=["notes"],
                required_for_global_understanding=True,
            )
        ],
    )
    plan = plan_evidence_extraction(_brief(10), document_map, blocks)
    assert plan.selected_block_ids


def _multi_section_document(sections: int = 4) -> ParsedDocument:
    blocks: list[ParsedBlock] = []
    for index in range(sections):
        title = f"Section {index}"
        blocks.append(
            ParsedBlock(
                source_block_key=f"h-{index}",
                text=title,
                page_start=index + 1,
                page_end=index + 1,
                heading_path=[title],
                kind="heading",
            )
        )
        blocks.append(
            ParsedBlock(
                source_block_key=f"p-{index}",
                text=(
                    f"Section {index} argues that action occurs directly between persons. "
                    f"It cannot be reduced to the fabrication of an object in case {index}."
                ),
                page_start=index + 1,
                page_end=index + 1,
                heading_path=[title],
                kind="text",
            )
        )
    return ParsedDocument(parser_name="fixture", parser_version="1", blocks=blocks)


class _BarrierRunner(FakeRunner):
    """Make every evidence call meet at a barrier, so overlap is proven, not timed.

    If extraction were sequential the first call would wait alone and the barrier would
    break, which is a deterministic failure rather than a flaky timing assertion.
    """

    def __init__(self, parties: int) -> None:
        super().__init__()
        self.barrier = Barrier(parties, timeout=10)

    def run(self, *, output_type, **kwargs):
        if output_type is EvidenceExtractionDraft:
            self.barrier.wait()
        return super().run(output_type=output_type, **kwargs)


def _map_for(blocks: list[SourceDocumentBlock], source_id: UUID) -> DocumentMap:
    document_map, _ = DocumentMapperService(FakeRunner()).map_document(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        model="fake",
    )
    return document_map


def test_evidence_extraction_runs_blocks_concurrently() -> None:
    source_id = uuid4()
    blocks, _ = BlockBuilder().build(_multi_section_document(), source_id=source_id)
    assert len(blocks) == 4
    document_map = _map_for(blocks, source_id)
    runner = _BarrierRunner(parties=len(blocks))

    records, _ = EvidenceExtractorService(runner, max_workers=4).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
    )

    # Order follows the document, not whichever call happened to finish first.
    assert [record.block_id for record in records] == [block.block_id for block in blocks]


def test_concurrent_extraction_spans_nest_under_the_submitting_thread(
    recording_tracer: tracing.Tracer,
) -> None:
    """Regression test for the ThreadPoolExecutor context-propagation trap:
    without tracing.bind_context() at the pool.submit() call site, every
    per-block span opened inside a worker thread is silently orphaned at
    the trace root instead of nesting under the caller's span."""

    recording_tracer.detail = "verbose"  # corpus.extract_evidence is per-block, verbose-gated
    source_id = uuid4()
    blocks, _ = BlockBuilder().build(_multi_section_document(), source_id=source_id)
    assert len(blocks) == 4
    document_map = _map_for(blocks, source_id)
    runner = _BarrierRunner(parties=len(blocks))

    with tracing.span("corpus.source", kind="stage", subject_id=str(source_id)):
        EvidenceExtractorService(runner, max_workers=4).extract_source(
            project_id=uuid4(),
            source_id=source_id,
            blocks=blocks,
            document_map=document_map,
            model="fake",
        )

    parent_span = recording_tracer.sink.one("corpus.source")
    children = recording_tracer.sink.find("corpus.extract_evidence")
    assert len(children) == 4
    assert all(child.parent_span_id == parent_span.context.span_id for child in children)
    assert all(child.context.trace_id == parent_span.context.trace_id for child in children)
    assert {child.subject_id for child in children} == {block.block_id for block in blocks}


def test_concurrent_extraction_saves_every_block_exactly_once() -> None:
    source_id = uuid4()
    blocks, _ = BlockBuilder().build(_multi_section_document(), source_id=source_id)
    document_map = _map_for(blocks, source_id)
    runner = _BarrierRunner(parties=len(blocks))
    saved: list[str] = []
    guard = Lock()

    def collect(record: BlockEvidenceExtraction) -> None:
        with guard:
            saved.append(record.block_id)

    EvidenceExtractorService(runner, max_workers=4).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
        on_extraction=collect,
    )

    assert sorted(saved) == sorted(block.block_id for block in blocks)


def test_concurrent_extraction_propagates_a_model_failure() -> None:
    class ExplodingRunner(FakeRunner):
        def run(self, *, output_type, **kwargs):
            if output_type is EvidenceExtractionDraft:
                raise RuntimeError("model exploded")
            return super().run(output_type=output_type, **kwargs)

    source_id = uuid4()
    blocks, _ = BlockBuilder().build(_multi_section_document(), source_id=source_id)
    document_map = _map_for(blocks, source_id)

    with pytest.raises(RuntimeError, match="model exploded"):
        EvidenceExtractorService(ExplodingRunner(), max_workers=4).extract_source(
            project_id=uuid4(),
            source_id=source_id,
            blocks=blocks,
            document_map=document_map,
            model="fake",
        )
