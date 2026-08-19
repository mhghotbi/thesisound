from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from uuid import UUID

from thesisound import tracing
from thesisound.domain import ClaimRecord, ClaimType, EvidenceItem, SupportStatus
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.services.model_runner import ModelRunner
from thesisound.source_analysis import (
    BlockEvidenceExtraction,
    ClaimLedger,
    ClaimMergeDraft,
    ClaimReconciliationDraft,
)

_WHITESPACE = re.compile(r"\s+")
# Probe one batch before fan-out, matching DocumentMapperService: a dead provider
# must not be paid for once per batch when the first failure already aborts.
_PROBE_BATCHES = 1


class ClaimReconcilerService:
    def __init__(
        self,
        model_runner: ModelRunner,
        *,
        maximum_batch_characters: int = 60_000,
        max_workers: int = 1,
    ) -> None:
        if maximum_batch_characters < 1:
            raise ValueError("maximum_batch_characters must be positive.")
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1.")
        self.model_runner = model_runner
        self.maximum_batch_characters = maximum_batch_characters
        self.max_workers = max_workers

    def reconcile(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        extractions: list[BlockEvidenceExtraction],
        model: str,
        prompt_version: str | None = None,
        skip_model: bool = False,
    ) -> tuple[ClaimLedger, list[ModelRunRecord]]:
        evidence = [
            item
            for record in extractions
            for item in record.extraction.claims
        ]
        # Extraction 2.0 (10c P2 Step 1) folded definitions/distinctions/examples/
        # objections/responses/must_not_be_lost into claims by claim_type, so the
        # aux-list dedupe/collection this reconciler used to do is gone; ClaimLedger
        # keeps those fields only for artifacts written before the change.
        if not evidence:
            return (
                ClaimLedger(
                    source_id=source_id,
                    claims=[],
                    warnings=["No claim-bearing evidence was available for reconciliation."],
                ),
                [_empty_run_record(project_id, model)],
            )
        evidence_by_id = {item.evidence_id: item for item in evidence}
        if len(evidence_by_id) != len(evidence):
            raise ValueError("Evidence collection contains duplicate evidence IDs.")

        # Single-source projects cannot produce cross-source disagreement; skip the
        # model call and promote each evidence item to a claim 1:1.
        if skip_model:
            return (
                _passthrough_ledger(source_id, evidence),
                [_empty_run_record(project_id, model)],
            )

        batches = _partition_evidence(evidence, self.maximum_batch_characters)
        if len(batches) == 1:
            draft, record = self._reconcile_batch(
                project_id=project_id,
                source_id=source_id,
                evidence=evidence,
                model=model,
                prompt_version=prompt_version,
            )
            ledger = _materialize_ledger(source_id, draft, evidence_by_id)
            return ledger, [record]

        drafts, batch_records = self._reconcile_batches(
            project_id=project_id,
            source_id=source_id,
            batches=batches,
            model=model,
            prompt_version=prompt_version,
        )
        batch_claims: list[list[ClaimRecord]] = []
        unresolved: list[str] = []
        warnings: list[str] = []
        for batch, draft in zip(batches, drafts, strict=True):
            batch_by_id = {item.evidence_id: item for item in batch}
            batch_ledger = _materialize_ledger(source_id, draft, batch_by_id)
            batch_claims.append(batch_ledger.claims)
            unresolved.extend(batch_ledger.unresolved_evidence_ids)
            warnings.extend(batch_ledger.warnings)

        merge_draft, merge_record = self._merge_batches(
            project_id=project_id,
            source_id=source_id,
            batch_claims=batch_claims,
            model=model,
            prompt_version=prompt_version,
        )
        claims = _apply_merge_groups(source_id, batch_claims, merge_draft)
        warnings.extend(merge_draft.warnings)
        warnings.append(
            "Claims were reconciled across "
            f"{len(batches)} evidence batches; no evidence items were omitted."
        )
        return (
            ClaimLedger(
                source_id=source_id,
                claims=claims,
                unresolved_evidence_ids=list(dict.fromkeys(unresolved)),
                warnings=warnings,
            ),
            [*batch_records, merge_record],
        )

    def _reconcile_batches(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        batches: list[list[EvidenceItem]],
        model: str,
        prompt_version: str | None,
    ) -> tuple[list[ClaimReconciliationDraft], list[ModelRunRecord]]:
        drafts: list[ClaimReconciliationDraft | None] = [None] * len(batches)
        records: list[ModelRunRecord | None] = [None] * len(batches)

        def work(index: int) -> tuple[int, ClaimReconciliationDraft, ModelRunRecord]:
            draft, record = self._reconcile_batch(
                project_id=project_id,
                source_id=source_id,
                evidence=batches[index],
                model=model,
                prompt_version=prompt_version,
            )
            return index, draft, record

        workers = min(self.max_workers, len(batches))
        if workers <= 1:
            for index in range(len(batches)):
                _, draft, record = work(index)
                drafts[index] = draft
                records[index] = record
        else:
            self._fan_out_batches(work, list(range(len(batches))), workers, drafts, records)

        complete = [draft for draft in drafts if draft is not None]
        if len(complete) != len(batches):
            raise AssertionError("A claim-reconciliation batch finished without a draft.")
        return complete, [record for record in records if record is not None]

    def _fan_out_batches(
        self,
        work: Callable[[int], tuple[int, ClaimReconciliationDraft, ModelRunRecord]],
        pending: list[int],
        workers: int,
        drafts: list[ClaimReconciliationDraft | None],
        records: list[ModelRunRecord | None],
    ) -> None:
        """Probe one batch, then run the rest concurrently.

        Never more futures in flight than the pool has threads. The first failure
        observed is the one that propagates — a failed batch aborts the stage.
        """

        bound_work = tracing.bind_context(work)
        position = 0
        futures: set[Future[tuple[int, ClaimReconciliationDraft, ModelRunRecord]]] = set()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for _ in range(min(_PROBE_BATCHES, len(pending))):
                futures.add(pool.submit(bound_work, pending[position]))
                position += 1
            while futures:
                future = next(as_completed(futures))
                futures.discard(future)
                index, draft, record = future.result()
                drafts[index] = draft
                records[index] = record
                while len(futures) < workers and position < len(pending):
                    futures.add(pool.submit(bound_work, pending[position]))
                    position += 1

    def _reconcile_batch(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        evidence: list[EvidenceItem],
        model: str,
        prompt_version: str | None,
    ) -> tuple[ClaimReconciliationDraft, ModelRunRecord]:
        evidence_by_id = {item.evidence_id: item for item in evidence}
        variables = {
            "source_id": str(source_id),
            "evidence_items": [item.model_dump(mode="json") for item in evidence],
        }

        def validate(draft: ClaimReconciliationDraft) -> None:
            _validate_draft(draft, evidence_by_id)

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
        return execution.output, execution.record

    def _merge_batches(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        batch_claims: list[list[ClaimRecord]],
        model: str,
        prompt_version: str | None,
    ) -> tuple[ClaimMergeDraft, ModelRunRecord]:
        known = {
            claim.claim_id: claim for claims in batch_claims for claim in claims
        }
        variables = {
            "source_id": str(source_id),
            "batch_count": len(batch_claims),
            "claims": [
                {
                    "batch_index": index,
                    "claim_id": claim.claim_id,
                    "claim": claim.claim,
                    "claim_type": claim.claim_type.value,
                    "support_status": claim.support_status.value,
                    "qualifications": list(claim.qualifications),
                    "must_not_be_lost": claim.must_not_be_lost,
                    "term": claim.term,
                    "contrast": list(claim.contrast) if claim.contrast is not None else None,
                }
                for index, claims in enumerate(batch_claims, start=1)
                for claim in claims
            ],
        }

        def validate(draft: ClaimMergeDraft) -> None:
            _validate_merge_draft(
                draft,
                set(known),
                {claim_id: record.claim_type for claim_id, record in known.items()},
            )

        execution = self.model_runner.run(
            project_id=project_id,
            stage="claim_reconciliation_merge",
            prompt_name="claim_reconciliation_merge",
            variables=variables,
            output_type=ClaimMergeDraft,
            model=model,
            prompt_version=prompt_version,
            validator=validate,
        )
        return execution.output, execution.record


