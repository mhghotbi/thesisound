from uuid import uuid4

import pytest

from thesisound.domain import Locator
from thesisound.ports import ParsedDocument
from thesisound.services.concept_map_builder import detect_chapters
from thesisound.source_analysis import SourceDocumentBlock

_SOURCE_ID = uuid4()
_PARSED_DOCUMENT = ParsedDocument(parser_name="fake", parser_version="0", blocks=[])


def _block(index: int, heading_path: list[str], *, tokens: int = 30) -> SourceDocumentBlock:
    return SourceDocumentBlock(
        block_id=f"b{index:04d}",
        source_id=_SOURCE_ID,
        locator=Locator(),
        heading_path=heading_path,
        block_type="other",
        text=f"block {index}",
        estimated_token_count=tokens,
        source_block_keys=[f"raw-{index}"],
    )


def _blocks_for_headings(heading_paths: list[list[str]]) -> list[SourceDocumentBlock]:
    return [_block(index, path) for index, path in enumerate(heading_paths)]


class TestAgreedDocling:
    """H1 chapters that both detectors read the same way, plus leading front matter."""

    def _blocks(self) -> list[SourceDocumentBlock]:
        heading_paths: list[list[str]] = [[], []]  # front matter, no heading yet
        for title in ("Chapter One", "Chapter Two", "Chapter Three"):
            heading_paths.extend([[title]] * 10)
        return _blocks_for_headings(heading_paths)

    def test_agrees_and_uses_heading_detector(self) -> None:
        chapters = detect_chapters(self._blocks(), _PARSED_DOCUMENT)
        assert [chapter.detection_agreement for chapter in chapters] == ["agreed"] * 3
        assert [chapter.detected_from for chapter in chapters] == ["heading"] * 3
        assert [chapter.title for chapter in chapters] == [
            "Chapter One",
            "Chapter Two",
            "Chapter Three",
        ]
        assert [chapter.chapter_index for chapter in chapters] == [0, 1, 2]

    def test_front_matter_joins_chapter_zero(self) -> None:
        chapters = detect_chapters(self._blocks(), _PARSED_DOCUMENT)
        assert chapters[0].block_ids[:2] == ["b0000", "b0001"]
        assert len(chapters[0].block_ids) == 12
        assert len(chapters[1].block_ids) == 10
        assert len(chapters[2].block_ids) == 10

    def test_estimated_minutes_from_token_sum(self) -> None:
        chapters = detect_chapters(self._blocks(), _PARSED_DOCUMENT)
        assert chapters[0].estimated_minutes == pytest.approx(12 * 30 / 300)


class TestTocOnlyFlatHeading:
    """Two depth-0 headings, wildly uneven -- H rejects them, T does not."""

    def _blocks(self) -> list[SourceDocumentBlock]:
        heading_paths = [["Part A"]] * 25 + [["Part B"]] * 5
        return _blocks_for_headings(heading_paths)

    def test_uses_toc_detector_only(self) -> None:
        chapters = detect_chapters(self._blocks(), _PARSED_DOCUMENT)
        assert [chapter.detected_from for chapter in chapters] == ["toc"] * 2
        assert [chapter.detection_agreement for chapter in chapters] == ["toc_only"] * 2
        assert [chapter.title for chapter in chapters] == ["Part A", "Part B"]
        assert len(chapters[0].block_ids) == 25
        assert len(chapters[1].block_ids) == 5


class TestEpubNavFallsBackToDepthOne:
    """One book title at depth 0 (T finds nothing); real chapters at depth 1."""

    def _blocks(self) -> list[SourceDocumentBlock]:
        heading_paths: list[list[str]] = []
        for title in ("Chapter 1", "Chapter 2", "Chapter 3"):
            heading_paths.extend([["Book", title]] * 12)
        return _blocks_for_headings(heading_paths)

    def test_uses_heading_detector_at_depth_one(self) -> None:
        chapters = detect_chapters(self._blocks(), _PARSED_DOCUMENT)
        assert [chapter.detected_from for chapter in chapters] == ["heading"] * 3
        assert [chapter.detection_agreement for chapter in chapters] == ["heading_only"] * 3
        assert [chapter.heading_path for chapter in chapters] == [
            ["Book", "Chapter 1"],
            ["Book", "Chapter 2"],
            ["Book", "Chapter 3"],
        ]
        assert [chapter.title for chapter in chapters] == ["Chapter 1", "Chapter 2", "Chapter 3"]


class TestDisagreedFallsBackToToc:
    """Depth-0 TOC exists but is uneven; the valid depth-1 split lands elsewhere."""

    def _blocks(self) -> list[SourceDocumentBlock]:
        heading_paths: list[list[str]] = []
        # Depth 0: "Part I" spans 36/40 blocks (90%), "Part II" the rest.
        for index in range(40):
            depth0 = "Part I" if index < 36 else "Part II"
            depth1 = ["Sec A", "Sec B", "Sec C", "Sec D"][index // 10]
            heading_paths.append([depth0, depth1])
        return _blocks_for_headings(heading_paths)

    def test_uses_toc_detector_and_flags_disagreement(self) -> None:
        chapters = detect_chapters(self._blocks(), _PARSED_DOCUMENT)
        assert [chapter.detected_from for chapter in chapters] == ["toc"] * 2
        assert [chapter.detection_agreement for chapter in chapters] == ["disagreed"] * 2
        assert [chapter.title for chapter in chapters] == ["Part I", "Part II"]
        assert len(chapters[0].block_ids) == 36
        assert len(chapters[1].block_ids) == 4


class TestSingleArticleSource:
    """No heading anywhere: neither detector finds chapters."""

    def test_returns_one_chapter(self) -> None:
        blocks = _blocks_for_headings([[]] * 15)
        chapters = detect_chapters(blocks, _PARSED_DOCUMENT)
        assert len(chapters) == 1
        chapter = chapters[0]
        assert chapter.chapter_index == 0
        assert chapter.detected_from == "single"
        assert chapter.detection_agreement == "agreed"
        assert chapter.heading_path == []
        assert len(chapter.block_ids) == 15
        assert chapter.title


class TestEmptyInput:
    def test_raises_on_no_blocks(self) -> None:
        with pytest.raises(ValueError):
            detect_chapters([], _PARSED_DOCUMENT)
