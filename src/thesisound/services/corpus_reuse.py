from __future__ import annotations

from pathlib import Path
from uuid import UUID

from thesisound.domain import Project
from thesisound.services.analysis_profile import (
    plan_evidence_extraction,
    resolve_extraction_seeds,
)
from thesisound.services.concept_map_overlay import effective_concept_map
from thesisound.services.lineage_events import emit_cache_lookup
from thesisound.services.semantic_identity import claim_reconciler_identity, first_mismatch
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import ClaimLedger

_RECONCILER_IDENTITY_FIELDS = (
    "model",
    "prompt_version",
    "reconciler_version",
    "extractor_version",
)


def reusable_claim_ledger(
    *,
    artifact_store: SourceArtifactStore,
    project: Project,
    source_id: UUID,
    ingestion_path: Path,
    model: str,
    prompt_version: str | None = None,
) -> ClaimLedger | None:
    """Return the stored ledger when rebuilding this source would repeat finished work.

    Three things have to still hold. The stored analysis must have finished
    (``claims_ready``) on the very same file, the ledger itself must be readable and
    belong to this source, and the current brief must still plan the same evidence
    extraction. A brief edit re-ranks and re-budgets blocks, so evidence extracted
    under the previous brief is no longer what this project would ask for.

    Semantic identity (reconciler model/prompt/versions) must also match; otherwise
    a model or prompt bump would silently reuse stale claims.

    The replan is seeded exactly like the real one (``resolve_extraction_seeds`` over
    the effective concept map). A ``source_coverage`` project selects blocks by
    in-scope cell, not by duration ranking; replanning it without the cells produced a
    duration-ranked plan that never matched the stored one, so a finished source was
    rebuilt from scratch on every confirm.

    Anything missing, unreadable or out of date returns ``None``, which means the
    source is queued and built from scratch.
    """

    project_id = project.project_id
    brief = project.brief
    current_identity = claim_reconciler_identity(
        model=model,
        prompt_version=prompt_version,
    )

    def _miss(reason: str | None = None) -> None:
        emit_cache_lookup(
            cache="claim_ledger",
            result="miss",
            project_id=project_id,
            subject_type="source",
            subject_id=str(source_id),
            invalidation_reason=reason,
        )
        return None

    if brief is None:
        return _miss("brief_missing")
    try:
        manifest = artifact_store.load_manifest(project_id, source_id)
    except (OSError, ValueError):
        return _miss()
    if manifest.status != "claims_ready":
        return _miss("status_not_ready")
    try:
        ingestion = artifact_store.load_ingestion(ingestion_path)
        if manifest.source_sha256 != ingestion.inspection.sha256:
            return _miss("source_hash_mismatch")
        ledger = artifact_store.load_claim_ledger(project_id, source_id)
        blocks = artifact_store.load_blocks(project_id, source_id)
        document_map = artifact_store.load_document_map(project_id, source_id)
        stored_plan = artifact_store.load_extraction_plan(project_id, source_id)
    except (OSError, ValueError):
        return _miss()
    if ledger.source_id != source_id:
        return _miss("source_id_mismatch")

    seed_cells, force_depth = resolve_extraction_seeds(
        project, effective_concept_map(artifact_store, project_id, source_id)
    )
    planned = plan_evidence_extraction(
        brief,
        document_map,
        blocks,
        seed_cells=seed_cells,
        force_depth=force_depth,
    )
    if planned.profile != stored_plan.profile:
        return _miss("profile_mismatch")
    if planned.selected_block_ids != stored_plan.selected_block_ids:
        return _miss("selected_blocks_mismatch")

    reason = first_mismatch(
        ledger.reconciler_identity,
        current_identity,
        _RECONCILER_IDENTITY_FIELDS,
    )
    if reason is not None:
        return _miss(reason)

    emit_cache_lookup(
        cache="claim_ledger",
        result="hit",
        project_id=project_id,
        subject_type="source",
        subject_id=str(source_id),
        avoided_calls=1,
    )
    return ledger
