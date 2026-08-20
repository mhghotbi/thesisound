from __future__ import annotations

from thesisound.services.excerpt_matching import locate_excerpt, locate_excerpt_span


def test_excerpt_matching_repairs_typographic_variants() -> None:
    cases = [
        (
            'She called it “action” in the chapter clearly.',
            'She called it "action" in the chapter clearly.',
        ),
        (
            "The span runs from 1933–1945 in exile abroad.",
            "The span runs from 1933-1945 in exile abroad.",
        ),
        (
            "The argument continues… into the next section.",
            "The argument continues... into the next section.",
        ),
        (
            "Action\u00a0occurs between persons in plurality.",
            "Action occurs between persons in plurality.",
        ),
        (
            "کتاب\u200cها در برابر اشیاء قرار می‌گیرند اینجا.",
            "کتابها در برابر اشیاء قرار می‌گیرند اینجا.",
        ),
        (
            "این یک یای فارسی است در متن بلند.",
            "این یک يای فارسی است در متن بلند.",
        ),
    ]
    for source, model_excerpt in cases:
        located = locate_excerpt(model_excerpt, source)
        assert located == source
        assert located != model_excerpt
        span = locate_excerpt_span(model_excerpt, source)
        assert span == (0, len(source))
        assert source[span[0] : span[1]] == source


def test_excerpt_matching_rejects_invented_text() -> None:
    source = "Action occurs directly between persons in the public realm."
    assert locate_excerpt("This sentence is invented entirely.", source) is None
    assert locate_excerpt_span("This sentence is invented entirely.", source) is None


def test_locate_excerpt_span_mid_string_and_digits() -> None:
    source = "پیش‌گفتار ۱۲۳ سپس ادامهٔ متن."
    excerpt = "123 سپس"
    span = locate_excerpt_span(excerpt, source)
    assert span is not None
    start, end = span
    assert "۱۲۳" in source[start:end] or "123" in source[start:end]
    assert locate_excerpt(excerpt, source) == source[start:end]


def test_locate_excerpt_span_zwnj_variant() -> None:
    source = "کتاب\u200cها مهم هستند در این بحث بلند."
    excerpt = "کتابها مهم هستند"
    span = locate_excerpt_span(excerpt, source)
    assert span is not None
    assert locate_excerpt(excerpt, source) == source[span[0] : span[1]]


def test_measure_excerpt_coverage_scores_only_extracted_blocks() -> None:
    """The extraction plan records coverage per extracted block (10c P2 Step 2).

    A skipped block is absent rather than 0.0: it has no claims, and a zero would
    read downstream as a thin extraction instead of a missing one.
    """

    from uuid import UUID

    from thesisound.domain import ClaimType, EvidenceExtraction, EvidenceItem, Locator
    from thesisound.services.source_analysis_service import _measure_excerpt_coverage
    from thesisound.source_analysis import BlockEvidenceExtraction, SourceDocumentBlock

    source_id = UUID("11111111-1111-1111-1111-111111111111")

    def block(block_id: str, text: str) -> SourceDocumentBlock:
        return SourceDocumentBlock(
            block_id=block_id,
            source_id=source_id,
            locator=Locator(page_start=1, page_end=1),
            heading_path=["Chapter"],
            block_type="other",
            text=text,
            estimated_token_count=10,
            source_block_keys=[block_id],
        )

    def record(
        block_id: str, excerpts: list[str], status: str
    ) -> BlockEvidenceExtraction:
        claims = [
            EvidenceItem(
                evidence_id=f"{block_id}-{index}",
                source_id=source_id,
                block_id=block_id,
                claim="A claim.",
                claim_type=ClaimType.AUTHOR_POSITION,
                supporting_excerpt=excerpt,
                locator=Locator(page_start=1, page_end=1),
                support_kind="direct",
                confidence=0.9,
            )
            for index, excerpt in enumerate(excerpts)
        ]
        return BlockEvidenceExtraction(
            source_id=source_id,
            block_id=block_id,
            extraction=EvidenceExtraction(segment_function="argument", claims=claims),
            status=status,  # type: ignore[arg-type]
        )

    blocks = [
        block("blk-half", "AAAABBBB"),
        block("blk-none", "CCCCDDDD"),
        block("blk-skipped", "EEEEFFFF"),
    ]
    records = [
        record("blk-half", ["AAAA"], "extracted"),
        record("blk-none", [], "extracted"),
        record("blk-skipped", [], "skipped"),
    ]

    coverage = _measure_excerpt_coverage(blocks, records)

    assert coverage == {"blk-half": 0.5, "blk-none": 0.0}
    assert "blk-skipped" not in coverage


def test_measure_excerpt_coverage_counts_overlapping_excerpts_once() -> None:
    from uuid import UUID

    from thesisound.domain import ClaimType, EvidenceExtraction, EvidenceItem, Locator
    from thesisound.services.source_analysis_service import _measure_excerpt_coverage
    from thesisound.source_analysis import BlockEvidenceExtraction, SourceDocumentBlock

    source_id = UUID("22222222-2222-2222-2222-222222222222")
    text = "The public realm is common to all."
    claims = [
        EvidenceItem(
            evidence_id=f"e{index}",
            source_id=source_id,
            block_id="blk",
            claim="A claim.",
            claim_type=ClaimType.AUTHOR_POSITION,
            supporting_excerpt=excerpt,
            locator=Locator(page_start=1, page_end=1),
            support_kind="direct",
            confidence=0.9,
        )
        # The second excerpt sits wholly inside the first.
        for index, excerpt in enumerate(["The public realm", "public realm"])
    ]
    coverage = _measure_excerpt_coverage(
        [
            SourceDocumentBlock(
                block_id="blk",
                source_id=source_id,
                locator=Locator(page_start=1, page_end=1),
                heading_path=["Chapter"],
                block_type="other",
                text=text,
                estimated_token_count=10,
                source_block_keys=["blk"],
            )
        ],
        [
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id="blk",
                extraction=EvidenceExtraction(
                    segment_function="argument", claims=claims
                ),
                status="extracted",
            )
        ],
    )

    assert coverage["blk"] == len("The public realm") / len(text)
