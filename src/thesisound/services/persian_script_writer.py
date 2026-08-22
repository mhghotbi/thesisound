from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from thesisound.domain import EpisodeSegment, ResearchBrief, ScriptTurn
from thesisound.episode import DisagreementGraph, SegmentEvidencePack
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.script import Glossary, SegmentScriptDraft
from thesisound.services.model_runner import ModelRunner

_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class SpeakerBalancePolicy:
    """The deterministic floor under speaker B's role (audit R10).

    Thresholds are calibrated against the 2026-08-09 script: with these values all four
    of its segments fail at least one rule, which is the point -- that script is the
    defect. `min_claims_for_b_substantive` is load-bearing and is not a tunable: in a
    one-claim segment, requiring B to be substantive forces B onto the same claim A just
    used, which is the restatement pattern R10 exists to remove.
    """

    enabled: bool = True
    max_editorial_word_ratio: float = 0.25
    opening_segment_editorial_word_ratio: float = 0.35
    min_claims_for_b_substantive: int = 2
    max_turns_per_claim: int = 2


@dataclass(frozen=True, slots=True)
class SegmentWriteResult:
    turns: list[ScriptTurn]
    draft: SegmentScriptDraft
    record: ModelRunRecord
    violations: list[str]


class PersianScriptWriterService:
    def __init__(
        self,
        model_runner: ModelRunner,
        policy: SpeakerBalancePolicy | None = None,
    ) -> None:
        self.model_runner = model_runner
        self.policy = policy or SpeakerBalancePolicy()

    def write_segment(
        self,
        *,
        project_id: UUID,
        brief: ResearchBrief,
        segment: EpisodeSegment,
        evidence_pack: SegmentEvidencePack,
        glossary: Glossary,
        disagreement_graph: DisagreementGraph,
        model: str,
        prompt_version: str | None = None,
        segment_index: int = 1,
        segment_count: int = 1,
    ) -> SegmentWriteResult:
        allowed_claims = set(segment.claim_ids)
        allowed_evidence = {item.evidence_id for item in evidence_pack.evidence_items}
        attempt = {"n": 0}
        max_attempts = _segment_max_attempts(self.model_runner, prompt_version)
        violations: list[str] = []
        execution = self.model_runner.run(
            project_id=project_id,
            stage=f"script_segment:{segment.segment_id}",
            prompt_name="persian_script_segment",
            variables={
                "research_brief": brief.model_dump(mode="json"),
                "segment": segment.model_dump(mode="json"),
                "claims": [claim.model_dump(mode="json") for claim in evidence_pack.claims],
                "known_concepts": [],
                "evidence_pack": evidence_pack.model_dump(mode="json"),
                "glossary": glossary.model_dump(mode="json"),
                "disagreement_graph": disagreement_graph.model_dump(mode="json"),
                "target_word_count": round(segment.estimated_minutes * 130),
                "segment_index": segment_index,
                "segment_count": segment_count,
                "part_index": 1,
                "part_count": 1,
            },
            output_type=SegmentScriptDraft,
            model=model,
            prompt_version=prompt_version,
            validator=lambda draft: _validate_segment_draft(
                draft,
                allowed_claim_ids=allowed_claims,
                allowed_evidence_ids=allowed_evidence,
                segment=segment,
                policy=self.policy,
                is_opening=segment_index == 1,
                attempt=attempt,
                max_attempts=max_attempts,
                violations=violations,
            ),
        )
        turns = [
            ScriptTurn(
                turn_id=f"{segment.segment_id}-turn-{index:03d}",
                segment_id=segment.segment_id,
                speaker=turn.speaker,
                spoken_text_fa=turn.spoken_text_fa.strip(),
                claim_ids=turn.claim_ids,
                evidence_ids=turn.evidence_ids,
                editorial_only=turn.editorial_only,
            )
            for index, turn in enumerate(execution.output.turns, start=1)
        ]
        return SegmentWriteResult(
            turns=turns,
            draft=execution.output,
            record=execution.record,
            violations=violations,
        )


