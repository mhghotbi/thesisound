from __future__ import annotations

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
    runner = SelectiveRunner(lambda block_id: "success" if block_id == "block-1" else "provider")

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
