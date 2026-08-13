from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import uuid4

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    DeliberatelyOmittedClaim,
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
    ClaimLedger,
    SourceAnalysisManifest,
)
from thesisound.web.evidence_views import (
    claim_groups_for_ids,
    grounding_cue,
    locator_label,
    omitted_claim_views,
    segment_views,
)
from thesisound.web.source_manifest import UiSourceManifest, UiSourceManifestStore, UiSourceStatus

TEMPLATES_ROOT = Path(__file__).parents[1] / "src" / "thesisound" / "web" / "templates"


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


def _evidence(
    source_id,
    evidence_id: str = "ev-1",
    *,
    support_kind: Literal["direct", "inferential"] = "direct",
    excerpt: str = "عبارت شاهد",
    locator: Locator | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source_id=source_id,
        block_id="block-1",
        claim="مدعا",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt=excerpt,
        locator=locator or Locator(page_start=1, page_end=1),
        support_kind=support_kind,
        confidence=0.9,
    )


def _claim(*evidence_ids: str, claim_id: str = "claim-1", text: str = "مدعا") -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        claim=text,
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


def _project_with_turn(
    *,
    claim_ids: list[str],
    evidence_ids: list[str],
    sources: list | None = None,
) -> Project:
    return Project(
        raw_input="موضوع",
        state=ProjectState.SCRIPT_VERIFIED,
        brief=ResearchBrief(
            normalized_topic="موضوع",
            topic_type=TopicType.CONCEPT,
            central_question="سؤال؟",
            target_duration_minutes=5,
        ),
        sources=list(sources or []),
        episode_plan=_plan(*claim_ids),
        script=Script(
            title="متن",
            turns=[
                ScriptTurn(
                    turn_id="t1",
                    segment_id="seg-1",
                    speaker="A",
                    spoken_text_fa="گفتهٔ محتوایی برای آزمون.",
                    claim_ids=claim_ids,
                    evidence_ids=evidence_ids,
                )
            ],
        ),
    )


