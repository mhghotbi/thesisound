from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from thesisound import tracing
from thesisound.domain import (
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
    TopicType,
)
from thesisound.modeling import ModelExecution
from thesisound.pipeline import WorkspaceStore
from thesisound.services.analysis_profile import (
    build_analysis_profile,
    plan_evidence_extraction,
    selection_is_exhaustive,
    selection_target_tokens,
)
from thesisound.services.block_builder import BlockBuilder
from thesisound.services.claim_reconciler import ClaimReconcilerService
from thesisound.services.document_map_cache import (
    EXHAUSTIVE_SELECTION_SKIP_PREFIX,
    DocumentMapCache,
    is_shareable_document_map,
)
from thesisound.services.document_mapper import build_exhaustive_document_map
from thesisound.services.evidence_extractor import EvidenceExtractorService
from thesisound.services.source_analysis_service import SourceAnalysisService
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    BlockBuildReport,
    SourceAnalysisManifest,
    SourceDocumentBlock,
)


def _brief(duration: int) -> ResearchBrief:
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


def _blocks(
    *,
    count: int,
    tokens_per_block: int,
    source_id: UUID | None = None,
) -> list[SourceDocumentBlock]:
    sid = source_id or uuid4()
    return [
        SourceDocumentBlock(
            block_id=f"block-{index:02d}",
            source_id=sid,
            locator=Locator(page_start=index, page_end=index),
            heading_path=["Body"],
            block_type="other",
            text=f"Semantic content for block {index}." * 10,
            estimated_token_count=tokens_per_block,
            source_block_keys=[f"source-{index}"],
        )
        for index in range(1, count + 1)
    ]


def test_selection_is_exhaustive_true_for_small_source() -> None:
    # ~3.3k tokens under an extended profile: coverage is 1.0 and the budget
    # does not bind, so the plan takes every eligible block.
    blocks = _blocks(count=3, tokens_per_block=1_106)
    profile = build_analysis_profile(_brief(60))
    total, target = selection_target_tokens(profile, blocks)

    assert total == 3_318
    assert target == total
    assert selection_is_exhaustive(profile, blocks)


def test_selection_is_exhaustive_false_when_coverage_binds() -> None:
    # Same tiny size as the measured f6f4d511 case: brief coverage leaves a
    # partial target, so the map still has ranking work to do.
    blocks = _blocks(count=3, tokens_per_block=1_023)
    profile = build_analysis_profile(_brief(10))
    total, target = selection_target_tokens(profile, blocks)

    assert total == 3_069
    assert target < total
    assert not selection_is_exhaustive(profile, blocks)


def test_selection_is_exhaustive_scales_with_duration() -> None:
    # Extended (46+) is the first tier where coverage×headroom reaches 1.0;
    # a 30-minute deep profile still binds on coverage for the same source.
    blocks = _blocks(count=3, tokens_per_block=1_106)
    short = build_analysis_profile(_brief(10))
    medium = build_analysis_profile(_brief(30))
    long = build_analysis_profile(_brief(60))

    assert not selection_is_exhaustive(short, blocks)
    assert not selection_is_exhaustive(medium, blocks)
    assert selection_is_exhaustive(long, blocks)


class _RecordingMapper:
    """Document mapper stub that fails if the model path is reached."""

    def __init__(self) -> None:
        self.calls = 0

    def map_document(self, **_: object):
        self.calls += 1
        raise AssertionError("document map model call must be skipped when selection is exhaustive")


def _prepare_mapped_source(
    tmp_path: Path,
    *,
    duration: int,
    block_count: int,
    tokens_per_block: int,
    mapper: object | None = None,
) -> tuple[SourceAnalysisService, UUID, UUID, list[SourceDocumentBlock], _RecordingMapper | None]:
    workspace = WorkspaceStore(tmp_path / "workspaces")
    source_id = uuid4()
    blocks = _blocks(
        count=block_count,
        tokens_per_block=tokens_per_block,
        source_id=source_id,
    )
    project = Project(
        raw_input="Arendt and action",
        state=ProjectState.BRIEF_READY,
        brief=_brief(duration),
        sources=[
            SourceCandidate(
                source_id=source_id,
                title="The Human Condition",
                role=SourceRole.PRIMARY,
                source_type="book",
                origin="upload",
                access=SourceAccess.FULL_TEXT,
                user_decision=SourceDecision.INCLUDE,
            )
        ],
    )
    workspace.save_project(project)
    store = SourceArtifactStore(tmp_path / "workspaces")
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
    recording: _RecordingMapper | None
    if mapper is None:
        recording = _RecordingMapper()
        document_mapper: object = recording
    else:
        recording = None
        document_mapper = mapper
    # Evidence/claims runners are unused by map_document but required by the ctor.
    unused = _UnusedRunner()
    service = SourceAnalysisService(
        workspace_store=workspace,
        artifact_store=store,
        block_builder=BlockBuilder(),
        document_mapper=document_mapper,  # type: ignore[arg-type]
        evidence_extractor=EvidenceExtractorService(unused),
        claim_reconciler=ClaimReconcilerService(unused),
    )
    return service, project.project_id, source_id, blocks, recording


