"""`segment_skeleton.build` (`10b` B1.6; `10c` P3 Step 7)."""

from __future__ import annotations

from thesisound.concepts import ConceptCell, ConceptEdge, LessonPart
from thesisound.domain import ClaimRecord, ClaimType, EvidenceItem, Locator, SupportStatus
from thesisound.services import segment_skeleton

_SOURCE_ID = "11111111-1111-1111-1111-111111111111"


def _cell(cell_key: str, kind: str, block_ids: list[str], *, minutes: float = 4.0) -> ConceptCell:
    return ConceptCell(
        cell_key=cell_key,
        label_fa=f"برچسب {cell_key}",
        kind=kind,  # type: ignore[arg-type]
        tier=1,
        chapter_index=0,
        section_ids=["section-1"],
        block_ids=block_ids,
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=minutes,
    )


def _claim(claim_id: str, evidence_ids: list[str]) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        claim=f"ادعای {claim_id}",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=evidence_ids,
        support_status=SupportStatus.STRONG,
    )


def _evidence(evidence_id: str, block_id: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source_id=_SOURCE_ID,  # type: ignore[arg-type]
        block_id=block_id,
        claim="گزاره",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt="نقل قول",
        locator=Locator(page_start=1, page_end=1),
        support_kind="direct",
        confidence=0.9,
    )


def _part(cell_keys: list[str]) -> LessonPart:
    return LessonPart(
        part_index=1,
        title_fa="بخش ۱",
        cell_keys=cell_keys,
        estimated_minutes=sum(4.0 for _ in cell_keys),
    )


def test_one_segment_per_cell_in_packer_order_with_block_ordered_claims() -> None:
    cells = [
        _cell("ch00-c001", "definition", ["block-1", "block-2"]),
        _cell("ch00-c002", "distinction", ["block-3"]),
    ]
    claims = [
        _claim("clm-2", ["ev-2"]),
        _claim("clm-1", ["ev-1"]),
        _claim("clm-3", ["ev-3"]),
    ]
    evidence = [
        _evidence("ev-1", "block-1"),
        _evidence("ev-2", "block-2"),
        _evidence("ev-3", "block-3"),
    ]
    part = _part(["ch00-c001", "ch00-c002"])

    segments = segment_skeleton.build(part, cells, claims, evidence, edges=[])

    assert [s.segment_index for s in segments] == [1, 2]
    assert segments[0].cell_key == "ch00-c001"
    assert segments[0].claim_ids == ["clm-1", "clm-2"]  # block order, not claim_id order
    assert segments[0].speaker_dynamic == "explanation"
    assert segments[1].cell_key == "ch00-c002"
    assert segments[1].claim_ids == ["clm-3"]
    assert segments[1].speaker_dynamic == "comparison"


def test_speaker_dynamic_follows_cell_kind() -> None:
    by_kind = {
        "definition": "explanation",
        "argument": "explanation",
        "position": "explanation",
        "thread": "explanation",
        "distinction": "comparison",
        "objection": "critique",
        "response": "critique",
        "example": "questioning",
    }
    cells = [
        _cell(f"ch00-c{i:03d}", kind, [f"block-{i}"]) for i, kind in enumerate(by_kind, start=1)
    ]
    claims = [_claim(f"clm-{i}", [f"ev-{i}"]) for i in range(1, len(cells) + 1)]
    evidence = [_evidence(f"ev-{i}", f"block-{i}") for i in range(1, len(cells) + 1)]
    part = _part([cell.cell_key for cell in cells])

    segments = segment_skeleton.build(part, cells, claims, evidence, edges=[])

    assert {s.cell_key: s.speaker_dynamic for s in segments if s.cell_key is not None} == {
        cell.cell_key: by_kind[cell.kind] for cell in cells
    }


def test_cell_with_no_linked_claim_is_skipped_not_emitted_empty() -> None:
    cells = [
        _cell("ch00-c001", "definition", ["block-1"]),
        _cell("ch00-c002", "example", ["block-2"]),
    ]
    claims = [_claim("clm-1", ["ev-1"])]  # nothing links to block-2
    evidence = [_evidence("ev-1", "block-1")]
    part = _part(["ch00-c001", "ch00-c002"])

    segments = segment_skeleton.build(part, cells, claims, evidence, edges=[])

    assert [s.cell_key for s in segments] == ["ch00-c001"]


def test_recap_appended_only_from_three_real_segments() -> None:
    def _fixture(n: int):
        cells = [_cell(f"ch00-c{i:03d}", "definition", [f"block-{i}"]) for i in range(1, n + 1)]
        claims = [_claim(f"clm-{i}", [f"ev-{i}"]) for i in range(1, n + 1)]
        evidence = [_evidence(f"ev-{i}", f"block-{i}") for i in range(1, n + 1)]
        part = _part([cell.cell_key for cell in cells])
        return segment_skeleton.build(part, cells, claims, evidence, edges=[])

    two = _fixture(2)
    three = _fixture(3)

    assert len(two) == 2  # no recap below three
    assert len(three) == 4
    recap = three[-1]
    assert recap.cell_key is None
    assert recap.claim_ids == []
    assert recap.speaker_dynamic == "recap"


def test_prerequisite_claim_ids_only_from_earlier_cells_in_the_same_part() -> None:
    cells = [
        _cell("ch00-c001", "definition", ["block-1"]),
        _cell("ch00-c002", "argument", ["block-2"]),
        _cell("ch00-c003", "argument", ["block-3"]),
    ]
    claims = [
        _claim("clm-1", ["ev-1"]),
        _claim("clm-2", ["ev-2"]),
        _claim("clm-3", ["ev-3"]),
    ]
    evidence = [
        _evidence("ev-1", "block-1"),
        _evidence("ev-2", "block-2"),
        _evidence("ev-3", "block-3"),
    ]
    edges = [
        # ch00-c002 depends on ch00-c001 (earlier in the part): pulled in.
        ConceptEdge(
            source_key="ch00-c001",
            target_key="ch00-c002",
            type="prerequisite",
            weight=1.0,
            confidence=1.0,
            rationale_fa="لازمه است.",
        ),
        # ch00-c003 depends on ch00-c002's prerequisite chain but the edge
        # points at a cell that is NOT in this part -- ignored, not an error.
        ConceptEdge(
            source_key="ch99-c001",
            target_key="ch00-c003",
            type="prerequisite",
            weight=1.0,
            confidence=1.0,
            rationale_fa="لازمه است.",
        ),
    ]
    part = _part(["ch00-c001", "ch00-c002", "ch00-c003"])

    segments = segment_skeleton.build(part, cells, claims, evidence, edges)

    by_cell = {s.cell_key: s for s in segments}
    assert by_cell["ch00-c001"].prerequisite_claim_ids == []
    assert by_cell["ch00-c002"].prerequisite_claim_ids == ["clm-1"]
    assert by_cell["ch00-c003"].prerequisite_claim_ids == []
