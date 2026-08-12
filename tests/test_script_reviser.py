from __future__ import annotations

import pytest

from thesisound.domain import ScriptTurn
from thesisound.modeling import DeterministicValidationError
from thesisound.script import RevisedTurnDraft, TargetedRevisionDraft
from thesisound.services.script_reviser import _validate_revision


def _turn(
    turn_id: str,
    *,
    claim_ids: list[str] | None = None,
    evidence_ids: list[str] | None = None,
) -> ScriptTurn:
    return ScriptTurn(
        turn_id=turn_id,
        segment_id="seg-004",
        speaker="A",
        spoken_text_fa="original text",
        claim_ids=claim_ids if claim_ids is not None else ["clm-real"],
        evidence_ids=evidence_ids if evidence_ids is not None else ["ev-real"],
    )


def _revised(
    turn_id: str,
    *,
    claim_ids: list[str],
    evidence_ids: list[str] | None = None,
    editorial_only: bool = False,
) -> RevisedTurnDraft:
    return RevisedTurnDraft(
        turn_id=turn_id,
        speaker="A",
        spoken_text_fa="revised text",
        claim_ids=claim_ids,
        evidence_ids=evidence_ids if evidence_ids is not None else ["ev-real"],
        editorial_only=editorial_only,
    )


def test_invented_id_alongside_a_real_one_is_dropped_and_turn_survives() -> None:
    original = {"seg-004-turn-001": _turn("seg-004-turn-001")}
    draft = TargetedRevisionDraft(
        revised_turns=[_revised("seg-004-turn-001", claim_ids=["clm-real", "clm-INVENTED"])]
    )

    _validate_revision(draft, target_ids=["seg-004-turn-001"], original_by_id=original)

    assert len(draft.revised_turns) == 1
    assert draft.revised_turns[0].claim_ids == ["clm-real"]


def test_invented_id_replacing_the_only_real_one_drops_the_whole_turn() -> None:
    """The exact production case: the model swapped its only claim ID for a
    fabricated one rather than citing alongside it. Nothing salvageable is
    left for this turn, so it is dropped from the revision -- not the whole
    build. _materialize_revision then falls back to the original, still-
    grounded turn for it, the same as any turn that was never targeted.
    """

    original = {"seg-004-turn-001": _turn("seg-004-turn-001")}
    draft = TargetedRevisionDraft(
        revised_turns=[_revised("seg-004-turn-001", claim_ids=["clm-INVENTED"])]
    )

    _validate_revision(draft, target_ids=["seg-004-turn-001"], original_by_id=original)

    assert draft.revised_turns == []


def test_only_the_ungroundable_turn_is_dropped_others_are_kept() -> None:
    original = {
        "seg-004-turn-001": _turn("seg-004-turn-001"),
        "seg-004-turn-002": _turn("seg-004-turn-002", claim_ids=["clm-other"]),
    }
    draft = TargetedRevisionDraft(
        revised_turns=[
            _revised("seg-004-turn-001", claim_ids=["clm-INVENTED"]),
            _revised("seg-004-turn-002", claim_ids=["clm-other"]),
        ]
    )

    _validate_revision(
        draft,
        target_ids=["seg-004-turn-001", "seg-004-turn-002"],
        original_by_id=original,
    )

    assert [turn.turn_id for turn in draft.revised_turns] == ["seg-004-turn-002"]


def test_editorial_only_turn_may_lose_all_grounding() -> None:
    original = {"seg-004-turn-001": _turn("seg-004-turn-001")}
    draft = TargetedRevisionDraft(
        revised_turns=[
            _revised(
                "seg-004-turn-001",
                claim_ids=[],
                evidence_ids=[],
                editorial_only=True,
            )
        ]
    )

    _validate_revision(draft, target_ids=["seg-004-turn-001"], original_by_id=original)

    assert len(draft.revised_turns) == 1


def test_changed_speaker_still_raises() -> None:
    original = {"seg-004-turn-001": _turn("seg-004-turn-001")}
    draft = TargetedRevisionDraft(
        revised_turns=[
            RevisedTurnDraft(
                turn_id="seg-004-turn-001",
                speaker="B",
                spoken_text_fa="revised text",
                claim_ids=["clm-real"],
                evidence_ids=["ev-real"],
            )
        ]
    )

    with pytest.raises(DeterministicValidationError, match="changed speaker"):
        _validate_revision(draft, target_ids=["seg-004-turn-001"], original_by_id=original)
