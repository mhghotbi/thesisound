from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from uuid import UUID

from thesisound.domain import (
    DocumentMap,
    DocumentMapSection,
    EvidenceExtraction,
    EvidenceItem,
    ExtractedDefinition,
    ExtractedDistinction,
)
from thesisound.modeling import (
    DeterministicValidationError,
    ModelRunRecord,
    StructuredOutputError,
)
from thesisound.services.evidence_validator import validate_evidence_extraction
from thesisound.services.excerpt_matching import locate_excerpt
from thesisound.services.model_runner import ModelRunner
from thesisound.source_analysis import (
    AnalysisProfile,
    BlockEvidenceExtraction,
    EvidenceClaimDraft,
    EvidenceExtractionDraft,
    EvidenceExtractionPlan,
    SourceDocumentBlock,
)

_WHITESPACE = re.compile(r"\s+")
ExtractionCallback = Callable[[BlockEvidenceExtraction], None]
_DEFAULT_MAX_ATTEMPTS = 3


class EvidenceExtractorService:
    def __init__(self, model_runner: ModelRunner, *, max_workers: int = 1) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1.")
        self.model_runner = model_runner
        self.max_workers = max_workers

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

        pending = [
            block
            for block in blocks
            if block.block_type != "front_matter"
            and block.block_id in selected_ids
            and block.block_id not in skip_ids
        ]
        if not pending:
            return [], []

        results: dict[str, tuple[BlockEvidenceExtraction, ModelRunRecord | None]] = {}
        # Callers persist from `on_extraction`, so serialize the callback here rather than
        # asking every caller to be thread-safe. The model call itself stays outside it.
        handover = Lock()

        def work(block: SourceDocumentBlock) -> None:
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
            with handover:
                results[block.block_id] = outcome
                if on_extraction is not None:
                    on_extraction(outcome[0])

        workers = min(self.max_workers, len(pending))
        if workers == 1:
            for block in pending:
                work(block)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(work, block) for block in pending]
                try:
                    for future in as_completed(futures):
                        future.result()
                except BaseException:
                    # Drop work that has not started but let in-flight blocks land: each
                    # finished block is already saved and is skipped by the next attempt.
                    pool.shutdown(wait=True, cancel_futures=True)
                    raise

        records: list[BlockEvidenceExtraction] = []
        runs: list[ModelRunRecord] = []
        for block in blocks:
            outcome = results.get(block.block_id)
            if outcome is None:
                continue
            records.append(outcome[0])
            if outcome[1] is not None:
                runs.append(outcome[1])
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
    ) -> tuple[BlockEvidenceExtraction, ModelRunRecord | None]:
        """Extract one block. Independent of every other block, so it runs concurrently."""

        variables = {
            "source_id": str(source_id),
            "block": block.model_dump(mode="json"),
            "section_context": (
                section.model_dump(mode="json") if section is not None else None
            ),
            "working_thesis": document_map.working_thesis,
            "analysis_profile": profile.model_dump(mode="json"),
            "neighbor_context": _neighbor_context(
                block,
                blocks,
                index_by_id,
                profile.neighbor_context_blocks,
            ),
        }
        attempt = {"n": 0}

        def validator(draft: EvidenceExtractionDraft) -> None:
            attempt["n"] += 1
            try:
                _validate_draft(draft, block=block, profile=profile)
            except DeterministicValidationError:
                if attempt["n"] < max_attempts:
                    raise
                _salvage_draft_inplace(draft, block=block, profile=profile)

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
                    rejection_reason=(
                        "No auditable evidence survived validation after retries."
                    ),
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
            )
        return record, run


def _evidence_max_attempts(
    model_runner: ModelRunner,
    prompt_version: str | None,
) -> int:
    loader = getattr(model_runner, "prompt_loader", None)
    if loader is None:
        return _DEFAULT_MAX_ATTEMPTS
    try:
        contract = loader.load_contract("evidence_extraction", version=prompt_version)
    except Exception:
        return _DEFAULT_MAX_ATTEMPTS
    return contract.max_attempts


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
    if not profile.include_objections_and_responses and (
        draft.objections or draft.responses
    ):
        raise DeterministicValidationError(
            "This analysis profile does not allocate budget for objections or responses."
        )


def _validate_claim_excerpt(claim: EvidenceClaimDraft, block_text: str) -> None:
    excerpt = _normalize(claim.supporting_excerpt)
    if len(excerpt) < 12:
        raise DeterministicValidationError("supporting_excerpt is too short to audit.")
    verbatim = locate_excerpt(claim.supporting_excerpt, block_text)
    if verbatim is None:
        raise DeterministicValidationError(
            "supporting_excerpt must be copied from the supplied source block."
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
                locator=block.locator.model_copy(deep=True),
            )
            for item in draft.definitions
        ],
        distinctions=[
            ExtractedDistinction(
                item_a=item.item_a,
                item_b=item.item_b,
                distinction=item.distinction,
                locator=block.locator.model_copy(deep=True),
            )
            for item in draft.distinctions
        ],
        examples=draft.examples,
        objections=draft.objections,
        responses=draft.responses,
        references_to_other_sections=draft.references_to_other_sections,
        unresolved_context=draft.unresolved_context,
        must_not_be_lost=draft.must_not_be_lost,
    )


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
        if neighbor.block_id != block.block_id
        and neighbor.block_type != "front_matter"
    ]


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
