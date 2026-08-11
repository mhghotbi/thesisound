from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from uuid import UUID

from thesisound.domain import (
    ClaimRecord,
    EvidenceItem,
    ExtractedAuxiliaryPoint,
    ExtractedDefinition,
    ExtractedDistinction,
    MustNotBeLostPoint,
)
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
        # Deduplicated deterministically, not by the reconciliation model call: none
        # of these categories need the judgment the model call exists for (merge vs.
        # keep-separate by attribution/scope/certainty). A block can have claims=[]
        # while still carrying real definitions/must_not_be_lost content, so this runs
        # regardless of whether `evidence` is empty -- see the early return below.
        definitions = _dedupe_definitions(
            item for record in extractions for item in record.extraction.definitions
        )
        distinctions = _dedupe_distinctions(
            item for record in extractions for item in record.extraction.distinctions
        )
        examples = _dedupe_points(
            item for record in extractions for item in record.extraction.examples
        )
        objections = _dedupe_points(
            item for record in extractions for item in record.extraction.objections
        )
        responses = _dedupe_points(
            item for record in extractions for item in record.extraction.responses
        )
        must_not_be_lost = _dedupe_must_not_be_lost(
            item for record in extractions for item in record.extraction.must_not_be_lost
        )
        if not evidence:
            return (
                ClaimLedger(
                    source_id=source_id,
                    claims=[],
                    warnings=["No claim-bearing evidence was available for reconciliation."],
                    definitions=definitions,
                    distinctions=distinctions,
                    examples=examples,
                    objections=objections,
                    responses=responses,
                    must_not_be_lost=must_not_be_lost,
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
        ledger = _materialize_ledger(
            source_id,
            execution.output,
            evidence_by_id,
            definitions=definitions,
            distinctions=distinctions,
            examples=examples,
            objections=objections,
            responses=responses,
            must_not_be_lost=must_not_be_lost,
        )
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
    *,
    definitions: list[ExtractedDefinition],
    distinctions: list[ExtractedDistinction],
    examples: list[ExtractedAuxiliaryPoint],
    objections: list[ExtractedAuxiliaryPoint],
    responses: list[ExtractedAuxiliaryPoint],
    must_not_be_lost: list[MustNotBeLostPoint],
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
        definitions=definitions,
        distinctions=distinctions,
        examples=examples,
        objections=objections,
        responses=responses,
        must_not_be_lost=must_not_be_lost,
    )


def _claim_id(source_id: UUID, claim: str, evidence_ids: list[str]) -> str:
    payload = "\x1f".join(
        [str(source_id), _normalize(claim), *sorted(evidence_ids)]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"clm-{digest}"


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _dedupe_definitions(
    items: Iterable[ExtractedDefinition],
) -> list[ExtractedDefinition]:
    """First-seen-wins on (term, definition).

    Two real definitions of the same term are kept side by side rather than
    collapsed -- only exact duplicates (e.g. neighbor-context bleed across
    blocks) are noise.
    """

    seen: set[tuple[str, str]] = set()
    kept: list[ExtractedDefinition] = []
    for item in items:
        key = (_normalize(item.term).casefold(), _normalize(item.definition).casefold())
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def _dedupe_distinctions(
    items: Iterable[ExtractedDistinction],
) -> list[ExtractedDistinction]:
    seen: set[tuple[str, str, str]] = set()
    kept: list[ExtractedDistinction] = []
    for item in items:
        key = (
            _normalize(item.item_a).casefold(),
            _normalize(item.item_b).casefold(),
            _normalize(item.distinction).casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def _dedupe_points(
    items: Iterable[ExtractedAuxiliaryPoint],
) -> list[ExtractedAuxiliaryPoint]:
    """Shared by examples/objections/responses: dedupe on text alone.

    Cross-block duplicate text is just noise here; the first occurrence's locator
    wins, matching the ``dict.fromkeys``-style dedup already used for evidence IDs.
    """

    seen: set[str] = set()
    kept: list[ExtractedAuxiliaryPoint] = []
    for item in items:
        key = _normalize(item.text).casefold()
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def _dedupe_must_not_be_lost(
    items: Iterable[MustNotBeLostPoint],
) -> list[MustNotBeLostPoint]:
    """Collapse only same-block repeats; cross-block recurrence stays visible.

    The same warning surfacing from two different blocks is provenance-meaningful
    for the must-not-be-lost review artifact, not noise to remove.
    """

    seen: set[tuple[str, str]] = set()
    kept: list[MustNotBeLostPoint] = []
    for item in items:
        key = (item.block_id, _normalize(item.text).casefold())
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


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
