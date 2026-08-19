from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from thesisound.config import Settings
from thesisound.domain import ClaimType, DocumentMap, DocumentMapSection, Locator
from thesisound.modeling import (
    ModelExecution,
    ModelProviderError,
    ModelRunRecord,
)
from thesisound.prompt_loader import PromptLoader
from thesisound.services.evidence_extractor import (
    _MAX_BATCH_SOURCE_TOKENS,
    EvidenceExtractorService,
    _plan_units,
)
from thesisound.source_analysis import (
    BatchEvidenceEntryDraft,
    BatchEvidenceExtractionDraft,
    EvidenceClaimDraft,
    EvidenceExtractionDraft,
    SourceDocumentBlock,
)


def _fixture(count: int = 8) -> tuple[UUID, list[SourceDocumentBlock], DocumentMap]:
    source_id = uuid4()
    blocks = [
        SourceDocumentBlock(
            block_id=f"block-{index}",
            source_id=source_id,
            locator=Locator(page_start=index, page_end=index),
            heading_path=["Test section"],
            text=(
                f"Block {index} says this claim is supported by its own unique source text, "
                "with enough words for an auditable excerpt."
            ),
            estimated_token_count=25,
            source_block_keys=[f"source-{index}"],
        )
        for index in range(1, count + 1)
    ]
    return source_id, blocks, DocumentMap(
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


def _draft(text: str, *, more_claims_available: bool = False) -> EvidenceExtractionDraft:
    return EvidenceExtractionDraft(
        segment_function="argument",
        claims=[
            EvidenceClaimDraft(
                claim=f"Claim grounded in {text[:16]}",
                claim_type=ClaimType.AUTHOR_POSITION,
                supporting_excerpt=text[:60],
                support_kind="direct",
                confidence=0.9,
            )
        ],
        more_claims_available=more_claims_available,
    )


class BatchRunner:
    def __init__(self, *, mode: str = "normal", more_claims_available: bool = False) -> None:
        self.mode = mode
        self.more_claims_available = more_claims_available
        self.calls: list[tuple[str, list[str]]] = []
        self.batch_prompt_versions: list[str | None] = []

    def run(
        self,
        *,
        project_id: UUID,
        stage: str,
        variables: dict[str, object],
        output_type: type,
        model: str,
        validator=None,
        **_: object,
    ) -> ModelExecution:
        if stage == "evidence_extraction":
            block = variables["block"]
            assert isinstance(block, dict)
            texts = [str(block["text"])]
            output = _draft(texts[0], more_claims_available=self.more_claims_available)
        else:
            assert stage == "evidence_extraction_batch"
            assert output_type is BatchEvidenceExtractionDraft
            prompt_version = _.get("prompt_version")
            assert prompt_version is None or isinstance(prompt_version, str)
            self.batch_prompt_versions.append(prompt_version)
            payload = variables["blocks"]
            assert isinstance(payload, list)
            texts = [str(block["text"]) for block in payload]
            self.calls.append((stage, texts))
            if self.mode == "provider":
                raise ModelProviderError("provider unavailable")
            entries = [
                BatchEvidenceEntryDraft(
                    block_index=index,
                    extraction=_draft(text, more_claims_available=self.more_claims_available),
                )
                for index, text in enumerate(texts, start=1)
            ]
            if self.mode == "reversed":
                entries.reverse()
            if self.mode == "missing":
                entries.pop()
            if self.mode == "cross_block":
                entries[1].extraction = _draft(texts[0])
            if self.mode == "empty":
                entries = [
                    BatchEvidenceEntryDraft(
                        block_index=index,
                        extraction=EvidenceExtractionDraft(segment_function="argument"),
                    )
                    for index in range(1, len(texts) + 1)
                ]
            output = BatchEvidenceExtractionDraft(entries=entries)
        if stage == "evidence_extraction":
            self.calls.append((stage, texts))
        if validator is not None:
            validator(output)
        return ModelExecution(
            output=output,
            record=ModelRunRecord(
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
            ),
        )


def test_plan_units_preserves_order_and_token_cap() -> None:
    _, blocks, _ = _fixture(10)
    assert _plan_units(blocks, 1) == [[block] for block in blocks]
    assert [len(unit) for unit in _plan_units(blocks, 4)] == [4, 4, 2]
    blocks[4].estimated_token_count = _MAX_BATCH_SOURCE_TOKENS + 1
    units = _plan_units(blocks, 4)
    assert units[1] == [blocks[4]]
    assert [block for unit in units for block in unit] == blocks


def test_batch_is_equivalent_to_single_block_and_deduplicates_runs() -> None:
    source_id, blocks, document_map = _fixture(8)
    single, _ = EvidenceExtractorService(BatchRunner(), batch_size=1).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
    )
    runner = BatchRunner()
    batched, runs = EvidenceExtractorService(runner, batch_size=4).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
    )
    assert [item.model_dump(mode="json") for item in batched] == [
        item.model_dump(mode="json") for item in single
    ]
    assert len(runs) == len(runner.calls) == 2
    assert {run.run_id for run in runs} == {run.run_id for run in runs}


