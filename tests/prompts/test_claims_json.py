from __future__ import annotations

from thesisound.prompt_loader import PromptLoader


def _claim_payload() -> list[dict[str, object]]:
    return [
        {
            "claim_id": "clm-1",
            "claim": "Action is distinct from fabrication.",
            "claim_type": "author_position",
            "evidence_ids": ["ev-1"],
            "support_status": "contested",
            "qualifications": ["only in the political realm"],
        }
    ]


def test_latest_verifier_is_1_2_0_and_renders_claims() -> None:
    loader = PromptLoader()
    contract = loader.load_contract("script_verifier")
    assert contract.version == "1.2.0"
    bundle = loader.load_bundle(
        "script_verifier",
        {
            "script": {},
            "deterministic_checks": {},
            "episode_plan": {},
            "evidence_packs": [],
            "glossary": {},
            "disagreement_graph": {},
            "claims": _claim_payload(),
            "plan_must_include": [],
            "known_concepts": [],
        },
    )
    assert "<CLAIMS_JSON>" in bundle.user_prompt
    assert "contested" in bundle.user_prompt
    assert "only in the political realm" in bundle.user_prompt
    assert "<PLAN_MUST_INCLUDE_JSON>" in bundle.user_prompt
    assert "<KNOWN_CONCEPTS>" in bundle.user_prompt
    assert "overstated certainty" in bundle.system_prompt
    assert "unsupported specifics" in bundle.system_prompt
    assert "{{" not in bundle.system_prompt + bundle.user_prompt


def test_latest_reviser_is_1_1_0_and_renders_claims() -> None:
    loader = PromptLoader()
    contract = loader.load_contract("script_reviser")
    assert contract.version == "1.1.0"
    bundle = loader.load_bundle(
        "script_reviser",
        {
            "target_turns": [],
            "deterministic_issues": {},
            "verification_issues": {},
            "evidence_packs": [],
            "glossary": {},
            "claims": _claim_payload(),
        },
    )
    assert "<CLAIMS_JSON>" in bundle.user_prompt
    assert "contested" in bundle.user_prompt
    assert "{{" not in bundle.system_prompt + bundle.user_prompt


def test_writer_1_3_0_renders_claims_json() -> None:
    bundle = PromptLoader().load_bundle(
        "persian_script_segment",
        version="1.3.0",
        variables={
            "research_brief": {},
            "segment": {"speaker_dynamic": "questioning"},
            "claims": _claim_payload(),
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
    assert "<CLAIMS_JSON>" in bundle.user_prompt
    assert "contested" in bundle.user_prompt
    assert "only in the political realm" in bundle.user_prompt
    assert "{{" not in bundle.system_prompt + bundle.user_prompt


def _writer_variables() -> dict[str, object]:
    return {
        "research_brief": {"central_question": "What is action?"},
        "segment": {"speaker_dynamic": "questioning"},
        "claims": _claim_payload(),
        "known_concepts": ["praxis"],
        "evidence_pack": {"ev-1": "excerpt"},
        "glossary": {"praxis": "کنش"},
        "disagreement_graph": {"nodes": []},
        "target_word_count": 100,
        "segment_index": 1,
        "segment_count": 1,
        "part_index": 1,
        "part_count": 1,
    }


def test_writer_1_4_0_is_the_default_and_renders_claims_json() -> None:
    bundle = PromptLoader().load_bundle("persian_script_segment", _writer_variables())
    assert bundle.contract.version == "1.4.0"
    assert "<CLAIMS_JSON>" in bundle.user_prompt
    assert "contested" in bundle.user_prompt
    assert "only in the political realm" in bundle.user_prompt
    assert "{{" not in bundle.system_prompt + bundle.user_prompt


def test_writer_1_4_0_puts_every_per_segment_block_after_every_shared_block() -> None:
    """Prefix caching only pays when the constant material is a true prefix.

    RESEARCH_BRIEF, GLOSSARY, DISAGREEMENT_GRAPH and KNOWN_CONCEPTS are identical
    for every segment of a project; SEGMENT, CLAIMS and EVIDENCE_PACK differ per
    call. In 1.3.0 the shared glossary/disagreement/known-concepts blocks sat
    *after* the per-segment ones, so they contributed nothing to the prefix two
    calls have in common -- measured cached_tokens on only 14 of 167 Gemini
    attempts despite 91% of runs re-sending an identical input. Keeping this
    order is the whole point of the version bump, so assert it rather than trust
    it.
    """

    bundle = PromptLoader().load_bundle("persian_script_segment", _writer_variables())
    shared = ("RESEARCH_BRIEF_JSON", "GLOSSARY_JSON", "DISAGREEMENT_GRAPH_JSON", "KNOWN_CONCEPTS")
    per_segment = ("SEGMENT_JSON", "CLAIMS_JSON", "EVIDENCE_PACK_JSON")

    positions = {tag: bundle.user_prompt.index(f"<{tag}>") for tag in shared + per_segment}
    assert max(positions[tag] for tag in shared) < min(positions[tag] for tag in per_segment)


def test_writer_1_4_0_changes_only_block_order_against_1_3_0() -> None:
    """A reorder, not a rewrite: same variables, same closing instruction."""

    import re

    loader = PromptLoader()
    old = loader.load_bundle("persian_script_segment", _writer_variables(), version="1.3.0")
    new = loader.load_bundle("persian_script_segment", _writer_variables(), version="1.4.0")

    assert old.system_prompt == new.system_prompt
    tags = lambda text: sorted(re.findall(r"<([A-Z_]+)>", text))  # noqa: E731
    assert tags(old.user_prompt) == tags(new.user_prompt)
    assert old.user_prompt.strip().splitlines()[-1] == new.user_prompt.strip().splitlines()[-1]
