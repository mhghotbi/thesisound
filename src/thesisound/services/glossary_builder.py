from __future__ import annotations

from uuid import UUID

from thesisound.domain import EpisodePlan, GlossaryTerm, ResearchBrief
from thesisound.episode import DisagreementGraph, SegmentEvidencePack
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.script import Glossary, GlossaryDraft
from thesisound.services.model_runner import ModelRunner


class GlossaryBuilderService:
    def __init__(self, model_runner: ModelRunner) -> None:
        self.model_runner = model_runner

    def build(
        self,
        *,
        project_id: UUID,
        brief: ResearchBrief,
        episode_plan: EpisodePlan,
        evidence_packs: list[SegmentEvidencePack],
        disagreement_graph: DisagreementGraph,
        model: str,
        prompt_version: str | None = None,
    ) -> tuple[Glossary, ModelRunRecord]:
        execution = self.model_runner.run(
            project_id=project_id,
            stage="glossary",
            prompt_name="glossary",
            variables={
                "research_brief": brief.model_dump(mode="json"),
                "episode_plan": episode_plan.model_dump(mode="json"),
                "evidence_packs": [pack.model_dump(mode="json") for pack in evidence_packs],
                "disagreement_graph": disagreement_graph.model_dump(mode="json"),
            },
            output_type=GlossaryDraft,
            model=model,
            prompt_version=prompt_version,
            validator=_validate_glossary,
        )
        glossary = Glossary(
            project_id=project_id,
            terms=[GlossaryTerm(**term.model_dump()) for term in execution.output.terms],
            warnings=execution.output.warnings,
            model_run_id=execution.record.run_id,
        )
        return glossary, execution.record


def _validate_glossary(draft: GlossaryDraft) -> None:
    source_terms = [term.source_term.casefold().strip() for term in draft.terms]
    if len(source_terms) != len(set(source_terms)):
        raise DeterministicValidationError("Glossary contains duplicate source terms.")
    preferred = [term.preferred_persian.strip() for term in draft.terms]
    if any(not item for item in preferred):
        raise DeterministicValidationError("Glossary terms require non-empty Persian forms.")
