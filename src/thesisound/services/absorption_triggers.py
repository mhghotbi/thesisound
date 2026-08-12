"""Pre-committed absorption triggers for spec 12 D6.

Thresholds exist before the data does. Crossing one only emits a structured
warning — it does not change product behaviour. Numbers are provisional and
will move once there is evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from thesisound.script import AbsorbedFault, QualityNote

TriggerId = Literal[
    "grounding_repaired_ratio",
    "ungrounded_claim_consecutive",
    "unknown_claim_any",
    "duration_shortfall_rate",
    "automatic_retries_double",
]


# >20% of substantive turns across 5 consecutive runs → fix the writer prompt.
REPAIRED_RATIO_WINDOW = 5
REPAIRED_RATIO_THRESHOLD = 0.20

# Any occurrence in 2 consecutive runs → investigate extraction/reconciliation.
UNGROUNDED_CONSECUTIVE_RUNS = 2

# >10% of runs in the recent window → the ceiling is too permissive.
DURATION_SHORTFALL_WINDOW = 10
DURATION_SHORTFALL_RATE = 0.10

# Any run needing 2 automatic retries → look at routing first.
AUTOMATIC_RETRIES_TRIGGER = 2


class DegradationCounters(BaseModel):
    """Per-run absorbed-failure counts (spec 12 D6). Kept separate by cause."""

    grounding_repaired: int = Field(default=0, ge=0)
    turn_excised_ungrounded_claim: int = Field(default=0, ge=0)
    turn_excised_unknown_claim: int = Field(default=0, ge=0)
    duration_shortfall: int = Field(default=0, ge=0)
    automatic_retries: int = Field(default=0, ge=0)
    substantive_turn_count: int = Field(default=0, ge=0)


@dataclass(frozen=True, slots=True)
class AbsorptionTriggerHit:
    trigger_id: TriggerId
    detail: str


class _CountedRun(Protocol):
    status: str
    degradation_counters: DegradationCounters


def count_degradation(
    *,
    notes: list[QualityNote],
    faults: list[AbsorbedFault],
    substantive_turn_count: int,
    automatic_retries: int,
) -> DegradationCounters:
    """Build counters from listener notes + operator faults + recovery attempts."""

    ungrounded_turns = {
        fault.detail or fault.subject
        for fault in faults
        if fault.kind == "ungrounded_claim"
    }
    return DegradationCounters(
        grounding_repaired=sum(1 for note in notes if note.kind == "grounding_repaired"),
        turn_excised_ungrounded_claim=len(ungrounded_turns),
        turn_excised_unknown_claim=sum(
            1 for fault in faults if fault.kind == "unknown_claim"
        ),
        duration_shortfall=sum(1 for note in notes if note.kind == "duration_shortfall"),
        automatic_retries=max(0, automatic_retries),
        substantive_turn_count=max(0, substantive_turn_count),
    )


def evaluate_absorption_triggers(
    recent_runs: list[_CountedRun],
) -> list[AbsorptionTriggerHit]:
    """Evaluate D6 triggers against finished runs (newest last)."""

    finished = [run for run in recent_runs if run.status in {"succeeded", "failed"}]
    if not finished:
        return []

    hits: list[AbsorptionTriggerHit] = []
    latest = finished[-1]
    counters = latest.degradation_counters

    if counters.turn_excised_unknown_claim > 0:
        hits.append(
            AbsorptionTriggerHit(
                trigger_id="unknown_claim_any",
                detail=(
                    f"turn_excised_unknown_claim={counters.turn_excised_unknown_claim} "
                    "in the latest run"
                ),
            )
        )

    if counters.automatic_retries >= AUTOMATIC_RETRIES_TRIGGER:
        hits.append(
            AbsorptionTriggerHit(
                trigger_id="automatic_retries_double",
                detail=f"automatic_retries={counters.automatic_retries} in the latest run",
            )
        )

    ungrounded_window = finished[-UNGROUNDED_CONSECUTIVE_RUNS:]
    if (
        len(ungrounded_window) >= UNGROUNDED_CONSECUTIVE_RUNS
        and all(
            run.degradation_counters.turn_excised_ungrounded_claim > 0
            for run in ungrounded_window
        )
    ):
        hits.append(
            AbsorptionTriggerHit(
                trigger_id="ungrounded_claim_consecutive",
                detail=(
                    f"ungrounded_claim present in {UNGROUNDED_CONSECUTIVE_RUNS} "
                    "consecutive runs"
                ),
            )
        )

    repaired_window = finished[-REPAIRED_RATIO_WINDOW:]
    if len(repaired_window) >= REPAIRED_RATIO_WINDOW:
        repaired = sum(
            run.degradation_counters.grounding_repaired for run in repaired_window
        )
        substantive = sum(
            run.degradation_counters.substantive_turn_count for run in repaired_window
        )
        ratio = (repaired / substantive) if substantive else 0.0
        if ratio > REPAIRED_RATIO_THRESHOLD:
            hits.append(
                AbsorptionTriggerHit(
                    trigger_id="grounding_repaired_ratio",
                    detail=(
                        f"grounding_repaired={repaired}/{substantive} "
                        f"({ratio:.1%}) over {REPAIRED_RATIO_WINDOW} runs"
                    ),
                )
            )

    shortfall_window = finished[-DURATION_SHORTFALL_WINDOW:]
    if shortfall_window:
        with_shortfall = sum(
            1
            for run in shortfall_window
            if run.degradation_counters.duration_shortfall > 0
        )
        rate = with_shortfall / len(shortfall_window)
        if rate > DURATION_SHORTFALL_RATE:
            hits.append(
                AbsorptionTriggerHit(
                    trigger_id="duration_shortfall_rate",
                    detail=(
                        f"duration_shortfall in {with_shortfall}/{len(shortfall_window)} "
                        f"runs ({rate:.1%})"
                    ),
                )
            )

    return hits
