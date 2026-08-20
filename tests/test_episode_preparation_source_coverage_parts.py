"""Per-part planning loop for `source_coverage` (`10c` P3 Step 8).

Exercises `EpisodePreparationService.plan_episode` end to end (through the
public API, the way `EpisodePlanningRunService` calls it) with a fake model
runner that returns segments copied verbatim from whatever skeleton it is
given -- the point is to prove the *orchestration* (part boundaries,
must-include linkage, `known_concepts` accumulation, part_index stamping,
re-pack on window overflow), not to re-test the model contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from thesisound.concepts import ConceptCell, ConceptMapStatistics, SourceChapter, SourceConceptMap
from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    Compression,
    DocumentMap,
    DocumentMapSection,
    EvidenceExtraction,
    EvidenceItem,
    LessonIntent,
    Locator,
    Project,
    ProjectScope,
    ProjectState,
    ResearchBrief,
    SourceAccess,
    SourceCandidate,
    SourceDecision,
    SourceRole,
    SupportStatus,
    TopicType,
)
from thesisound.episode import (
    CoverageAuditDraft,
    EpisodePlanDraft,
    EpisodeSegmentDraft,
    ObjectiveCoverageDraft,
)
from thesisound.modeling import ModelExecution, ModelRunRecord
from thesisound.pipeline import WorkspaceStore
from thesisound.services.analysis_profile import plan_evidence_extraction, resolve_extraction_seeds
from thesisound.services.claim_prioritizer import ClaimPrioritizer
from thesisound.services.concept_map_overlay import effective_concept_map
from thesisound.services.coverage_auditor import CoverageAuditorService
from thesisound.services.disagreement_graph import DisagreementGraphBuilder
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.episode_budget import EpisodeBudgetEstimator
from thesisound.services.episode_planner import EpisodePlannerService
from thesisound.services.episode_preparation_service import EpisodePreparationService
from thesisound.services.evidence_pack_builder import EvidencePackBuilder
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    BlockBuildReport,
    BlockEvidenceExtraction,
    ClaimLedger,
    SourceAnalysisManifest,
    SourceDocumentBlock,
)

_SHA256 = "e" * 64
_FINGERPRINT = "f" * 64


class SkeletonEchoingRunner:
    """A fake `ModelRunner`: coverage always continues; plans copy the skeleton."""

    def __init__(self) -> None:
        self.plan_calls: list[dict[str, object]] = []

    def run(
        self, *, project_id: UUID, stage: str, variables: dict, output_type, model: str,
        validator=None, **_,
    ):
        if output_type is CoverageAuditDraft:
            brief = variables["research_brief"]
            claims = variables["claims"]
            claim_ids = [item["claim_id"] for item in claims]
            output = CoverageAuditDraft(
                central_question_status="well_covered",
                central_question_claim_ids=claim_ids[:1],
                objective_coverage=[
                    ObjectiveCoverageDraft(
                        objective=objective,
                        status="well_covered",
                        claim_ids=claim_ids[:1],
                        rationale="A grounded claim directly supports this objective.",
                    )
                    for objective in brief["learning_objectives"]
                ],
                max_supported_minutes=brief["target_duration_minutes"],
                recommendation="continue",
                recommendation_reason="The corpus supports the requested scope.",
            )
        elif output_type is EpisodePlanDraft:
            self.plan_calls.append(dict(variables))
            skeleton = variables["segment_skeleton"]
            assert skeleton, "source_coverage part calls must always carry a skeleton"
            segments = [
                EpisodeSegmentDraft(
                    title=f"Segment {index}",
                    purpose="Explain the cell's content.",
                    target_minutes=item["estimated_minutes"],
                    claim_ids=item["claim_ids"],
                    prerequisite_claim_ids=item.get("prerequisite_claim_ids", []),
                    key_question="What does this establish?",
                    speaker_dynamic=item["speaker_dynamic"],
                )
                for index, item in enumerate(skeleton, start=1)
            ]
            output = EpisodePlanDraft(
                title="Part title",
                listener_outcome=f"Outcome for part {variables['part']['part_index']}.",
                segments=segments,
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


class _StubIngestionStore(SourceArtifactStore):
    def load_ingestion(self, path: Path):  # type: ignore[override]
        del path
        return SimpleNamespace(inspection=SimpleNamespace(sha256=_SHA256))


def _brief() -> ResearchBrief:
    return ResearchBrief(
        normalized_topic="کتاب آزمون",
        topic_type=TopicType.WORK,
        central_question="کتاب چه می‌گوید؟",
        learning_objectives=["فهم فصل صفر"],
        target_duration_minutes=10,
    )


def _cell(cell_key: str, block_id: str, *, minutes: float) -> ConceptCell:
    return ConceptCell(
        cell_key=cell_key,
        label_fa=f"مفهوم {cell_key}",
        kind="argument",
        tier=1,
        chapter_index=0,
        section_ids=["section-1"],
        block_ids=[block_id],
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=minutes,
    )


def _service(root: Path, runner: SkeletonEchoingRunner) -> EpisodePreparationService:
    return EpisodePreparationService(
        workspace_store=WorkspaceStore(root),
        source_store=_StubIngestionStore(root),
        episode_store=EpisodeArtifactStore(root),
        coverage_auditor=CoverageAuditorService(runner),
        claim_prioritizer=ClaimPrioritizer(),
        budget_estimator=EpisodeBudgetEstimator(),
        disagreement_builder=DisagreementGraphBuilder(),
        episode_planner=EpisodePlannerService(runner),
        evidence_pack_builder=EvidencePackBuilder(),
    )


def _seed(
    root: Path,
    project: Project,
    source_id: UUID,
    *,
    cells: list[ConceptCell],
) -> None:
    store = _StubIngestionStore(root)
    blocks = [
        SourceDocumentBlock(
            block_id=cell.block_ids[0],
            source_id=source_id,
            locator=Locator(page_start=index, page_end=index),
            heading_path=["فصل ۰"],
            block_type="argument",
            text=f"متن معنایی بلوک {index}." * 5,
            estimated_token_count=80,
            source_block_keys=[f"p{index}"],
        )
        for index, cell in enumerate(cells, start=1)
    ]
    store.save_blocks(
        project.project_id,
        source_id,
        blocks,
        BlockBuildReport(
            source_id=source_id,
            input_block_count=len(blocks),
            output_block_count=len(blocks),
        ),
    )
    document_map = DocumentMap(
        source_id=source_id,
        scope_locator=Locator(page_start=1, page_end=len(blocks)),
        working_thesis="یک بحث واحد.",
        sections=[
            DocumentMapSection(
                section_id="section-1",
                source_block_ids=[block.block_id for block in blocks],
                title="بخش ۱",
                function="argument",
            )
        ],
    )
    store.save_document_map(project.project_id, source_id, document_map)
    concept_map = SourceConceptMap(
        source_fingerprint=_FINGERPRINT,
        builder_version=1,
        chapters=[
            SourceChapter(
                chapter_index=0,
                title="فصل ۰",
                heading_path=["فصل ۰"],
                block_ids=[block.block_id for block in blocks],
                estimated_minutes=sum(cell.estimated_minutes for cell in cells),
                detected_from="heading",
                detection_agreement="agreed",
            )
        ],
        cells=cells,
        edges=[],
        statistics=ConceptMapStatistics(cell_count=len(cells)),
        created_at=datetime.now(UTC),
    )
    store.save_concept_map(project.project_id, source_id, concept_map)

    claims = []
    extraction_records = []
    for index, cell in enumerate(cells, start=1):
        claim_id = f"clm-{index}"
        evidence_id = f"ev-{index}"
        claims.append(
            ClaimRecord(
                claim_id=claim_id,
                claim=f"مدعای {index}",
                claim_type=ClaimType.AUTHOR_POSITION,
                evidence_ids=[evidence_id],
                support_status=SupportStatus.STRONG,
            )
        )
        evidence_item = EvidenceItem(
            evidence_id=evidence_id,
            source_id=source_id,
            block_id=cell.block_ids[0],
            claim=f"مدعای {index}",
            claim_type=ClaimType.AUTHOR_POSITION,
            supporting_excerpt="نقل قول",
            locator=Locator(page_start=index, page_end=index),
            support_kind="direct",
            confidence=0.9,
        )
        extraction_records.append(
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id=cell.block_ids[0],
                extraction=EvidenceExtraction(segment_function="argument", claims=[evidence_item]),
            )
        )
    store.save_evidence(project.project_id, source_id, extraction_records)
    store.save_claim_ledger(
        project.project_id,
        source_id,
        ClaimLedger(source_id=source_id, claims=claims),
    )
    seed_cells, force_depth = resolve_extraction_seeds(
        project, effective_concept_map(store, project.project_id, source_id)
    )
    assert project.brief is not None
    store.save_extraction_plan(
        project.project_id,
        source_id,
        plan_evidence_extraction(
            project.brief,
            document_map,
            blocks,
            seed_cells=seed_cells,
            force_depth=force_depth,
            project=project,
        ),
    )
    store.save_manifest(
        SourceAnalysisManifest(
            project_id=project.project_id,
            source_id=source_id,
            source_sha256=_SHA256,
            status="claims_ready",
            block_count=len(blocks),
            claim_count=len(claims),
        )
    )


def _project(source_id: UUID, *, episode_target_minutes: int) -> Project:
    return Project(
        raw_input="کتاب",
        state=ProjectState.CORPUS_READY,
        brief=_brief(),
        lesson_intent=LessonIntent.SOURCE_COVERAGE,
        compression=Compression.STANDARD,
        episode_target_minutes=episode_target_minutes,
        scope=ProjectScope(source_id=source_id),
        sources=[
            SourceCandidate(
                source_id=source_id,
                title="منبع آزمون",
                role=SourceRole.USER_CONTEXT,
                source_type="pdf",
                origin="user_upload",
                access=SourceAccess.FULL_TEXT,
                user_decision=SourceDecision.INCLUDE,
            )
        ],
    )


def _prepare(
    root: Path, project: Project, runner: SkeletonEchoingRunner
) -> EpisodePreparationService:
    workspace = WorkspaceStore(root)
    workspace.save_project(project)
    service = _service(root, runner)
    service.audit_coverage(project.project_id, model="fake-strong")
    service.prioritize_claims(project.project_id)
    service.estimate_budget(project.project_id)
    service.build_disagreement_graph(project.project_id)
    return service


def test_multi_part_loop_stamps_part_index_and_accumulates_known_concepts(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    source_id = uuid4()
    # Six cells at 3 minutes each; target 5 -> FILL window [4, 5] packs one part
    # at a time (one cell fits, a second cell of 3 would overflow 5, so each
    # part holds exactly one cell -- six parts total, well under FILL_MIN
    # individually and each flagged short except by construction here every
    # part is "the last" of its own pack call... instead use a target that
    # cleanly packs two cells per part).
    cells = [_cell(f"ch00-c{i:03d}", f"block-{i}", minutes=2.0) for i in range(1, 5)]
    project = _project(source_id, episode_target_minutes=5)
    _seed(root, project, source_id, cells=cells)
    runner = SkeletonEchoingRunner()
    service = _prepare(root, project, runner)

    plan = service.plan_episode(project.project_id, model="fake-strong")

    assert len(plan.parts) >= 1
    part_indexes = [part.part_index for part in plan.parts]
    assert part_indexes == list(range(1, len(plan.parts) + 1))
    segment_part_indexes = [segment.part_index for segment in plan.segments]
    assert segment_part_indexes == sorted(segment_part_indexes)
    assert {seg.part_index for seg in plan.segments} == set(part_indexes)

    all_claim_ids = {claim_id for part in plan.parts for claim_id in part.claim_ids}
    assert all_claim_ids == {"clm-1", "clm-2", "clm-3", "clm-4"}

    segment_ids = [segment.segment_id for segment in plan.segments]
    assert len(segment_ids) == len(set(segment_ids)), "segment_id must be unique across parts"

    if len(plan.parts) > 1:
        second_call_known = runner.plan_calls[1]["known_concepts"]
        first_part_keys = set(plan.parts[0].cell_keys)
        first_part_labels = {cell.label_fa for cell in cells if cell.cell_key in first_part_keys}
        assert first_part_labels <= set(second_call_known)


def test_part_over_the_1_25x_ceiling_is_repacked_into_two(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    source_id = uuid4()
    # Three 1.6-minute cells at target 5: they pack into ONE part (4.8 <= 5.0
    # FILL_MAX, and >= 4.0 FILL_MIN so the boundary check never fires with no
    # boundary to cross); the skeleton then adds a 1.5-minute recap (3
    # real segments), pushing the total to 6.3 > 5 * 1.25 = 6.25 -- forcing a
    # re-pack at half budget (2.5), which the packer's own FILL_MIN fallback
    # (force-fill the smallest ready cell even past FILL_MAX) may still not
    # settle in one split; every cell still ends up covered exactly once, in
    # book order, with a plan that actually validated (no oversized part was
    # silently sent to the model as-is with an unreachable target).
    cells = [_cell(f"ch00-c{i:03d}", f"block-{i}", minutes=1.6) for i in range(1, 4)]
    project = _project(source_id, episode_target_minutes=5)
    _seed(root, project, source_id, cells=cells)
    runner = SkeletonEchoingRunner()
    service = _prepare(root, project, runner)

    plan = service.plan_episode(project.project_id, model="fake-strong")

    assert len(plan.parts) > 1, "the oversized single part must be split"
    all_cell_keys = [key for part in plan.parts for key in part.cell_keys]
    assert sorted(all_cell_keys) == [cell.cell_key for cell in cells]
    assert [part.part_index for part in plan.parts] == list(range(1, len(plan.parts) + 1))
    all_claim_ids = {claim_id for part in plan.parts for claim_id in part.claim_ids}
    assert all_claim_ids == {"clm-1", "clm-2", "clm-3"}


def test_part_within_the_ceiling_is_not_repacked(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    source_id = uuid4()
    # Two cells only: no recap (needs >= 3 real segments), so no overflow risk.
    cells = [_cell(f"ch00-c{i:03d}", f"block-{i}", minutes=2.0) for i in range(1, 3)]
    project = _project(source_id, episode_target_minutes=5)
    _seed(root, project, source_id, cells=cells)
    runner = SkeletonEchoingRunner()
    service = _prepare(root, project, runner)

    plan = service.plan_episode(project.project_id, model="fake-strong")

    assert len(plan.parts) == 1
    assert sorted(plan.parts[0].cell_keys) == [cell.cell_key for cell in cells]