def _partition_evidence(
    evidence: list[EvidenceItem],
    maximum_characters: int,
) -> list[list[EvidenceItem]]:
    """Greedily pack evidence items under a serialized-character budget.

    Size is ``len(item.model_dump_json())`` — what actually enters the prompt.
    Order is preserved. When the whole list already fits, return it as one batch.
    A single item larger than the budget cannot be split without losing its
    locator/evidence identity, so that case fails loudly (same contract as
    document-map block partitioning).
    """

    sizes = [len(item.model_dump_json()) for item in evidence]
    total = sum(sizes)
    if total <= maximum_characters:
        return [evidence]

    batches: list[list[EvidenceItem]] = []
    current: list[EvidenceItem] = []
    current_size = 0
    for item, size in zip(evidence, sizes, strict=True):
        if size > maximum_characters:
            raise ValueError(
                "An evidence item is larger than the claim-reconciliation batch "
                f"budget. Evidence {item.evidence_id} serializes to {size:,} "
                "characters; shorten its excerpt or raise "
                "maximum_batch_characters before reconciling."
            )
        if current and current_size + size > maximum_characters:
            batches.append(current)
            current = []
            current_size = 0
        current.append(item)
        current_size += size
    if current:
        batches.append(current)

    flattened_ids = {item.evidence_id for batch in batches for item in batch}
    expected_ids = {item.evidence_id for item in evidence}
    if flattened_ids != expected_ids:
        raise AssertionError(
            "Evidence partitioning changed coverage (dropped, duplicated, or "
            "double-counted an evidence ID)."
        )
    return batches


