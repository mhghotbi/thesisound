from uuid import uuid4

from thesisound.concepts import ConceptCell
from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    EpisodePlan,
    EpisodeSegment,
    EvidenceItem,
    Locator,
    Script,
    ScriptTurn,
    SupportStatus,
)
from thesisound.services.claim_cell_linkage import cell_coverage_levels, link_claims_to_cells


def _cell(cell_key: str, block_ids: list[str]) -> ConceptCell:
    return ConceptCell(
        cell_key=cell_key,
        label_fa="برچسب",
        kind="argument",
        tier=1,
        chapter_index=int(cell_key[2:4]),
        section_ids=["s001"],
        block_ids=block_ids,
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=4.0,
    )


def _evidence(evidence_id: str, block_id: str) -> EvidenceItem:
    source_id = uuid4()
    return EvidenceItem(
        evidence_id=evidence_id,
        source_id=source_id,
        block_id=block_id,
        claim="Action is distinct from fabrication.",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt="Original grounded passage about action.",
        locator=Locator(page_start=1, page_end=1),
        support_kind="direct",
        confidence=0.9,
    )


def _claim(claim_id: str, evidence_ids: list[str]) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        claim="Action is distinct from fabrication.",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=evidence_ids,
        support_status=SupportStatus.STRONG,
    )


def test_link_claims_to_cells_primary_is_the_earliest_in_book_order() -> None:
    cells = [
        _cell("ch01-c001", ["block-late"]),
        _cell("ch00-c002", ["block-shared"]),
        _cell("ch00-c001", ["block-shared", "block-early"]),
    ]
    claim = _claim("clm-1", ["ev-shared"])
    evidence = [_evidence("ev-shared", "block-shared")]

    linked = link_claims_to_cells([claim], evidence, cells)

    assert linked["clm-1"] == ["ch00-c001", "ch00-c002"]


def test_link_claims_to_cells_omits_unmatched_as_empty() -> None:
    cells = [_cell("ch00-c001", ["block-1"])]
    claim = _claim("clm-orphan", ["ev-elsewhere"])
    evidence = [_evidence("ev-elsewhere", "block-99")]

    linked = link_claims_to_cells([claim], evidence, cells)

    assert linked["clm-orphan"] == []


def test_coverage_levels_extracted_planned_spoken() -> None:
    cells = [
        _cell("ch00-c001", ["block-1"]),
        _cell("ch00-c002", ["block-2"]),
        _cell("ch00-c003", ["block-3"]),
        _cell("ch00-c004", ["block-4"]),
    ]
    claims = [
        _claim("clm-spoken", ["ev-1"]),
        _claim("clm-planned", ["ev-2"]),
        _claim("clm-extracted", ["ev-3"]),
    ]
    evidence = [
        _evidence("ev-1", "block-1"),
        _evidence("ev-2", "block-2"),
        _evidence("ev-3", "block-3"),
    ]
    linkage = link_claims_to_cells(claims, evidence, cells)
    plan = EpisodePlan(
        title="Action",
        listener_outcome="The listener can explain the distinction.",
        estimated_duration_minutes=10,
        segments=[
            EpisodeSegment(
                segment_id="seg-1",
                title="Core",
                purpose="Introduce.",
                estimated_minutes=5,
                claim_ids=["clm-spoken", "clm-planned"],
                key_question="What distinguishes action?",
                speaker_dynamic="explanation",
            )
        ],
    )
    script = Script(
        title="Action",
        turns=[
            ScriptTurn(
                turn_id="t-1",
                segment_id="seg-1",
                speaker="A",
                spoken_text_fa="کنش با ساختن فرق دارد.",
                claim_ids=["clm-spoken"],
                evidence_ids=["ev-1"],
            )
        ],
    )

    coverage = cell_coverage_levels(cells, linkage, plan=plan, script=script)

    assert coverage["ch00-c001"].level == "spoken"
    assert coverage["ch00-c001"].extracted is True
    assert coverage["ch00-c001"].planned is True
    assert coverage["ch00-c001"].spoken is True
    assert coverage["ch00-c002"].level == "planned"
    assert coverage["ch00-c002"].spoken is False
    assert coverage["ch00-c003"].level == "extracted"
    assert coverage["ch00-c003"].planned is False
    assert coverage["ch00-c004"].level is None
    assert coverage["ch00-c004"].extracted is False
