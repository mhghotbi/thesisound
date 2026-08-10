from __future__ import annotations

from thesisound.prompt_loader import PromptLoader
from thesisound.services.document_mapper import _merge_section_payload
from thesisound.source_analysis import DocumentMapDraftSection


def _merge_variables(*, block_id: str = "block") -> tuple[dict[str, object], list[str]]:
    section_ids = [
        f"part-{part_number:04d}:sec-{letter}"
        for part_number in (1, 2)
        for letter in ("a", "b", "c")
    ]
    partitions = []
    for part_number in (1, 2):
        sections = [
            DocumentMapDraftSection(
                section_id=f"part-{part_number:04d}:sec-{letter}",
                source_block_ids=[block_id],
                title=f"Section {letter}",
                function="argument",
            )
            for letter in ("a", "b", "c")
        ]
        partitions.append(
            {
                "part_number": part_number,
                "scope": {},
                "working_thesis": f"Thesis {part_number}",
                "sections": [_merge_section_payload(section) for section in sections],
                "cross_section_threads": [],
                "warnings": [],
            }
        )
    return {
        "source_id": "source",
        "partition_count": 2,
        "partitions": partitions,
    }, section_ids


def test_merge_prompt_carries_every_partition_section_id() -> None:
    variables, section_ids = _merge_variables()
    bundle = PromptLoader().load_bundle("document_map_merge", variables)
    assert all(section_id in bundle.user_prompt for section_id in section_ids)
    partition_count = bundle.user_prompt.split("<PARTITION_COUNT>", 1)[1].split(
        "</PARTITION_COUNT>", 1
    )[0]
    assert "2" in partition_count


def test_merge_prompt_has_no_unsubstituted_token() -> None:
    variables, _ = _merge_variables()
    bundle = PromptLoader().load_bundle("document_map_merge", variables)
    assert "| tojson" not in bundle.user_prompt
    assert "{{" not in bundle.user_prompt


def test_merge_prompt_omits_block_ids() -> None:
    variables, _ = _merge_variables(block_id="blk-should-not-leak")
    bundle = PromptLoader().load_bundle("document_map_merge", variables)
    assert "blk-should-not-leak" not in bundle.user_prompt
    assert "block_count" in bundle.user_prompt


def test_document_map_merge_default_version_is_1_1_0() -> None:
    contract = PromptLoader().load_contract("document_map_merge")
    assert contract.version == "1.1.0"
    assert contract.output_model == "DocumentMapMergeDraft"
    assert contract.max_attempts == 2
