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
        {
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
