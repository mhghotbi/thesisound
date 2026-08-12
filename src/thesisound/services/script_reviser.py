from __future__ import annotations

from uuid import UUID

from thesisound.domain import Script, ScriptTurn
from thesisound.episode import SegmentEvidencePack
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.script import (
    Glossary,
    QualityNote,
    ScriptCheckReport,
    TargetedRevisionDraft,
    VerificationDraft,
)
from thesisound.services.model_runner import ModelRunner
from thesisound.services.quality_notes import make_quality_note


class TargetedScriptReviserService:
    def __init__(self, model_runner: ModelRunner) -> None:
        self.model_runner = model_runner

    def revise(
        self,
        *,
        project_id: UUID,
        script: Script,
        checks: ScriptCheckReport,
        verification: VerificationDraft,
        evidence_packs: list[SegmentEvidencePack],
        glossary: Glossary,
        model: str,
        prompt_version: str | None = None,
    ) -> tuple[Script, TargetedRevisionDraft, ModelRunRecord, list[QualityNote]]:
        target_ids = _target_turn_ids(script, checks, verification)
        if not target_ids:
            raise ValueError("No turn-specific or global revision targets were found.")
        original_by_id = {turn.turn_id: turn for turn in script.turns}
        target_turns = [original_by_id[turn_id] for turn_id in target_ids]
        target_segments = {turn.segment_id for turn in target_turns}
        relevant_packs = [
            pack for pack in evidence_packs if pack.segment_id in target_segments
        ]
        notes: list[QualityNote] = []
        execution = self.model_runner.run(
            project_id=project_id,
            stage="script_reviser",
            prompt_name="script_reviser",
            variables={
                "target_turns": [turn.model_dump(mode="json") for turn in target_turns],
                "deterministic_issues": checks.model_dump(mode="json"),
                "verification_issues": verification.model_dump(mode="json"),
                "evidence_packs": [pack.model_dump(mode="json") for pack in relevant_packs],
                "glossary": glossary.model_dump(mode="json"),
            },
            output_type=TargetedRevisionDraft,
            model=model,
            prompt_version=prompt_version,
            validator=lambda draft: _validate_revision(
                draft,
                target_ids=target_ids,
                original_by_id=original_by_id,
                notes=notes,
            ),
        )
        revised_by_id = {turn.turn_id: turn for turn in execution.output.revised_turns}
        merged = Script(
            title=script.title,
            turns=[
                _materialize_revision(turn, revised_by_id.get(turn.turn_id))
                for turn in script.turns
            ],
            glossary_terms_used=script.glossary_terms_used,
        )
        return merged, execution.output, execution.record, notes


def _target_turn_ids(
    script: Script,
    checks: ScriptCheckReport,
    verification: VerificationDraft,
) -> list[str]:
    known = {turn.turn_id for turn in script.turns}
    target: set[str] = {issue.turn_id for issue in verification.issues}
    for issue in checks.issues:
        if issue.turn_id is not None:
            target.add(issue.turn_id)
        elif issue.segment_id is not None:
            target.update(
                turn.turn_id for turn in script.turns if turn.segment_id == issue.segment_id
            )
        elif issue.severity in {"high", "blocking"}:
            target.update(known)
    return [turn.turn_id for turn in script.turns if turn.turn_id in target]


def _validate_revision(
    draft: TargetedRevisionDraft,
    *,
    target_ids: list[str],
    original_by_id: dict[str, ScriptTurn],
    notes: list[QualityNote] | None = None,
) -> None:
    revised_ids = [turn.turn_id for turn in draft.revised_turns]
    if len(revised_ids) != len(set(revised_ids)):
        # Structural: duplicate turn IDs need model repair.
        raise DeterministicValidationError("Revision contains duplicate turn IDs.")
    if set(revised_ids) != set(target_ids):
        missing = sorted(set(target_ids) - set(revised_ids))
        extra = sorted(set(revised_ids) - set(target_ids))
        # Structural: reviser must return exactly the targeted set.
        raise DeterministicValidationError(
            f"Revision must return exactly targeted turns; missing={missing}, extra={extra}."
        )
    ungroundable_turn_ids: list[str] = []
    for revised in draft.revised_turns:
        original = original_by_id[revised.turn_id]
        if revised.speaker != original.speaker:
            # Structural: speaker identity is a consent/integrity contract.
            raise DeterministicValidationError(
                f"Revision changed speaker for turn {revised.turn_id}."
            )
        # Recoverable: drop invented IDs — keep real ones and the spoken text.
        original_claims = set(original.claim_ids)
        original_evidence = set(original.evidence_ids)
        kept_claims = [cid for cid in revised.claim_ids if cid in original_claims]
        kept_evidence = [eid for eid in revised.evidence_ids if eid in original_evidence]
        dropped_citation = kept_claims != list(revised.claim_ids) or kept_evidence != list(
            revised.evidence_ids
        )
        revised.claim_ids = kept_claims
        revised.evidence_ids = kept_evidence
        if not revised.editorial_only and (
            not revised.claim_ids or not revised.evidence_ids
        ):
            # Recoverable: drop this turn from the revision; _materialize_revision
            # falls back to the original grounded turn.
            ungroundable_turn_ids.append(revised.turn_id)
        elif dropped_citation and notes is not None:
            notes.append(
                make_quality_note(
                    stage="script_reviser",
                    kind="citation_dropped",
                    subject=revised.turn_id,
                )
            )
    if ungroundable_turn_ids:
        draft.revised_turns = [
            turn for turn in draft.revised_turns if turn.turn_id not in ungroundable_turn_ids
        ]
        if notes is not None:
            notes.extend(
                make_quality_note(
                    stage="script_reviser",
                    kind="turn_not_revised",
                    subject=turn_id,
                )
                for turn_id in ungroundable_turn_ids
            )


def _materialize_revision(
    original: ScriptTurn,
    revised,
) -> ScriptTurn:
    if revised is None:
        return original
    return ScriptTurn(
        turn_id=original.turn_id,
        segment_id=original.segment_id,
        speaker=revised.speaker,
        spoken_text_fa=revised.spoken_text_fa.strip(),
        claim_ids=revised.claim_ids,
        evidence_ids=revised.evidence_ids,
        editorial_only=revised.editorial_only,
    )