def test_batch_attributes_reordered_entries_by_index() -> None:
    source_id, blocks, document_map = _fixture(4)
    service = EvidenceExtractorService(BatchRunner(mode="reversed"), batch_size=4)
    records, _ = service.extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
    )
    assert all(
        record.extraction.claims[0].supporting_excerpt in block.text
        for record, block in zip(records, blocks, strict=True)
    )


@pytest.mark.parametrize("mode", ["missing", "cross_block"])
def test_unusable_batch_entry_falls_back_only_where_needed(mode: str) -> None:
    source_id, blocks, document_map = _fixture(4)
    runner = BatchRunner(mode=mode)
    records, _ = EvidenceExtractorService(runner, batch_size=4).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
    )
    assert all(record.status == "extracted" for record in records)
    if mode == "missing":
        assert [stage for stage, _ in runner.calls] == ["evidence_extraction_batch"] + [
            "evidence_extraction"
        ] * 4
    else:
        assert [stage for stage, _ in runner.calls] == [
            "evidence_extraction_batch",
            "evidence_extraction",
        ]


def test_batch_fallback_keeps_its_first_validation_measurements(recording_tracer) -> None:
    source_id, blocks, document_map = _fixture(4)
    project_id = uuid4()
    EvidenceExtractorService(BatchRunner(mode="cross_block"), batch_size=4).extract_source(
        project_id=project_id,
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
    )

    events = {
        event.subject_id: event
        for event in recording_tracer.sink.events
        if event.name == "corpus.evidence_attempts"
    }
    fallback = events["block-2"].attributes
    assert len(events) == 4
    assert fallback["attempt_count"] == 2
    assert fallback["excerpt_failure_count"] == 1
    assert fallback["salvaged"] is True
    assert fallback["dropped_claim_count"] == 1


def test_first_provider_batch_failure_is_skipped_without_fallback() -> None:
    source_id, blocks, document_map = _fixture(4)
    runner = BatchRunner(mode="provider")
    records, _ = EvidenceExtractorService(runner, batch_size=4).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
    )
    assert all(record.status == "skipped" for record in records)
    assert [stage for stage, _ in runner.calls] == ["evidence_extraction_batch"]


def test_batch_prompt_contract_and_trimmed_payload() -> None:
    source_id, blocks, document_map = _fixture(1)
    bundle = PromptLoader().load_bundle(
        "evidence_extraction_batch",
        {
            "source_id": str(source_id),
            "working_thesis": document_map.working_thesis,
            "analysis_profile": {},
            "block_count": 1,
            "blocks": [{"index": 1, "heading_path": ["Heading"], "text": blocks[0].text}],
        },
    )
    assert bundle.contract.output_model == "BatchEvidenceExtractionDraft"
    assert bundle.contract.model_tier == "fast"
    assert bundle.contract.max_attempts == 3
    assert "BatchEvidenceExtractionDraft" in bundle.system_prompt
    assert "{{" not in bundle.user_prompt
    assert blocks[0].block_id not in bundle.user_prompt


def test_batch_uses_its_latest_contract_when_single_block_version_is_newer() -> None:
    source_id, blocks, document_map = _fixture(4)
    runner = BatchRunner()
    runner.prompt_loader = PromptLoader()  # type: ignore[attr-defined]

    EvidenceExtractorService(runner, batch_size=4).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
        prompt_version="1.3.0",
    )

    assert runner.batch_prompt_versions == [None]


def test_all_fallback_batch_retains_the_successful_batch_run() -> None:
    source_id, blocks, document_map = _fixture(4)
    runner = BatchRunner(mode="empty")

    records, runs = EvidenceExtractorService(runner, batch_size=4).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
    )

    assert all(record.status == "extracted" for record in records)
    assert [stage for stage, _ in runner.calls] == ["evidence_extraction_batch"] + [
        "evidence_extraction"
    ] * 4
    assert [run.stage for run in runs].count("evidence_extraction_batch") == 1
    assert len(runs) == 5


def test_batch_size_setting_and_constructor_are_bounded() -> None:
    assert Settings(environment="test").evidence_extraction_batch_size == 1
    with pytest.raises(ValueError):
        Settings(environment="test", evidence_extraction_batch_size=0)
    with pytest.raises(ValueError, match="batch_size"):
        EvidenceExtractorService(BatchRunner(), batch_size=0)


def test_batch_entry_index_is_one_based() -> None:
    with pytest.raises(ValueError):
        BatchEvidenceEntryDraft(block_index=0, extraction=_draft("enough source text"))


def test_more_claims_available_persists_on_single_block_extraction() -> None:
    source_id, blocks, document_map = _fixture(1)
    records, _ = EvidenceExtractorService(
        BatchRunner(more_claims_available=True),
        batch_size=1,
    ).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
    )
    assert len(records) == 1
    assert records[0].more_claims_available is True


def test_more_claims_available_persists_on_batch_extraction() -> None:
    source_id, blocks, document_map = _fixture(4)
    records, _ = EvidenceExtractorService(
        BatchRunner(more_claims_available=True),
        batch_size=4,
    ).extract_source(
        project_id=uuid4(),
        source_id=source_id,
        blocks=blocks,
        document_map=document_map,
        model="fake",
    )
    assert len(records) == 4
    assert all(record.more_claims_available for record in records)
