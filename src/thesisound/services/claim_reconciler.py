from __future__ import annotations

import hashlib
import re
from uuid import UUID

from thesisound.domain import ClaimRecord, EvidenceItem
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.services.model_runner import ModelRunner
from thesisound.source_analysis import (
    BlockEvidenceExtraction,
    ClaimLedger,
    ClaimReconciliationDraft,
)

_WHITESPACE = re.compile(r"\s+")


class ClaimReconcilerService:
    def __init__(self, model_runner: ModelRunner) -> None:
        self.model_runner = model_runner

    def reconcile(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        extractions: list[BlockEvidenceExtraction],
        model: str,
        prompt_version: str | None = None,
    ) -> tuple[ClaimLedger, ModelRunRecord]:
        evidence = [
            item
            for record in extractions
            for item in record.extraction.claims
        ]
        if not evidence:
            return (
                ClaimLedger(
                    source_id=source_id,
                    claims=[],
                    warnings=["No claim-bearing evidence was available for reconciliation."],
                ),
                _empty_run_record(project_id, model),
            )
        evidence_by_id = {item.evidence_id: item for item in evidence}
        if len(evidence_by_id) != len(evidence):
            raise ValueError("Evidence collection contains duplicate evidence IDs.")

        variables = {
            "source_id": str(source_id),
            "evidence_items": [item.model_dump(mode="json") for item in evidence],
        }

        def validate(draft: ClaimReconciliationDraft) -> None:
            _validate_draft(draft, set(evidence_by_id))

        execution = self.model_runner.run(
            project_id=project_id,
            stage="claim_reconciliation",
            prompt_name="claim_reconciliation",
            variables=variables,
            output_type=ClaimReconciliationDraft,
            model=model,
            prompt_version=prompt_version,
            validator=validate,
        )
        ledger = _materialize_ledger(source_id, execution.output, evidence_by_id)
        return ledger, execution.record


def _validate_draft(
    draft: ClaimReconciliationDraft,
    evidence_ids: set[str],
) -> None:
    referenced: list[str] = []
    normalized_claims: set[str] = set()
    for claim in draft.claims:
        unknown = set(claim.evidence_ids) - evidence_ids
        if unknown:
            raise DeterministicValidationError(
                "Claim referenced unknown evidence IDs: "
                f"{', '.join(sorted(unknown))}."
            )
        normalized = _normalize(claim.claim).casefold()
        if normalized in normalized_claims:
            raise DeterministicValidationError("Reconciled claims must not be duplicates.")
        normalized_claims.add(normalized)
        referenced.extend(claim.evidence_ids)

    unknown_unresolved = set(draft.unresolved_evidence_ids) - evidence_ids
    if unknown_unresolved:
        raise DeterministicValidationError(
            "unresolved_evidence_ids contains unknown IDs: "
            f"{', '.join(sorted(unknown_unresolved))}."
        )
    overlap = set(referenced) & set(draft.unresolved_evidence_ids)
    if overlap:
        raise DeterministicValidationError(
            "Evidence cannot be both claimed and unresolved: "
            f"{', '.join(sorted(overlap))}."
        )
    accounted_for = set(referenced) | set(draft.unresolved_evidence_ids)
    missing = evidence_ids - accounted_for
    if missing:
        raise DeterministicValidationError(
            "Every evidence item must be used or explicitly unresolved. Missing: "
            f"{', '.join(sorted(missing))}."
        )


def _materialize_ledger(
    source_id: UUID,
    draft: ClaimReconciliationDraft,
    evidence_by_id: dict[str, EvidenceItem],
) -> ClaimLedger:
    claims: list[ClaimRecord] = []
    for item in draft.claims:
        evidence_ids = list(dict.fromkeys(item.evidence_ids))
        source_ids = sorted(
            {evidence_by_id[evidence_id].source_id for evidence_id in evidence_ids},
            key=str,
        )
        claims.append(
            ClaimRecord(
                claim_id=_claim_id(source_id, item.claim, evidence_ids),
                claim=item.claim.strip(),
                claim_type=item.claim_type,
                evidence_ids=evidence_ids,
                support_status=item.support_status,
                qualifications=item.qualifications,
                agreeing_source_ids=source_ids,
                disagreeing_source_ids=[],
            )
        )
    return ClaimLedger(
        source_id=source_id,
        claims=claims,
        unresolved_evidence_ids=list(dict.fromkeys(draft.unresolved_evidence_ids)),
        warnings=draft.warnings,
    )


def _claim_id(source_id: UUID, claim: str, evidence_ids: list[str]) -> str:
    payload = "\x1f".join(
        [str(source_id), _normalize(claim), *sorted(evidence_ids)]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"clm-{digest}"


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _empty_run_record(project_id: UUID, model: str) -> ModelRunRecord:
    record = ModelRunRecord(
        project_id=project_id,
        stage="claim_reconciliation",
        prompt_id="claim_reconciliation",
        prompt_version="not-run",
        prompt_hash="",
        input_hash="",
        provider="none",
        model=model,
        output_model="ClaimReconciliationDraft",
        status="succeeded",
    )
    record.completed_at = record.started_at
    return record
