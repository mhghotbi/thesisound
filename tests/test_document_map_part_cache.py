from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from thesisound.domain import Locator
from thesisound.services.document_identity import partition_block_key
from thesisound.services.document_map_part_cache import (
    PART_BUILDER_VERSION,
    CachedDocumentMapPart,
    CachedPartitionSection,
    DocumentMapPartCache,
)
from thesisound.source_analysis import (
    DocumentMapDraft,
    DocumentMapDraftSection,
    SourceDocumentBlock,
)


def _blocks() -> list[SourceDocumentBlock]:
    source_id = uuid4()
    return [
        SourceDocumentBlock(
            block_id=f"block-{index}",
            source_id=source_id,
            locator=Locator(page_start=index, page_end=index),
            heading_path=["Chapter one"],
            block_type="argument",
            text=f"Semantic content {index}.",
            estimated_token_count=10,
            source_block_keys=[f"source-{index}"],
        )
        for index in range(1, 3)
    ]


def _draft(blocks: list[SourceDocumentBlock]) -> DocumentMapDraft:
    return DocumentMapDraft(
        working_thesis="A complete argument.",
        sections=[
            DocumentMapDraftSection(
                section_id="section",
                source_block_ids=[block.block_id for block in blocks],
                title="Argument",
                function="argument",
                key_concepts=["argument"],
            )
        ],
    )


def _cached_payload(content_key: str, blocks: list[SourceDocumentBlock]) -> dict[str, object]:
    return CachedDocumentMapPart(
        content_key=content_key,
        builder_version=PART_BUILDER_VERSION,
        block_count=len(blocks),
        working_thesis="A complete argument.",
        sections=[
            CachedPartitionSection(
                section_id="section",
                block_indexes=list(range(len(blocks))),
                title="Argument",
                function="argument",
                key_concepts=["argument"],
            )
        ],
    ).model_dump(mode="json")


def test_builder_version_mismatch_is_a_miss(tmp_path: Path) -> None:
    blocks = _blocks()
    content_key = partition_block_key(blocks)
    cache = DocumentMapPartCache(tmp_path)
    payload = _cached_payload(content_key, blocks)
    payload["builder_version"] = PART_BUILDER_VERSION + 1
    path = cache.path(content_key)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert cache.load(content_key, blocks) is None


@pytest.mark.parametrize(
    "stored_state",
    [
        "absent",
        "not json",
        "wrong schema",
        "wrong content key",
        "wrong block count",
        "out-of-range index",
        "empty sections",
        "empty blocks",
    ],
)
def test_load_never_raises_for_inconsistent_stored_states(
    tmp_path: Path,
    stored_state: str,
) -> None:
    blocks = _blocks()
    content_key = partition_block_key(blocks)
    cache = DocumentMapPartCache(tmp_path)
    path = cache.path(content_key)
    payload: object = _cached_payload(content_key, blocks)

    if stored_state == "not json":
        payload = "not json"
    elif stored_state == "wrong schema":
        payload = {"a": 1}
    elif stored_state == "wrong content key":
        assert isinstance(payload, dict)
        payload["content_key"] = "0" * 64
    elif stored_state == "wrong block count":
        assert isinstance(payload, dict)
        payload["block_count"] = len(blocks) + 1
    elif stored_state == "out-of-range index":
        assert isinstance(payload, dict)
        sections = payload["sections"]
        assert isinstance(sections, list)
        assert isinstance(sections[0], dict)
        sections[0]["block_indexes"] = [len(blocks)]
    elif stored_state == "empty sections":
        assert isinstance(payload, dict)
        payload["sections"] = []

    if stored_state not in {"absent", "empty blocks"}:
        path.parent.mkdir(parents=True)
        path.write_text(
            payload if isinstance(payload, str) else json.dumps(payload),
            encoding="utf-8",
        )

    supplied_blocks = [] if stored_state == "empty blocks" else blocks
    assert cache.load(content_key, supplied_blocks) is None


@pytest.mark.parametrize("content_key", ["../etc/passwd", "short", ""])
def test_path_rejects_non_sha256_keys(tmp_path: Path, content_key: str) -> None:
    with pytest.raises(ValueError):
        DocumentMapPartCache(tmp_path).path(content_key)


def test_save_refuses_draft_referencing_an_out_of_partition_block(tmp_path: Path) -> None:
    blocks = _blocks()
    content_key = partition_block_key(blocks)
    cache = DocumentMapPartCache(tmp_path)
    draft = _draft(blocks)
    draft.sections[0].source_block_ids.append("outside-this-partition")

    assert cache.save(content_key, blocks, draft) is None
    assert not cache.path(content_key).exists()


def test_save_is_atomic_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    blocks = _blocks()
    content_key = partition_block_key(blocks)
    cache = DocumentMapPartCache(tmp_path)

    assert cache.save(content_key, blocks, _draft(blocks)) == cache.path(content_key)
    assert list(cache.root.glob("*.tmp")) == []