def _validate_draft(
    draft: ClaimReconciliationDraft,
    evidence_by_id: dict[str, EvidenceItem],
) -> None:
    evidence_ids = set(evidence_by_id)
    referenced: list[str] = []
    normalized_claims: set[str] = set()
    for claim in draft.claims:
        unknown = set(claim.evidence_ids) - evidence_ids
        if unknown:
            raise DeterministicValidationError(
                "Claim referenced unknown evidence IDs: "
                f"{', '.join(sorted(unknown))}."
            )
        cited_types = {evidence_by_id[evidence_id].claim_type for evidence_id in claim.evidence_ids}
        if len(cited_types) > 1:
            raise DeterministicValidationError(
                "Reconciled claims must not merge evidence of different claim_type "
                f"(got: {', '.join(sorted(item.value for item in cited_types))})."
            )
        only_type = next(iter(cited_types))
        if claim.claim_type != only_type:
            raise DeterministicValidationError(
                "Reconciled claim_type must match the cited evidence "
                f"(claim is {claim.claim_type.value}, evidence is {only_type.value})."
            )
        normalized = _normalize(claim.claim).casefold()
        if normalized in normalized_claims:
            # Embed the duplicate text so identical_repair fingerprints differ.
            raise DeterministicValidationError(
                "Reconciled claims must not be duplicates "
                f"(got: {claim.claim[:80]!r})."
            )
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


def _validate_merge_draft(
    draft: ClaimMergeDraft,
    known_ids: set[str],
    claim_types: dict[str, ClaimType] | None = None,
) -> None:
    seen: set[str] = set()
    for group in draft.merge_groups:
        if group.canonical_claim_id not in group.claim_ids:
            raise DeterministicValidationError(
                "canonical_claim_id must be one of the group's claim_ids "
                f"(got {group.canonical_claim_id!r})."
            )
        group_types: set[ClaimType] = set()
        for claim_id in group.claim_ids:
            if claim_id not in known_ids:
                raise DeterministicValidationError(
                    f"Merge group referenced unknown claim ID: {claim_id}."
                )
            if claim_id in seen:
                raise DeterministicValidationError(
                    f"Claim ID appears in more than one merge group: {claim_id}."
                )
            seen.add(claim_id)
            if claim_types is not None and claim_id in claim_types:
                group_types.add(claim_types[claim_id])
        if len(group_types) > 1:
            raise DeterministicValidationError(
                "Merge groups must not mix claim_type "
                f"(got: {', '.join(sorted(item.value for item in group_types))})."
            )


