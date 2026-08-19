from __future__ import annotations

from uuid import UUID, uuid4

from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    EpisodePlan,
    EpisodeSegment,
    EvidenceItem,
    Locator,
    ResearchBrief,
    Script,
    ScriptTurn,
    SupportStatus,
    TopicType,
    VerificationIssue,
)
from thesisound.episode import DisagreementGraph, SegmentEvidencePack
from thesisound.modeling import ModelExecution, ModelRunRecord
from thesisound.script import (
    Glossary,
    RevisedTurnDraft,
    ScriptCheckReport,
    ScriptQualityScore,
    ScriptTurnDraft,
    SegmentScriptDraft,
    TargetedRevisionDraft,
    VerificationDraft,
)
from thesisound.services.evidence_pack_builder import EvidencePackBuilder
from thesisound.services.persian_script_writer import PersianScriptWriterService
from thesisound.services.script_reviser import TargetedScriptReviserService
from thesisound.services.script_verifier import ScriptVerifierService
from thesisound.source_analysis import SourceDocumentBlock


_SOURCE_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


class _SpyRunner:
    def __init__(self, output) -> None:
        self.output = output
        self.variables: dict[str, object] | None = None

    def run(self, *, project_id, stage, variables, output_type, model, validator=None, **_):
        self.variables = variables
        if validator is not None:
            validator(self.output)
        return ModelExecution(
            output=self.output,
            record=ModelRunRecord(
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
            ),
        )


def _block() -> SourceDocumentBlock:
    return SourceDocumentBlock(
        block_id="block-1",
        source_id=_SOURCE_ID,
        locator=Locator(page_start=1, page_end=1),
        heading_path=["Section"],
        block_type="argument",
        text="Original grounded passage about action.",
        estimated_token_count=40,
        source_block_keys=["p1"],
    )


def _evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev-1",
        source_id=_SOURCE_ID,
        block_id="block-1",
        claim="Action is distinct from fabrication.",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt="Original grounded passage about action.",
        locator=Locator(page_start=1, page_end=1),
        support_kind="direct",
        confidence=0.9,
    )


def _claim(
    claim_id: str = "clm-1",
    *,
    support_status: SupportStatus = SupportStatus.CONTESTED,
    qualifications: list[str] | None = None,
) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        claim="Action is distinct from fabrication.",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=["ev-1"],
        support_status=support_status,
        qualifications=qualifications
        if qualifications is not None
        else ["only in the political realm"],
    )


def _segment(*claim_ids: str) -> EpisodeSegment:
    return EpisodeSegment(
        segment_id="seg-001",
        title="Core distinction",
        purpose="Introduce the distinction.",
        estimated_minutes=5,
        claim_ids=list(claim_ids),
        key_question="What distinguishes action?",
        speaker_dynamic="explanation",
    )


def _plan(*claim_ids: str) -> EpisodePlan:
    return EpisodePlan(
        title="Action",
        listener_outcome="The listener can explain the distinction.",
        estimated_duration_minutes=5,
        segments=[_segment(*claim_ids)],
    )


def _pack(claim: ClaimRecord) -> SegmentEvidencePack:
    return SegmentEvidencePack(
        segment_id="seg-001",
        claim_ids=[claim.claim_id],
        claims=[claim],
        evidence_items=[_evidence()],
        original_blocks=[_block()],
        token_budget=2000,
        actual_tokens=40,
    )


def test_builder_fills_claims_matching_claim_ids_in_order() -> None:
    first = _claim("clm-1", support_status=SupportStatus.CONTESTED)
    second = _claim("clm-2", support_status=SupportStatus.STRONG, qualifications=[])
    unused = _claim("clm-unused", support_status=SupportStatus.UNCERTAIN)

    packs = EvidencePackBuilder().build(
        episode_plan=_plan("clm-2", "clm-1"),
        claims=[unused, first, second],
        evidence_items=[_evidence()],
        blocks=[_block()],
        extraction_plans=[],
    )

    assert len(packs) == 1
    pack = packs[0]
    assert [claim.claim_id for claim in pack.claims] == pack.claim_ids == ["clm-2", "clm-1"]
    by_id = {claim.claim_id: claim for claim in pack.claims}
    assert by_id["clm-1"].support_status is SupportStatus.CONTESTED
    assert by_id["clm-1"].qualifications == ["only in the political realm"]
    assert "clm-unused" not in by_id