class _UnusedRunner:
    def run(self, **_: object) -> ModelExecution:
        raise AssertionError("unexpected model call")


def test_synthetic_map_skips_model_call(tmp_path: Path) -> None:
    service, project_id, source_id, _blocks, recording = _prepare_mapped_source(
        tmp_path,
        duration=60,
        block_count=3,
        tokens_per_block=1_106,
    )
    assert recording is not None

    manifest = service.map_document(project_id, source_id, model="fake")

    assert recording.calls == 0
    assert manifest.status == "document_mapped"
    assert manifest.model_run_ids == []
    document_map = service.artifact_store.load_document_map(project_id, source_id)
    assert len(document_map.sections) == 1
    assert document_map.sections[0].title == "The Human Condition"


def test_synthetic_map_yields_identical_plan() -> None:
    source_id = uuid4()
    blocks = _blocks(count=3, tokens_per_block=1_106, source_id=source_id)
    brief = _brief(60)
    multi_section = DocumentMap(
        source_id=source_id,
        scope_locator=Locator(page_start=1, page_end=3),
        working_thesis="A real map thesis.",
        sections=[
            DocumentMapSection(
                section_id=f"sec-{index:03d}",
                source_block_ids=[block.block_id],
                title=f"Section {index}",
                function="argument",
                required_for_global_understanding=index == 1,
            )
            for index, block in enumerate(blocks, start=1)
        ],
    )
    total, target = selection_target_tokens(build_analysis_profile(brief), blocks)
    synthetic = build_exhaustive_document_map(
        source_id=source_id,
        blocks=blocks,
        eligible_block_ids=[block.block_id for block in blocks],
        title="The Human Condition",
        total_tokens=total,
        target_tokens=target,
    )

    real_plan = plan_evidence_extraction(brief, multi_section, blocks)
    synthetic_plan = plan_evidence_extraction(brief, synthetic, blocks)

    assert set(real_plan.selected_block_ids) == set(synthetic_plan.selected_block_ids)
    assert set(real_plan.selected_block_ids) == {block.block_id for block in blocks}


def test_synthetic_map_not_cached(tmp_path: Path) -> None:
    service, project_id, source_id, _blocks, recording = _prepare_mapped_source(
        tmp_path,
        duration=60,
        block_count=3,
        tokens_per_block=1_106,
    )
    assert recording is not None

    service.map_document(project_id, source_id, model="fake")
    document_map = service.artifact_store.load_document_map(project_id, source_id)

    assert not is_shareable_document_map(document_map)
    cache = DocumentMapCache(tmp_path / "workspaces")
    assert list(cache.root.glob("*.json")) == []
    # Remap must not treat the synthetic artifact as reusable project cache either.
    assert not service.has_reusable_document_map(project_id, source_id)
    service.map_document(project_id, source_id, model="fake")
    assert recording.calls == 0


def test_synthetic_map_carries_skip_warning() -> None:
    source_id = uuid4()
    blocks = _blocks(count=3, tokens_per_block=1_106, source_id=source_id)
    document_map = build_exhaustive_document_map(
        source_id=source_id,
        blocks=blocks,
        eligible_block_ids=[block.block_id for block in blocks],
        title="The Human Condition",
        total_tokens=3_318,
        target_tokens=3_318,
    )

    assert len(document_map.warnings) == 1
    assert document_map.warnings[0].startswith(EXHAUSTIVE_SELECTION_SKIP_PREFIX)
    assert "3 blocks" in document_map.warnings[0]
    assert "3318 tokens ≤ target" in document_map.warnings[0]
    assert document_map.working_thesis is None
    assert document_map.cross_section_threads == []
    assert document_map.sections[0].required_for_global_understanding is True
    assert document_map.sections[0].function == "other"


def test_synthetic_map_emits_distinct_skip_reason(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    service, project_id, source_id, _blocks, _recording = _prepare_mapped_source(
        tmp_path,
        duration=60,
        block_count=3,
        tokens_per_block=1_106,
    )

    service.map_document(project_id, source_id, model="fake")

    skip_events = [
        event
        for event in recording_tracer.sink.events
        if event.name == "cache.lookup"
        and event.attributes.get("cache") == "document_map"
        and event.attributes.get("result") == "skip"
    ]
    assert len(skip_events) == 1
    assert skip_events[0].attributes.get("reason") == "selection_exhaustive"
    assert skip_events[0].attributes.get("avoided_calls") == 1
    assert recording_tracer.sink.one("corpus.map_document").attributes["source"] == (
        "exhaustive_skip"
    )
