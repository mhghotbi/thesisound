"""Read-only prediction: will a duration change force evidence re-extraction?"""

from __future__ import annotations

from uuid import UUID

from thesisound.domain import Project, ResearchBrief
from thesisound.services.analysis_profile import plan_evidence_extraction
from thesisound.services.evidence_scope import extraction_profiles_compatible
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import EvidenceExtractionPlan

DURATION_COST_CHEAP = (
    "طرح فعلی دوباره ساخته می‌شود. تحلیل منابع دست‌نخورده می‌ماند"
    " و ممیزی کفایت هم دوباره هزینه نمی‌شود."
)
DURATION_COST_EXPENSIVE = (
    "برای این مدت، منابع باید عمیق‌تر کاویده شوند؛"
    " این کار زمان‌برتر است و کفایت منابع دوباره سنجیده می‌شود."
)
DURATION_COST_CHEAP_BLOCKED = (
    "تحلیل منابع دست‌نخورده می‌ماند و ممیزی کفایت هم دوباره هزینه نمی‌شود."
)


def duration_cost_hint(*, reextraction_required: bool, blocked: bool = False) -> str:
    if reextraction_required:
        return DURATION_COST_EXPENSIVE
    if blocked:
        return DURATION_COST_CHEAP_BLOCKED
    return DURATION_COST_CHEAP


def source_needs_reextraction(
    stored_plan: EvidenceExtractionPlan | None,
    planned: EvidenceExtractionPlan,
) -> bool:
    """Same early-return predicate as ``sync_to_current_profile`` (no I/O)."""

    if stored_plan is None:
        return True
    return not (
        extraction_profiles_compatible(stored_plan.profile, planned.profile)
        and stored_plan.selected_block_ids == planned.selected_block_ids
    )


def brief_with_duration(brief: ResearchBrief, duration_minutes: int) -> ResearchBrief:
    return brief.model_copy(update={"target_duration_minutes": duration_minutes})


def reextraction_required_for_duration(
    project: Project,
    source_store: SourceArtifactStore,
    duration_minutes: int,
) -> bool:
    """True when any claim-ready source would re-extract under ``duration_minutes``.

    Mirrors ``SourceAnalysisService.sync_to_current_profile`` compatibility checks
    without writing or calling models.
    """

    if project.brief is None:
        return False
    brief = brief_with_duration(project.brief, duration_minutes)
    claim_ready = set(source_store.list_claim_ready_source_ids(project.project_id))
    source_ids = [
        source.source_id for source in project.sources if source.usable_as_evidence
    ]
    if not source_ids:
        source_ids = list(claim_ready)
    for source_id in source_ids:
        if source_id not in claim_ready:
            continue
        if _source_would_reextract(project.project_id, source_id, brief, source_store):
            return True
    return False


def _source_would_reextract(
    project_id: UUID,
    source_id: UUID,
    brief: ResearchBrief,
    source_store: SourceArtifactStore,
) -> bool:
    try:
        blocks = source_store.load_blocks(project_id, source_id)
        document_map = source_store.load_document_map(project_id, source_id)
    except (OSError, ValueError):
        return True
    planned = plan_evidence_extraction(brief, document_map, blocks)
    try:
        stored_plan = source_store.load_extraction_plan(project_id, source_id)
    except (OSError, ValueError):
        stored_plan = None
    return source_needs_reextraction(stored_plan, planned)