def _validate_segment_draft(
    draft: SegmentScriptDraft,
    *,
    allowed_claim_ids: set[str],
    allowed_evidence_ids: set[str],
    segment: EpisodeSegment | None = None,
    policy: SpeakerBalancePolicy | None = None,
    is_opening: bool = True,
    attempt: dict[str, int] | None = None,
    max_attempts: int = 1,
    violations: list[str] | None = None,
) -> None:
    if not draft.turns:
        raise DeterministicValidationError("Segment script contains no turns.")
    for index, turn in enumerate(draft.turns, start=1):
        unknown_claims = sorted(set(turn.claim_ids) - allowed_claim_ids)
        if unknown_claims:
            raise DeterministicValidationError(
                f"Turn {index} uses claims outside the segment: {', '.join(unknown_claims)}"
            )
        unknown_evidence = sorted(set(turn.evidence_ids) - allowed_evidence_ids)
        if unknown_evidence:
            raise DeterministicValidationError(
                f"Turn {index} uses evidence outside the pack: {', '.join(unknown_evidence)}"
            )
        if turn.editorial_only and (turn.claim_ids or turn.evidence_ids):
            raise DeterministicValidationError(
                f"Editorial turn {index} must not carry claim or evidence IDs."
            )

    if segment is None:
        return
    effective_policy = policy or SpeakerBalancePolicy()
    if not effective_policy.enabled:
        return
    counter = attempt if attempt is not None else {"n": 0}
    recorded_violations = violations if violations is not None else []
    counter["n"] += 1
    failures = _speaker_balance_failures(
        draft,
        segment,
        effective_policy,
        is_opening=is_opening,
    )
    if not failures:
        return
    if counter["n"] < max_attempts:
        raise DeterministicValidationError("; ".join(failures))
    # Final attempt: a stylistic floor must never abort a script build. Record it instead;
    # ScriptChecker turns these into high-severity issues so the gate revises rather than ships.
    recorded_violations.extend(failures)


def _speaker_balance_failures(
    draft: SegmentScriptDraft,
    segment: EpisodeSegment,
    policy: SpeakerBalancePolicy,
    *,
    is_opening: bool,
) -> list[str]:
    """Return speaker-balance floor failures in stable F1/F2/F3 order."""

    if not policy.enabled:
        return []
    if not segment.claim_ids:
        # A claimless segment (the skeleton's trailing recap, `10c` P3 Step 7) has
        # no claims to ground turns in, so it is expected to be near-entirely
        # editorial -- F1's ratio cap assumes a claim-bearing segment and would
        # otherwise reject every recap draft by construction, not by any real
        # writing defect. F2/F3 already pass vacuously here (no claims to require
        # B substance for, or to repeat), so this only needs to skip F1.
        return []
    total_words = sum(len(_WORD.findall(turn.spoken_text_fa)) for turn in draft.turns)
    editorial_words = sum(
        len(_WORD.findall(turn.spoken_text_fa))
        for turn in draft.turns
        if turn.editorial_only
    )
    failures: list[str] = []
    ratio = editorial_words / total_words if total_words else 0.0
    maximum = (
        policy.opening_segment_editorial_word_ratio
        if is_opening
        else policy.max_editorial_word_ratio
    )
    if ratio > maximum:
        failures.append(
            "F1 editorial words are "
            f"{ratio:.1%} of segment words; maximum is {maximum:.1%}."
        )

    if len(segment.claim_ids) >= policy.min_claims_for_b_substantive and not any(
        turn.speaker == "B" and not turn.editorial_only for turn in draft.turns
    ):
        failures.append(
            "F2 speaker B needs at least one substantive turn when the segment has "
            f"at least {policy.min_claims_for_b_substantive} claims."
        )

    claim_turns: Counter[str] = Counter(
        claim_id for turn in draft.turns for claim_id in set(turn.claim_ids)
    )
    repeated = [
        f"{claim_id} ({count})"
        for claim_id, count in sorted(claim_turns.items())
        if count > policy.max_turns_per_claim
    ]
    if repeated:
        failures.append(
            "F3 claims appear in more than "
            f"{policy.max_turns_per_claim} turns: {', '.join(repeated)}."
        )
    return failures


def _segment_max_attempts(model_runner: ModelRunner, prompt_version: str | None) -> int:
    loader = getattr(model_runner, "prompt_loader", None)
    if loader is None:
        return 2
    return loader.load_contract("persian_script_segment", version=prompt_version).max_attempts
