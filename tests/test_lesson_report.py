"""`LessonReportBuilder` (`10c` P3 Step 11)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from thesisound.concepts import (
    ConceptCell,
    ConceptMapStatistics,
    LessonPart,
    SourceChapter,
    SourceConceptMap,
)
from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    Compression,
    DeliberatelyOmittedClaim,
    EpisodePlan,
    EpisodeSegment,
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
from thesisound.episode import MustNotBeLostReview, MustNotBeLostReviewItem
from thesisound.pipeline import WorkspaceStore
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.lesson_report import LessonReportBuilder
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    AnalysisProfile,
    BlockEvidenceExtraction,
    ClaimLedger,
    EvidenceExtractionPlan,
)

_FINGERPRINT = "a" * 64


def _cell(cell_key: str, block_id: str, *, tier: int = 1, minutes: float = 4.0) -> ConceptCell:
    return ConceptCell(
        cell_key=cell_key,
        label_fa=f"برچسب {cell_key}",
        kind="argument",
        tier=tier,  # type: ignore[arg-type]
        chapter_index=0,
        section_ids=["section-1"],
        block_ids=[block_id],
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=minutes,
    )


def _project(project_id: UUID, source_id: UUID) -> Project:
    project = Project(
        raw_input="کتاب",
        state=ProjectState.CORPUS_READY,
        brief=ResearchBrief(
            normalized_topic="کتاب آزمون",
            topic_type=TopicType.WORK,
            central_question="کتاب چه می‌گوید؟",
            target_duration_minutes=10,
        ),
        lesson_intent=LessonIntent.SOURCE_COVERAGE,
        compression=Compression.STANDARD,
        episode_target_minutes=10,
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
    object.__setattr__(project, "project_id", project_id)
    return project


def test_report_covers_covered_omitted_and_not_covered_cells(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    source_store = SourceArtifactStore(root)
    episode_store = EpisodeArtifactStore(root)
    source_id = uuid4()
    project = _project(uuid4(), source_id)
    project_id = project.project_id
    workspace.save_project(project)

    covered = _cell("ch00-c001", "block-1", tier=1)  # will be spoken
    tier3 = _cell("ch00-c002", "block-2", tier=3)  # omitted by compression (standard=tier 1-2)
    uncovered = _cell("ch00-c003", "block-3", tier=1)  # no claim at all

    concept_map = SourceConceptMap(
        source_fingerprint=_FINGERPRINT,
        builder_version=1,
        chapters=[
            SourceChapter(
                chapter_index=0,
                title="فصل ۰",
                heading_path=["فصل ۰"],
                block_ids=["block-1", "block-2", "block-3"],
                estimated_minutes=12.0,
                detected_from="heading",
                detection_agreement="agreed",
            )
        ],
        cells=[covered, tier3, uncovered],
        edges=[],
        statistics=ConceptMapStatistics(cell_count=3),
        created_at=datetime.now(UTC),
    )
    source_store.save_concept_map(project_id, source_id, concept_map)

    claim = ClaimRecord(
        claim_id="clm-1",
        claim="مدعای پوشش‌یافته",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=["ev-1"],
        support_status=SupportStatus.STRONG,
        must_not_be_lost=True,
    )
    evidence_item = EvidenceItem(
        evidence_id="ev-1",
        source_id=source_id,
        block_id="block-1",
        claim="مدعای پوشش‌یافته",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt="نقل قول",
        locator=Locator(page_start=1, page_end=1),
        support_kind="direct",
        confidence=0.9,
    )
    source_store.save_evidence(
        project_id,
        source_id,
        [
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id="block-1",
                extraction=EvidenceExtraction(segment_function="argument", claims=[evidence_item]),
            )
        ],
    )
    source_store.save_claim_ledger(
        project_id, source_id, ClaimLedger(source_id=source_id, claims=[claim])
    )
    source_store.save_extraction_plan(
        project_id,
        source_id,
        EvidenceExtractionPlan(
            source_id=source_id,
            profile=AnalysisProfile(
                depth="extended",
                target_duration_minutes=10,
                block_coverage_target=1.0,
                evidence_input_token_budget=20_000,
                max_claims_per_block=7,
                neighbor_context_blocks=2,
                include_examples=True,
                second_pass_for_core_sections=False,
            ),
            selected_block_ids=["block-1", "block-3"],
            selected_source_tokens=100,
            total_source_tokens=100,
            achieved_token_coverage=1.0,
            excerpt_char_coverage={"block-3": 0.1},
        ),
    )

    plan = EpisodePlan(
        title="عنوان",
        listener_outcome="فهم",
        estimated_duration_minutes=4.0,
        segments=[
            EpisodeSegment(
                segment_id="seg-001",
                title="بخش",
                purpose="شرح",
                estimated_minutes=4.0,
                claim_ids=["clm-1"],
                key_question="چرا؟",
                speaker_dynamic="explanation",
                part_index=1,
            )
        ],
        deliberately_omitted_claims=[
            DeliberatelyOmittedClaim(claim_id="clm-2", reason="فشرده‌سازی")
        ],
        parts=[
            LessonPart(
                part_index=1,
                title_fa="بخش ۱",
                cell_keys=["ch00-c001"],
                claim_ids=["clm-1"],
                estimated_minutes=4.0,
                graph_backed=False,
                flags=[],
            )
        ],
    )
    from thesisound.episode import EpisodePlanDraft, EpisodeSegmentDraft

    episode_store.save_plan(
        project_id,
        plan,
        EpisodePlanDraft(
            title=plan.title,
            listener_outcome=plan.listener_outcome,
            segments=[
                EpisodeSegmentDraft(
                    title="بخش",
                    purpose="شرح",
                    target_minutes=4.0,
                    claim_ids=["clm-1"],
                    key_question="چرا؟",
                    speaker_dynamic="explanation",
                )
            ],
        ),
    )
    project.episode_plan = plan
    episode_store.save_must_not_be_lost_review(
        MustNotBeLostReview(
            project_id=project_id,
            items=[
                MustNotBeLostReviewItem(claim_id="clm-1", claim=claim.claim, used_in_plan=True)
            ],
            unused_count=0,
        )
    )

    report = LessonReportBuilder(source_store=source_store, episode_store=episode_store).build(
        project_id, project
    )

    by_key = {item.cell_key: item for item in report.cells_covered}
    assert by_key["ch00-c001"].coverage_level == "planned"
    assert {item.cell_key for item in report.omitted_by_compression} == {"ch00-c002"}
    not_covered_by_key = {item.cell_key: item for item in report.not_covered}
    assert not_covered_by_key["ch00-c003"].reason == "thin_extraction"
    assert report.must_not_be_lost is not None
    assert report.must_not_be_lost.items[0].used_in_plan is True
    assert {item.stage for item in report.cost_by_stage} == {
        "map", "cells", "extraction", "plan", "script", "verify",
    }
    assert len(report.parts) == 1
    assert report.parts[0].estimated_minutes == 4.0


def test_focused_question_project_gets_an_empty_report(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    source_store = SourceArtifactStore(root)
    episode_store = EpisodeArtifactStore(root)
    project = Project(
        raw_input="کتاب",
        state=ProjectState.CORPUS_READY,
        brief=ResearchBrief(
            normalized_topic="موضوع",
            topic_type=TopicType.CONCEPT,
            central_question="سؤال؟",
            target_duration_minutes=10,
        ),
    )
    report = LessonReportBuilder(source_store=source_store, episode_store=episode_store).build(
        project.project_id, project
    )
    assert report.parts == []
    assert report.cells_covered == []
