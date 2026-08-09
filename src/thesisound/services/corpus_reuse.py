from __future__ import annotations

from pathlib import Path
from uuid import UUID

from thesisound.domain import ResearchBrief
from thesisound.services.analysis_profile import plan_evidence_extraction
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import ClaimLedger


def reusable_claim_ledger(
    *,
    artifact_store: SourceArtifactStore,
    project_id: UUID,
    source_id: UUID,
    ingestion_path: Path,
    brief: ResearchBrief | None,
) -> ClaimLedger | None:
    """Return the stored ledger when rebuilding this source would repeat finished work.

    Three things have to still hold. The stored analysis must have finished
    (``claims_ready``) on the very same file, the ledger itself must be readable and
    belong to this source, and the current brief must still plan the same evidence
    extraction. A brief edit re-ranks and re-budgets blocks, so evidence extracted
    under the previous brief is no longer what this project would ask for.

    Anything missing, unreadable or out of date returns ``None``, which means the
    source is queued and built from scratch.
    """

    if brief is None:
        return None
    try:
        manifest = artifact_store.load_manifest(project_id, source_id)
    except (OSError, ValueError):
        return None
    if manifest.status != "claims_ready":
        return None
    try:
        ingestion = artifact_store.load_ingestion(ingestion_path)
        if manifest.source_sha256 != ingestion.inspection.sha256:
            return None
        ledger = artifact_store.load_claim_ledger(project_id, source_id)
        blocks = artifact_store.load_blocks(project_id, source_id)
        document_map = artifact_store.load_document_map(project_id, source_id)
        stored_plan = artifact_store.load_extraction_plan(project_id, source_id)
    except (OSError, ValueError):
        return None
    if ledger.source_id != source_id:
        return None

    planned = plan_evidence_extraction(brief, document_map, blocks)
    if planned.profile != stored_plan.profile:
        return None
    if planned.selected_block_ids != stored_plan.selected_block_ids:
        return None
    return ledger
