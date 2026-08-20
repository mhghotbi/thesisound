"""Every replan must seed from cells, not just the one that writes artifacts.

``corpus_reuse`` and ``episode_duration_cost`` reconstruct an extraction plan and
compare it to the stored one. Both used to replan without concept cells, so a
``source_coverage`` project -- whose real plan is cell-seeded at forced depth --
never matched itself: a finished source was rebuilt on confirm, and the duration
dialog warned about a re-extraction the run would not have paid for.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from thesisound.concepts import (
    ConceptCell,
    ConceptMapOverlay,
    ConceptMapStatistics,
    SourceChapter,
    SourceConceptMap,
)
from thesisound.domain import (
    ClaimType,
    Compression,
    DocumentMap,
    DocumentMapSection,
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
from thesisound.services.analysis_profile import (
    plan_evidence_extraction,
    resolve_extraction_seeds,
)
from thesisound.services.concept_map_overlay import (
    ConceptMapOverlayService,
    effective_concept_map,
)
from thesisound.services.corpus_reuse import reusable_claim_ledger
from thesisound.services.episode_duration_cost import reextraction_required_for_duration
from thesisound.services.semantic_identity import claim_reconciler_identity
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    BlockBuildReport,
    ClaimLedger,
    ClaimRecord,
    SourceAnalysisManifest,
    SourceDocumentBlock,
)

_SHA256 = "c" * 64
_FINGERPRINT = "d" * 64
_SEEDED_BLOCK_IDS = ["block-1", "block-2", "block-4"]


class _StubIngestionStore(SourceArtifactStore):
    """Real artifact store; the ingestion file itself is stubbed out."""

    def load_ingestion(self, path: Path):  # type: ignore[override]
        del path
        return SimpleNamespace(inspection=SimpleNamespace(sha256=_SHA256))


def _brief(duration: int = 5) -> ResearchBrief:
    return ResearchBrief(
        normalized_topic="کنش و ساختن",
        topic_type=TopicType.CONCEPT,
        central_question="کنش از ساختن چه تفاوتی دارد؟",
        target_duration_minutes=duration,
    )


def _cell(cell_key: str, block_ids: list[str], *, tier: int = 1) -> ConceptCell:
    return ConceptCell(
        cell_key=cell_key,
        label_fa="برچسب",
        kind="argument",
        tier=tier,  # type: ignore[arg-type]
        chapter_index=0,
        section_ids=["section-1"],
        block_ids=block_ids,
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=4.0,
    )


def _concept_map(cells: list[ConceptCell]) -> SourceConceptMap:
    return SourceConceptMap(
        source_fingerprint=_FINGERPRINT,
        builder_version=1,
        chapters=[
            SourceChapter(
                chapter_index=0,
                title="فصل ۰",
                heading_path=["فصل ۰"],
                block_ids=[f"block-{index}" for index in range(1, 11)],
                estimated_minutes=10.0,
                detected_from="heading",
                detection_agreement="agreed",
            )
        ],
        cells=cells,
        edges=[],
        statistics=ConceptMapStatistics(cell_count=len(cells)),
        created_at=datetime.now(UTC),
    )


def _corpus(source_id: UUID) -> tuple[list[SourceDocumentBlock], DocumentMap]:
    blocks = [
        SourceDocumentBlock(
            block_id=f"block-{index}",
            source_id=source_id,
            locator=Locator(page_start=index, page_end=index),
            heading_path=[f"Section {index}"],
            block_type="other",
            text=f"محتوای معنایی بلوک {index}." * 10,
            estimated_token_count=100,
            source_block_keys=[f"source-{index}"],
        )
        for index in range(1, 11)
    ]
    document_map = DocumentMap(
        source_id=source_id,
        scope_locator=Locator(page_start=1, page_end=10),
        working_thesis="کنش با ساختن یکی نیست.",
        sections=[
            DocumentMapSection(
                section_id=f"section-{index}",
                source_block_ids=[f"block-{index * 2 - 1}", f"block-{index * 2}"],
                title=f"بخش {index}",
                function="argument",
            )
            for index in range(1, 6)
        ],
    )
    return blocks, document_map


def _project(
    source_id: UUID,
    *,
    intent: LessonIntent,
    compression: Compression = Compression.STANDARD,
) -> Project:
    return Project(
        raw_input="کتاب",
        state=ProjectState.CORPUS_BUILDING,
        brief=_brief(),
        lesson_intent=intent,
        compression=compression,
        scope=ProjectScope(source_id=source_id),
        sources=[
            SourceCandidate(
                source_id=source_id,
                title="وضع بشر",
                role=SourceRole.USER_CONTEXT,
                source_type="pdf",
                origin="user_upload",
                access=SourceAccess.FULL_TEXT,
                user_decision=SourceDecision.INCLUDE,
            )
        ],
    )


def _seed_finished_source(
    store: SourceArtifactStore,
    project: Project,
    source_id: UUID,
    *,
    cells: list[ConceptCell] | None = None,
) -> None:
    """Write what a finished source leaves on disk, planned the way the pipeline plans."""

    assert project.brief is not None
    blocks, document_map = _corpus(source_id)
    store.save_blocks(
        project.project_id,
        source_id,
        blocks,
        BlockBuildReport(source_id=source_id, input_block_count=10, output_block_count=10),
    )
    store.save_document_map(project.project_id, source_id, document_map)
    if cells is not None:
        store.save_concept_map(project.project_id, source_id, _concept_map(cells))
    seed_cells, force_depth = resolve_extraction_seeds(
        project, effective_concept_map(store, project.project_id, source_id)
    )
    store.save_extraction_plan(
        project.project_id,
        source_id,
        plan_evidence_extraction(
            project.brief,
            document_map,
            blocks,
            seed_cells=seed_cells,
            force_depth=force_depth,
        ),
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
            reconciler_identity=claim_reconciler_identity(
                model="fake-strong",
                prompt_version=None,
            ),
        ),
    )
    store.save_manifest(
        SourceAnalysisManifest(
            project_id=project.project_id,
            source_id=source_id,
            source_sha256=_SHA256,
            status="claims_ready",
            block_count=10,
            claim_count=1,
        )
    )


def _coverage_fixture(
    tmp_path: Path,
    *,
    cells: list[ConceptCell] | None = None,
    compression: Compression = Compression.STANDARD,
) -> tuple[SourceArtifactStore, Project, UUID]:
    store = _StubIngestionStore(tmp_path / "workspaces")
    source_id = uuid4()
    project = _project(
        source_id, intent=LessonIntent.SOURCE_COVERAGE, compression=compression
    )
    if cells is None:
        cells = [
            _cell("ch00-c001", ["block-1", "block-2"]),
            _cell("ch00-c002", ["block-4"]),
        ]
    _seed_finished_source(store, project, source_id, cells=cells)
    return store, project, source_id


def test_cell_seeding_really_changes_the_plan(tmp_path: Path) -> None:
    """Guards the tests below from passing for the wrong reason."""

    store, project, source_id = _coverage_fixture(tmp_path)
    assert project.brief is not None
    blocks, document_map = _corpus(source_id)

    stored = store.load_extraction_plan(project.project_id, source_id)
    unseeded = plan_evidence_extraction(project.brief, document_map, blocks)

    assert stored.selected_block_ids == _SEEDED_BLOCK_IDS
    assert unseeded.selected_block_ids != stored.selected_block_ids
    assert unseeded.profile != stored.profile


def test_source_coverage_ledger_is_reused_instead_of_rebuilt(tmp_path: Path) -> None:
    store, project, source_id = _coverage_fixture(tmp_path)

    ledger = reusable_claim_ledger(
        artifact_store=store,
        project=project,
        source_id=source_id,
        ingestion_path=tmp_path / "ingestion.json",
        model="fake-strong",
    )

    assert ledger is not None
    assert len(ledger.claims) == 1


def test_reuse_sees_the_owner_overlay_not_just_the_cached_map(tmp_path: Path) -> None:
    """A tier promoted only in the overlay must widen the replan the same way."""

    promoted = [
        _cell("ch00-c001", ["block-1", "block-2"], tier=1),
        _cell("ch00-c002", ["block-4"], tier=3),
    ]
    store = _StubIngestionStore(tmp_path / "workspaces")
    source_id = uuid4()
    project = _project(
        source_id,
        intent=LessonIntent.SOURCE_COVERAGE,
        compression=Compression.CONCISE,
    )
    store.save_concept_map(project.project_id, source_id, _concept_map(promoted))
    ConceptMapOverlayService(store.workspace_root).save(
        project.project_id,
        source_id,
        ConceptMapOverlay(
            source_fingerprint=_FINGERPRINT,
            version=1,
            tier_overrides={"ch00-c002": 1},
        ),
    )
    _seed_finished_source(store, project, source_id)

    stored = store.load_extraction_plan(project.project_id, source_id)
    ledger = reusable_claim_ledger(
        artifact_store=store,
        project=project,
        source_id=source_id,
        ingestion_path=tmp_path / "ingestion.json",
        model="fake-strong",
    )

    # block-4 is in scope only because the overlay promoted its tier-3 cell.
    assert stored.selected_block_ids == _SEEDED_BLOCK_IDS
    assert ledger is not None


def test_duration_change_costs_nothing_for_a_source_coverage_lesson(
    tmp_path: Path,
) -> None:
    store, project, _source_id = _coverage_fixture(tmp_path)

    assert reextraction_required_for_duration(project, store, 90) is False
    assert reextraction_required_for_duration(project, store, 5) is False


def test_duration_change_still_costs_re_extraction_for_a_focused_question(
    tmp_path: Path,
) -> None:
    store = _StubIngestionStore(tmp_path / "workspaces")
    source_id = uuid4()
    project = _project(source_id, intent=LessonIntent.FOCUSED_QUESTION)
    _seed_finished_source(store, project, source_id)

    assert reextraction_required_for_duration(project, store, 90) is True
