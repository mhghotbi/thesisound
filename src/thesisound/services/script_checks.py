from __future__ import annotations

import re
from collections import Counter
from uuid import UUID

from thesisound.domain import ClaimRecord, EpisodePlan, Script, ScriptTurn
from thesisound.episode import MustNotBeLostReview, SegmentEvidencePack
from thesisound.script import Glossary, ScriptCheckIssue, ScriptCheckReport
from thesisound.services.excerpt_matching import normalize_for_match

_WORD = re.compile(r"\w+", re.UNICODE)
_ZWNJ = "\u200c"
_SENTENCE_END = re.compile(r"[.!?؟۔…]")
_DIGIT_RUN = re.compile(r"\d{2,}")
_FOUR_DIGIT_YEAR = re.compile(r"\d{4}")
_LATIN_CAPITALISED = re.compile(r"(?<![A-Za-z])[A-Z][A-Za-z]+(?![A-Za-z])")
_GUILLEMET_SPAN = re.compile(r"«([^»]+)»")
_ASCII_QUOTE_SPAN = re.compile(r'"([^"]+)"')
_CURLY_DOUBLE_QUOTES = (
    "\u201c",
    "\u201d",
    "\u201e",
    "\u201f",
)


def _normalize_spoken(text: str) -> str:
    collapsed = text.replace(_ZWNJ, "").casefold()
    return " ".join(collapsed.split())


_FILLER_PHRASES = tuple(
    sorted(
        (
            _normalize_spoken(phrase)
            for phrase in (
                "بله، دقیقاً",
                "دقیقاً همین‌طور است",
                "کاملاً درست است",
                "همین‌طور است",
                "نکته جالب",
                "بسیار خوب",
                "درست است",
                "در واقع",
                "دقیقاً",
            )
        ),
        key=len,
        reverse=True,
    )
)
_PROMPT_LEAKAGE = (
    "system prompt",
    "repair_instruction",
    "research_brief_json",
    "evidence_pack_json",
    "as an ai",
    "به عنوان یک مدل زبانی",
)

_EDITORIAL_RATIO_MAX = 0.25
_SPEAKER_SKEW_MAX = 2.0
_SPEAKER_B_SUBSTANTIVE_MIN_RATIO = 0.25
_FILLER_RATE_HIGH = 0.20
_TRIGRAM_JACCARD_HIGH = 0.6
_OPENING_TOKEN_COUNT = 4
# A quoted span shorter than this is terminology, not a citation. Digits, years
# and Latin names are checked regardless of length -- a fabricated date is a
# date whether or not anyone put quotes around it.
_QUOTED_SPAN_MIN_WORDS = 4
_DROPPED_CONTENT_HIGH_RATIO = 0.25


def _first_sentence(normalized: str) -> str:
    match = _SENTENCE_END.search(normalized)
    if match is None:
        return normalized
    return normalized[: match.start()].strip()


def _tokens(normalized: str) -> list[str]:
    return _WORD.findall(normalized)


def _trigrams(tokens: list[str]) -> set[tuple[str, str, str]]:
    if len(tokens) < 3:
        return set()
    return {(tokens[i], tokens[i + 1], tokens[i + 2]) for i in range(len(tokens) - 2)}


def _jaccard(left: set[tuple[str, str, str]], right: set[tuple[str, str, str]]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union)


def _is_substantive_turn(turn: ScriptTurn) -> bool:
    return bool(turn.claim_ids or turn.evidence_ids)


