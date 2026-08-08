from __future__ import annotations

import re
from collections import Counter
from uuid import UUID

from thesisound.domain import ClaimRecord, EpisodePlan, Script
from thesisound.episode import SegmentEvidencePack
from thesisound.script import Glossary, ScriptCheckIssue, ScriptCheckReport

_WORD = re.compile(r"\w+", re.UNICODE)
_PROMPT_LEAKAGE = (
    "system prompt",
    "repair_instruction",
    "research_brief_json",
    "evidence_pack_json",
    "as an ai",
    "به عنوان یک مدل زبانی",
)


class ScriptChecker:
    def __init__(self, *, words_per_minute: int = 130) -> None:
        self.words_per_minute = words_per_minute

    def check(
        self,
        *,
        project_id: UUID,
        script: Script,
        episode_plan: EpisodePlan,
        evidence_packs: list[SegmentEvidencePack],
        claims: list[ClaimRecord],
        glossary: Glossary,
    ) -> ScriptCheckReport:
        issues: list[ScriptCheckIssue] = []
        segment_by_id = {segment.segment_id: segment for segment in episode_plan.segments}
        pack_by_segment = {pack.segment_id: pack for pack in evidence_packs}
        claim_by_id = {claim.claim_id: claim for claim in claims}

        seen_text: Counter[str] = Counter()
        consecutive_speaker = 0
        previous_speaker: str | None = None
        for turn in script.turns:
            segment = segment_by_id.get(turn.segment_id)
            pack = pack_by_segment.get(turn.segment_id)
            if segment is None or pack is None:
                issues.append(
                    ScriptCheckIssue(
                        turn_id=turn.turn_id,
                        segment_id=turn.segment_id,
                        severity="blocking",
                        issue_type="other",
                        explanation=(
                            "Turn references an unknown segment or missing evidence pack."
                        ),
                    )
                )
                continue
            unknown_claims = sorted(set(turn.claim_ids) - set(segment.claim_ids))
            if unknown_claims:
                issues.append(
                    ScriptCheckIssue(
                        turn_id=turn.turn_id,
                        segment_id=turn.segment_id,
                        severity="blocking",
                        issue_type="claim_outside_segment",
                        explanation="Turn uses claims outside its segment: "
                        + ", ".join(unknown_claims),
                    )
                )
            allowed_pack_evidence = {item.evidence_id for item in pack.evidence_items}
            unknown_evidence = sorted(set(turn.evidence_ids) - allowed_pack_evidence)
            if unknown_evidence:
                issues.append(
                    ScriptCheckIssue(
                        turn_id=turn.turn_id,
                        segment_id=turn.segment_id,
                        severity="blocking",
                        issue_type="evidence_outside_pack",
                        explanation="Turn uses evidence outside its pack: "
                        + ", ".join(unknown_evidence),
                    )
                )
            expected_evidence: set[str] = set()
            for claim_id in turn.claim_ids:
                claim = claim_by_id.get(claim_id)
                if claim is None:
                    issues.append(
                        ScriptCheckIssue(
                            turn_id=turn.turn_id,
                            segment_id=turn.segment_id,
                            severity="blocking",
                            issue_type="unknown_claim",
                            explanation=f"Turn references unknown claim {claim_id}.",
                        )
                    )
                else:
                    expected_evidence.update(claim.evidence_ids)
            has_linked_evidence = bool(set(turn.evidence_ids) & expected_evidence)
            if not turn.editorial_only and not has_linked_evidence:
                issues.append(
                    ScriptCheckIssue(
                        turn_id=turn.turn_id,
                        segment_id=turn.segment_id,
                        severity="blocking",
                        issue_type="missing_grounding",
                        explanation=(
                            "Substantive turn has no evidence linked to its claim IDs."
                        ),
                    )
                )

            normalized = " ".join(turn.spoken_text_fa.casefold().split())
            seen_text[normalized] += 1
            if any(marker in normalized for marker in _PROMPT_LEAKAGE):
                issues.append(
                    ScriptCheckIssue(
                        turn_id=turn.turn_id,
                        segment_id=turn.segment_id,
                        severity="blocking",
                        issue_type="prompt_leakage",
                        explanation=(
                            "Turn appears to expose pipeline instructions or prompt markers."
                        ),
                    )
                )
            if turn.speaker == previous_speaker:
                consecutive_speaker += 1
            else:
                previous_speaker = turn.speaker
                consecutive_speaker = 1
            if consecutive_speaker > 3:
                issues.append(
                    ScriptCheckIssue(
                        turn_id=turn.turn_id,
                        segment_id=turn.segment_id,
                        severity="low",
                        issue_type="speaker_pattern",
                        explanation="More than three consecutive turns use the same speaker.",
                    )
                )

        for normalized, count in seen_text.items():
            if count > 1 and len(normalized) > 20:
                issues.append(
                    ScriptCheckIssue(
                        severity="high",
                        issue_type="repetition",
                        explanation=f"A spoken turn is repeated {count} times.",
                    )
                )

        joined = " ".join(turn.spoken_text_fa for turn in script.turns)
        for term in glossary.terms:
            source_used = term.source_term.casefold() in joined.casefold()
            preferred_missing = term.preferred_persian not in joined
            if source_used and preferred_missing:
                issues.append(
                    ScriptCheckIssue(
                        severity="high",
                        issue_type="glossary_inconsistency",
                        explanation=(
                            f"Source term '{term.source_term}' appears without preferred Persian "
                            f"form '{term.preferred_persian}'."
                        ),
                    )
                )

        word_count = len(_WORD.findall(joined))
        estimated_minutes = word_count / self.words_per_minute if word_count else 0
        target = episode_plan.estimated_duration_minutes
        if target and not target * 0.8 <= estimated_minutes <= target * 1.2:
            issues.append(
                ScriptCheckIssue(
                    severity="high",
                    issue_type="duration_mismatch",
                    explanation=(
                        f"Estimated duration is {estimated_minutes:.1f} minutes; "
                        f"episode plan targets {target:.1f}."
                    ),
                )
            )

        if any(issue.severity == "blocking" for issue in issues):
            verdict = "reject"
        elif any(issue.severity in {"high", "medium"} for issue in issues):
            verdict = "revise"
        else:
            verdict = "pass"
        return ScriptCheckReport(
            project_id=project_id,
            verdict=verdict,
            issues=issues,
            word_count=word_count,
            estimated_minutes=round(estimated_minutes, 2),
            substantive_turn_count=sum(not turn.editorial_only for turn in script.turns),
        )
