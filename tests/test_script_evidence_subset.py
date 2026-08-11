from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    EpisodePlan,
    EpisodeSegment,
    EvidenceExtraction,
    EvidenceItem,
    Locator,
    Project,
    ProjectState,
    ResearchBrief,
    Script,
    ScriptTurn,
    SupportStatus,
    TopicType,
)
from thesisound.episode import SegmentEvidencePack
from thesisound.script import Glossary
from thesisound.services.script_checks import ScriptChecker
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    BlockEvidenceExtraction,
    SourceAnalysisManifest,
)
from thesisound.web.script_routes import _segment_views
from thesisound.web.source_manifest import UiSourceManifest, UiSourceManifestStore, UiSourceStatus


def _plan(*claim_ids: str) -> EpisodePlan:
    return EpisodePlan(
        title="طرح",
        listener_outcome="نتیجه",
        estimated_duration_minutes=5,
        segments=[
            EpisodeSegment(
                segment_id="seg-1",
                title="بخش",
                purpose="آزمون",
                estimated_minutes=5,
                claim_ids=list(claim_ids or ("claim-1",)),
                key_question="پرسش؟",
                speaker_dynamic="explanation",
            )
        ],
    )


def _evidence(source_id, evidence_id: str = "ev-1") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source_id=source_id,
        block_id="block-1",
        claim="مدعا",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt="عبارت شاهد",
        locator=Locator(page_start=1, page_end=1),
        support_kind="direct",
        confidence=0.9,
    )


def _claim(*evidence_ids: str, claim_id: str = "claim-1") -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        claim="مدعا",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=list(evidence_ids),
        support_status=SupportStatus.STRONG,
    )


def _pack(source_id, *evidence_ids: str) -> SegmentEvidencePack:
    items = [_evidence(source_id, evidence_id) for evidence_id in evidence_ids]
    return SegmentEvidencePack.model_construct(
        segment_id="seg-1",
        claim_ids=["claim-1"],
        evidence_items=items,
        original_blocks=[],
        token_budget=100,
        actual_tokens=2,
    )


def _check(
    *,
    turns: list[ScriptTurn],
    claims: list[ClaimRecord],
    pack: SegmentEvidencePack,
) -> object:
    project_id = uuid4()
    return ScriptChecker(words_per_minute=130).check(
        project_id=project_id,
        script=Script(title="متن", turns=turns),
        episode_plan=_plan(*(claim.claim_id for claim in claims) or ("claim-1",)),
        evidence_packs=[pack],
        claims=claims,
        glossary=Glossary(project_id=project_id, model_run_id=uuid4()),
    )


def test_script_checker_flags_evidence_unlinked_to_claim() -> None:
    source_id = uuid4()
    report = _check(
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-1",
                speaker="A",
                spoken_text_fa="گفتهٔ محتوایی با شاهد اضافی است.",
                claim_ids=["claim-1"],
                evidence_ids=["ev-1", "ev-extra"],
            )
        ],
        claims=[_claim("ev-1")],
        pack=_pack(source_id, "ev-1", "ev-extra"),
    )
    issue_types = {issue.issue_type for issue in report.issues}
    assert "evidence_unlinked_to_claim" in issue_types
    unlinked = next(
        issue for issue in report.issues if issue.issue_type == "evidence_unlinked_to_claim"
    )
    assert unlinked.severity == "blocking"
    assert "ev-extra" in unlinked.explanation
    assert report.verdict == "reject"


def test_script_checker_accepts_linked_evidence() -> None:
    source_id = uuid4()
    report = _check(
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-1",
                speaker="A",
                spoken_text_fa="گفتهٔ محتوایی با شاهد درست است.",
                claim_ids=["claim-1"],
                evidence_ids=["ev-1"],
            )
        ],
        claims=[_claim("ev-1")],
        pack=_pack(source_id, "ev-1"),
    )
    issue_types = {issue.issue_type for issue in report.issues}
    assert "evidence_unlinked_to_claim" not in issue_types
    assert "missing_grounding" not in issue_types


def test_script_checker_skips_editorial_turns() -> None:
    source_id = uuid4()
    report = _check(
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-1",
                speaker="B",
                spoken_text_fa="گفتهٔ گذار بدون شاهد.",
                editorial_only=True,
            )
        ],
        claims=[_claim("ev-1")],
        pack=_pack(source_id, "ev-1"),
    )
    issue_types = {issue.issue_type for issue in report.issues}
    assert "missing_grounding" not in issue_types
    assert "evidence_unlinked_to_claim" not in issue_types


