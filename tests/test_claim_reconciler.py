from __future__ import annotations

from uuid import UUID, uuid4

from thesisound.domain import (
    ClaimType,
    EvidenceExtraction,
    EvidenceItem,
    ExtractedAuxiliaryPoint,
    ExtractedDefinition,
    ExtractedDistinction,
    Locator,
    MustNotBeLostPoint,
    SupportStatus,
)
from thesisound.modeling import ModelExecution, ModelRunRecord
from thesisound.services.claim_reconciler import ClaimReconcilerService
from thesisound.source_analysis import (
    BlockEvidenceExtraction,
    ClaimDraft,
    ClaimReconciliationDraft,
)


class _FakeRunner:
    """Reconciles every evidence item into one claim, unresolving none."""

    def __init__(self) -> None:
        self.called = False

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
        self.called = True
        assert output_type is ClaimReconciliationDraft
        evidence = variables["evidence_items"]
        assert isinstance(evidence, list)
        output = ClaimReconciliationDraft(
            claims=[
                ClaimDraft(
                    claim="Action occurs directly between persons.",
                    claim_type=ClaimType.AUTHOR_POSITION,
                    evidence_ids=[item["evidence_id"] for item in evidence],
                    support_status=SupportStatus.STRONG,
                )
            ]
        )
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


def _locator(page: int) -> Locator:
    return Locator(page_start=page, page_end=page)


def _claim_evidence(source_id: UUID, block_id: str, evidence_id: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source_id=source_id,
        block_id=block_id,
        claim="Action occurs directly between persons.",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt="Action occurs directly between persons in the text.",
        locator=_locator(1),
        support_kind="direct",
        confidence=0.9,
    )


def test_reconcile_deduplicates_auxiliary_evidence_across_and_within_blocks() -> None:
    source_id = uuid4()
    block_a, block_b = "block-01", "block-02"

    extraction_a = EvidenceExtraction(
        segment_function="argument",
        claims=[_claim_evidence(source_id, block_a, "ev-a")],
        definitions=[
            ExtractedDefinition(
                term="Action",
                definition="Direct disclosure between persons.",
                source_id=source_id,
                block_id=block_a,
                locator=_locator(1),
            ),
        ],
        distinctions=[
            ExtractedDistinction(
                item_a="Action",
                item_b="Fabrication",
                distinction="Action cannot be repeated identically.",
                source_id=source_id,
                block_id=block_a,
                locator=_locator(1),
            ),
        ],
        examples=[
            ExtractedAuxiliaryPoint(
                text="Speech in the assembly.",
                source_id=source_id,
                block_id=block_a,
                locator=_locator(1),
            ),
        ],
        objections=[
            ExtractedAuxiliaryPoint(
                text="Some deny action is distinct from labor.",
                source_id=source_id,
                block_id=block_a,
                locator=_locator(1),
            ),
        ],
        responses=[
            ExtractedAuxiliaryPoint(
                text="The distinction rests on plurality, not effort.",
                source_id=source_id,
                block_id=block_a,
                locator=_locator(1),
            ),
        ],
        # Exact same-block repeat: must collapse to one.
        must_not_be_lost=[
            MustNotBeLostPoint(
                text="The link between action and plurality.",
                source_id=source_id,
                block_id=block_a,
                locator=_locator(1),
            ),
            MustNotBeLostPoint(
                text="The link between action and plurality.",
                source_id=source_id,
                block_id=block_a,
                locator=_locator(1),
            ),
        ],
    )
    extraction_b = EvidenceExtraction(
        segment_function="argument",
        claims=[_claim_evidence(source_id, block_b, "ev-b")],
        # Exact duplicate of block_a's definition: must collapse to one.
        definitions=[
            ExtractedDefinition(
                term="Action",
                definition="Direct disclosure between persons.",
                source_id=source_id,
                block_id=block_b,
                locator=_locator(2),
            ),
            ExtractedDefinition(
                term="Fabrication",
                definition="Making an object according to a model.",
                source_id=source_id,
                block_id=block_b,
                locator=_locator(2),
            ),
        ],
        # Exact duplicate example text: must collapse to one.
        examples=[
            ExtractedAuxiliaryPoint(
                text="Speech in the assembly.",
                source_id=source_id,
                block_id=block_b,
                locator=_locator(2),
            ),
        ],
        # Same text as block_a, but a different block: must NOT collapse.
        must_not_be_lost=[
            MustNotBeLostPoint(
                text="The link between action and plurality.",
                source_id=source_id,
                block_id=block_b,
                locator=_locator(2),
            ),
        ],
    )
    records = [
        BlockEvidenceExtraction(source_id=source_id, block_id=block_a, extraction=extraction_a),
        BlockEvidenceExtraction(source_id=source_id, block_id=block_b, extraction=extraction_b),
    ]

    ledger, _ = ClaimReconcilerService(_FakeRunner()).reconcile(
        project_id=uuid4(),
        source_id=source_id,
        extractions=records,
        model="fake",
    )

    assert [item.term for item in ledger.definitions] == ["Action", "Fabrication"]
    assert len(ledger.distinctions) == 1
    assert [item.text for item in ledger.examples] == ["Speech in the assembly."]
    assert len(ledger.objections) == 1
    assert len(ledger.responses) == 1
    assert len(ledger.must_not_be_lost) == 2
    assert {item.block_id for item in ledger.must_not_be_lost} == {block_a, block_b}
    assert all(
        item.text == "The link between action and plurality." for item in ledger.must_not_be_lost
    )


def test_reconcile_preserves_auxiliary_evidence_when_no_claims() -> None:
    """Regression test: a block can have claims=[] but real definitions/must_not_be_lost."""

    source_id = uuid4()
    extraction = EvidenceExtraction(
        segment_function="argument",
        claims=[],
        definitions=[
            ExtractedDefinition(
                term="Action",
                definition="Direct disclosure between persons.",
                source_id=source_id,
                block_id="block-01",
                locator=_locator(1),
            ),
        ],
        must_not_be_lost=[
            MustNotBeLostPoint(
                text="The link between action and plurality.",
                source_id=source_id,
                block_id="block-01",
                locator=_locator(1),
            ),
        ],
    )
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
    assert [item.term for item in ledger.definitions] == ["Action"]
    assert [item.text for item in ledger.must_not_be_lost] == [
        "The link between action and plurality."
    ]


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
                        claim="Plurality is the condition of action.",
                        claim_type=ClaimType.AUTHOR_POSITION,
                        supporting_excerpt="Plurality is the condition of action in the text.",
                        locator=_locator(1),
                        support_kind="inferential",
                        confidence=0.6,
                        qualifications=["Within the political realm."],
                    ),
                ],
            ),
        ),
    ]

    ledger, run = ClaimReconcilerService(runner).reconcile(
        project_id=uuid4(),
        source_id=source_id,
        extractions=records,
        model="fake-strong",
        skip_model=True,
    )

    assert runner.called is False
    assert run.provider == "none"
    assert len(ledger.claims) == 2
    assert [claim.evidence_ids for claim in ledger.claims] == [["ev-a"], ["ev-b"]]
    assert ledger.claims[0].support_status == SupportStatus.STRONG
    assert ledger.claims[1].support_status == SupportStatus.MODERATE
    assert ledger.claims[1].qualifications == ["Within the political realm."]
    assert ledger.warnings == ["Claim reconciliation skipped for single-source project."]
