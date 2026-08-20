"""Acceptance tests for specs 09 (degrade) and 11 (disclosure)."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest

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
)
from thesisound.episode import (
    ClaimPriorityRecord,
    ClaimPriorityReport,
    CoverageReport,
    DisagreementGraph,
    EpisodeBudgetReport,
    EpisodePlanDraft,
    EpisodeSegmentDraft,
    SegmentEvidencePack,
)
from thesisound.modeling import DeterministicValidationError
from thesisound.script import (
    AbsorbedFault,
    Glossary,
    QualityNote,
    QualityNotesLedger,
    RevisedTurnDraft,
    ScriptCheckIssue,
    ScriptCheckReport,
    ScriptQualityScore,
    TargetedRevisionDraft,
    VerificationDraft,
)
from thesisound.services.absorption_triggers import (
    DegradationCounters,
    count_degradation,
    evaluate_absorption_triggers,
)
from thesisound.services.episode_planner import EpisodePlannerService, _validate_draft
from thesisound.services.evidence_extractor import _validate_claim_excerpt
from thesisound.services.model_retry import error_fingerprint
from thesisound.services.quality_notes import (
    all_quality_note_kinds,
    exceeds_degradation_ceiling,
    listener_impact_for,
    make_quality_note,
)
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_checks import ScriptChecker
from thesisound.services.script_grounding_remediation import remediate_script_grounding
from thesisound.services.script_outcome import script_outcome
from thesisound.services.script_reviser import _validate_revision
from thesisound.services.script_run import ScriptBuildRun
from thesisound.source_analysis import EvidenceClaimDraft

_INTERNAL_ID = re.compile(
    r"\b(?:clm|seg|ev|turn|block)-[0-9a-fA-F]+\b"
    r"|SegmentScriptDraft|Okian|Gemini"
)


def _brief(minutes: int = 10) -> ResearchBrief:
    return ResearchBrief(
        normalized_topic="topic",
        topic_type=TopicType.CONCEPT,
        central_question="What is it?",
        learning_objectives=["Understand A", "Understand B"],
        target_duration_minutes=minutes,
    )


def _checks(*, verdict: str = "pass", issues=None) -> ScriptCheckReport:
    return ScriptCheckReport(
        project_id=uuid4(),
        verdict=verdict,
        issues=issues or [],
        word_count=100,
        estimated_minutes=1,
        substantive_turn_count=2,
    )


def _quality(value: float = 0.9) -> ScriptQualityScore:
    return ScriptQualityScore(
        evidence_fidelity=value,
        qualification_preservation=value,
        stance_and_disagreement=value,
        terminology_consistency=value,
        listenability=value,
    )


def test_listener_impact_is_context_free_for_every_kind() -> None:
    for kind in all_quality_note_kinds():
        impact = listener_impact_for(kind)
        assert impact.strip()
        assert _INTERNAL_ID.search(impact) is None
        note = make_quality_note(stage="test", kind=kind, subject="clm-deadbeef")
        assert note.listener_impact == impact


def test_unaccounted_claim_is_auto_omitted_with_a_note() -> None:
    draft = EpisodePlanDraft(
        title="Title",
        listener_outcome="Outcome",
        segments=[
            EpisodeSegmentDraft(
                title="Seg",
                purpose="Purpose",
                target_minutes=10,
                claim_ids=["clm-must"],
                prerequisite_claim_ids=[],
                key_question="Why?",
                speaker_dynamic="explanation",
            )
        ],
        deliberately_omitted_claims=[],
        follow_up_topics=[],
    )
    priorities = {
        "clm-must": ClaimPriorityRecord(
            claim_id="clm-must", level="must_include", score=90, estimated_explanation_seconds=60
        ),
        "clm-support": ClaimPriorityRecord(
            claim_id="clm-support", level="supporting", score=50, estimated_explanation_seconds=30
        ),
    }
    notes: list[QualityNote] = []
    _validate_draft(
        draft,
        brief=_brief(10),
        known_claim_ids={"clm-must", "clm-support"},
        priority_by_id=priorities,
        notes=notes,
    )
    assert [item.claim_id for item in draft.deliberately_omitted_claims] == ["clm-support"]
    assert len(notes) == 1
    assert notes[0].kind == "claim_omitted"
    assert notes[0].subject == "clm-support"
    assert notes[0].severity == "notable"


def test_invented_claim_id_is_dropped_not_fatal() -> None:
    original = {
        "seg-004-turn-001": ScriptTurn(
            turn_id="seg-004-turn-001",
            segment_id="seg-004",
            speaker="A",
            spoken_text_fa="original",
            claim_ids=["clm-real"],
            evidence_ids=["ev-real"],
        )
    }
    draft = TargetedRevisionDraft(
        revised_turns=[
            RevisedTurnDraft(
                turn_id="seg-004-turn-001",
                speaker="A",
                spoken_text_fa="revised",
                claim_ids=["clm-real", "clm-INVENTED"],
                evidence_ids=["ev-real"],
            )
        ]
    )
    notes: list[QualityNote] = []
    _validate_revision(
        draft,
        target_ids=["seg-004-turn-001"],
        original_by_id=original,
        notes=notes,
    )
    assert draft.revised_turns[0].claim_ids == ["clm-real"]
    assert [note.kind for note in notes] == ["citation_dropped"]


def test_ungroundable_revised_turn_falls_back_to_original() -> None:
    original = {
        "seg-004-turn-001": ScriptTurn(
            turn_id="seg-004-turn-001",
            segment_id="seg-004",
            speaker="A",
            spoken_text_fa="original",
            claim_ids=["clm-real"],
            evidence_ids=["ev-real"],
        )
    }
    draft = TargetedRevisionDraft(
        revised_turns=[
            RevisedTurnDraft(
                turn_id="seg-004-turn-001",
                speaker="A",
                spoken_text_fa="revised",
                claim_ids=["clm-INVENTED"],
                evidence_ids=["ev-real"],
            )
        ]
    )
    notes: list[QualityNote] = []
    _validate_revision(
        draft,
        target_ids=["seg-004-turn-001"],
        original_by_id=original,
        notes=notes,
    )
    assert draft.revised_turns == []
    assert [note.kind for note in notes] == ["turn_not_revised"]


def test_degradation_ceiling_forces_review_required() -> None:
    notes = [
        make_quality_note(stage="episode_plan", kind="claim_omitted", subject=f"clm-{i}")
        for i in range(3)
    ]
    assert exceeds_degradation_ceiling(notes, segment_count=20)
    outcome, reason = script_outcome(
        _checks(),
        VerificationDraft(
            verdict="pass",
            unsupported_claim_ratio=0,
            quality=_quality(),
        ),
        quality_notes=notes,
        segment_count=20,
    )
    assert outcome == "review_required"
    assert "degraded" in reason.casefold() or "passage" in reason.casefold()


def _grounding_plan(*claim_ids: str, minutes: float = 5.0) -> EpisodePlan:
    return EpisodePlan(
        title="طرح",
        listener_outcome="نتیجه",
        estimated_duration_minutes=minutes,
        segments=[
            EpisodeSegment(
                segment_id="seg-1",
                title="بخش",
                purpose="آزمون",
                estimated_minutes=minutes,
                claim_ids=list(claim_ids or ("claim-1",)),
                key_question="پرسش؟",
                speaker_dynamic="explanation",
            )
        ],
    )


def test_mislinked_turn_evidence_is_repaired_not_rejected() -> None:
    source_id = uuid4()
    claims = [
        ClaimRecord(
            claim_id="claim-1",
            claim="مدعا",
            claim_type=ClaimType.AUTHOR_POSITION,
            evidence_ids=["ev-1"],
            support_status=SupportStatus.STRONG,
        )
    ]
    script = Script(
        title="متن",
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-1",
                speaker="A",
                spoken_text_fa="گفتهٔ محتوایی با شاهد نادرست است.",
                claim_ids=["claim-1"],
                evidence_ids=["ev-wrong"],
            )
        ],
    )
    result = remediate_script_grounding(
        script,
        claims,
        episode_plan=_grounding_plan("claim-1"),
    )
    remedied, notes = result.script, result.notes
    assert remedied.turns[0].evidence_ids == ["ev-1"]
    assert [note.kind for note in notes] == ["grounding_repaired"]
    assert result.faults == []
    pack = SegmentEvidencePack.model_construct(
        segment_id="seg-1",
        claim_ids=["claim-1"],
        evidence_items=[
            EvidenceItem(
                evidence_id="ev-1",
                source_id=source_id,
                block_id="block-1",
                claim="مدعا",
                claim_type=ClaimType.AUTHOR_POSITION,
                supporting_excerpt="عبارت شاهد",
                locator=Locator(page_start=1, page_end=1),
                support_kind="direct",
                confidence=0.9,
            )
        ],
        original_blocks=[],
        token_budget=100,
        actual_tokens=2,
    )
    project_id = uuid4()
    report = ScriptChecker().check(
        project_id=project_id,
        script=remedied,
        episode_plan=_grounding_plan("claim-1"),
        evidence_packs=[pack],
        claims=claims,
        glossary=Glossary(project_id=project_id, model_run_id=uuid4()),
    )
    issue_types = {issue.issue_type for issue in report.issues}
    assert "missing_grounding" not in issue_types
    assert "evidence_unlinked_to_claim" not in issue_types


_GROUNDED_TEXT = "این گفته به شاهد واقعی وصل است و متن آن به اندازهٔ کافی بلند است."


def _grounded_claim() -> ClaimRecord:
    return ClaimRecord(
        claim_id="claim-1",
        claim="مدعا",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=["ev-1"],
        support_status=SupportStatus.STRONG,
    )


def _evidence_less_claim() -> ClaimRecord:
    return ClaimRecord(
        claim_id="claim-empty",
        claim="مدعای بدون شاهد",
        claim_type=ClaimType.EDITORIAL_EXPLANATION,
        evidence_ids=[],
        support_status=SupportStatus.UNCERTAIN,
    )


def _grounded_turn(turn_id: str = "t1", segment_id: str = "seg-1") -> ScriptTurn:
    return ScriptTurn(
        turn_id=turn_id,
        segment_id=segment_id,
        speaker="A",
        spoken_text_fa=_GROUNDED_TEXT,
        claim_ids=["claim-1"],
        evidence_ids=["ev-1"],
    )


def _ungrounded_turn(turn_id: str = "t2", segment_id: str = "seg-2") -> ScriptTurn:
    return ScriptTurn(
        turn_id=turn_id,
        segment_id=segment_id,
        speaker="B",
        spoken_text_fa="این گفته به مدعایی ارجاع می‌دهد که هیچ شاهدی ندارد.",
        claim_ids=["claim-empty"],
        evidence_ids=["ev-placeholder"],
    )


def test_evidence_less_claim_is_excised_not_raised() -> None:
    """Spec 12 D3: the passage must not be spoken, but the episode survives."""

    script = Script(title="متن", turns=[_grounded_turn(), _ungrounded_turn()])
    result = remediate_script_grounding(
        script,
        [_grounded_claim(), _evidence_less_claim()],
        episode_plan=_grounding_plan("claim-1", minutes=0.1),
    )
    assert [turn.turn_id for turn in result.script.turns] == ["t1"]
    assert [(note.kind, note.subject) for note in result.notes] == [("turn_excised", "t2")]
    assert [(fault.kind, fault.subject) for fault in result.faults] == [
        ("ungrounded_claim", "claim-empty")
    ]


def test_emptied_segment_is_excised_whole() -> None:
    editorial = ScriptTurn(
        turn_id="t2",
        segment_id="seg-2",
        speaker="A",
        spoken_text_fa="حالا به نکتهٔ بعدی می‌رسیم.",
        editorial_only=True,
    )
    script = Script(
        title="متن",
        turns=[_grounded_turn(), editorial, _ungrounded_turn("t3", "seg-2")],
    )
    result = remediate_script_grounding(
        script,
        [_grounded_claim(), _evidence_less_claim()],
        episode_plan=_grounding_plan("claim-1", minutes=0.1),
    )
    # The editorial turn introduces a point the script no longer makes.
    assert [turn.turn_id for turn in result.script.turns] == ["t1"]
    assert [note.kind for note in result.notes] == ["turn_excised"]
    assert [fault.kind for fault in result.faults] == ["ungrounded_claim"]


def test_duration_shortfall_notes_instead_of_raising() -> None:
    script = Script(title="متن", turns=[_grounded_turn(), _ungrounded_turn()])
    result = remediate_script_grounding(
        script,
        [_grounded_claim(), _evidence_less_claim()],
        episode_plan=_grounding_plan("claim-1", minutes=5.0),
    )
    assert [turn.turn_id for turn in result.script.turns] == ["t1"]
    assert [note.kind for note in result.notes] == ["turn_excised", "duration_shortfall"]
    assert result.notes[-1].severity == "notable"


def test_unknown_claim_id_alongside_a_real_one_is_dropped() -> None:
    turn = _grounded_turn().model_copy(update={"claim_ids": ["claim-1", "claim-ghost"]})
    result = remediate_script_grounding(
        Script(title="متن", turns=[turn]),
        [_grounded_claim()],
        episode_plan=_grounding_plan("claim-1", minutes=0.1),
    )
    assert result.script.turns[0].claim_ids == ["claim-1"]
    assert result.script.turns[0].evidence_ids == ["ev-1"]
    assert [note.kind for note in result.notes] == ["citation_dropped"]
    assert result.faults == []


def test_empty_script_is_the_only_grounding_raise() -> None:
    script = Script(title="متن", turns=[_ungrounded_turn("t1", "seg-1")])
    with pytest.raises(
        DeterministicValidationError, match="linked to the evidence ledger"
    ) as raised:
        remediate_script_grounding(
            script,
            [_evidence_less_claim()],
            episode_plan=_grounding_plan("claim-empty"),
        )
    assert raised.value.stop_reason == "integrity_breach"


def test_heavy_excision_ends_review_required_not_rejected() -> None:
    """Spec 12 §4.4: length lost to excision routes to review, never rejected."""

    notes = [
        make_quality_note(stage="script_grounding", kind="turn_excised", subject=f"t{i}")
        for i in range(3)
    ] + [
        make_quality_note(
            stage="script_grounding",
            kind="duration_shortfall",
            subject="script:7.0/10min",
        )
    ]
    outcome, reason = script_outcome(
        _checks(),
        VerificationDraft(
            verdict="pass",
            unsupported_claim_ratio=0,
            quality=_quality(),
        ),
        quality_notes=notes,
        segment_count=4,
    )
    assert outcome == "review_required"
    assert outcome != "rejected"
    assert "degraded" in reason


def test_repair_and_excise_are_counted_separately() -> None:
    """Spec 12 D6: a flood of Case A repairs must not inflate Case B."""

    notes = [
        make_quality_note(stage="script_grounding", kind="grounding_repaired", subject=f"t{i}")
        for i in range(8)
    ] + [
        make_quality_note(stage="script_grounding", kind="turn_excised", subject="t-x")
    ]
    faults = [
        AbsorbedFault(kind="ungrounded_claim", subject="claim-empty", detail="t-x")
    ]
    counters = count_degradation(
        notes=notes,
        faults=faults,
        substantive_turn_count=10,
        automatic_retries=0,
    )
    assert counters.grounding_repaired == 8
    assert counters.turn_excised_ungrounded_claim == 1
    assert counters.turn_excised_unknown_claim == 0


def test_unknown_claim_excision_records_unknown_fault() -> None:
    turn = ScriptTurn(
        turn_id="t1",
        segment_id="seg-1",
        speaker="A",
        spoken_text_fa=_GROUNDED_TEXT,
        claim_ids=["claim-ghost"],
        evidence_ids=["ev-1"],
    )
    keeper = _grounded_turn("t2", "seg-2")
    result = remediate_script_grounding(
        Script(title="متن", turns=[turn, keeper]),
        [_grounded_claim()],
        episode_plan=_grounding_plan("claim-1", minutes=0.1),
    )
    assert [turn.turn_id for turn in result.script.turns] == ["t2"]
    assert [fault.kind for fault in result.faults] == ["unknown_claim"]
    assert [note.kind for note in result.notes] == ["turn_excised"]


def _run_with_counters(**counter_fields: int) -> ScriptBuildRun:
    return ScriptBuildRun(
        project_id=uuid4(),
        approved_plan_hash="a" * 64,
        approved_by="tester",
        status="succeeded",
        degradation_counters=DegradationCounters(**counter_fields),
    )


def test_unknown_claim_trigger_fires_immediately() -> None:
    hits = evaluate_absorption_triggers(
        [_run_with_counters(turn_excised_unknown_claim=1, substantive_turn_count=4)]
    )
    assert [hit.trigger_id for hit in hits] == ["unknown_claim_any"]


def test_ungrounded_claim_trigger_needs_two_consecutive_runs() -> None:
    first = _run_with_counters(turn_excised_ungrounded_claim=1, substantive_turn_count=4)
    alone = evaluate_absorption_triggers([first])
    assert "ungrounded_claim_consecutive" not in {hit.trigger_id for hit in alone}

    second = _run_with_counters(turn_excised_ungrounded_claim=1, substantive_turn_count=4)
    both = evaluate_absorption_triggers([first, second])
    assert "ungrounded_claim_consecutive" in {hit.trigger_id for hit in both}


def test_repaired_ratio_trigger_over_five_runs() -> None:
    # 3 repairs / 10 substantive each → 30% over 5 runs, above 20%.
    runs = [
        _run_with_counters(grounding_repaired=3, substantive_turn_count=10)
        for _ in range(5)
    ]
    hits = evaluate_absorption_triggers(runs)
    assert "grounding_repaired_ratio" in {hit.trigger_id for hit in hits}

    quiet = [
        _run_with_counters(grounding_repaired=1, substantive_turn_count=10)
        for _ in range(5)
    ]
    assert "grounding_repaired_ratio" not in {
        hit.trigger_id for hit in evaluate_absorption_triggers(quiet)
    }


def test_clean_run_emits_no_quality_notes() -> None:
    outcome, _ = script_outcome(
        _checks(),
        VerificationDraft(
            verdict="pass",
            unsupported_claim_ratio=0,
            quality=_quality(),
        ),
        quality_notes=[],
        segment_count=4,
    )
    assert outcome == "verified"
    assert not exceeds_degradation_ceiling([], segment_count=4)


def test_clean_build_is_distinguishable_from_degraded() -> None:
    clean = ScriptBuildRun(
        project_id=uuid4(),
        approved_plan_hash="a" * 64,
        approved_by="tester",
        quality_disposition="clean",
    )
    degraded = clean.model_copy(update={"quality_disposition": "degraded"})
    assert clean.quality_disposition != degraded.quality_disposition


def test_insufficient_coverage_still_raises() -> None:
    class _UnusedRunner:
        def run(self, **_: object) -> None:  # pragma: no cover
            raise AssertionError("runner should not be called")

    service = EpisodePlannerService(_UnusedRunner())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Coverage is insufficient"):
        service.plan(
            project_id=uuid4(),
            brief=_brief(10),
            claims=[],
            coverage=CoverageReport(
                project_id=uuid4(),
                central_question_status="not_covered",
                central_question_claim_ids=[],
                objective_coverage=[],
                max_supported_minutes=2,
                recommendation="more_evidence",
                recommendation_reason="Too thin.",
                can_plan_episode=False,
                model_run_id=uuid4(),
            ),
            budget=EpisodeBudgetReport(
                project_id=uuid4(),
                target_duration_minutes=10,
                words_per_minute=150,
                available_claim_seconds=120,
                original_evidence_tokens=100,
                estimated_supported_minutes=2,
                model_reported_supported_minutes=2,
                effective_supported_minutes=2,
                calibration_status="uncalibrated",
            ),
            priorities=ClaimPriorityReport(
                project_id=uuid4(),
                target_duration_minutes=10,
                priorities=[],
                available_content_seconds=120,
                estimated_selected_seconds=0,
            ),
            disagreement_graph=DisagreementGraph(project_id=uuid4()),
            extraction_plans=[],
            definitions=[],
            distinctions=[],
            examples=[],
            objections=[],
            responses=[],
            model="fake",
        )


def test_prompt_leakage_still_blocks() -> None:
    issue = ScriptCheckIssue(
        severity="blocking",
        issue_type="prompt_leakage",
        explanation=(
            "A spoken line looks like internal instructions rather than "
            "episode dialogue. Regenerate that passage before shipping."
        ),
    )
    outcome, _ = script_outcome(
        _checks(verdict="reject", issues=[issue]),
        VerificationDraft(verdict="pass", unsupported_claim_ratio=0),
    )
    assert outcome == "rejected"


def test_coverage_stop_keeps_its_actionable_message() -> None:
    message = "Coverage is insufficient for the requested duration; narrow scope or add evidence."
    assert "narrow scope" in message
    assert _INTERNAL_ID.search(message) is None


def test_every_fatal_raise_declares_a_stop_reason() -> None:
    structural = [
        DeterministicValidationError(
            "One or more required points were left out of the episode plan. "
            "Add a section that covers them, or shorten the episode.",
            stop_reason="integrity_breach",
        ),
        DeterministicValidationError(
            "One section referenced points that are not in the evidence set.",
            stop_reason="integrity_breach",
        ),
    ]
    for error in structural:
        assert error.stop_reason in {
            "information_asymmetry",
            "changeable_input",
            "consent",
            "integrity_breach",
        }


def test_no_user_facing_string_contains_an_internal_id() -> None:
    for kind in all_quality_note_kinds():
        assert _INTERNAL_ID.search(listener_impact_for(kind)) is None
    for message in (
        "Coverage is insufficient for the requested duration; narrow scope or add evidence.",
        "One or more required points were left out of the episode plan. "
        "Add a section that covers them, or shorten the episode.",
        "A spoken line looks like internal instructions rather than "
        "episode dialogue. Regenerate that passage before shipping.",
    ):
        assert _INTERNAL_ID.search(message) is None


def test_distinct_bad_excerpts_have_distinct_fingerprints() -> None:
    short_a = EvidenceClaimDraft(
        claim="A",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt="short-a",
        support_kind="direct",
        confidence=0.9,
    )
    short_b = EvidenceClaimDraft(
        claim="B",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt="short-b-xx",
        support_kind="direct",
        confidence=0.9,
    )
    with pytest.raises(DeterministicValidationError) as first:
        _validate_claim_excerpt(short_a, "A long enough source block for auditing.")
    with pytest.raises(DeterministicValidationError) as second:
        _validate_claim_excerpt(short_b, "A long enough source block for auditing.")
    assert error_fingerprint(first.value) != error_fingerprint(second.value)


def test_single_degradation_surfaces_one_note_at_review(tmp_path: Path) -> None:
    project_id = uuid4()
    store = ScriptArtifactStore(tmp_path)
    note = make_quality_note(
        stage="episode_plan",
        kind="claim_omitted",
        subject="clm-abc",
    )
    store.save_quality_notes(QualityNotesLedger(project_id=project_id, notes=[note]))
    loaded = store.load_quality_notes_optional(project_id)
    assert loaded is not None
    assert len(loaded.notes) == 1
    assert loaded.notes[0].listener_impact == listener_impact_for("claim_omitted")
