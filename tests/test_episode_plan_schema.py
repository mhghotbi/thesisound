from __future__ import annotations

from pydantic import BaseModel, Field

from thesisound.adapters.models.gemini import gemini_response_json_schema
from thesisound.domain import EpisodePlan
from thesisound.episode import EpisodePlanDraft


def _has_key(node: object, key: str) -> bool:
    if isinstance(node, dict):
        if key in node:
            return True
        return any(_has_key(value, key) for value in node.values())
    if isinstance(node, list):
        return any(_has_key(value, key) for value in node)
    return False


def test_episode_plan_draft_schema_is_gemini_safe() -> None:
    schema = gemini_response_json_schema(EpisodePlanDraft)
    assert not _has_key(schema, "additionalProperties")
    assert not _has_key(schema, "exclusiveMinimum")
    assert not _has_key(schema, "exclusiveMaximum")
    omitted = schema["properties"]["deliberately_omitted_claims"]
    assert omitted["type"] == "array"
    assert "$ref" in omitted["items"]
    target_minutes = schema["$defs"]["EpisodeSegmentDraft"]["properties"]["target_minutes"]
    assert target_minutes["type"] == "number"
    assert target_minutes["minimum"] > 0


def test_gemini_schema_rewrites_exclusive_integer_bounds() -> None:
    class Bounds(BaseModel):
        count: int = Field(gt=0, lt=10)

    schema = gemini_response_json_schema(Bounds)
    count = schema["properties"]["count"]
    assert count["minimum"] == 1
    assert count["maximum"] == 9
    assert "exclusiveMinimum" not in count
    assert "exclusiveMaximum" not in count


def test_episode_plan_accepts_legacy_omitted_claim_map() -> None:
    plan = EpisodePlan.model_validate(
        {
            "title": "Title",
            "listener_outcome": "Outcome",
            "estimated_duration_minutes": 10,
            "segments": [
                {
                    "segment_id": "seg-001",
                    "title": "Segment",
                    "purpose": "Purpose",
                    "estimated_minutes": 10,
                    "claim_ids": ["c1"],
                    "key_question": "Why?",
                    "speaker_dynamic": "explanation",
                }
            ],
            "deliberately_omitted_claims": {"c2": "Out of scope for this duration"},
        }
    )
    assert len(plan.deliberately_omitted_claims) == 1
    assert plan.deliberately_omitted_claims[0].claim_id == "c2"
    assert plan.deliberately_omitted_claims[0].reason == "Out of scope for this duration"
