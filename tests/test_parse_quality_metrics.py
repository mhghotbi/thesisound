from thesisound.ports import ParsedBlock
from thesisound.services.parse_quality import duplicate_content_ratio


def _block(text: str, *, kind: str = "text") -> ParsedBlock:
    return ParsedBlock(
        source_block_key=text[:20] or "empty",
        text=text,
        page_start=1,
        page_end=1,
        kind=kind,
    )


def test_repeated_short_tokens_do_not_trigger_duplicate_content() -> None:
    blocks = [_block("<pad>", kind="list_item") for _ in range(20)]
    blocks += [_block("the", kind="list_item") for _ in range(10)]
    blocks += [_block("A substantive unique paragraph. " * 8)]

    assert duplicate_content_ratio(blocks) == 0


def test_repeated_substantive_paragraphs_are_weighted_by_character_volume() -> None:
    repeated = "A long duplicated paragraph with enough content to matter. " * 3
    unique = "A different long paragraph with enough content to matter. " * 3
    blocks = [_block(repeated), _block(repeated), _block(unique)]

    ratio = duplicate_content_ratio(blocks)

    assert 0.30 < ratio < 0.36
