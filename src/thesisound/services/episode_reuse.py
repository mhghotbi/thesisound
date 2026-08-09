from __future__ import annotations

import json
from hashlib import sha256
from uuid import UUID

from thesisound.domain import ResearchBrief
from thesisound.source_analysis import EvidenceExtractionPlan


def planning_input_key(
    *,
    source_ids: list[UUID],
    claim_ids: list[str],
    extraction_plans: list[EvidenceExtractionPlan],
    brief: ResearchBrief,
    include_duration: bool,
) -> str:
    """Identify the inputs a planning stage was produced from.

    The corpus enters as the planner actually sees it: which sources, which claims, and
    how deeply each source was mined. `include_duration` is what separates the two
    stages. The coverage audit describes what the corpus can support at all, so a
    shorter requested duration does not change its answer — only whether that answer is
    enough, which is recomputed on reuse. The episode plan is shaped by the requested
    duration, so a new duration is a new plan.
    """

    payload = {
        "source_ids": sorted(str(source_id) for source_id in source_ids),
        "claim_ids": sorted(claim_ids),
        "extraction_plans": sorted(
            json.dumps(plan.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
            for plan in extraction_plans
        ),
        "brief": _brief_payload(brief, include_duration=include_duration),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def _brief_payload(brief: ResearchBrief, *, include_duration: bool) -> dict[str, object]:
    payload = brief.model_dump(mode="json")
    if not include_duration:
        payload.pop("target_duration_minutes", None)
    return payload
