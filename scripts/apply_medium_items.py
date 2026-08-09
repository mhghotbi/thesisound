from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one anchor in {path}, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def apply_item_8() -> None:
    replace_once(
        "src/thesisound/source_analysis.py",
        '''class BlockEvidenceExtraction(BaseModel):
    source_id: UUID
    block_id: str = Field(min_length=1)
    extraction: EvidenceExtraction
    status: Literal["extracted", "rejected"] = "extracted"
    rejection_reason: str | None = None
''',
        '''class BlockEvidenceExtraction(BaseModel):
    """One block extraction outcome.

    ``rejected`` means the model answered but the answer remained unusable after
    retries. ``skipped`` means no usable answer was obtained at all, normally
    because a provider or safety failure prevented the model from answering.
    """

    source_id: UUID
    block_id: str = Field(min_length=1)
    extraction: EvidenceExtraction
    status: Literal["extracted", "rejected", "skipped"] = "extracted"
    rejection_reason: str | None = None
    failure_kind: Literal["contract", "provider"] | None = None
''',
    )
    replace_once(
        "src/thesisound/source_analysis.py",
        '''    evidence_count: int = Field(default=0, ge=0)
    claim_count: int = Field(default=0, ge=0)
''',
        '''    evidence_count: int = Field(default=0, ge=0)
    skipped_block_count: int = Field(default=0, ge=0)
    claim_count: int = Field(default=0, ge=0)
''',
    )

    replace_once(
        "src/thesisound/services/evidence_extractor.py",
        '''from thesisound.modeling import (
    DeterministicValidationError,
    ModelRunRecord,
    StructuredOutputError,
)
''',
        '''from thesisound.modeling import (
    DeterministicValidationError,
    ModelProviderError,
    ModelRunRecord,
    ModelSafetyError,
    StructuredOutputError,
)
''',
    )
    replace_once(
        "src/thesisound/services/evidence_extractor.py",
        '''_DEFAULT_MAX_ATTEMPTS = 3
''',
        '''_DEFAULT_MAX_ATTEMPTS = 3
# A global provider failure looks like a per-block failure. Before any block has
# succeeded, probe at most this many blocks so a revoked key or dead endpoint
# aborts without paying for one call per remaining block.
_BREAKER_CONSECUTIVE_FAILURES = 3
''',
    )
    replace_once(
        "src/thesisound/services/evidence_extractor.py",
        '''        results: dict[str, tuple[BlockEvidenceExtraction, ModelRunRecord | None]] = {}
        # Callers persist from `on_extraction`, so serialize the callback here rather than
        # asking every caller to be thread-safe. The model call itself stays outside it.
        handover = Lock()

        def work(block: SourceDocumentBlock) -> None:
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
            with handover:
                results[block.block_id] = outcome
                if on_extraction is not None:
                    on_extraction(outcome[0])

        workers = min(self.max_workers, len(pending))
        if workers == 1:
            for block in pending:
                work(block)
        else:
            # concurrent.futures.ThreadPoolExecutor does NOT copy contextvars
            # into the worker thread (unlike anyio's run_in_threadpool), so
            # every span opened inside work() would otherwise be orphaned at
            # the trace root instead of nesting under whatever span is open
            # on the submitting thread (e.g. corpus.source). bind_context
            # re-attaches that context inside each worker.
            bound_work = tracing.bind_context(work)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(bound_work, block) for block in pending]
                try:
                    for future in as_completed(futures):
                        future.result()
                except BaseException:
                    # Drop work that has not started but let in-flight blocks land: each
                    # finished block is already saved and is skipped by the next attempt.
                    pool.shutdown(wait=True, cancel_futures=True)
                    raise
''',
        '''        results: dict[str, tuple[BlockEvidenceExtraction, ModelRunRecord | None]] = {}
        # Callers persist from `on_extraction`, so serialize the callback here rather than
        # asking every caller to be thread-safe. The model call itself stays outside it.
        handover = Lock()
        consecutive_skipped = 0
        succeeded = 0

        def work(
            block: SourceDocumentBlock,
        ) -> tuple[str, tuple[BlockEvidenceExtraction, ModelRunRecord | None]]:
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
            return block.block_id, outcome

        def hand_over(
            block_id: str,
            outcome: tuple[BlockEvidenceExtraction, ModelRunRecord | None],
        ) -> str | None:
            nonlocal consecutive_skipped, succeeded
            with handover:
                record = outcome[0]
                results[block_id] = outcome
                if on_extraction is not None:
                    on_extraction(record)
                if record.status == "skipped":
                    consecutive_skipped += 1
                else:
                    succeeded += 1
                    consecutive_skipped = 0
                if (
                    succeeded == 0
                    and consecutive_skipped >= _BREAKER_CONSECUTIVE_FAILURES
                ):
                    return record.rejection_reason or "provider failure"
            return None

        workers = min(self.max_workers, len(pending))
        if workers == 1:
            for block in pending:
                block_id, outcome = work(block)
                breaker_reason = hand_over(block_id, outcome)
                if breaker_reason is not None:
                    raise ModelProviderError(
                        "Evidence extraction circuit breaker opened after "
                        f"{_BREAKER_CONSECUTIVE_FAILURES} consecutive provider failures "
                        f"before any block succeeded: {breaker_reason}"
                    )
        else:
            # Before any success, submit no more than the breaker limit in total.
            # This keeps an all-provider-failure batch bounded at exactly three calls,
            # even when max_workers is larger. Once any block receives a usable model
            # answer, fill the pool normally because failures are then demonstrably local.
            bound_work = tracing.bind_context(work)
            next_index = 0
            futures = {}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                initial = min(
                    workers,
                    len(pending),
                    _BREAKER_CONSECUTIVE_FAILURES,
                )
                for _ in range(initial):
                    block = pending[next_index]
                    next_index += 1
                    futures[pool.submit(bound_work, block)] = block.block_id
                try:
                    while futures:
                        future = next(as_completed(futures))
                        futures.pop(future)
                        block_id, outcome = future.result()
                        breaker_reason = hand_over(block_id, outcome)
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
                            while len(futures) < workers and next_index < len(pending):
                                block = pending[next_index]
                                next_index += 1
                                futures[pool.submit(bound_work, block)] = block.block_id
                except BaseException:
                    # Drop work that has not started but let in-flight blocks land: each
                    # finished block is already saved and is retried by the next attempt
                    # unless it was extracted successfully.
                    pool.shutdown(wait=True, cancel_futures=True)
                    raise
''',
    )
    replace_once(
        "src/thesisound/services/evidence_extractor.py",
        '''        except StructuredOutputError as exc:
            record = BlockEvidenceExtraction(
                source_id=source_id,
                block_id=block.block_id,
                extraction=EvidenceExtraction(segment_function="rejected"),
                status="rejected",
                rejection_reason=str(exc)[:1_000] or type(exc).__name__,
            )
        return record, run
''',
        '''        except StructuredOutputError as exc:
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
        return record, run
''',
    )

    replace_once(
        "src/thesisound/services/source_analysis_service.py",
        '''        rejected = [record for record in records if record.status == "rejected"]
        warnings = [
            f"Rejected evidence for {record.block_id}: {record.rejection_reason}"
            for record in rejected
            if record.rejection_reason
        ]
''',
        '''        rejected = [record for record in records if record.status == "rejected"]
        skipped = [record for record in records if record.status == "skipped"]
        warnings = [
            f"Rejected evidence for {record.block_id}: {record.rejection_reason}"
            for record in rejected
            if record.rejection_reason
        ]
        for record in skipped:
            reason = record.rejection_reason or "provider failure"
            warnings.append(f"Skipped evidence for {record.block_id}: {reason}")
            tracing.event(
                "corpus.block_skipped",
                component="corpus",
                level="warn",
                project_id=project_id,
                subject_type="block",
                subject_id=record.block_id,
                reason=reason,
            )
        warnings.append(
            f"Extracted {len(kept_ids)} of {len(plan.selected_block_ids)} planned blocks; "
            f"{len(skipped)} skipped after provider errors, {len(rejected)} rejected. "
            f"Kept {retention:.0%} of planned tokens."
        )
''',
    )
    replace_once(
        "src/thesisound/services/source_analysis_service.py",
        '''        manifest.evidence_count = claim_count
        manifest.model_run_ids.extend(run.run_id for run in runs)
''',
        '''        manifest.evidence_count = claim_count
        manifest.skipped_block_count = len(skipped)
        manifest.model_run_ids.extend(run.run_id for run in runs)
''',
    )
    replace_once(
        "src/thesisound/services/source_analysis_service.py",
        '''                f"Evidence extraction lost {1 - retention:.0%} of the planned source tokens "
                f"across {len(rejected)} rejected block(s); at least "
''',
        '''                f"Evidence extraction lost {1 - retention:.0%} of the planned source tokens "
                f"across {len(rejected)} rejected and {len(skipped)} skipped block(s); at least "
''',
    )

    write(
        "tests/test_evidence_fanout.py",
        '''from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest

from thesisound.domain import ClaimType, DocumentMap, DocumentMapSection, Locator
from thesisound.modeling import (
    ModelConfigurationError,
    ModelExecution,
    ModelProviderError,
    ModelRunRecord,
    StructuredOutputError,
)
from thesisound.services.evidence_extractor import EvidenceExtractorService
from thesisound.source_analysis import (
    DocumentMapDraft,
    EvidenceClaimDraft,
    EvidenceExtractionDraft,
    SourceDocumentBlock,
)


class SelectiveRunner:
    def __init__(
        self,
        behavior: Callable[[str], str] | None = None,
    ) -> None:
        self.behavior = behavior or (lambda _: "success")
        self.calls: list[str] = []

    def run(
        self,
        *,
        project_id: UUID,
        stage: str,
        variables: dict[str, object],
        output_type,
        model: str,
        **_: object,
    ) -> ModelExecution:
        assert output_type is EvidenceExtractionDraft
        block = variables["block"]
        assert isinstance(block, dict)
        block_id = str(block["block_id"])
        self.calls.append(block_id)
        behavior = self.behavior(block_id)
        if behavior == "provider":
            raise ModelProviderError(f"provider failed for {block_id}")
        if behavior == "contract":
            raise StructuredOutputError(f"contract failed for {block_id}")
        if behavior == "configuration":
            raise ModelConfigurationError("missing model configuration")
        text = str(block["text"])
        excerpt = text[:40]
        output = EvidenceExtractionDraft(
            segment_function="argument",
            claims=[
                EvidenceClaimDraft(
                    claim=f"Claim for {block_id}",
                    claim_type=ClaimType.AUTHOR_POSITION,
                    supporting_excerpt=excerpt,
                    support_kind="direct",
                    confidence=0.9,
                )
            ],
        )
        record = ModelRunRecord(
            project_id=project_id,
            stage=stage,
            prompt_id=stage,
            prompt_version="test",
            prompt_hash="test",
            input_hash="test",
            provider="fake",
            model=model,
            output_model=output_type.__name__,
            status="succeeded",
        )
        return ModelExecution(output=output, record=record)


def _fixture(count: int = 10) -> tuple[UUID, list[SourceDocumentBlock], DocumentMap]:
    source_id = uuid4()
    blocks = [
        SourceDocumentBlock(
            block_id=f"block-{index}",
            source_id=source_id,
            locator=Locator(page_start=index, page_end=index),
            text=(
                f"Reliable source material for block {index} contains enough exact text "
                "for an auditable excerpt."
            ),
            estimated_token_count=25,
            source_block_keys=[f"source-{index}"],
        )
        for index in range(1, count + 1)
    ]
    document_map = DocumentMap(
        source_id=source_id,
        scope_locator=Locator(page_start=1, page_end=count),
        sections=[
            DocumentMapSection(
                section_id="section-1",
                source_block_ids=[block.block_id for block in blocks],
                title="Test section",
                function="argument",
            )
        ],
    )
    return source_id, blocks, document_map


@pytest.mark.parametrize("max_workers", [1, 4])
def test_provider_error_on_one_block_skips_it_and_keeps_the_rest(max_workers: int) -> None:
    source_id, blocks, document_map = _fixture()
    runner = SelectiveRunner(lambda block_id: "provider" if block_id == "block-4" else "success")

    records, _ = EvidenceExtractorService(runner, max_workers=max_workers).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
    )

    assert sum(record.status == "extracted" for record in records) == 9
    skipped = [record for record in records if record.status == "skipped"]
    assert len(skipped) == 1
    assert skipped[0].block_id == "block-4"
    assert skipped[0].failure_kind == "provider"


@pytest.mark.parametrize("max_workers", [1, 4])
def test_contract_failure_is_still_rejected_not_skipped(max_workers: int) -> None:
    source_id, blocks, document_map = _fixture(1)
    runner = SelectiveRunner(lambda _: "contract")

    records, _ = EvidenceExtractorService(runner, max_workers=max_workers).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
    )

    assert records[0].status == "rejected"
    assert records[0].failure_kind == "contract"


@pytest.mark.parametrize("max_workers", [1, 4])
def test_configuration_error_aborts_the_batch(max_workers: int) -> None:
    source_id, blocks, document_map = _fixture()
    runner = SelectiveRunner(lambda _: "configuration")

    with pytest.raises(ModelConfigurationError):
        EvidenceExtractorService(runner, max_workers=max_workers).extract_source(
            project_id=uuid4(),
            source_id=source_id,
            blocks=blocks,
            document_map=document_map,
            model="fake",
        )


@pytest.mark.parametrize("max_workers", [1, 4])
def test_breaker_aborts_after_three_consecutive_provider_failures(max_workers: int) -> None:
    source_id, blocks, document_map = _fixture()
    runner = SelectiveRunner(lambda _: "provider")

    with pytest.raises(ModelProviderError, match="circuit breaker"):
        EvidenceExtractorService(runner, max_workers=max_workers).extract_source(
            project_id=uuid4(),
            source_id=source_id,
            blocks=blocks,
            document_map=document_map,
            model="fake",
        )

    assert len(runner.calls) == 3


@pytest.mark.parametrize("max_workers", [1, 4])
def test_breaker_does_not_trip_when_a_block_succeeded_first(max_workers: int) -> None:
    source_id, blocks, document_map = _fixture(4)
    runner = SelectiveRunner(
        lambda block_id: "success" if block_id == "block-1" else "provider"
    )

    records, _ = EvidenceExtractorService(runner, max_workers=max_workers).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
    )

    assert records[0].status == "extracted"
    assert sum(record.status == "skipped" for record in records) == 3


@pytest.mark.parametrize("max_workers", [1, 4])
def test_skipped_blocks_are_retried_on_the_next_attempt(max_workers: int) -> None:
    source_id, blocks, document_map = _fixture()
    first_runner = SelectiveRunner(
        lambda block_id: "provider" if block_id == "block-4" else "success"
    )
    first, _ = EvidenceExtractorService(first_runner, max_workers=max_workers).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
    )
    extracted_ids = {record.block_id for record in first if record.status == "extracted"}

    second_runner = SelectiveRunner()
    second, _ = EvidenceExtractorService(second_runner, max_workers=max_workers).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
        skip_block_ids=extracted_ids,
    )

    assert second_runner.calls == ["block-4"]
    assert second[0].status == "extracted"


def test_old_extraction_artifacts_default_failure_kind_to_none() -> None:
    source_id, blocks, _ = _fixture(1)
    payload = {
        "source_id": str(source_id),
        "block_id": blocks[0].block_id,
        "extraction": {"segment_function": "argument"},
        "status": "extracted",
    }

    from thesisound.source_analysis import BlockEvidenceExtraction

    record = BlockEvidenceExtraction.model_validate(payload)
    assert record.failure_kind is None
''',
    )


if __name__ == "__main__":
    apply_item_8()
