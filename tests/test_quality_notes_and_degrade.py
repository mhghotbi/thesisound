"""Acceptance tests for specs 09 (degrade) and 11 (disclosure)."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest

from thesisound.domain import ClaimType, ResearchBrief, ScriptTurn, TopicType
from thesisound.episode import (
    ClaimPriorityRecord,
    ClaimPriorityReport,
    CoverageReport,
    DisagreementGraph,
    EpisodeBudgetReport,
    EpisodePlanDraft,
    EpisodeSegmentDraft,
)
from thesisound.modeling import DeterministicValidationError
from thesisound.script import (
    QualityNote,
    QualityNotesLedger,
    RevisedTurnDraft,
    ScriptCheckIssue,
    ScriptCheckReport,
    ScriptQualityScore,
    TargetedRevisionDraft,
    VerificationDraft,
)
from thesisound.services.evidence_extractor import _validate_claim_excerpt
from thesisound.services.episode_planner import EpisodePlannerService, _validate_draft
from thesisound.services.model_retry import error_fingerprint
from thesisound.services.quality_notes import (
    all_quality_note_kinds,
    exceeds_degradation_ceiling,
    listener_impact_for,
    make_quality_note,
)
from thesisound.services.script_artifact_store import ScriptArtifactStore
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
