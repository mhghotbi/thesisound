from __future__ import annotations

from threading import Barrier, Lock
from time import perf_counter
from uuid import UUID, uuid4

import pytest

from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    EvidenceExtraction,
    EvidenceItem,
    Locator,
    SupportStatus,
)
from thesisound.modeling import (
    DeterministicValidationError,
    ModelExecution,
    ModelRunRecord,
)
from thesisound.prompt_loader import PromptLoader
from thesisound.services.claim_reconciler import (
    ClaimReconcilerService,
    _apply_merge_groups,
    _claim_id,
    _materialize_ledger,
    _partition_evidence,
    _validate_draft,
    _validate_merge_draft,
)
from thesisound.source_analysis import (
    BlockEvidenceExtraction,
    ClaimDraft,
    ClaimMergeDraft,
    ClaimMergeGroup,
    ClaimReconciliationDraft,
)


class _FakeRunner:
    """Reconciles every evidence item into one claim, unresolving none."""

    def __init__(self) -> None:
        self.called = False
        self.calls: list[str] = []
        self._lock = Lock()

    def run(
        self,
        *,
        project_id: UUID,
        stage: str,
        variables: dict[str, object],
        output_type,
        model: str,
        validator=None,
        **_: object,
    ):
        with self._lock:
            self.called = True
            self.calls.append(stage)
        if output_type is ClaimReconciliationDraft:
            evidence = variables["evidence_items"]
            assert isinstance(evidence, list)
            output = ClaimReconciliationDraft(
                claims=[
                    ClaimDraft(
                        claim=str(evidence[0]["claim"]),
                        claim_type=ClaimType.AUTHOR_POSITION,
                        evidence_ids=[item["evidence_id"] for item in evidence],
                        support_status=SupportStatus.STRONG,
                    )
                ]
            )
        elif output_type is ClaimMergeDraft:
            output = ClaimMergeDraft()
        else:
            raise AssertionError(f"Unexpected output type: {output_type}")
        if validator is not None:
            validator(output)
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


class _MergingRunner(_FakeRunner):
    """Like _FakeRunner, but merges every claim ID into one group when asked."""

    def run(self, **kwargs):
        if kwargs["output_type"] is ClaimMergeDraft:
            claims = kwargs["variables"]["claims"]
            assert isinstance(claims, list)
            claim_ids = [str(item["claim_id"]) for item in claims]
            output = ClaimMergeDraft(
                merge_groups=[ClaimMergeGroup(claim_ids=claim_ids)]
                if len(claim_ids) >= 2
                else []
            )
            if kwargs.get("validator") is not None:
                kwargs["validator"](output)
            record = ModelRunRecord(
                project_id=kwargs["project_id"],
                stage=kwargs["stage"],
                prompt_id=kwargs["stage"],
                prompt_version="test",
                prompt_hash="test",
                input_hash="test",
                provider="fake",
                model=kwargs["model"],
                output_model="ClaimMergeDraft",
                status="succeeded",
            )
            with self._lock:
                self.called = True
                self.calls.append(kwargs["stage"])
            return ModelExecution(output=output, record=record)
        return super().run(**kwargs)


class _ConcurrentBatchRunner(_FakeRunner):
    """Records in-flight batch concurrency; barriers post-probe batches."""

    def __init__(self, parties: int, timeout: float = 5.0) -> None:
        super().__init__()
        self.barrier = Barrier(parties, timeout=timeout)
        self._intervals_lock = Lock()
        self.intervals: list[tuple[float, float]] = []
        self.peak_in_flight = 0
        self._in_flight = 0

    def run(self, **kwargs):
        is_batch = kwargs["output_type"] is ClaimReconciliationDraft
        started = perf_counter()
        if is_batch:
            with self._intervals_lock:
                self._in_flight += 1
                self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        try:
            if is_batch and len(self.intervals) >= 1:
                self.barrier.wait()
            return super().run(**kwargs)
        finally:
            if is_batch:
                with self._intervals_lock:
                    self._in_flight -= 1
                    self.intervals.append((started, perf_counter()))


