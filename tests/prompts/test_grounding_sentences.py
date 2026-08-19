from __future__ import annotations

from thesisound.prompt_loader import PromptLoader


def test_active_writer_system_prompt_contains_grounding_sentences() -> None:
    bundle = PromptLoader().load_bundle(
        "persian_script_segment",
        {
            "research_brief": {},
            "segment": {"speaker_dynamic": "questioning"},
            "claims": [],
            "known_concepts": [],
            "evidence_pack": {},
            "glossary": {},
            "disagreement_graph": {},
            "target_word_count": 100,
            "segment_index": 1,
            "segment_count": 1,
            "part_index": 1,
            "part_count": 1,
        },
    )
    assert bundle.contract.version == "1.3.0"
    system = bundle.system_prompt
    for sentence in (
        "Never add outside knowledge",
        "editorial_only",
        "analogy",
        "support_status",
        "KNOWN_CONCEPTS",
    ):
        assert sentence in system, f"missing grounding sentence: {sentence!r}"