def _filler_in_first_sentence(normalized: str) -> str | None:
    first = _first_sentence(normalized)
    return next((phrase for phrase in _FILLER_PHRASES if phrase in first), None)


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
        speaker_balance_violations: dict[str, list[str]] | None = None,
        must_not_be_lost_review: MustNotBeLostReview | None = None,
        single_speaker: bool = False,
    ) -> ScriptCheckReport:
        issues: list[ScriptCheckIssue] = []
        glossary_forms = _glossary_forms(glossary)
        segment_by_id = {segment.segment_id: segment for segment in episode_plan.segments}
        pack_by_segment = {pack.segment_id: pack for pack in evidence_packs}
        claim_by_id = {claim.claim_id: claim for claim in claims}

        consecutive_speaker = 0
        previous_speaker: str | None = None
        speaker_words: Counter[str] = Counter()
        speaker_b_turn_count = 0
        speaker_b_substantive_turn_count = 0
        filler_open_count = 0
        normalized_turns: list[tuple[ScriptTurn, str, list[str]]] = []

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
            # Plan placement, not grounding. A claim used in a neighbouring
            # segment is still a real, grounded, traceable claim -- what differs
            # is which segment the plan assigned it to. Dropping the citation
            # would be wrong (the spoken text really is about that claim) and
            # excising the turn would delete good content over bookkeeping, so
            # this reports and the episode ships with its structure slightly off
            # the approved plan.
            unknown_claims = sorted(set(turn.claim_ids) - set(segment.claim_ids))
            if unknown_claims:
                issues.append(
                    ScriptCheckIssue(
                        turn_id=turn.turn_id,
                        segment_id=turn.segment_id,
                        severity="low",
                        issue_type="claim_outside_segment",
                        explanation="Turn uses claims outside its segment: "
                        + ", ".join(unknown_claims),
                    )
                )
            # A pack holds exactly the evidence of its segment's claims, so this
            # is the same event as the check above seen from the evidence side --
            # and remediation's repair, which rewrites evidence_ids from claim
            # provenance, is itself a source of it. It cannot admit fabricated
            # ids: after remediation every substantive turn's evidence is
            # ledger-derived by construction. The source-trace view resolves
            # evidence from the source store, not from the pack, so an
            # out-of-pack citation still traces for the reader.
            allowed_pack_evidence = {item.evidence_id for item in pack.evidence_items}
            unknown_evidence = sorted(set(turn.evidence_ids) - allowed_pack_evidence)
            if unknown_evidence:
                issues.append(
                    ScriptCheckIssue(
                        turn_id=turn.turn_id,
                        segment_id=turn.segment_id,
                        severity="low",
                        issue_type="evidence_outside_pack",
                        explanation="Turn uses evidence outside its pack: "
                        + ", ".join(unknown_evidence),
                    )
                )
            expected_evidence: set[str] = set()
            for claim_id in turn.claim_ids:
                claim = claim_by_id.get(claim_id)
                if claim is None:
                    # Same invariant, same tripwire: remediation drops invented
                    # ids before this runs, so reaching here is a defect report,
                    # not a gate. See the note below the loop.
                    issues.append(
                        ScriptCheckIssue(
                            turn_id=turn.turn_id,
                            segment_id=turn.segment_id,
                            severity="low",
                            issue_type="unknown_claim",
                            explanation=f"Turn references unknown claim {claim_id}.",
                        )
                    )
                else:
                    expected_evidence.update(claim.evidence_ids)
            turn_evidence = set(turn.evidence_ids)
            has_linked_evidence = bool(turn_evidence & expected_evidence)
            # Grounding is enforced upstream now, by remediate_script_grounding:
            # a turn that reaches here has either been repaired against the
            # ledger or excised. These two checks are therefore a tripwire on
            # that invariant, not the gate that holds it -- so they record at
            # `low` and never stop a build. If either fires, remediation and
            # this checker disagree, which is a defect to investigate in the
            # ledger, not a reason to destroy the user's episode.
            if not turn.editorial_only and not has_linked_evidence:
                issues.append(
                    ScriptCheckIssue(
                        turn_id=turn.turn_id,
                        segment_id=turn.segment_id,
                        severity="low",
                        issue_type="missing_grounding",
                        explanation=(
                            "Substantive turn has no evidence linked to its claim IDs."
                        ),
                    )
                )
            unlinked_evidence = sorted(turn_evidence - expected_evidence)
            if not turn.editorial_only and unlinked_evidence:
                issues.append(
                    ScriptCheckIssue(
                        turn_id=turn.turn_id,
                        segment_id=turn.segment_id,
                        severity="low",
                        issue_type="evidence_unlinked_to_claim",
                        explanation=(
                            "Turn cites evidence not linked to its claim IDs: "
                            + ", ".join(unlinked_evidence)
                        ),
                    )
                )
            if not turn.editorial_only:
                issues.extend(
                    _unsupported_specifics_issues(turn, pack, glossary_forms)
                )

            normalized = _normalize_spoken(turn.spoken_text_fa)
            tokens = _tokens(normalized)
            normalized_turns.append((turn, normalized, tokens))
            speaker_words[turn.speaker] += len(_WORD.findall(turn.spoken_text_fa))
            if turn.speaker == "B":
                speaker_b_turn_count += 1
                if not turn.editorial_only:
                    speaker_b_substantive_turn_count += 1

            if not _is_substantive_turn(turn):
                opener = _filler_in_first_sentence(normalized)
                if opener is not None:
                    filler_open_count += 1
                    issues.append(
                        ScriptCheckIssue(
                            turn_id=turn.turn_id,
                            segment_id=turn.segment_id,
                            # Style, not correctness -- recorded for later
                            # polish, not blocking (MVP policy, 2026-08-13).
                            severity="low",
                            issue_type="restatement",
                            explanation=(
                                "Turn opens with filler that can signal restatement: "
                                f"{opener}."
                            ),
                        )
                    )

            if any(marker in normalized for marker in _PROMPT_LEAKAGE):
                issues.append(
                    ScriptCheckIssue(
                        turn_id=turn.turn_id,
                        segment_id=turn.segment_id,
                        severity="blocking",
                        # Structural / integrity_breach: shipping prompt text
                        # breaks the product's core promise — still blocking.
                        issue_type="prompt_leakage",
                        explanation=(
                            "A spoken line looks like internal instructions rather than "
                            "episode dialogue. Regenerate that passage before shipping."
                        ),
                    )
                )
            if turn.speaker == previous_speaker:
                consecutive_speaker += 1
            else:
                previous_speaker = turn.speaker
                consecutive_speaker = 1
            if not single_speaker and consecutive_speaker > 3:
                issues.append(
                    ScriptCheckIssue(
                        turn_id=turn.turn_id,
                        segment_id=turn.segment_id,
                        severity="low",
                        issue_type="speaker_pattern",
                        explanation="More than three consecutive turns use the same speaker.",
                    )
                )

        turn_count = len(script.turns)
        if turn_count and filler_open_count / turn_count > _FILLER_RATE_HIGH:
            issues.append(
                ScriptCheckIssue(
                    # Style, not correctness -- see the per-turn restatement note above.
                    severity="low",
                    issue_type="restatement",
                    explanation=(
                        f"Filler openers appear in {filler_open_count} of {turn_count} turns "
                        f"({filler_open_count / turn_count:.0%}); maximum is 20%."
                    ),
                )
            )

        issues.extend(_repetition_issues(normalized_turns))

        joined = " ".join(turn.spoken_text_fa for turn in script.turns)
        if (
            glossary.build_kind == "deterministic"
            and not glossary.terms
            and glossary.corpus_had_latin_tokens
        ):
            issues.append(
                ScriptCheckIssue(
                    severity="medium",
                    issue_type="glossary_inconsistency",
                    explanation=(
                        "Deterministic glossary is empty but the corpus contains "
                        "Latin-script tokens."
                    ),
                )
            )
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
                    # Pacing, not correctness -- recorded for later polish, not
                    # blocking (MVP policy, 2026-08-13).
                    severity="low",
                    issue_type="duration_mismatch",
                    explanation=(
                        f"Estimated duration is {estimated_minutes:.1f} minutes; "
                        f"episode plan targets {target:.1f}."
                    ),
                )
            )

        for segment_id, violations in (speaker_balance_violations or {}).items():
            for violation in violations:
                issues.append(
                    ScriptCheckIssue(
                        segment_id=segment_id,
                        # Style, not correctness -- recorded for later polish,
                        # not blocking (MVP policy, 2026-08-13).
                        severity="low",
                        issue_type="speaker_balance",
                        explanation=violation,
                    )
                )

        editorial_word_count = sum(
            len(_WORD.findall(turn.spoken_text_fa))
            for turn in script.turns
            if turn.editorial_only
        )
        editorial_word_ratio = (
            round(editorial_word_count / word_count, 4) if word_count else 0.0
        )
        speaker_a_word_count = speaker_words["A"]
        speaker_b_word_count = speaker_words["B"]

        # editorial_ratio, speaker_skew, and speaker_b_substantive are style/format
        # measures, not content correctness. Recorded at "low" (non-blocking) for
        # now -- content grounding matters more for MVP; tighten these later
        # (MVP policy, 2026-08-13).
        if editorial_word_ratio > _EDITORIAL_RATIO_MAX:
            issues.append(
                ScriptCheckIssue(
                    severity="low",
                    issue_type="editorial_ratio",
                    explanation=(
                        f"Editorial word ratio is {editorial_word_ratio:.1%}; "
                        f"maximum is {_EDITORIAL_RATIO_MAX:.0%}."
                    ),
                )
            )

        if speaker_a_word_count and speaker_b_word_count:
            skew = max(speaker_a_word_count, speaker_b_word_count) / min(
                speaker_a_word_count, speaker_b_word_count
            )
            if skew > _SPEAKER_SKEW_MAX:
                issues.append(
                    ScriptCheckIssue(
                        severity="low",
                        issue_type="speaker_skew",
                        explanation=(
                            f"Speaker word skew is {skew:.2f}× "
                            f"({speaker_a_word_count}:{speaker_b_word_count}); "
                            f"maximum is {_SPEAKER_SKEW_MAX:.1f}×."
                        ),
                    )
                )

        if speaker_b_turn_count and (
            speaker_b_substantive_turn_count / speaker_b_turn_count
            < _SPEAKER_B_SUBSTANTIVE_MIN_RATIO
        ):
            issues.append(
                ScriptCheckIssue(
                    severity="low",
                    issue_type="speaker_b_substantive",
                    explanation=(
                        f"Speaker B has {speaker_b_substantive_turn_count} substantive "
                        f"of {speaker_b_turn_count} turns "
                        f"({speaker_b_substantive_turn_count / speaker_b_turn_count:.0%}); "
                        f"minimum is {_SPEAKER_B_SUBSTANTIVE_MIN_RATIO:.0%}."
                    ),
                )
            )

        if must_not_be_lost_review is not None:
            issues.extend(
                _dropped_content_issues(script, must_not_be_lost_review)
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
            editorial_word_ratio=editorial_word_ratio,
            speaker_a_word_count=speaker_a_word_count,
            speaker_b_word_count=speaker_b_word_count,
            speaker_b_substantive_turn_count=speaker_b_substantive_turn_count,
            claims_per_segment_minute=(
                round(
                    len(
                        {
                            claim_id
                            for segment in episode_plan.segments
                            for claim_id in segment.claim_ids
                        }
                    )
                    / target,
                    4,
                )
                if target
                else 0.0
            ),
        )