def _locator(page: int) -> Locator:
    return Locator(page_start=page, page_end=page)


def _claim_evidence(
    source_id: UUID,
    block_id: str,
    evidence_id: str,
    *,
    claim: str = "Action occurs directly between persons.",
    excerpt: str | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source_id=source_id,
        block_id=block_id,
        claim=claim,
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt=excerpt or f"{claim} in the text.",
        locator=_locator(1),
        support_kind="direct",
        confidence=0.9,
    )


def _extraction_records(
    source_id: UUID,
    evidence: list[EvidenceItem],
) -> list[BlockEvidenceExtraction]:
    return [
        BlockEvidenceExtraction(
            source_id=source_id,
            block_id=item.block_id,
            extraction=EvidenceExtraction(
                segment_function="argument",
                claims=[item],
            ),
        )
        for item in evidence
    ]


def test_reconcile_preserves_claim_level_must_not_be_lost_when_no_evidence_survives() -> None:
    """Extraction 2.0: a block can extract zero claims and still hold no fallback aux state."""

    source_id = uuid4()
    extraction = EvidenceExtraction(segment_function="argument", claims=[])
    records = [
        BlockEvidenceExtraction(source_id=source_id, block_id="block-01", extraction=extraction),
    ]

    ledger, _ = ClaimReconcilerService(_FakeRunner()).reconcile(
        project_id=uuid4(),
        source_id=source_id,
        extractions=records,
        model="fake",
    )

    assert ledger.claims == []
    assert ledger.definitions == []
    assert ledger.must_not_be_lost == []


def test_reconcile_skip_model_promotes_evidence_one_to_one() -> None:
    source_id = uuid4()
    runner = _FakeRunner()
    records = [
        BlockEvidenceExtraction(
            source_id=source_id,
            block_id="block-01",
            extraction=EvidenceExtraction(
                segment_function="argument",
                claims=[
                    _claim_evidence(source_id, "block-01", "ev-a"),
                    EvidenceItem(
                        evidence_id="ev-b",
                        source_id=source_id,
                        block_id="block-01",
                        claim="Action is distinguished from fabrication.",
                        claim_type=ClaimType.DISTINCTION,
                        supporting_excerpt="Plurality is the condition of action in the text.",
                        locator=_locator(1),
                        support_kind="inferential",
                        confidence=0.6,
                        qualifications=["Within the political realm."],
                        must_not_be_lost=True,
                        contrast=("Action", "Fabrication"),
                    ),
                ],
            ),
        ),
    ]

    ledger, runs = ClaimReconcilerService(runner).reconcile(
        project_id=uuid4(),
        source_id=source_id,
        extractions=records,
        model="fake-strong",
        skip_model=True,
    )

    assert runner.called is False
    assert len(runs) == 1
    assert runs[0].provider == "none"
    assert len(ledger.claims) == 2
    assert [claim.evidence_ids for claim in ledger.claims] == [["ev-a"], ["ev-b"]]
    assert ledger.claims[0].support_status == SupportStatus.STRONG
    assert ledger.claims[1].support_status == SupportStatus.MODERATE
    assert ledger.claims[1].qualifications == ["Within the political realm."]
    assert ledger.claims[0].must_not_be_lost is False
    assert ledger.claims[1].must_not_be_lost is True
    assert ledger.claims[1].contrast == ("Action", "Fabrication")
    assert ledger.warnings == ["Claim reconciliation skipped for single-source project."]


def test_partition_evidence_single_batch_when_under_budget() -> None:
    source_id = uuid4()
    evidence = [
        _claim_evidence(source_id, "b1", "ev-a"),
        _claim_evidence(source_id, "b2", "ev-b", claim="Plurality conditions action."),
    ]
    total = sum(len(item.model_dump_json()) for item in evidence)

    batches = _partition_evidence(evidence, maximum_characters=total)

    assert len(batches) == 1
    assert batches[0] is evidence


