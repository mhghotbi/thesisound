from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from thesisound.domain import EpisodeSegment, ResearchBrief, ScriptTurn
from thesisound.episode import DisagreementGraph, SegmentEvidencePack
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.script import Glossary, ProseLessonDraft
from thesisound.services.model_runner import ModelRunner


@dataclass(frozen=True, slots=True)
class SegmentProseWriteResult:
    turns: list[ScriptTurn]
    draft: ProseLessonDraft
    record: ModelRunRecord


class PersianLessonProseWriterService:
    """Writes one segment as single-narrator Persian prose (`delivery == text`).

    Paragraphs are stored as `ScriptTurn`s (speaker fixed to "A", `heading_level`
    carried through) so the rest of the script pipeline -- checks, verification,
    revision, remediation -- runs unchanged over the same `Script` model.
    """

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
        segment_index: int = 1,
        segment_count: int = 1,
    ) -> SegmentProseWriteResult:
        allowed_claims = set(segment.claim_ids)
        allowed_evidence = {item.evidence_id for item in evidence_pack.evidence_items}
        execution = self.model_runner.run(
            project_id=project_id,
            stage=f"lesson_prose_segment:{segment.segment_id}",
            prompt_name="persian_lesson_prose",
            variables={
                "research_brief": brief.model_dump(mode="json"),
                "segment": segment.model_dump(mode="json"),
                "claims": [claim.model_dump(mode="json") for claim in evidence_pack.claims],
                "known_concepts": [],
                "evidence_pack": evidence_pack.model_dump(mode="json"),
                "glossary": glossary.model_dump(mode="json"),
                "disagreement_graph": disagreement_graph.model_dump(mode="json"),
                "target_word_count": round(segment.estimated_minutes * 160),
                "segment_index": segment_index,
                "segment_count": segment_count,
                "part_index": 1,
                "part_count": 1,
            },
            output_type=ProseLessonDraft,
            model=model,
            prompt_version=prompt_version,
            validator=lambda draft: _validate_prose_draft(
                draft,
                allowed_claim_ids=allowed_claims,
                allowed_evidence_ids=allowed_evidence,
            ),
        )
        turns = [
            ScriptTurn(
                turn_id=f"{segment.segment_id}-turn-{index:03d}",
                segment_id=segment.segment_id,
                speaker="A",
                spoken_text_fa=paragraph.text_fa.strip(),
                claim_ids=paragraph.claim_ids,
                evidence_ids=paragraph.evidence_ids,
                editorial_only=paragraph.editorial_only,
                heading_level=paragraph.heading_level,
            )
            for index, paragraph in enumerate(execution.output.paragraphs, start=1)
        ]
        return SegmentProseWriteResult(
            turns=turns,
            draft=execution.output,
            record=execution.record,
        )


def _validate_prose_draft(
    draft: ProseLessonDraft,
    *,
    allowed_claim_ids: set[str],
    allowed_evidence_ids: set[str],
) -> None:
    if not draft.paragraphs:
        raise DeterministicValidationError("Segment prose contains no paragraphs.")
    for index, paragraph in enumerate(draft.paragraphs, start=1):
        unknown_claims = sorted(set(paragraph.claim_ids) - allowed_claim_ids)
        if unknown_claims:
            raise DeterministicValidationError(
                f"Paragraph {index} uses claims outside the segment: {', '.join(unknown_claims)}"
            )
        unknown_evidence = sorted(set(paragraph.evidence_ids) - allowed_evidence_ids)
        if unknown_evidence:
            raise DeterministicValidationError(
                f"Paragraph {index} uses evidence outside the pack: {', '.join(unknown_evidence)}"
            )
        if paragraph.editorial_only and (paragraph.claim_ids or paragraph.evidence_ids):
            raise DeterministicValidationError(
                f"Editorial paragraph {index} must not carry claim or evidence IDs."
            )