def test_script_checker_missing_grounding_when_expected_empty() -> None:
    source_id = uuid4()
    report = _check(
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-1",
                speaker="A",
                spoken_text_fa="گفتهٔ محتوایی بدون مدعای شناخته‌شده.",
                claim_ids=["claim-missing"],
                evidence_ids=["ev-1"],
            )
        ],
        claims=[_claim("ev-1")],
        pack=_pack(source_id, "ev-1"),
    )
    by_type = {issue.issue_type: issue for issue in report.issues}
    assert "unknown_claim" in by_type
    assert "missing_grounding" in by_type
    assert by_type["missing_grounding"].severity == "blocking"
    # Extra evidence relative to empty expected set also surfaces as unlinked.
    assert "evidence_unlinked_to_claim" in by_type


def test_segment_views_marks_missing_evidence_unavailable(tmp_path: Path) -> None:
    project = Project(
        raw_input="موضوع",
        state=ProjectState.SCRIPT_VERIFIED,
        brief=ResearchBrief(
            normalized_topic="موضوع",
            topic_type=TopicType.CONCEPT,
            central_question="سؤال؟",
            target_duration_minutes=5,
        ),
        episode_plan=_plan("claim-1"),
        script=Script(
            title="متن",
            turns=[
                ScriptTurn(
                    turn_id="t1",
                    segment_id="seg-1",
                    speaker="A",
                    spoken_text_fa="گفته بدون شاهد قابل بارگذاری.",
                    claim_ids=["claim-1"],
                    evidence_ids=["missing-ev"],
                )
            ],
        ),
    )
    store = SourceArtifactStore(tmp_path)
    views = _segment_views(project, project.script, store)
    refs = views[0]["turns"][0]["references"]
    assert len(refs) == 1
    assert refs[0]["status"] == "unavailable"
    assert refs[0]["evidence_id"] == "missing-ev"
    assert "در دسترس نیست" in str(refs[0]["message"])


def test_segment_views_uses_ui_manifest_title_when_project_sources_empty(
    tmp_path: Path,
) -> None:
    source_id = uuid4()
    project = Project(
        raw_input="موضوع",
        state=ProjectState.SCRIPT_VERIFIED,
        brief=ResearchBrief(
            normalized_topic="موضوع",
            topic_type=TopicType.CONCEPT,
            central_question="سؤال؟",
            target_duration_minutes=5,
        ),
        sources=[],
        episode_plan=_plan("claim-1"),
        script=Script(
            title="متن",
            turns=[
                ScriptTurn(
                    turn_id="t1",
                    segment_id="seg-1",
                    speaker="A",
                    spoken_text_fa="گفته با عنوان از مانیفست رابط.",
                    claim_ids=["claim-1"],
                    evidence_ids=["ev-1"],
                )
            ],
        ),
    )
    store = SourceArtifactStore(tmp_path)
    store.save_manifest(
        SourceAnalysisManifest(
            project_id=project.project_id,
            source_id=source_id,
            source_sha256="a" * 64,
            status="claims_ready",
            block_count=1,
            evidence_count=1,
            claim_count=1,
        )
    )
    store.save_evidence(
        project.project_id,
        source_id,
        [
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id="block-1",
                extraction=EvidenceExtraction(
                    segment_function="argument",
                    claims=[_evidence(source_id, "ev-1")],
                ),
            )
        ],
    )
    UiSourceManifestStore(tmp_path / str(project.project_id)).save(
        [
            UiSourceManifest(
                source_id=source_id,
                filename="book.pdf",
                display_title="عنوان از مانیفست",
                size_bytes=10,
                status=UiSourceStatus.READY,
            )
        ]
    )

    views = _segment_views(project, project.script, store)
    refs = views[0]["turns"][0]["references"]
    assert refs[0]["status"] == "ok"
    assert refs[0]["source_title"] == "عنوان از مانیفست"
    assert str(source_id) not in refs[0]["source_title"]


def test_segment_views_marks_deselected_source_evidence_unavailable(
    tmp_path: Path,
) -> None:
    source_id = uuid4()
    project = Project(
        raw_input="موضوع",
        state=ProjectState.SCRIPT_VERIFIED,
        brief=ResearchBrief(
            normalized_topic="موضوع",
            topic_type=TopicType.CONCEPT,
            central_question="سؤال؟",
            target_duration_minutes=5,
        ),
        sources=[],
        episode_plan=_plan("claim-1"),
        script=Script(
            title="متن",
            turns=[
                ScriptTurn(
                    turn_id="t1",
                    segment_id="seg-1",
                    speaker="A",
                    spoken_text_fa="گفته با منبع خارج‌شده.",
                    claim_ids=["claim-1"],
                    evidence_ids=["ev-gone"],
                )
            ],
        ),
    )
    store = SourceArtifactStore(tmp_path)
    views = _segment_views(project, project.script, store)
    refs = views[0]["turns"][0]["references"]
    assert refs[0]["status"] == "unavailable"
    assert refs[0]["evidence_id"] == "ev-gone"
