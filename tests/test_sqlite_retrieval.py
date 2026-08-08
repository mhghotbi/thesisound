from pathlib import Path
from uuid import uuid4

from thesisound.domain import Locator
from thesisound.services.sqlite_block_retriever import SQLiteBlockRetriever
from thesisound.source_analysis import SourceDocumentBlock


def test_fts_retrieval_returns_relevant_source_block(tmp_path: Path) -> None:
    source_id = uuid4()
    blocks = [
        SourceDocumentBlock(
            block_id="action",
            source_id=source_id,
            locator=Locator(page_start=1, page_end=1),
            heading_path=["کنش"],
            block_type="argument",
            text="کنش در اندیشه آرنت با کثرت انسانی و حضور دیگران پیوند دارد.",
            estimated_token_count=30,
            source_block_keys=["p1"],
        ),
        SourceDocumentBlock(
            block_id="fabrication",
            source_id=source_id,
            locator=Locator(page_start=2, page_end=2),
            heading_path=["ساختن"],
            block_type="argument",
            text="ساختن بر تولید یک شیء و نسبت وسیله و هدف متمرکز است.",
            estimated_token_count=30,
            source_block_keys=["p2"],
        ),
    ]
    retriever = SQLiteBlockRetriever(tmp_path / "blocks.sqlite3")
    retriever.rebuild(blocks)

    hits = retriever.search("کثرت انسانی در کنش", source_ids={source_id})

    assert hits
    assert hits[0].block_id == "action"
    assert hits[0].source_id == source_id