def _save_source_artifacts(
    store: SourceArtifactStore,
    project_id,
    source_id,
    *,
    evidence_items: list[EvidenceItem],
    claims: list[ClaimRecord],
) -> None:
    store.save_manifest(
        SourceAnalysisManifest(
            project_id=project_id,
            source_id=source_id,
            source_sha256="a" * 64,
            status="claims_ready",
            block_count=1,
            evidence_count=len(evidence_items),
            claim_count=len(claims),
        )
    )
    store.save_evidence(
        project_id,
        source_id,
        [
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id="block-1",
                extraction=EvidenceExtraction(
                    segment_function="argument",
                    claims=evidence_items,
                ),
            )
        ],
    )
    store.save_claim_ledger(
        project_id,
        source_id,
        ClaimLedger(source_id=source_id, claims=claims),
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
    # Grounding is enforced by remediate_script_grounding before this runs; the
    # check stays as a tripwire that reports without stopping the build.
    assert unlinked.severity == "low"
    assert "ev-extra" in unlinked.explanation
    assert report.verdict != "reject"


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
    assert by_type["missing_grounding"].severity == "low"
    assert "evidence_unlinked_to_claim" in by_type
    # None of the three grounding tripwires may stop a build on its own. This
    # fixture also trips `claim_outside_segment`, which is a plan-conformance
    # check and still blocking, so assert on the trio rather than the verdict.
    grounding = {"unknown_claim", "missing_grounding", "evidence_unlinked_to_claim"}
    assert not [
        issue
        for issue in report.issues
        if issue.issue_type in grounding and issue.severity == "blocking"
    ]


def test_locator_label_no_page_copy() -> None:
    label = locator_label(Locator(chapter="۳", section="الف"))
    assert not label.startswith("صفحه")
    assert "فصل ۳" in label
    assert "این منبع شماره‌گذاری صفحه ندارد" in label
    assert "نشانی در منبع مشخص نیست" not in label


def test_locator_label_with_page_keeps_chapter() -> None:
    label = locator_label(Locator(page_start=12, page_end=12, chapter="۲"))
    assert "صفحه 12" in label
    assert "فصل ۲" in label
    assert "شماره‌گذاری صفحه ندارد" not in label


def test_claim_groups_two_claims_intersect_evidence() -> None:
    source_id = uuid4()
    claims = {
        "c1": _claim("ev-1", claim_id="c1", text="مدعای یک"),
        "c2": _claim("ev-2", claim_id="c2", text="مدعای دو"),
    }
    evidence_by_id = {
        "ev-1": {
            "evidence_id": "ev-1",
            "status": "ok",
            "availability": "ok",
            "source_title": "کتاب",
            "locator": "صفحه 1",
            "locator_label": "صفحه 1",
            "excerpt": "عبارت یک",
            "support_kind": "direct",
            "support_kind_label": "شاهد صریح",
        },
        "ev-2": {
            "evidence_id": "ev-2",
            "status": "ok",
            "availability": "ok",
            "source_title": "کتاب",
            "locator": "صفحه 2",
            "locator_label": "صفحه 2",
            "excerpt": "عبارت دو",
            "support_kind": "inferential",
            "support_kind_label": "شاهد استنباطی",
        },
        "ev-extra": {
            "evidence_id": "ev-extra",
            "status": "ok",
            "availability": "ok",
            "source_title": "کتاب",
            "locator": "صفحه 3",
            "locator_label": "صفحه 3",
            "excerpt": "عبارت اضافی",
            "support_kind": "direct",
            "support_kind_label": "شاهد صریح",
        },
    }
    groups = claim_groups_for_ids(
        ["c1", "c2"],
        turn_evidence_ids=["ev-1", "ev-2", "ev-extra"],
        claims=claims,
        evidence_by_id=evidence_by_id,
    )
    assert len(groups) == 2
    assert groups[0]["claim_text"] == "مدعای یک"
    assert [e["evidence_id"] for e in groups[0]["evidence"]] == ["ev-1"]
    assert groups[1]["claim_text"] == "مدعای دو"
    assert [e["evidence_id"] for e in groups[1]["evidence"]] == ["ev-2"]
    all_ids = {e["evidence_id"] for g in groups for e in g["evidence"]}
    assert "ev-extra" not in all_ids
    cue = grounding_cue(groups)
    assert cue is not None
    assert cue["source_title"] == "کتاب"


def test_claim_groups_unknown_claim_unavailable() -> None:
    groups = claim_groups_for_ids(
        ["missing-claim"],
        turn_evidence_ids=["ev-1"],
        claims={},
        evidence_by_id={},
    )
    assert len(groups) == 1
    assert groups[0]["availability"] == "unavailable"
    assert groups[0]["claim_text"] is None
    assert groups[0]["evidence"] == []


def test_claim_groups_shared_claim_across_turns() -> None:
    claims = {"c1": _claim("ev-1", claim_id="c1", text="مدعای مشترک")}
    evidence_by_id = {
        "ev-1": {
            "evidence_id": "ev-1",
            "status": "ok",
            "availability": "ok",
            "source_title": "منبع",
            "locator": "صفحه 1",
            "locator_label": "صفحه 1",
            "excerpt": "عبارت",
            "support_kind": "direct",
            "support_kind_label": "شاهد صریح",
        }
    }
    g1 = claim_groups_for_ids(
        ["c1"], turn_evidence_ids=["ev-1"], claims=claims, evidence_by_id=evidence_by_id
    )
    g2 = claim_groups_for_ids(
        ["c1"], turn_evidence_ids=["ev-1"], claims=claims, evidence_by_id=evidence_by_id
    )
    assert g1[0]["claim_text"] == g2[0]["claim_text"] == "مدعای مشترک"


def test_omitted_claim_views_invalid_claim_id() -> None:
    rows = omitted_claim_views(
        [DeliberatelyOmittedClaim(claim_id="gone", reason="خارج از بودجه")],
        claims={},
        evidence_by_id={},
    )
    assert len(rows) == 1
    assert rows[0]["reason"] == "خارج از بودجه"
    assert rows[0]["claim_groups"][0]["availability"] == "unavailable"


def test_segment_views_marks_missing_evidence_unavailable(tmp_path: Path) -> None:
    source_id = uuid4()
    project = _project_with_turn(claim_ids=["claim-1"], evidence_ids=["missing-ev"])
    store = SourceArtifactStore(tmp_path)
    _save_source_artifacts(
        store,
        project.project_id,
        source_id,
        evidence_items=[],
        claims=[_claim("missing-ev")],
    )
    views = segment_views(project, project.script, store)
    groups = views[0]["turns"][0]["claim_groups"]
    assert len(groups) == 1
    assert groups[0]["availability"] == "ok"
    assert groups[0]["evidence"][0]["status"] == "unavailable"
    assert "در دسترس نیست" in str(groups[0]["evidence"][0]["message"])


def test_segment_views_unknown_claim_without_ledger(tmp_path: Path) -> None:
    project = _project_with_turn(claim_ids=["claim-1"], evidence_ids=["missing-ev"])
    store = SourceArtifactStore(tmp_path)
    views = segment_views(project, project.script, store)
    groups = views[0]["turns"][0]["claim_groups"]
    assert groups[0]["availability"] == "unavailable"
    assert views[0]["turns"][0]["grounding_cue"] is None


def test_segment_views_uses_ui_manifest_title_when_project_sources_empty(
    tmp_path: Path,
) -> None:
    source_id = uuid4()
    project = _project_with_turn(claim_ids=["claim-1"], evidence_ids=["ev-1"])
    store = SourceArtifactStore(tmp_path)
    _save_source_artifacts(
        store,
        project.project_id,
        source_id,
        evidence_items=[_evidence(source_id, "ev-1")],
        claims=[_claim("ev-1")],
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

    views = segment_views(project, project.script, store)
    turn_view = views[0]["turns"][0]
    evidence = turn_view["claim_groups"][0]["evidence"][0]
    assert evidence["status"] == "ok"
    assert evidence["source_title"] == "عنوان از مانیفست"
    assert str(source_id) not in evidence["source_title"]
    assert turn_view["grounding_cue"]["source_title"] == "عنوان از مانیفست"


def test_segment_views_marks_deselected_source_evidence_unavailable(
    tmp_path: Path,
) -> None:
    project = _project_with_turn(claim_ids=["claim-1"], evidence_ids=["ev-gone"])
    store = SourceArtifactStore(tmp_path)
    views = segment_views(project, project.script, store)
    groups = views[0]["turns"][0]["claim_groups"]
    assert groups[0]["availability"] == "unavailable"


def test_evidence_claim_groups_macro_renders_support_kinds() -> None:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATES_ROOT),
        autoescape=True,
        undefined=StrictUndefined,
    )
    environment.filters["fa_num"] = str
    template = environment.from_string(
        "{% from 'components.html' import evidence_claim_groups %}"
        "{{ evidence_claim_groups(claim_groups, 'proj', true) }}"
    )
    html = template.render(
        claim_groups=[
            {
                "claim_id": "c1",
                "claim_text": "متن مدعا",
                "support_status": "strong",
                "support_status_label": "پشتوانه قوی",
                "availability": "ok",
                "evidence": [
                    {
                        "evidence_id": "ev-1",
                        "status": "ok",
                        "availability": "ok",
                        "source_title": "کتاب",
                        "locator": "صفحه 1",
                        "locator_label": "صفحه 1",
                        "excerpt": "عبارت مستقیم",
                        "support_kind": "direct",
                        "support_kind_label": "شاهد صریح",
                    },
                    {
                        "evidence_id": "ev-2",
                        "status": "ok",
                        "availability": "ok",
                        "source_title": "کتاب",
                        "locator": "صفحه 2",
                        "locator_label": "صفحه 2",
                        "excerpt": "عبارت استنباطی",
                        "support_kind": "inferential",
                        "support_kind_label": "شاهد استنباطی",
                    },
                ],
            },
            {
                "claim_id": "c-missing",
                "claim_text": None,
                "support_status": None,
                "support_status_label": None,
                "availability": "unavailable",
                "evidence": [],
            },
        ]
    )
    assert "این گفته از کجا آمد؟" in html
    assert "متن مدعا" in html
    assert "شاهد صریح" in html
    assert "شاهد استنباطی" in html
    assert "متن این مدعا در دسترس نیست" in html
    assert "evidence-drawer" in html
