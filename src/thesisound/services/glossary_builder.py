from __future__ import annotations

from uuid import UUID

from thesisound.concepts import ConceptCell
from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    EpisodePlan,
    ExtractedDefinition,
    GlossaryTerm,
    ResearchBrief,
)
from thesisound.episode import DisagreementGraph, SegmentEvidencePack
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.script import Glossary, GlossaryDraft
from thesisound.services.deterministic_glossary import build_deterministic_glossary
from thesisound.services.lineage_events import emit_cache_lookup
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
        definitions: list[ExtractedDefinition] | None = None,
        claims: list[ClaimRecord] | None = None,
        concept_cells: list[ConceptCell] | None = None,
        model: str,
        prompt_version: str | None = None,
    ) -> tuple[Glossary, ModelRunRecord]:
        """Build a glossary: deterministic always; model only when open decisions remain."""

        cells = concept_cells or []
        claim_list = claims or []
        deterministic = build_deterministic_glossary(
            project_id=project_id,
            definitions=definitions or [],
            evidence_packs=evidence_packs,
            claims=claim_list,
            concept_cells=cells,
            model=model,
        )
        if not deterministic.needs_model:
            emit_cache_lookup(
                cache="script_glossary",
                result="skip",
                project_id=project_id,
                avoided_calls=1,
                reason="no_open_glossary_decisions",
            )
            assert deterministic.run_record is not None
            return deterministic.glossary, deterministic.run_record

        definition_claims = [
            {
                "claim_id": claim.claim_id,
                "term": claim.term,
                "claim": claim.claim,
                "claim_type": claim.claim_type.value,
            }
            for claim in claim_list
            if claim.claim_type == ClaimType.DEFINITION
        ]
        cell_payload = [
            {
                "cell_key": cell.cell_key,
                "label_fa": cell.label_fa,
                "label_source": cell.label_source,
                "kind": cell.kind,
            }
            for cell in cells
        ]

        execution = self.model_runner.run(
            project_id=project_id,
            stage="glossary",
            prompt_name="glossary",
            variables={
                "research_brief": brief.model_dump(mode="json"),
                "episode_plan": episode_plan.model_dump(mode="json"),
                "evidence_packs": [pack.model_dump(mode="json") for pack in evidence_packs],
                "disagreement_graph": disagreement_graph.model_dump(mode="json"),
                "concept_cells": cell_payload,
                "definition_claims": definition_claims,
            },
            output_type=GlossaryDraft,
            model=model,
            prompt_version=prompt_version,
            validator=_validate_glossary,
        )
        glossary = Glossary(
            project_id=project_id,
            terms=[GlossaryTerm(**term.model_dump()) for term in execution.output.terms],
            warnings=list(execution.output.warnings) + list(deterministic.warnings),
            model_run_id=execution.record.run_id,
            build_kind="model",
            corpus_had_latin_tokens=deterministic.corpus_has_latin_tokens,
        )
        return glossary, execution.record


def _validate_glossary(draft: GlossaryDraft) -> None:
    source_terms = [term.source_term.casefold().strip() for term in draft.terms]
    if len(source_terms) != len(set(source_terms)):
        raise DeterministicValidationError("Glossary contains duplicate source terms.")
    preferred = [term.preferred_persian.strip() for term in draft.terms]
    if any(not item for item in preferred):
        raise DeterministicValidationError("Glossary terms require non-empty Persian forms.")
