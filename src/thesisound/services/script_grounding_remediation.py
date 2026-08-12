"""Pre-check grounding remediation (spec 09 D3 ladder, narrowed by spec 12 D3).

The ladder is repair -> excise -> stop. Spec 12 D3 removed two of the three
original stops -- a passage citing an evidence-less claim, and excision that
costs the script part of its duration band -- because neither breaks the
evidence promise once the passage is gone, and spec 11 D1 reason 4 only covers
breaches that shipping would cause. One stop survives; see the single raise.

Cumulative degradation is bounded by ``exceeds_degradation_ceiling``, not here.
"""

from __future__ import annotations

import re

from thesisound.domain import ClaimRecord, EpisodePlan, Script, ScriptTurn
from thesisound.modeling import DeterministicValidationError
from thesisound.script import QualityNote, QualityNoteKind
from thesisound.services.quality_notes import make_quality_note

_WORD = re.compile(r"\w+", re.UNICODE)
_DURATION_FLOOR = 0.8


def _provenance_evidence_ids(claim_ids: list[str], claim_by_id: dict[str, ClaimRecord]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for claim_id in claim_ids:
        claim = claim_by_id.get(claim_id)
        if claim is None:
            continue
        for evidence_id in claim.evidence_ids:
            if evidence_id not in seen:
                seen.add(evidence_id)
                ordered.append(evidence_id)
    return ordered


def _estimated_minutes(turns: list[ScriptTurn], *, words_per_minute: int) -> float:
    word_count = sum(len(_WORD.findall(turn.spoken_text_fa)) for turn in turns)
    if not word_count or words_per_minute <= 0:
        return 0.0
    return word_count / words_per_minute


def _substantive_segment_ids(turns: list[ScriptTurn]) -> set[str]:
    return {turn.segment_id for turn in turns if not turn.editorial_only}


def _note(kind: QualityNoteKind, subject: str) -> QualityNote:
    return make_quality_note(stage="script_grounding", kind=kind, subject=subject)


def remediate_script_grounding(
    script: Script,
    claims: list[ClaimRecord],
    *,
    episode_plan: EpisodePlan,
    words_per_minute: int = 130,
) -> tuple[Script, list[QualityNote]]:
    """Apply the D3 ladder: repair mislinked evidence, excise what cannot be grounded."""

    claim_by_id = {claim.claim_id: claim for claim in claims}
    notes: list[QualityNote] = []
    kept: list[ScriptTurn] = []
    excise_ids: list[str] = []

    for turn in script.turns:
        if turn.editorial_only:
            kept.append(turn)
            continue

        known_ids = [claim_id for claim_id in turn.claim_ids if claim_id in claim_by_id]
        ungrounded = [
            claim_id for claim_id in known_ids if not claim_by_id[claim_id].evidence_ids
        ]
        if ungrounded or not known_ids:
            # Rung 2. Either the writer invented every id it cited, or a cited
            # claim carries no evidence in the ledger. The passage must not be
            # spoken -- but removing it keeps the promise, and removing is not
            # the same as destroying the episode, which is why rung 3 no longer
            # applies here. An evidence-less claim is an upstream extraction
            # fault: excision hides it from the listener, which is correct, and
            # not from the ledger, which is what matters for fixing it.
            excise_ids.append(turn.turn_id)
            kept.append(turn)
            continue

        # Every surviving cited claim is known and carries evidence from here on.
        repaired = turn
        if len(known_ids) != len(turn.claim_ids):
            # Recoverable: invented ids alongside real ones. Keeping them buys
            # nothing and guarantees a blocking `unknown_claim` downstream.
            repaired = repaired.model_copy(update={"claim_ids": known_ids})
            notes.append(_note("citation_dropped", turn.turn_id))

        expected = _provenance_evidence_ids(known_ids, claim_by_id)
        turn_evidence = set(repaired.evidence_ids)
        expected_evidence = set(expected)
        if not (turn_evidence & expected_evidence) or (turn_evidence - expected_evidence):
            # Rung 1: the grounding exists on the claims; the model mislabelled
            # the link. Clears both `missing_grounding` and its mirror image,
            # `evidence_unlinked_to_claim`.
            repaired = repaired.model_copy(update={"evidence_ids": expected})
            notes.append(_note("grounding_repaired", turn.turn_id))
        kept.append(repaired)

    if excise_ids:
        excised = set(excise_ids)
        remaining = [turn for turn in kept if turn.turn_id not in excised]
        affected = {turn.segment_id for turn in kept if turn.turn_id in excised}
        emptied = affected - _substantive_segment_ids(remaining)
        if emptied:
            # Editorial turns in a segment with nothing substantive left are
            # framing for a point that is no longer made. Drop the segment whole
            # rather than ship an introduction to nothing.
            remaining = [turn for turn in remaining if turn.segment_id not in emptied]
        if not remaining:
            # Rung 3, and the only one left. Reason 4 genuinely holds: there is
            # no artifact to degrade, so there is nothing to disclose either.
            # Rungs 1 and 2 do not apply because repair needs a ledger row to
            # repair against and excision has already taken everything.
            raise DeterministicValidationError(
                "No passage in this script could be linked to the evidence ledger.",
                stop_reason="integrity_breach",
            )
        notes.extend(_note("turn_excised", turn_id) for turn_id in excise_ids)

        target = episode_plan.estimated_duration_minutes
        minutes = _estimated_minutes(remaining, words_per_minute=words_per_minute)
        if target and minutes < target * _DURATION_FLOOR:
            # A shorter episode is shorter, not false, so this discloses rather
            # than stops. Whether the total degradation is still acceptable is
            # the degradation ceiling's call, not this function's.
            notes.append(
                _note("duration_shortfall", f"script:{minutes:.1f}/{target:.0f}min")
            )
        kept = remaining

    if notes:
        return script.model_copy(update={"turns": kept}), notes
    return script, notes