def test_partition_evidence_splits_on_character_budget() -> None:
    source_id = uuid4()
    evidence = [
        _claim_evidence(
            source_id,
            f"b{index}",
            f"ev-{index}",
            claim=f"Claim number {index}.",
            excerpt="x" * 200,
        )
        for index in range(4)
    ]
    item_size = len(evidence[0].model_dump_json())

    batches = _partition_evidence(evidence, maximum_characters=item_size + 10)

    assert len(batches) == 4
    assert [item.evidence_id for batch in batches for item in batch] == [
        item.evidence_id for item in evidence
    ]


def test_partition_evidence_rejects_item_larger_than_budget() -> None:
    source_id = uuid4()
    evidence = [
        _claim_evidence(
            source_id,
            "b1",
            "ev-oversized",
            claim="Oversized claim.",
            excerpt="x" * 500,
        ),
        _claim_evidence(source_id, "b2", "ev-small", claim="Fits easily."),
    ]
    oversized = len(evidence[0].model_dump_json())

    with pytest.raises(ValueError, match="ev-oversized"):
        _partition_evidence(evidence, maximum_characters=oversized - 1)


def test_partition_evidence_covers_every_id_exactly_once() -> None:
    source_id = uuid4()
    evidence = [
        _claim_evidence(
            source_id,
            f"b{index}",
            f"ev-{index}",
            claim=f"Distinct claim {index}.",
            excerpt="y" * 150,
        )
        for index in range(5)
    ]
    item_size = len(evidence[0].model_dump_json())

    batches = _partition_evidence(evidence, maximum_characters=item_size * 2 + 20)

    flattened = [item.evidence_id for batch in batches for item in batch]
    assert flattened == [item.evidence_id for item in evidence]
    assert len(flattened) == len(set(flattened))
    assert len(batches) >= 2


def test_reconcile_single_batch_matches_current_output() -> None:
    source_id = uuid4()
    runner = _FakeRunner()
    evidence = [
        _claim_evidence(source_id, "b1", "ev-a"),
        _claim_evidence(source_id, "b2", "ev-b", claim="Action discloses the agent."),
    ]
    records = _extraction_records(source_id, evidence)

    ledger, runs = ClaimReconcilerService(
        runner,
        maximum_batch_characters=1_000_000,
    ).reconcile(
        project_id=uuid4(),
        source_id=source_id,
        extractions=records,
        model="fake",
    )

    assert runner.calls == ["claim_reconciliation"]
    assert len(runs) == 1
    assert runs[0].stage == "claim_reconciliation"
    assert len(ledger.claims) == 1
    assert set(ledger.claims[0].evidence_ids) == {"ev-a", "ev-b"}


def test_reconcile_multi_batch_issues_one_merge_call() -> None:
    source_id = uuid4()
    runner = _FakeRunner()
    evidence = [
        _claim_evidence(
            source_id,
            f"b{index}",
            f"ev-{index}",
            claim=f"Claim {index} about action.",
            excerpt="z" * 300,
        )
        for index in range(3)
    ]
    item_size = len(evidence[0].model_dump_json())
    records = _extraction_records(source_id, evidence)

    ledger, runs = ClaimReconcilerService(
        runner,
        maximum_batch_characters=item_size + 10,
        max_workers=1,
    ).reconcile(
        project_id=uuid4(),
        source_id=source_id,
        extractions=records,
        model="fake",
    )

    assert runner.calls.count("claim_reconciliation") == 3
    assert runner.calls.count("claim_reconciliation_merge") == 1
    assert [run.stage for run in runs] == [
        "claim_reconciliation",
        "claim_reconciliation",
        "claim_reconciliation",
        "claim_reconciliation_merge",
    ]
    assert len({run.run_id for run in runs}) == 4
    assert len(ledger.claims) == 3
    all_evidence = {eid for claim in ledger.claims for eid in claim.evidence_ids}
    assert all_evidence == {f"ev-{index}" for index in range(3)}


