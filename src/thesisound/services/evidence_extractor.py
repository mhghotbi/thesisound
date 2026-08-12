from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from uuid import UUID

from thesisound import tracing
from thesisound.domain import (
    DocumentMap,
    DocumentMapSection,
    EvidenceExtraction,
    EvidenceItem,
    ExtractedAuxiliaryPoint,
    ExtractedDefinition,
    ExtractedDistinction,
    MustNotBeLostPoint,
)
from thesisound.modeling import (
    DeterministicValidationError,
    ModelProviderError,
    ModelRunRecord,
    ModelSafetyError,
    StructuredOutputError,
)
from thesisound.services.evidence_validator import validate_evidence_extraction
from thesisound.services.excerpt_matching import locate_excerpt
from thesisound.services.model_runner import ModelRunner
from thesisound.services.semantic_identity import evidence_extraction_identity
from thesisound.source_analysis import (
    AnalysisProfile,
    BatchEvidenceExtractionDraft,
    BlockEvidenceExtraction,
    EvidenceClaimDraft,
    EvidenceExtractionDraft,
    EvidenceExtractionPlan,
    SourceDocumentBlock,
)

_WHITESPACE = re.compile(r"\s+")
ExtractionCallback = Callable[[BlockEvidenceExtraction], None]
_DEFAULT_MAX_ATTEMPTS = 3
# A global provider failure looks like a per-block failure. Before any block has
# succeeded, probe at most this many blocks so a revoked key or dead endpoint
# aborts without paying for one call per remaining block.
_BREAKER_CONSECUTIVE_FAILURES = 3
# Cap the source text carried by one batch. Ordinary blocks fit the configured maximum;
# this only isolates pathological blocks so one truncated output cannot lose siblings.
_MAX_BATCH_SOURCE_TOKENS = 12_000


class ExcerptNotFoundError(DeterministicValidationError):
    """The excerpt is absent from the source block after normalisation."""


