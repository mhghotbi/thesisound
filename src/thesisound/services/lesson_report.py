"""The `source_coverage` completion report (`10b` B1.1; `10c` P3 Step 11)."""

from __future__ import annotations

import contextlib
from uuid import UUID

from thesisound.concepts import ConceptCell, SourceConceptMap
from thesisound.domain import EpisodePlan, LessonIntent, Project
from thesisound.episode import (
    CellReportItem,
    LessonReport,
    NotCoveredCellItem,
    NotCoveredReason,
    OmittedCellItem,
    PartReportItem,
    StageCostItem,
)
from thesisound.observability import ObservabilityLedger
from thesisound.services.cell_selection import SelectedCell, select_cells
from thesisound.services.claim_cell_linkage import (
    CellCoverage,
    cell_coverage_levels,
    link_claims_to_cells,
)
from thesisound.services.concept_map_overlay import effective_concept_map
from thesisound.services.cost_estimate import estimate as estimate_cost
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import EvidenceExtractionPlan

# Same threshold `10b` B5.2 C2 names for the (not yet gated) tier-1
# `thin_extraction` signal; used here for report-only classification.
THIN_EXTRACTION_THRESHOLD = 0.35


class LessonReportBuilder:
    def __init__(
        self,
        *,
        source_store: SourceArtifactStore,
        episode_store: EpisodeArtifactStore,
        ledger: ObservabilityLedger | None = None,
    ) -> None:
        self.source_store = source_store
        self.episode_store = episode_store
        self.ledger = ledger

    def build(self, project_id: UUID, project: Project) -> LessonReport:
        if project.lesson_intent != LessonIntent.SOURCE_COVERAGE:
            return LessonReport(project_id=project_id)

        if project.scope is not None:
            source_id = project.scope.source_id
        else:
            claim_ready = self.source_store.list_claim_ready_source_ids(project_id)
            if not claim_ready:
                raise ValueError("No claim-ready source to report on.")
            source_id = claim_ready[0]

        concept_map = effective_concept_map(self.source_store, project_id, source_id)
        if concept_map is None:
            raise ValueError("source_coverage reporting requires a built concept map.")
        in_scope, omitted = select_cells(concept_map, project.scope, project.compression)
        in_scope_cells = [item.cell for item in in_scope]
        reason_by_cell_key = {item.cell.cell_key: item.in_scope_reason for item in in_scope}

        source_ledger = self.source_store.load_claim_ledger(project_id, source_id)
        evidence_items = self.source_store.load_evidence_items(project_id, source_id)
        extraction_plan = None
        with contextlib.suppress(OSError, ValueError):
            extraction_plan = self.source_store.load_extraction_plan(project_id, source_id)

        claim_to_cells = link_claims_to_cells(source_ledger.claims, evidence_items, in_scope_cells)
        plan = self.episode_store.load_plan(project_id) if project.episode_plan else None
        coverage = cell_coverage_levels(
            in_scope_cells, claim_to_cells, plan=plan, script=project.script
        )

        cells_covered = [
            CellReportItem(
                cell_key=cell.cell_key,
                label_fa=cell.label_fa,
                tier=cell.tier,
                in_scope_reason=reason_by_cell_key[cell.cell_key],
                coverage_level=coverage[cell.cell_key].level,
            )
            for cell in in_scope_cells
        ]
        not_covered = [
            NotCoveredCellItem(
                cell_key=cell.cell_key,
                label_fa=cell.label_fa,
                tier=cell.tier,
                reason=self._not_covered_reason(cell, coverage[cell.cell_key], extraction_plan),
            )
            for cell in in_scope_cells
            if coverage[cell.cell_key].level is None
        ]
        omitted_by_compression = [
            OmittedCellItem(cell_key=cell.cell_key, label_fa=cell.label_fa, tier=cell.tier)
            for cell in omitted
        ]

        must_not_be_lost = None
        with contextlib.suppress(OSError, ValueError):
            must_not_be_lost = self.episode_store.load_must_not_be_lost_review(project_id)

        parts = self._part_items(project, plan)
        cost_by_stage, pricing_version, price_status = self._cost_by_stage(
            project_id, project, concept_map, in_scope
        )

        return LessonReport(
            project_id=project_id,
            parts=parts,
            cells_covered=cells_covered,
            omitted_by_compression=omitted_by_compression,
            not_covered=not_covered,
            must_not_be_lost=must_not_be_lost,
            cost_by_stage=cost_by_stage,
            pricing_version=pricing_version,
            price_status=price_status,
        )

    @staticmethod
    def _part_items(project: Project, plan: EpisodePlan | None) -> list[PartReportItem]:
        if plan is None:
            return []
        target = float(project.episode_target_minutes)
        return [
            PartReportItem(
                part_index=part.part_index,
                title_fa=part.title_fa,
                target_minutes=target,
                estimated_minutes=part.estimated_minutes,
                graph_backed=part.graph_backed,
                flags=part.flags,
            )
            for part in plan.parts
        ]

    @staticmethod
    def _not_covered_reason(
        cell: ConceptCell,
        coverage: CellCoverage,
        extraction_plan: EvidenceExtractionPlan | None,
    ) -> NotCoveredReason:
        if not coverage.extracted:
            if extraction_plan is not None and extraction_plan.excerpt_char_coverage:
                values = [
                    extraction_plan.excerpt_char_coverage[block_id]
                    for block_id in cell.block_ids
                    if block_id in extraction_plan.excerpt_char_coverage
                ]
                if values and (sum(values) / len(values)) < THIN_EXTRACTION_THRESHOLD:
                    return "thin_extraction"
            return "no_claim"
        return "planned_but_excised"

    def _cost_by_stage(
        self,
        project_id: UUID,
        project: Project,
        concept_map: SourceConceptMap,
        in_scope: list[SelectedCell],
    ) -> tuple[list[StageCostItem], str | None, str | None]:
        estimate = estimate_cost(project, concept_map, in_scope)
        actual_by_stage: dict[str, int] = {}
        if self.ledger is not None:
            for call in self.ledger.list_calls(project_id, include_synthetic=False, limit=2_000):
                if call.cost_micros is None:
                    continue
                actual_by_stage[call.stage] = actual_by_stage.get(call.stage, 0) + call.cost_micros
        stages = estimate.cost_micros_by_stage or {}
        items = [
            StageCostItem(
                stage=stage,
                estimated_input_tokens=tokens,
                estimated_cost_micros=stages.get(stage),
                actual_cost_micros=actual_by_stage.get(stage),
            )
            for stage, tokens in estimate.input_tokens.items()
            if stage != "total"
        ]
        return items, estimate.pricing_version, estimate.price_status