def test_reconcile_multi_batch_never_sends_full_evidence_set() -> None:
    source_id = uuid4()
    sizes: list[int] = []

    class _SizeRecordingRunner(_FakeRunner):
        def run(self, **kwargs):
            if kwargs["output_type"] is ClaimReconciliationDraft:
                evidence = kwargs["variables"]["evidence_items"]
                assert isinstance(evidence, list)
                sizes.append(len(evidence))
            return super().run(**kwargs)

    runner = _SizeRecordingRunner()
    evidence = [
        _claim_evidence(
            source_id,
            f"b{index}",
            f"ev-{index}",
            claim=f"Claim {index}.",
            excerpt="w" * 250,
        )
        for index in range(4)
    ]
    item_size = len(evidence[0].model_dump_json())
    ClaimReconcilerService(
        runner,
        maximum_batch_characters=item_size + 10,
        max_workers=1,
    ).reconcile(
        project_id=uuid4(),
        source_id=source_id,
        extractions=_extraction_records(source_id, evidence),
        model="fake",
    )

    assert sizes
    assert all(size < 4 for size in sizes)
    assert sum(sizes) == 4


def test_merge_group_unifies_evidence_and_source_ids() -> None:
    source_id = uuid4()
    first = ClaimRecord(
        claim_id="clm-a",
        claim="Action is disclosure.",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=["ev-1"],
        support_status=SupportStatus.STRONG,
        agreeing_source_ids=[source_id],
    )
    second = ClaimRecord(
        claim_id="clm-b",
        claim="Action discloses the agent.",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=["ev-2"],
        support_status=SupportStatus.MODERATE,
        agreeing_source_ids=[source_id],
    )
    draft = ClaimMergeDraft(
        merge_groups=[
            ClaimMergeGroup(claim_ids=["clm-a", "clm-b"], canonical_claim_id="clm-a")
        ]
    )

    merged = _apply_merge_groups(source_id, [[first], [second]], draft)

    assert len(merged) == 1
    assert merged[0].evidence_ids == ["ev-1", "ev-2"]
    assert merged[0].agreeing_source_ids == [source_id]
    assert merged[0].claim == "Action is disclosure."
    assert merged[0].support_status == SupportStatus.STRONG
    assert merged[0].claim_id == _claim_id(
        source_id, "Action is disclosure.", ["ev-1", "ev-2"]
    )


def test_merge_group_uses_canonical_claim_id() -> None:
    source_id = uuid4()
    earlier = ClaimRecord(
        claim_id="clm-early",
        claim="Earlier wording.",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=["ev-1"],
        support_status=SupportStatus.MODERATE,
        qualifications=["From batch one."],
        agreeing_source_ids=[source_id],
        term=None,
    )
    later = ClaimRecord(
        claim_id="clm-late",
        claim="Later wording, more qualified.",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=["ev-2"],
        support_status=SupportStatus.STRONG,
        qualifications=["From batch two."],
        agreeing_source_ids=[source_id],
        must_not_be_lost=True,
        term="Action",
        contrast=("Action", "Labor"),
    )
    draft = ClaimMergeDraft(
        merge_groups=[
            ClaimMergeGroup(
                claim_ids=["clm-late", "clm-early"],
                canonical_claim_id="clm-late",
            )
        ]
    )

    merged = _apply_merge_groups(source_id, [[earlier], [later]], draft)

    assert len(merged) == 1
    assert merged[0].claim == "Later wording, more qualified."
    assert merged[0].claim_type == ClaimType.AUTHOR_POSITION
    assert merged[0].support_status == SupportStatus.STRONG
    assert merged[0].qualifications == ["From batch two.", "From batch one."]
    assert merged[0].must_not_be_lost is True
    assert merged[0].term == "Action"
    assert merged[0].contrast == ("Action", "Labor")
    assert merged[0].claim_id == _claim_id(
        source_id, "Later wording, more qualified.", ["ev-2", "ev-1"]
    )