def _apply_merge_groups(
    source_id: UUID,
    batch_claims: list[list[ClaimRecord]],
    draft: ClaimMergeDraft,
) -> list[ClaimRecord]:
    """Keep the canonical member's text; union evidence, qualifications, and flags."""

    ordered: list[ClaimRecord] = [claim for claims in batch_claims for claim in claims]
    by_id = {claim.claim_id: claim for claim in ordered}
    merged_away: set[str] = set()
    result: list[ClaimRecord] = []

    for group in draft.merge_groups:
        members = [by_id[claim_id] for claim_id in group.claim_ids]
        members_in_order = sorted(
            members,
            key=lambda claim: next(
                index for index, item in enumerate(ordered) if item.claim_id == claim.claim_id
            ),
        )
        canonical = by_id[group.canonical_claim_id]
        carry_order = [
            canonical,
            *[
                member
                for member in members_in_order
                if member.claim_id != canonical.claim_id
            ],
        ]
        evidence_ids = list(
            dict.fromkeys(
                evidence_id for claim in carry_order for evidence_id in claim.evidence_ids
            )
        )
        agreeing = sorted(
            {
                source
                for claim in carry_order
                for source in claim.agreeing_source_ids
            },
            key=str,
        )
        result.append(
            ClaimRecord(
                claim_id=_claim_id(source_id, canonical.claim, evidence_ids),
                claim=canonical.claim,
                claim_type=canonical.claim_type,
                evidence_ids=evidence_ids,
                support_status=canonical.support_status,
                qualifications=_unique_in_order(
                    qualification
                    for claim in carry_order
                    for qualification in claim.qualifications
                ),
                agreeing_source_ids=agreeing,
                disagreeing_source_ids=[],
                must_not_be_lost=any(member.must_not_be_lost for member in carry_order),
                term=_first_present(member.term for member in carry_order),
                contrast=_first_present(member.contrast for member in carry_order),
            )
        )
        merged_away.update(group.claim_ids)

    for claim in ordered:
        if claim.claim_id not in merged_away:
            result.append(claim)
    return result


def _materialize_ledger(
    source_id: UUID,
    draft: ClaimReconciliationDraft,
    evidence_by_id: dict[str, EvidenceItem],
) -> ClaimLedger:
    claims: list[ClaimRecord] = []
    for item in draft.claims:
        evidence_ids = list(dict.fromkeys(item.evidence_ids))
        cited = [evidence_by_id[evidence_id] for evidence_id in evidence_ids]
        source_ids = sorted({record.source_id for record in cited}, key=str)
        claims.append(
            ClaimRecord(
                claim_id=_claim_id(source_id, item.claim, evidence_ids),
                claim=item.claim.strip(),
                claim_type=item.claim_type,
                evidence_ids=evidence_ids,
                support_status=item.support_status,
                qualifications=_unique_in_order(
                    [
                        *item.qualifications,
                        *(
                            qualification
                            for record in cited
                            for qualification in record.qualifications
                        ),
                    ]
                ),
                agreeing_source_ids=source_ids,
                disagreeing_source_ids=[],
                must_not_be_lost=item.must_not_be_lost
                or any(record.must_not_be_lost for record in cited),
                term=item.term or _first_present(record.term for record in cited),
                contrast=item.contrast or _first_present(record.contrast for record in cited),
            )
        )
    return ClaimLedger(
        source_id=source_id,
        claims=claims,
        unresolved_evidence_ids=list(dict.fromkeys(draft.unresolved_evidence_ids)),
        warnings=draft.warnings,
    )


def _passthrough_ledger(
    source_id: UUID,
    evidence: list[EvidenceItem],
) -> ClaimLedger:
    claims = [
        ClaimRecord(
            claim_id=_claim_id(source_id, item.claim, [item.evidence_id]),
            claim=item.claim.strip(),
            claim_type=item.claim_type,
            evidence_ids=[item.evidence_id],
            support_status=_support_status_from_evidence(item),
            qualifications=list(item.qualifications),
            agreeing_source_ids=[item.source_id],
            disagreeing_source_ids=[],
            must_not_be_lost=item.must_not_be_lost,
            term=item.term,
            contrast=item.contrast,
        )
        for item in evidence
    ]
    return ClaimLedger(
        source_id=source_id,
        claims=claims,
        warnings=["Claim reconciliation skipped for single-source project."],
    )


def _support_status_from_evidence(item: EvidenceItem) -> SupportStatus:
    if item.support_kind == "inferential":
        return SupportStatus.MODERATE
    if item.confidence >= 0.75:
        return SupportStatus.STRONG
    if item.confidence >= 0.4:
        return SupportStatus.MODERATE
    return SupportStatus.UNCERTAIN


def _claim_id(source_id: UUID, claim: str, evidence_ids: list[str]) -> str:
    payload = "\x1f".join(
        [str(source_id), _normalize(claim), *sorted(evidence_ids)]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"clm-{digest}"


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _unique_in_order(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _first_present[T](values: Iterable[T]) -> T | None:
    for value in values:
        if value is not None:
            return value
    return None


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