def _repetition_issues(
    normalized_turns: list[tuple[ScriptTurn, str, list[str]]],
) -> list[ScriptCheckIssue]:
    issues: list[ScriptCheckIssue] = []
    by_text: dict[str, list[ScriptTurn]] = {}
    for turn, normalized, _tokens_for_turn in normalized_turns:
        by_text.setdefault(normalized, []).append(turn)
    for normalized, turns in by_text.items():
        if len(turns) > 1 and len(normalized) > 20:
            issues.append(
                ScriptCheckIssue(
                    turn_id=turns[0].turn_id,
                    segment_id=turns[0].segment_id,
                    severity="blocking",
                    issue_type="repetition",
                    explanation=f"A spoken turn is repeated exactly {len(turns)} times.",
                )
            )

    flagged_pairs: set[tuple[str, str]] = set()
    for index, (left_turn, left_norm, left_tokens) in enumerate(normalized_turns):
        left_trigrams = _trigrams(left_tokens)
        left_opening = tuple(left_tokens[:_OPENING_TOKEN_COUNT])
        for right_turn, right_norm, right_tokens in normalized_turns[index + 1 :]:
            pair_key = tuple(sorted((left_turn.turn_id, right_turn.turn_id)))
            if pair_key in flagged_pairs:
                continue
            if left_norm == right_norm and len(left_norm) > 20:
                continue
            similarity = _jaccard(left_trigrams, _trigrams(right_tokens))
            if similarity >= _TRIGRAM_JACCARD_HIGH:
                flagged_pairs.add(pair_key)
                issues.append(
                    ScriptCheckIssue(
                        turn_id=left_turn.turn_id,
                        segment_id=left_turn.segment_id,
                        severity="high",
                        issue_type="repetition",
                        explanation=(
                            f"Near-duplicate turns {left_turn.turn_id} and "
                            f"{right_turn.turn_id} (trigram Jaccard {similarity:.2f})."
                        ),
                    )
                )
                continue
            right_opening = tuple(right_tokens[:_OPENING_TOKEN_COUNT])
            if (
                len(left_opening) == _OPENING_TOKEN_COUNT
                and left_opening == right_opening
            ):
                flagged_pairs.add(pair_key)
                issues.append(
                    ScriptCheckIssue(
                        turn_id=left_turn.turn_id,
                        segment_id=left_turn.segment_id,
                        severity="medium",
                        issue_type="repetition",
                        explanation=(
                            f"Turns {left_turn.turn_id} and {right_turn.turn_id} share "
                            "the same four-token opening."
                        ),
                    )
                )
    return issues