def test_old_pack_json_defaults_claims_to_empty() -> None:
    pack = SegmentEvidencePack.model_validate(
        {
            "segment_id": "seg-001",
            "claim_ids": ["clm-1"],
            "evidence_items": [_evidence().model_dump(mode="json")],
            "original_blocks": [_block().model_dump(mode="json")],
            "token_budget": 2000,
            "actual_tokens": 40,
        }
    )
    assert pack.claims == []
    assert pack.claim_ids == ["clm-1"]


def test_writer_sends_pack_claims() -> None:
    claim = _claim()
    pack = _pack(claim)
    runner = _SpyRunner(
        SegmentScriptDraft(
            turns=[
                ScriptTurnDraft(
                    speaker="A",
                    spoken_text_fa="کنش از ساختن جداست.",
                    claim_ids=[claim.claim_id],
                    evidence_ids=["ev-1"],
                )
            ]
        )
    )
    PersianScriptWriterService(runner).write_segment(
        project_id=uuid4(),
        brief=ResearchBrief(
            normalized_topic="action",
            topic_type=TopicType.CONCEPT,
            central_question="What is action?",
        ),
        segment=_segment(claim.claim_id),
        evidence_pack=pack,
        glossary=Glossary(project_id=uuid4(), model_run_id=uuid4()),
        disagreement_graph=DisagreementGraph(project_id=uuid4()),
        model="fake",
    )
    assert runner.variables is not None
    sent = runner.variables["claims"]
    assert sent == [claim.model_dump(mode="json")]
    assert sent[0]["support_status"] == "contested"
    assert sent[0]["qualifications"] == ["only in the political realm"]


def test_verifier_sends_claims_and_empty_placeholders() -> None:
    claim = _claim()
    pack = _pack(claim)
    project_id = uuid4()
    runner = _SpyRunner(
        VerificationDraft(
            verdict="pass",
            unsupported_claim_ratio=0,
            quality=ScriptQualityScore(
                evidence_fidelity=1,
                qualification_preservation=1,
                stance_and_disagreement=1,
                terminology_consistency=1,
                listenability=1,
            ),
        )
    )
    ScriptVerifierService(runner).verify(
        project_id=project_id,
        script=Script(
            title="Action",
            turns=[
                ScriptTurn(
                    turn_id="seg-001-turn-001",
                    segment_id="seg-001",
                    speaker="A",
                    spoken_text_fa="کنش از ساختن جداست.",
                    claim_ids=[claim.claim_id],
                    evidence_ids=["ev-1"],
                )
            ],
        ),
        checks=ScriptCheckReport(
            project_id=project_id,
            verdict="pass",
            word_count=4,
            estimated_minutes=1,
            substantive_turn_count=1,
        ),
        episode_plan=_plan(claim.claim_id),
        evidence_packs=[pack],
        glossary=Glossary(project_id=project_id, model_run_id=uuid4()),
        disagreement_graph=DisagreementGraph(project_id=project_id),
        model="fake",
    )
    assert runner.variables is not None
    assert runner.variables["claims"] == [claim.model_dump(mode="json")]
    assert runner.variables["plan_must_include"] == []
    assert runner.variables["known_concepts"] == []


