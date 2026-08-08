from __future__ import annotations

from uuid import UUID

from thesisound.domain import EpisodeSegment, ResearchBrief, ScriptTurn
from thesisound.episode import DisagreementGraph, SegmentEvidencePack
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.script import Glossary, SegmentScriptDraft
from thesisound.services.model_runner import ModelRunner


class PersianScriptWriterService:
    def __init__(self, model_runner: ModelRunner) -> None:
        self.model_runner = model_runner

    def write_segment(
        self,
        *,
        project_id: UUID,
        brief: ResearchBrief,
        segment: EpisodeSegment,
        evidence_pack: SegmentEvidencePack,
        glossary: Glossary,
        disagreement_graph: DisagreementGraph,
        model: str,
        prompt_version: str | None = None,
    ) -> tuple[list[ScriptTurn], SegmentScriptDraft, ModelRunRecord]:
        allowed_claims = set(segment.claim_ids)
        allowed_evidence = {item.evidence_id for item in evidence_pack.evidence_items}
        execution = self.model_runner.run(
            project_id=project_id,
            stage=f"script_segment:{segment.segment_id}",
            prompt_name="persian_script_segment",
            variables={
                "research_brief": brief.model_dump(mode="json"),
                "segment": segment.model_dump(mode="json"),
                "evidence_pack": evidence_pack.model_dump(mode="json"),
                "glossary": glossary.model_dump(mode="json"),
                "disagreement_graph": disagreement_graph.model_dump(mode="json"),
                "target_word_count": round(segment.estimated_minutes * 130),
            },
            output_type=SegmentScriptDraft,
            model=model,
            prompt_version=prompt_version,
            validator=lambda draft: _validate_segment_draft(
                draft,
                allowed_claim_ids=allowed_claims,
                allowed_evidence_ids=allowed_evidence,
            ),
        )
        turns = [
            ScriptTurn(
                turn_id=f"{segment.segment_id}-turn-{index:03d}",
                segment_id=segment.segment_id,
                speaker=turn.speaker,
                spoken_text_fa=turn.spoken_text_fa.strip(),
                claim_ids=turn.claim_ids,
                evidence_ids=turn.evidence_ids,
                editorial_only=turn.editorial_only,
            )
            for index, turn in enumerate(execution.output.turns, start=1)
        ]
        return turns, execution.output, execution.record


def _validate_segment_draft(
    draft: SegmentScriptDraft,
    *,
    allowed_claim_ids: set[str],
    allowed_evidence_ids: set[str],
) -> None:
    if not draft.turns:
        raise DeterministicValidationError("Segment script contains no turns.")
    for index, turn in enumerate(draft.turns, start=1):
        unknown_claims = sorted(set(turn.claim_ids) - allowed_claim_ids)
        if unknown_claims:
            raise DeterministicValidationError(
                f"Turn {index} uses claims outside the segment: {', '.join(unknown_claims)}"
            )
        unknown_evidence = sorted(set(turn.evidence_ids) - allowed_evidence_ids)
        if unknown_evidence:
            raise DeterministicValidationError(
                f"Turn {index} uses evidence outside the pack: {', '.join(unknown_evidence)}"
            )
        if turn.editorial_only and (turn.claim_ids or turn.evidence_ids):
            raise DeterministicValidationError(
                f"Editorial turn {index} must not carry claim or evidence IDs."
            )