class EvidenceExtractorService:
    def __init__(
        self,
        model_runner: ModelRunner,
        *,
        max_workers: int = 1,
        batch_size: int = 1,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1.")
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1.")
        self.model_runner = model_runner
        self.max_workers = max_workers
        self.batch_size = batch_size

    def extract_source(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        blocks: list[SourceDocumentBlock],
        document_map: DocumentMap,
        model: str,
        plan: EvidenceExtractionPlan | None = None,
        prompt_version: str | None = None,
        on_extraction: ExtractionCallback | None = None,
        skip_block_ids: set[str] | None = None,
    ) -> tuple[list[BlockEvidenceExtraction], list[ModelRunRecord]]:
        if document_map.source_id != source_id:
            raise ValueError("Document map belongs to a different source.")
        if plan is not None and plan.source_id != source_id:
            raise ValueError("Evidence extraction plan belongs to a different source.")

        profile = plan.profile if plan is not None else _full_profile()
        selected_ids = (
            set(plan.selected_block_ids)
            if plan is not None
            else {block.block_id for block in blocks}
        )
        skip_ids = skip_block_ids or set()
        section_by_block = {
            block_id: section
            for section in document_map.sections
            for block_id in section.source_block_ids
        }
        index_by_id = {block.block_id: index for index, block in enumerate(blocks)}
        max_attempts = _evidence_max_attempts(self.model_runner, prompt_version)
        batch_prompt_version = _batch_prompt_version(self.model_runner, prompt_version)
        batch_max_attempts = _evidence_max_attempts(
            self.model_runner,
            batch_prompt_version,
            "evidence_extraction_batch",
        )

        pending = [
            block
            for block in blocks
            if block.block_type != "front_matter"
            and block.block_id in selected_ids
            and block.block_id not in skip_ids
        ]
        if not pending:
            return [], []

        units = _plan_units(pending, self.batch_size)
        results: dict[str, tuple[BlockEvidenceExtraction, ModelRunRecord | None]] = {}
        # A batch can successfully return empty entries for every block, causing all
        # blocks to fall back to single-block calls. Keep that billed batch run even
        # though no per-block outcome refers to it.
        batch_runs: list[ModelRunRecord] = []
        # Callers persist from `on_extraction`, so serialize the callback here rather than
        # asking every caller to be thread-safe. The model call itself stays outside it.
        handover = Lock()
        consecutive_skipped = 0
        succeeded = 0
        identity = evidence_extraction_identity(model=model, prompt_version=prompt_version)

        def any_block_succeeded() -> bool:
            with handover:
                return succeeded > 0

        def work(
            unit: list[SourceDocumentBlock],
        ) -> tuple[
            list[tuple[str, tuple[BlockEvidenceExtraction, ModelRunRecord | None]]],
            list[ModelRunRecord],
        ]:
            if len(unit) == 1:
                block = unit[0]
                with tracing.span(
                    "corpus.extract_evidence",
                    component="corpus",
                    subject_type="block",
                    subject_id=block.block_id,
                    detail="verbose",
                ):
                    outcome = self._extract_block(
                        project_id=project_id,
                        source_id=source_id,
                        block=block,
                        section=section_by_block.get(block.block_id),
                        blocks=blocks,
                        index_by_id=index_by_id,
                        document_map=document_map,
                        profile=profile,
                        model=model,
                        prompt_version=prompt_version,
                        max_attempts=max_attempts,
                    )
                return [(block.block_id, outcome)], []
            with tracing.span(
                "corpus.extract_evidence_batch",
                component="corpus",
                subject_type="block_batch",
                subject_id=f"{unit[0].block_id}+{len(unit) - 1}",
                detail="verbose",
            ):
                return self._extract_batch(
                    project_id=project_id,
                    source_id=source_id,
                    unit=unit,
                    section_by_block=section_by_block,
                    blocks=blocks,
                    index_by_id=index_by_id,
                    document_map=document_map,
                    profile=profile,
                    model=model,
                    prompt_version=batch_prompt_version,
                    max_attempts=batch_max_attempts,
                    fallback_max_attempts=max_attempts,
                    fallback_allowed=any_block_succeeded,
                )

        def hand_over(
            work_result: tuple[
                list[tuple[str, tuple[BlockEvidenceExtraction, ModelRunRecord | None]]],
                list[ModelRunRecord],
            ],
        ) -> str | None:
            nonlocal consecutive_skipped, succeeded
            outcomes, completed_batch_runs = work_result
            with handover:
                batch_runs.extend(completed_batch_runs)
                for block_id, outcome in outcomes:
                    record, run = outcome
                    stamped = record.model_copy(update={"extraction_identity": identity})
                    results[block_id] = (stamped, run)
                    if on_extraction is not None:
                        on_extraction(stamped)
                records = [results[block_id][0] for block_id, _ in outcomes]
                if records and all(record.status == "skipped" for record in records):
                    consecutive_skipped += 1
                else:
                    succeeded += 1
                    consecutive_skipped = 0
                if succeeded == 0 and consecutive_skipped >= _BREAKER_CONSECUTIVE_FAILURES:
                    return records[0].rejection_reason or "provider failure"
            return None

        workers = min(self.max_workers, len(units))
        if workers == 1:
            for unit in units:
                breaker_reason = hand_over(work(unit))
                if breaker_reason is not None:
                    raise ModelProviderError(
                        "Evidence extraction circuit breaker opened after "
                        f"{_BREAKER_CONSECUTIVE_FAILURES} consecutive provider failures "
                        f"before any block succeeded: {breaker_reason}"
                    )
        else:
            # Preserve one-wave concurrency for small batches. Larger batches probe
            # only the breaker limit until the first usable answer releases full fan-out.
            bound_work = tracing.bind_context(work)
            next_index = 0
            futures = {}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                initial = (
                    len(units)
                    if len(units) <= workers
                    else min(len(units), _BREAKER_CONSECUTIVE_FAILURES)
                )
                for _ in range(initial):
                    unit = units[next_index]
                    next_index += 1
                    futures[pool.submit(bound_work, unit)] = next_index - 1
                try:
                    while futures:
                        future = next(as_completed(futures))
                        futures.pop(future)
                        outcomes = future.result()
                        breaker_reason = hand_over(outcomes)
                        if breaker_reason is not None:
                            for remaining in futures:
                                remaining.cancel()
                            pool.shutdown(wait=True, cancel_futures=True)
                            raise ModelProviderError(
                                "Evidence extraction circuit breaker opened after "
                                f"{_BREAKER_CONSECUTIVE_FAILURES} consecutive provider "
                                f"failures before any block succeeded: {breaker_reason}"
                            )
                        if succeeded > 0:
                            while len(futures) < workers and next_index < len(units):
                                unit = units[next_index]
                                next_index += 1
                                futures[pool.submit(bound_work, unit)] = next_index - 1
                except BaseException:
                    pool.shutdown(wait=True, cancel_futures=True)
                    raise

        records: list[BlockEvidenceExtraction] = []
        runs: list[ModelRunRecord] = []
        seen_runs: set[UUID] = set()
        for block in blocks:
            outcome = results.get(block.block_id)
            if outcome is None:
                continue
            records.append(outcome[0])
            if outcome[1] is not None and outcome[1].run_id not in seen_runs:
                seen_runs.add(outcome[1].run_id)
                runs.append(outcome[1])
        for run in batch_runs:
            if run.run_id not in seen_runs:
                seen_runs.add(run.run_id)
                runs.append(run)
        return records, runs

    def _extract_block(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        block: SourceDocumentBlock,
        section: DocumentMapSection | None,
        blocks: list[SourceDocumentBlock],
        index_by_id: dict[str, int],
        document_map: DocumentMap,
        profile: AnalysisProfile,
        model: str,
        prompt_version: str | None,
        max_attempts: int,
        initial_counters: dict[str, int | bool] | None = None,
    ) -> tuple[BlockEvidenceExtraction, ModelRunRecord | None]:
        """Extract one block. Independent of every other block, so it runs concurrently."""

        variables = {
            "source_id": str(source_id),
            "block": block.model_dump(mode="json"),
            "section_context": (section.model_dump(mode="json") if section is not None else None),
            "working_thesis": document_map.working_thesis,
            "analysis_profile": profile.model_dump(mode="json"),
            "neighbor_context": _neighbor_context(
                block,
                blocks,
                index_by_id,
                profile.neighbor_context_blocks,
            ),
        }
        # This closure runs on a worker thread. These counters must stay local
        # to the block rather than on the shared service instance.
        counters: dict[str, int | bool] = (
            dict(initial_counters)
            if initial_counters is not None
            else {"n": 0, "excerpt_failures": 0, "salvaged": False, "dropped": 0}
        )

        def validator(draft: EvidenceExtractionDraft) -> None:
            counters["n"] += 1
            try:
                _validate_draft(draft, block=block, profile=profile)
            except ExcerptNotFoundError:
                counters["excerpt_failures"] += 1
                if counters["n"] < max_attempts:
                    raise
                before = len(draft.claims)
                _salvage_draft_inplace(draft, block=block, profile=profile)
                counters["salvaged"] = True
                counters["dropped"] = int(counters["dropped"]) + before - len(draft.claims)
            except DeterministicValidationError:
                if counters["n"] < max_attempts:
                    raise
                before = len(draft.claims)
                _salvage_draft_inplace(draft, block=block, profile=profile)
                counters["salvaged"] = True
                counters["dropped"] = int(counters["dropped"]) + before - len(draft.claims)

        record: BlockEvidenceExtraction
        run: ModelRunRecord | None = None
        try:
            execution = self.model_runner.run(
                project_id=project_id,
                stage="evidence_extraction",
                prompt_name="evidence_extraction",
                variables=variables,
                output_type=EvidenceExtractionDraft,
                model=model,
                prompt_version=prompt_version,
                validator=validator,
            )
            run = execution.record
            extraction = _materialize_extraction(execution.output, block)
            validate_evidence_extraction(extraction, block)
            if not extraction.claims and not _has_auxiliary_content(extraction):
                record = BlockEvidenceExtraction(
                    source_id=source_id,
                    block_id=block.block_id,
                    extraction=extraction,
                    status="rejected",
                    rejection_reason=("No auditable evidence survived validation after retries."),
                )
            else:
                record = BlockEvidenceExtraction(
                    source_id=source_id,
                    block_id=block.block_id,
                    extraction=extraction,
                    status="extracted",
                )
        except StructuredOutputError as exc:
            record = BlockEvidenceExtraction(
                source_id=source_id,
                block_id=block.block_id,
                extraction=EvidenceExtraction(segment_function="rejected"),
                status="rejected",
                rejection_reason=str(exc)[:1_000] or type(exc).__name__,
                failure_kind="contract",
            )
        except (ModelProviderError, ModelSafetyError) as exc:
            record = BlockEvidenceExtraction(
                source_id=source_id,
                block_id=block.block_id,
                extraction=EvidenceExtraction(segment_function="rejected"),
                status="skipped",
                rejection_reason=str(exc)[:1_000] or type(exc).__name__,
                failure_kind="provider",
            )
        # Validation attempts intentionally exclude provider failures: those
        # calls never reach the validator and have a different denominator.
        _emit_evidence_attempt_event(project_id, block, record, counters)
        return record, run

    def _extract_batch(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        unit: list[SourceDocumentBlock],
        section_by_block: dict[str, DocumentMapSection],
        blocks: list[SourceDocumentBlock],
        index_by_id: dict[str, int],
        document_map: DocumentMap,
        profile: AnalysisProfile,
        model: str,
        prompt_version: str | None,
        max_attempts: int,
        fallback_max_attempts: int,
        fallback_allowed: Callable[[], bool],
    ) -> tuple[
        list[tuple[str, tuple[BlockEvidenceExtraction, ModelRunRecord | None]]],
        list[ModelRunRecord],
    ]:
        """Extract one consecutive unit, falling back only for affected blocks."""

        unit_ids = {block.block_id for block in unit}
        variables = {
            "source_id": str(source_id),
            "working_thesis": document_map.working_thesis,
            "analysis_profile": profile.model_dump(mode="json"),
            "block_count": len(unit),
            "blocks": [
                _block_payload(
                    position,
                    block,
                    section_by_block.get(block.block_id),
                    [
                        neighbor
                        for neighbor in _neighbor_context(
                            block, blocks, index_by_id, profile.neighbor_context_blocks
                        )
                        if neighbor["block_id"] not in unit_ids
                    ],
                )
                for position, block in enumerate(unit, start=1)
            ],
        }
        stats: dict[str, object] = {
            "dropped_claims": 0,
            "cross_block_excerpts": 0,
            "by_block": {
                block.block_id: {
                    "attempt_count": 0,
                    "excerpt_failure_count": 0,
                    "salvaged": False,
                    "dropped_claim_count": 0,
                }
                for block in unit
            },
        }

        def validator(draft: BatchEvidenceExtractionDraft) -> None:
            _validate_batch_structure(draft, unit)
            for entry in draft.entries:
                block = unit[entry.block_index - 1]
                counter = _batch_counter(stats, block.block_id)
                counter["attempt_count"] += 1
                dropped, excerpt_failure = _salvage_entry_inplace(
                    entry.extraction, block, unit, profile, stats
                )
                counter["dropped_claim_count"] += dropped
                counter["salvaged"] = bool(counter["salvaged"] or dropped)
                if excerpt_failure:
                    counter["excerpt_failure_count"] += 1

        fallback_ids: set[str] = set()
        outcomes: dict[str, tuple[BlockEvidenceExtraction, ModelRunRecord | None]] = {}
        batch_run: ModelRunRecord | None = None
        try:
            execution = self.model_runner.run(
                project_id=project_id,
                stage="evidence_extraction_batch",
                prompt_name="evidence_extraction_batch",
                variables=variables,
                output_type=BatchEvidenceExtractionDraft,
                model=model,
                prompt_version=prompt_version,
                validator=validator,
            )
            batch_run = execution.record
            for entry in execution.output.entries:
                block = unit[entry.block_index - 1]
                extraction = _materialize_extraction(entry.extraction, block)
                validate_evidence_extraction(extraction, block)
                if not extraction.claims and not _has_auxiliary_content(extraction):
                    fallback_ids.add(block.block_id)
                    continue
                outcomes[block.block_id] = (
                    BlockEvidenceExtraction(
                        source_id=source_id,
                        block_id=block.block_id,
                        extraction=extraction,
                        status="extracted",
                    ),
                    execution.record,
                )
        except (ModelProviderError, ModelSafetyError) as exc:
            if not fallback_allowed():
                _emit_batch_event(project_id, unit, fallback_block_count=0, stats=stats)
                skipped = [
                    (
                        block.block_id,
                        (
                            BlockEvidenceExtraction(
                                source_id=source_id,
                                block_id=block.block_id,
                                extraction=EvidenceExtraction(segment_function="rejected"),
                                status="skipped",
                                rejection_reason=str(exc)[:1_000] or type(exc).__name__,
                                failure_kind="provider",
                            ),
                            None,
                        ),
                    )
                    for block in unit
                ]
                for block_id, outcome in skipped:
                    block = next(item for item in unit if item.block_id == block_id)
                    _emit_evidence_attempt_event(
                        project_id, block, outcome[0], _batch_counter(stats, block_id)
                    )
                return skipped, []
            fallback_ids = set(unit_ids)
        except StructuredOutputError:
            fallback_ids = set(unit_ids)

        _emit_batch_event(
            project_id, unit, fallback_block_count=len(fallback_ids), stats=stats
        )
        for block in unit:
            if block.block_id in fallback_ids:
                continue
            _emit_evidence_attempt_event(
                project_id,
                block,
                outcomes[block.block_id][0],
                _batch_counter(stats, block.block_id),
            )
        for block in unit:
            if block.block_id not in fallback_ids:
                continue
            outcomes[block.block_id] = self._extract_block(
                project_id=project_id,
                source_id=source_id,
                block=block,
                section=section_by_block.get(block.block_id),
                blocks=blocks,
                index_by_id=index_by_id,
                document_map=document_map,
                profile=profile,
                model=model,
                prompt_version=prompt_version,
                max_attempts=fallback_max_attempts,
                initial_counters=_single_block_counters(_batch_counter(stats, block.block_id)),
            )
        return (
            [(block.block_id, outcomes[block.block_id]) for block in unit],
            [batch_run] if batch_run is not None else [],
        )


def _evidence_max_attempts(
    model_runner: ModelRunner,
    prompt_version: str | None,
    prompt_name: str = "evidence_extraction",
) -> int:
    loader = getattr(model_runner, "prompt_loader", None)
    if loader is None:
        return _DEFAULT_MAX_ATTEMPTS
    try:
        contract = loader.load_contract(prompt_name, version=prompt_version)
    except Exception:
        return _DEFAULT_MAX_ATTEMPTS
    return contract.max_attempts


def _batch_prompt_version(model_runner: ModelRunner, prompt_version: str | None) -> str | None:
    """Use the requested version only when the batch prompt provides it.

    ``--prompt-version`` selects the single-block prompt. Batch prompts have
    their own release cadence, so an otherwise valid single-block version must
    fall back to the latest compatible batch contract instead of failing.
    """

    if prompt_version is None:
        return None
    loader = getattr(model_runner, "prompt_loader", None)
    if loader is None:
        return None
    try:
        loader.load_contract("evidence_extraction_batch", version=prompt_version)
    except Exception:
        return None
    return prompt_version


def _validate_draft(
    draft: EvidenceExtractionDraft,
    *,
    block: SourceDocumentBlock,
    profile: AnalysisProfile,
) -> None:
    _validate_profile_budget(draft, profile)
    seen_claims: set[str] = set()
    for claim in draft.claims:
        normalized_claim = _normalize(claim.claim).casefold()
        if normalized_claim in seen_claims:
            raise DeterministicValidationError(
                f"Duplicate claim extracted from block {block.block_id}."
            )
        seen_claims.add(normalized_claim)
        _validate_claim_excerpt(claim, block.text)
        if claim.claim_type.value == "editorial_explanation":
            raise DeterministicValidationError(
                "Evidence extraction may not create editorial claims."
            )


def _validate_profile_budget(
    draft: EvidenceExtractionDraft,
    profile: AnalysisProfile,
) -> None:
    if len(draft.claims) > profile.max_claims_per_block:
        raise DeterministicValidationError(
            "Evidence extraction exceeded max_claims_per_block for this analysis profile."
        )
    if not profile.include_examples and draft.examples:
        raise DeterministicValidationError(
            "This analysis profile does not allocate budget for examples."
        )
    if not profile.include_objections_and_responses and (draft.objections or draft.responses):
        raise DeterministicValidationError(
            "This analysis profile does not allocate budget for objections or responses."
        )


def _validate_claim_excerpt(claim: EvidenceClaimDraft, block_text: str) -> None:
    excerpt = _normalize(claim.supporting_excerpt)
    if len(excerpt) < 12:
        # Offending excerpt in the message: constant strings collide under
        # identical_repair (see ExcerptNotFoundError below).
        raise DeterministicValidationError(
            "supporting_excerpt is too short to audit "
            f"(got: {claim.supporting_excerpt[:60]!r})"
        )
    verbatim = locate_excerpt(claim.supporting_excerpt, block_text)
    if verbatim is None:
        # The offending excerpt travels in the message on purpose: retry's
        # identical_repair guard (model_retry.error_fingerprint) compares
        # stringified messages, and a bare constant string collides on every
        # second failure regardless of which claim actually failed this time
        # -- cutting a 3-attempt budget down to 2 even when each attempt was a
        # genuinely different (and sometimes salvageable) mistake.
        raise ExcerptNotFoundError(
            "supporting_excerpt must be copied from the supplied source block "
            f"(got: {claim.supporting_excerpt[:60]!r})"
        )
    if _normalize(verbatim) != excerpt:
        # Repair typographic drift so downstream auditing stays byte-exact.
        claim.supporting_excerpt = verbatim


def _salvage_draft_inplace(
    draft: EvidenceExtractionDraft,
    *,
    block: SourceDocumentBlock,
    profile: AnalysisProfile,
) -> None:
    """Drop invalid claims/fields on the final attempt; keep the rest."""

    kept: list[EvidenceClaimDraft] = []
    seen_claims: set[str] = set()
    for claim in draft.claims:
        if claim.claim_type.value == "editorial_explanation":
            continue
        normalized_claim = _normalize(claim.claim).casefold()
        if normalized_claim in seen_claims:
            continue
        try:
            _validate_claim_excerpt(claim, block.text)
        except DeterministicValidationError:
            continue
        seen_claims.add(normalized_claim)
        kept.append(claim)
        if len(kept) >= profile.max_claims_per_block:
            break
    draft.claims = kept
    if not profile.include_examples:
        draft.examples = []
    if not profile.include_objections_and_responses:
        draft.objections = []
        draft.responses = []


def _validate_batch_structure(
    draft: BatchEvidenceExtractionDraft,
    unit: list[SourceDocumentBlock],
) -> None:
    """Structural batch failures retry; entry-level content failures do not."""

    indices = [entry.block_index for entry in draft.entries]
    if sorted(indices) != list(range(1, len(unit) + 1)):
        raise DeterministicValidationError(
            f"Batched extraction must return exactly {len(unit)} entries with "
            f"block_index 1..{len(unit)}; got {sorted(indices)}."
        )


def _salvage_entry_inplace(
    draft: EvidenceExtractionDraft,
    block: SourceDocumentBlock,
    unit: list[SourceDocumentBlock],
    profile: AnalysisProfile,
    stats: dict[str, object],
) -> tuple[int, bool]:
    """Batch-only copy of single-block salvage, with measurement counters.

    Keep this separate from ``_salvage_draft_inplace``: the single-block path is
    experiment E2's control arm and must not change with the batched treatment.
    """

    kept: list[EvidenceClaimDraft] = []
    seen_claims: set[str] = set()
    dropped_claims = 0
    excerpt_failure = False
    for position, claim in enumerate(draft.claims):
        if claim.claim_type.value == "editorial_explanation":
            dropped_claims += 1
            continue
        normalized_claim = _normalize(claim.claim).casefold()
        if normalized_claim in seen_claims:
            dropped_claims += 1
            continue
        try:
            _validate_claim_excerpt(claim, block.text)
        except DeterministicValidationError as exc:
            dropped_claims += 1
            excerpt_failure = excerpt_failure or isinstance(exc, ExcerptNotFoundError)
            if any(
                sibling.block_id != block.block_id
                and locate_excerpt(claim.supporting_excerpt, sibling.text) is not None
                for sibling in unit
            ):
                stats["cross_block_excerpts"] = int(stats["cross_block_excerpts"]) + 1
            continue
        seen_claims.add(normalized_claim)
        kept.append(claim)
        if len(kept) >= profile.max_claims_per_block:
            dropped_claims += len(draft.claims) - position - 1
            break
    # Claims beyond the budget are deliberately dropped in place rather than retrying K blocks.
    stats["dropped_claims"] = int(stats["dropped_claims"]) + dropped_claims
    draft.claims = kept
    if not profile.include_examples:
        draft.examples = []
    if not profile.include_objections_and_responses:
        draft.objections = []
        draft.responses = []
    return dropped_claims, excerpt_failure


def _materialize_extraction(
    draft: EvidenceExtractionDraft,
    block: SourceDocumentBlock,
) -> EvidenceExtraction:
    claims = [
        EvidenceItem(
            evidence_id=_evidence_id(block, claim.claim, claim.supporting_excerpt),
            source_id=block.source_id,
            block_id=block.block_id,
            claim=claim.claim.strip(),
            claim_type=claim.claim_type,
            supporting_excerpt=claim.supporting_excerpt.strip(),
            locator=block.locator.model_copy(deep=True),
            support_kind=claim.support_kind,
            qualifications=claim.qualifications,
            confidence=claim.confidence,
        )
        for claim in draft.claims
    ]
    return EvidenceExtraction(
        segment_function=draft.segment_function,
        claims=claims,
        definitions=[
            ExtractedDefinition(
                term=item.term,
                definition=item.definition,
                source_id=block.source_id,
                block_id=block.block_id,
                locator=block.locator.model_copy(deep=True),
            )
            for item in draft.definitions
        ],
        distinctions=[
            ExtractedDistinction(
                item_a=item.item_a,
                item_b=item.item_b,
                distinction=item.distinction,
                source_id=block.source_id,
                block_id=block.block_id,
                locator=block.locator.model_copy(deep=True),
            )
            for item in draft.distinctions
        ],
        examples=_materialize_points(draft.examples, block),
        objections=_materialize_points(draft.objections, block),
        responses=_materialize_points(draft.responses, block),
        must_not_be_lost=[
            MustNotBeLostPoint(
                text=text,
                source_id=block.source_id,
                block_id=block.block_id,
                locator=block.locator.model_copy(deep=True),
            )
            for text in draft.must_not_be_lost
        ],
    )


def _materialize_points(
    texts: list[str],
    block: SourceDocumentBlock,
) -> list[ExtractedAuxiliaryPoint]:
    return [
        ExtractedAuxiliaryPoint(
            text=text,
            source_id=block.source_id,
            block_id=block.block_id,
            locator=block.locator.model_copy(deep=True),
        )
        for text in texts
    ]


def _has_auxiliary_content(extraction: EvidenceExtraction) -> bool:
    return bool(
        extraction.definitions
        or extraction.distinctions
        or extraction.examples
        or extraction.objections
        or extraction.responses
        or extraction.must_not_be_lost
    )


def _neighbor_context(
    block: SourceDocumentBlock,
    blocks: list[SourceDocumentBlock],
    index_by_id: dict[str, int],
    radius: int,
) -> list[dict[str, object]]:
    if radius == 0:
        return []
    index = index_by_id[block.block_id]
    start = max(0, index - radius)
    end = min(len(blocks), index + radius + 1)
    return [
        {
            "block_id": neighbor.block_id,
            "heading_path": neighbor.heading_path,
            "text": neighbor.text[:2_000],
        }
        for neighbor in blocks[start:end]
        if neighbor.block_id != block.block_id and neighbor.block_type != "front_matter"
    ]


def _plan_units(
    pending: list[SourceDocumentBlock],
    batch_size: int,
) -> list[list[SourceDocumentBlock]]:
    """Consecutive slices capped by block count and source-token mass."""

    if batch_size <= 1:
        return [[block] for block in pending]
    units: list[list[SourceDocumentBlock]] = []
    current: list[SourceDocumentBlock] = []
    current_tokens = 0
    for block in pending:
        if current and (
            len(current) >= batch_size
            or current_tokens + block.estimated_token_count > _MAX_BATCH_SOURCE_TOKENS
        ):
            units.append(current)
            current = []
            current_tokens = 0
        current.append(block)
        current_tokens += block.estimated_token_count
    if current:
        units.append(current)
    return units


def _block_payload(
    index: int,
    block: SourceDocumentBlock,
    section: DocumentMapSection | None,
    neighbors: list[dict[str, object]],
) -> dict[str, object]:
    """Trimmed model payload: IDs and locators stay application-side."""

    return {
        "index": index,
        "block_type": block.block_type,
        "heading_path": block.heading_path,
        "text": block.text,
        "section_context": None
        if section is None
        else {
            "title": section.title,
            "function": section.function,
            "key_concepts": section.key_concepts,
            "unresolved_context": section.unresolved_context,
        },
        "neighbor_context": neighbors,
    }


def _emit_evidence_attempt_event(
    project_id: UUID,
    block: SourceDocumentBlock,
    record: BlockEvidenceExtraction,
    counters: dict[str, int | bool],
) -> None:
    """Emit exactly one E3 measurement event for a processed block."""

    tracing.event(
        "corpus.evidence_attempts",
        component="corpus",
        project_id=project_id,
        subject_type="block",
        subject_id=block.block_id,
        attempt_count=counters["n"] if "n" in counters else counters["attempt_count"],
        excerpt_failure_count=(
            counters["excerpt_failures"]
            if "excerpt_failures" in counters
            else counters["excerpt_failure_count"]
        ),
        salvaged=counters["salvaged"],
        dropped_claim_count=(
            counters["dropped"] if "dropped" in counters else counters["dropped_claim_count"]
        ),
        kept_claim_count=len(record.extraction.claims),
        status=record.status,
    )


def _batch_counter(stats: dict[str, object], block_id: str) -> dict[str, int | bool]:
    by_block = stats["by_block"]
    assert isinstance(by_block, dict)
    counter = by_block[block_id]
    assert isinstance(counter, dict)
    return counter


def _single_block_counters(batch_counter: dict[str, int | bool]) -> dict[str, int | bool]:
    """Carry one batch entry's measurements into its single-block fallback."""

    return {
        "n": int(batch_counter["attempt_count"]),
        "excerpt_failures": int(batch_counter["excerpt_failure_count"]),
        "salvaged": bool(batch_counter["salvaged"]),
        "dropped": int(batch_counter["dropped_claim_count"]),
    }


def _emit_batch_event(
    project_id: UUID,
    unit: list[SourceDocumentBlock],
    *,
    fallback_block_count: int,
    stats: dict[str, object],
) -> None:
    """Emit E2's per-call measurement record, including aborted calls."""

    tracing.event(
        "corpus.evidence_batch",
        component="corpus",
        project_id=project_id,
        subject_type="block_batch",
        subject_id=f"{unit[0].block_id}+{len(unit) - 1}",
        block_count=len(unit),
        fallback_block_count=fallback_block_count,
        dropped_claim_count=int(stats["dropped_claims"]),
        cross_block_excerpt_count=int(stats["cross_block_excerpts"]),
    )


def _full_profile() -> AnalysisProfile:
    return AnalysisProfile(
        depth="extended",
        target_duration_minutes=120,
        block_coverage_target=1.0,
        evidence_input_token_budget=180_000,
        max_claims_per_block=12,
        neighbor_context_blocks=0,
        include_examples=True,
        include_objections_and_responses=True,
        second_pass_for_core_sections=False,
        rationale=["Compatibility profile for direct service calls without a plan."],
    )


def _evidence_id(block: SourceDocumentBlock, claim: str, excerpt: str) -> str:
    payload = "\x1f".join(
        [str(block.source_id), block.block_id, _normalize(claim), _normalize(excerpt)]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"ev-{digest}"


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()