def test_verifier_sends_planned_must_not_be_lost_claim_ids() -> None:
    project_id = uuid4()
    kept = _claim("clm-kept")
    kept = kept.model_copy(update={"must_not_be_lost": True})
    omitted_flag = _claim("clm-omitted")
    omitted_flag = omitted_flag.model_copy(update={"must_not_be_lost": True})
    pack = _pack(kept)
    pack.claims = [kept, omitted_flag]
    runner = _SpyRunner(
        VerificationDraft(
            verdict="pass",
            issues=[],
            unsupported_claim_ratio=0.0,
            quality=ScriptQualityScore(
                evidence_fidelity=1,
                qualification_preservation=1,
                stance_and_disagreement=1,
                terminology_consistency=1,
                listenability=1,
            ),
        )
    )
    ScriptVerifierService(runner).verify(
        project_id=project_id,
        script=Script(
            title="Action",
            turns=[
                ScriptTurn(
                    turn_id="seg-001-turn-001",
                    segment_id="seg-001",
                    speaker="A",
                    spoken_text_fa="کنش از ساختن جداست.",
                    claim_ids=[kept.claim_id],
                    evidence_ids=["ev-1"],
                )
            ],
        ),
        checks=ScriptCheckReport(
            project_id=project_id,
            verdict="pass",
            word_count=4,
            estimated_minutes=1,
            substantive_turn_count=1,
        ),
        episode_plan=_plan(kept.claim_id),
        evidence_packs=[pack],
        glossary=Glossary(project_id=project_id, model_run_id=uuid4()),
        disagreement_graph=DisagreementGraph(project_id=project_id),
        model="fake",
    )
    assert runner.variables is not None
    assert runner.variables["plan_must_include"] == ["clm-kept"]


def test_reviser_sends_claims_from_relevant_packs() -> None:
    claim = _claim()
    pack = _pack(claim)
    other = _claim("clm-other")
    other_pack = SegmentEvidencePack(
        segment_id="seg-002",
        claim_ids=[other.claim_id],
        claims=[other],
        evidence_items=[_evidence()],
        original_blocks=[_block()],
        token_budget=2000,
        actual_tokens=40,
    )
    project_id = uuid4()
    turn = ScriptTurn(
        turn_id="seg-001-turn-001",
        segment_id="seg-001",
        speaker="A",
        spoken_text_fa="کنش از ساختن جداست.",
        claim_ids=[claim.claim_id],
        evidence_ids=["ev-1"],
    )
    runner = _SpyRunner(
        TargetedRevisionDraft(
            revised_turns=[
                RevisedTurnDraft(
                    turn_id=turn.turn_id,
                    speaker="A",
                    spoken_text_fa="کنش، در سپهر سیاسی، از ساختن جداست.",
                    claim_ids=[claim.claim_id],
                    evidence_ids=["ev-1"],
                )
            ]
        )
    )
    TargetedScriptReviserService(runner).revise(
        project_id=project_id,
        script=Script(title="Action", turns=[turn]),
        checks=ScriptCheckReport(
            project_id=project_id,
            verdict="revise",
            word_count=4,
            estimated_minutes=1,
            substantive_turn_count=1,
        ),
        verification=VerificationDraft(
            verdict="revise",
            unsupported_claim_ratio=0,
            issues=[
                VerificationIssue(
                    turn_id=turn.turn_id,
                    severity="high",
                    issue_type="lost_qualification",
                    explanation="The political-realm hedge was dropped.",
                    required_revision="Restore the qualification.",
                )
            ],
            quality=ScriptQualityScore(
                evidence_fidelity=0.8,
                qualification_preservation=0.4,
                stance_and_disagreement=0.8,
                terminology_consistency=0.8,
                listenability=0.8,
                actionable_feedback="Restore the qualification.",
            ),
        ),
        evidence_packs=[pack, other_pack],
        glossary=Glossary(project_id=project_id, model_run_id=uuid4()),
        model="fake",
    )
    assert runner.variables is not None
    assert runner.variables["claims"] == [claim.model_dump(mode="json")]
    assert "clm-other" not in {item["claim_id"] for item in runner.variables["claims"]}