def _ascii_double_quoted(text: str) -> str:
    mapped = text
    for mark in _CURLY_DOUBLE_QUOTES:
        mapped = mapped.replace(mark, '"')
    return mapped


def _specifics_in_spoken(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    def add(token: str) -> None:
        stripped = token.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            ordered.append(stripped)

    for match in _DIGIT_RUN.finditer(text):
        add(match.group(0))
    for match in _FOUR_DIGIT_YEAR.finditer(text):
        add(match.group(0))
    for match in _LATIN_CAPITALISED.finditer(text):
        add(match.group(0))
    # Persian guillemets mark terminology as often as quotation -- «حیات فعال» is a
    # term, «...» around a sentence is a quotation. Only the second kind can be a
    # fabricated citation, and length is what separates them: a term is a noun
    # phrase, a quotation is a clause. Below the threshold the check cannot tell a
    # coined term from a coined quote, so it says nothing rather than crying wolf on
    # every turn -- which is what made its real hits invisible.
    for span in _GUILLEMET_SPAN.findall(text):
        if len(span.split()) >= _QUOTED_SPAN_MIN_WORDS:
            add(span)
    for span in _ASCII_QUOTE_SPAN.findall(_ascii_double_quoted(text)):
        if len(span.split()) >= _QUOTED_SPAN_MIN_WORDS:
            add(span)
    return ordered


def _pack_specifics_haystack(turn: ScriptTurn, pack: SegmentEvidencePack) -> str:
    cited = set(turn.evidence_ids)
    parts: list[str] = [
        item.supporting_excerpt
        for item in pack.evidence_items
        if item.evidence_id in cited
    ]
    parts.extend(block.text for block in pack.original_blocks)
    parts.extend(block.text for block in pack.context_blocks)
    joined = "\n".join(parts)
    return normalize_for_match(joined)[0]


def _glossary_forms(glossary: Glossary) -> set[str]:
    """Every agreed spoken form of a glossary term, normalised for matching.

    Persian writes quotations and terminology alike in guillemets, so a term the
    glossary itself defines -- often the source's own title -- reads to the specifics
    check as an unattributed quotation. Those hits are not findings: the term is
    agreed vocabulary, and flagging it on every turn buries the fabricated date or
    name the check exists to catch.
    """

    forms: set[str] = set()
    for term in glossary.terms:
        for value in (
            term.source_term,
            term.preferred_persian,
            term.first_use_form,
            term.subsequent_use_form,
        ):
            needle, _ = normalize_for_match(value or "")
            if needle:
                forms.add(needle)
    return forms


def _unsupported_specifics_issues(
    turn: ScriptTurn,
    pack: SegmentEvidencePack,
    glossary_forms: set[str] | None = None,
) -> list[ScriptCheckIssue]:
    haystack = _pack_specifics_haystack(turn, pack)
    known = glossary_forms or set()
    offending: list[str] = []
    for token in _specifics_in_spoken(turn.spoken_text_fa):
        needle, _ = normalize_for_match(token)
        if not needle or needle in known:
            continue
        if needle not in haystack:
            offending.append(token)
    if not offending:
        return []
    listed = ", ".join(offending)
    return [
        ScriptCheckIssue(
            turn_id=turn.turn_id,
            segment_id=turn.segment_id,
            severity="medium",
            issue_type="unsupported_specifics",
            explanation=(
                "Turn uses specifics not found in cited excerpts or pack blocks: "
                f"{listed}."
            ),
        )
    ]


def _dropped_content_issues(
    script: Script,
    review: MustNotBeLostReview,
) -> list[ScriptCheckIssue]:
    cited_claims = {
        claim_id for turn in script.turns for claim_id in turn.claim_ids
    }
    plan_used = [item for item in review.items if item.used_in_plan]
    if not plan_used:
        return []
    unreached = [item for item in plan_used if item.claim_id not in cited_claims]
    if not unreached:
        return []
    prefixes = [item.claim[:40] for item in unreached[:4]]
    listed = "; ".join(prefixes)
    severity = (
        "high"
        if len(unreached) / len(plan_used) > _DROPPED_CONTENT_HIGH_RATIO
        else "medium"
    )
    return [
        ScriptCheckIssue(
            severity=severity,
            issue_type="dropped_content",
            explanation=(
                f"{len(unreached)} of {len(plan_used)} plan-used must-not-be-lost "
                f"claims reach no turn claim_ids: {listed}."
            ),
        )
    ]