def test_merge_rejects_mixed_claim_types() -> None:
    with pytest.raises(DeterministicValidationError, match="mix claim_type"):
        _validate_merge_draft(
            ClaimMergeDraft(
                merge_groups=[
                    ClaimMergeGroup(
                        claim_ids=["clm-a", "clm-b"],
                        canonical_claim_id="clm-a",
                    )
                ]
            ),
            known_ids={"clm-a", "clm-b"},
            claim_types={
                "clm-a": ClaimType.DEFINITION,
                "clm-b": ClaimType.AUTHOR_POSITION,
            },
        )


def test_reconcile_rejects_mixed_claim_types() -> None:
    source_id = uuid4()
    evidence_by_id = {
        "ev-def": EvidenceItem(
            evidence_id="ev-def",
            source_id=source_id,
            block_id="block-01",
            claim="Action is defined as beginning.",
            claim_type=ClaimType.DEFINITION,
            supporting_excerpt="Action is defined as beginning.",
            locator=_locator(1),
            support_kind="direct",
            confidence=0.9,
            term="Action",
        ),
        "ev-pos": _claim_evidence(source_id, "block-01", "ev-pos"),
    }
    draft = ClaimReconciliationDraft(
        claims=[
            ClaimDraft(
                claim="Action is beginning and occurs between persons.",
                claim_type=ClaimType.DEFINITION,
                evidence_ids=["ev-def", "ev-pos"],
                support_status=SupportStatus.STRONG,
            )
        ]
    )

    with pytest.raises(DeterministicValidationError, match="different claim_type"):
        _validate_draft(draft, evidence_by_id)


def test_materialize_ledger_carries_must_not_be_lost_term_and_contrast() -> None:
    source_id = uuid4()
    evidence_by_id = {
        "ev-a": EvidenceItem(
            evidence_id="ev-a",
            source_id=source_id,
            block_id="block-01",
            claim="Action is beginning.",
            claim_type=ClaimType.DEFINITION,
            supporting_excerpt="Action is beginning.",
            locator=_locator(1),
            support_kind="direct",
            confidence=0.9,
            qualifications=["In the political realm."],
            must_not_be_lost=False,
            term=None,
        ),
        "ev-b": EvidenceItem(
            evidence_id="ev-b",
            source_id=source_id,
            block_id="block-02",
            claim="Action means beginning something new.",
            claim_type=ClaimType.DEFINITION,
            supporting_excerpt="Action means beginning something new.",
            locator=_locator(2),
            support_kind="direct",
            confidence=0.8,
            qualifications=["Not labor."],
            must_not_be_lost=True,
            term="Action",
            contrast=("Action", "Labor"),
        ),
    }
    draft = ClaimReconciliationDraft(
        claims=[
            ClaimDraft(
                claim="Action is beginning something new.",
                claim_type=ClaimType.DEFINITION,
                evidence_ids=["ev-a", "ev-b"],
                support_status=SupportStatus.STRONG,
                qualifications=["As natality."],
            )
        ]
    )

    ledger = _materialize_ledger(source_id, draft, evidence_by_id)

    assert len(ledger.claims) == 1
    assert ledger.claims[0].must_not_be_lost is True
    assert ledger.claims[0].term == "Action"
    assert ledger.claims[0].contrast == ("Action", "Labor")
    assert ledger.claims[0].qualifications == [
        "As natality.",
        "In the political realm.",
        "Not labor.",
    ]


def test_merge_rejects_unknown_claim_id() -> None:
    with pytest.raises(DeterministicValidationError, match="unknown claim ID"):
        _validate_merge_draft(
            ClaimMergeDraft(merge_groups=[ClaimMergeGroup(claim_ids=["clm-a", "clm-missing"])]),
            known_ids={"clm-a", "clm-b"},
        )


