from __future__ import annotations

from uuid import UUID

from thesisound.domain import Script, ScriptTurn
from thesisound.episode import SegmentEvidencePack
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.script import (
    Glossary,
    ScriptCheckReport,
    TargetedRevisionDraft,
    VerificationDraft,
)
from thesisound.services.model_runner import ModelRunner


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
    ) -> tuple[Script, TargetedRevisionDraft, ModelRunRecord]:
        target_ids = _target_turn_ids(script, checks, verification)
        if not target_ids:
            raise ValueError("No turn-specific or global revision targets were found.")
        original_by_id = {turn.turn_id: turn for turn in script.turns}
        target_turns = [original_by_id[turn_id] for turn_id in target_ids]
        target_segments = {turn.segment_id for turn in target_turns}
        relevant_packs = [
            pack for pack in evidence_packs if pack.segment_id in target_segments
        ]
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
        return merged, execution.output, execution.record


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
) -> None:
    revised_ids = [turn.turn_id for turn in draft.revised_turns]
    if len(revised_ids) != len(set(revised_ids)):
        raise DeterministicValidationError("Revision contains duplicate turn IDs.")
    if set(revised_ids) != set(target_ids):
        missing = sorted(set(target_ids) - set(revised_ids))
        extra = sorted(set(revised_ids) - set(target_ids))
        raise DeterministicValidationError(
            f"Revision must return exactly targeted turns; missing={missing}, extra={extra}."
        )
    for revised in draft.revised_turns:
        original = original_by_id[revised.turn_id]
        if revised.speaker != original.speaker:
            raise DeterministicValidationError(
                f"Revision changed speaker for turn {revised.turn_id}."
            )
        if not set(revised.claim_ids) <= set(original.claim_ids):
            raise DeterministicValidationError(
                f"Revision introduced new claim IDs in turn {revised.turn_id}."
            )
        if not set(revised.evidence_ids) <= set(original.evidence_ids):
            raise DeterministicValidationError(
                f"Revision introduced new evidence IDs in turn {revised.turn_id}."
            )
        if not revised.editorial_only and (
            not revised.claim_ids or not revised.evidence_ids
        ):
            raise DeterministicValidationError(
                f"Revised substantive turn {revised.turn_id} lost grounding."
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
