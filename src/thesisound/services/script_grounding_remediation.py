"""Pre-check grounding remediation (spec 09 D3 repair / excise / stop ladder)."""

from __future__ import annotations

import re

from thesisound.domain import ClaimRecord, EpisodePlan, Script, ScriptTurn
from thesisound.modeling import DeterministicValidationError
from thesisound.script import QualityNote
from thesisound.services.quality_notes import make_quality_note

_WORD = re.compile(r"\w+", re.UNICODE)


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


def remediate_script_grounding(
    script: Script,
    claims: list[ClaimRecord],
    *,
    episode_plan: EpisodePlan,
    words_per_minute: int = 130,
) -> tuple[Script, list[QualityNote]]:
    """Apply D3 ladder: repair mislinked evidence, excise ungroundable turns, or stop."""

    claim_by_id = {claim.claim_id: claim for claim in claims}
    notes: list[QualityNote] = []
    repaired_turns: list[ScriptTurn] = []
    excise_ids: list[str] = []

    for turn in script.turns:
        if turn.editorial_only:
            repaired_turns.append(turn)
            continue

        known_claims = [
            claim_by_id[claim_id] for claim_id in turn.claim_ids if claim_id in claim_by_id
        ]
        for claim in known_claims:
            if not claim.evidence_ids:
                # Rung 3: nothing to relink; excision would hide an upstream ledger fault.
                raise DeterministicValidationError(
                    "A spoken passage cites a point that has no supporting evidence in the "
                    "ledger. Add evidence for that point, or remove it from the episode plan.",
                    stop_reason="integrity_breach",
                )

        if not known_claims:
            # Rung 2 candidate: no ledger row to repair against.
            excise_ids.append(turn.turn_id)
            repaired_turns.append(turn)
            continue

        expected_evidence = set(_provenance_evidence_ids(turn.claim_ids, claim_by_id))
        turn_evidence = set(turn.evidence_ids)
        needs_repair = bool(expected_evidence) and (
            not (turn_evidence & expected_evidence) or bool(turn_evidence - expected_evidence)
        )
        if needs_repair:
            # Rung 1: grounding exists on the claims; the model mislabelled the link.
            repaired = turn.model_copy(
                update={"evidence_ids": _provenance_evidence_ids(turn.claim_ids, claim_by_id)}
            )
            repaired_turns.append(repaired)
            notes.append(
                make_quality_note(
                    stage="script_grounding",
                    kind="grounding_repaired",
                    subject=turn.turn_id,
                )
            )
        else:
            repaired_turns.append(turn)

    if excise_ids:
        remaining = [turn for turn in repaired_turns if turn.turn_id not in set(excise_ids)]
        affected_segments = {
            turn.segment_id for turn in repaired_turns if turn.turn_id in set(excise_ids)
        }
        remaining_substantive = _substantive_segment_ids(remaining)
        emptied = affected_segments - remaining_substantive
        target = episode_plan.estimated_duration_minutes
        post_minutes = _estimated_minutes(remaining, words_per_minute=words_per_minute)
        under_duration = bool(target) and post_minutes < target * 0.8
        if emptied or under_duration or not remaining:
            # Rung 3: excision would leave a segment with no substance, hollow the
            # duration band, or empty the script — unsafe.
            raise DeterministicValidationError(
                "One or more passages could not be grounded, and removing them would "
                "leave the episode incomplete. Regenerate those passages or narrow the plan.",
                stop_reason="integrity_breach",
            )
        repaired_turns = remaining
        notes.extend(
            make_quality_note(
                stage="script_grounding",
                kind="turn_excised",
                subject=turn_id,
            )
            for turn_id in excise_ids
        )

    if notes or excise_ids:
        return script.model_copy(update={"turns": repaired_turns}), notes
    return script, notes