def test_merge_rejects_claim_id_in_two_groups() -> None:
    with pytest.raises(DeterministicValidationError, match="more than one merge group"):
        _validate_merge_draft(
            ClaimMergeDraft(
                merge_groups=[
                    ClaimMergeGroup(claim_ids=["clm-a", "clm-b"]),
                    ClaimMergeGroup(claim_ids=["clm-b", "clm-c"]),
                ]
            ),
            known_ids={"clm-a", "clm-b", "clm-c"},
        )


def test_batches_run_concurrently_up_to_worker_limit() -> None:
    source_id = uuid4()
    evidence = [
        _claim_evidence(
            source_id,
            f"b{index}",
            f"ev-{index}",
            claim=f"Concurrent claim {index}.",
            excerpt="c" * 280,
        )
        for index in range(4)
    ]
    item_size = len(evidence[0].model_dump_json())
    # Probe + 3 post-probe batches; barrier parties = 3.
    runner = _ConcurrentBatchRunner(parties=3)
    ClaimReconcilerService(
        runner,
        maximum_batch_characters=item_size + 10,
        max_workers=3,
    ).reconcile(
        project_id=uuid4(),
        source_id=source_id,
        extractions=_extraction_records(source_id, evidence),
        model="fake",
    )

    assert runner.calls.count("claim_reconciliation") == 4
    assert runner.calls.count("claim_reconciliation_merge") == 1
    assert runner.peak_in_flight <= 3
    assert runner.peak_in_flight >= 2


def test_skip_model_condition_unchanged_even_when_evidence_would_batch() -> None:
    source_id = uuid4()
    runner = _FakeRunner()
    evidence = [
        _claim_evidence(
            source_id,
            f"b{index}",
            f"ev-{index}",
            claim=f"Skip claim {index}.",
            excerpt="s" * 300,
        )
        for index in range(3)
    ]
    item_size = len(evidence[0].model_dump_json())

    ledger, runs = ClaimReconcilerService(
        runner,
        maximum_batch_characters=item_size + 10,
        max_workers=4,
    ).reconcile(
        project_id=uuid4(),
        source_id=source_id,
        extractions=_extraction_records(source_id, evidence),
        model="fake",
        skip_model=True,
    )

    assert runner.calls == []
    assert len(runs) == 1
    assert runs[0].provider == "none"
    assert len(ledger.claims) == 3


def test_reconcile_multi_batch_merge_unifies_matching_claims() -> None:
    source_id = uuid4()
    runner = _MergingRunner()
    evidence = [
        _claim_evidence(
            source_id,
            f"b{index}",
            f"ev-{index}",
            claim="Same proposition across batches.",
            excerpt="m" * 300,
        )
        for index in range(2)
    ]
    item_size = len(evidence[0].model_dump_json())

    ledger, _ = ClaimReconcilerService(
        runner,
        maximum_batch_characters=item_size + 10,
        max_workers=1,
    ).reconcile(
        project_id=uuid4(),
        source_id=source_id,
        extractions=_extraction_records(source_id, evidence),
        model="fake",
    )

    assert len(ledger.claims) == 1
    assert set(ledger.claims[0].evidence_ids) == {"ev-0", "ev-1"}


def test_latest_reconciliation_prompts_are_1_1_0() -> None:
    loader = PromptLoader()
    recon = loader.load_bundle(
        "claim_reconciliation",
        {"source_id": "source", "evidence_items": []},
    )
    merge = loader.load_bundle(
        "claim_reconciliation_merge",
        {"source_id": "source", "batch_count": 2, "claims": []},
    )
    assert recon.contract.version == "1.1.0"
    assert merge.contract.version == "1.1.0"
    assert "Never merge claims of different claim_type" in recon.system_prompt
    assert "canonical_claim_id" in merge.system_prompt
    older = loader.load_bundle(
        "claim_reconciliation",
        {"source_id": "source", "evidence_items": []},
        version="1.0.0",
    )
    assert "Never merge claims of different claim_type" not in older.system_prompt
