# 02 — Script Dialogue Quality Gate

Date: 2026-08-12 · Status: implemented · Effort: M · Source: [MVP readiness audit](../thesisound-mvp-readiness-audit-fa.html), finding "generic dialogue, filler, template repetition, and dropped points in long documents"

The measurements that would catch generic dialogue already exist and are already computed. None of them can change a verdict. This spec makes the existing floor binding, widens two checks that are scoped too narrowly to fire, and connects the dropped-content signal the pipeline already extracts to the gate that ships the script.

## 1. Measured problem

The stored script for `f781a5c7` — 22 turns, 1221 words, 9.39 estimated minutes:

| Signal | Value |
|---|---|
| `checks.json` verdict | **`pass`, 0 issues** |
| Turns with no `claim_ids` and no `evidence_ids` | 11 of 22 |
| Those turns, by speaker | A: 1 · **B: 10 of B's 11** |
| Words, A : B | 757 : 355 (2.13×) |
| Turns containing «دقیق» | 8 of 22 (A: 5 · B: 3) |
| Turns ending in «؟» | 10 of 22 |
| Speaker sequence | `ABABABBABABABABABABABA` |

Editorial word ratio, against the R10 policy floor:

| Segment | Editorial words | Policy max | Result |
|---|---|---|---|
| seg-001 (opening) | 39.7% | 35% | fail |
| seg-002 | 28.7% | 25% | fail |
| seg-003 | 23.9% | 25% | pass |
| seg-004 | 36.8% | 25% | fail |
| **whole script** | **31.4%** | 25% | fail |

Speaker B is a question-asking device: ten of its eleven turns carry no claim and no evidence. This is not a wording defect that better prompting fixes — the alternating format guarantees that every second turn is connective tissue, and «پرسش‌ها بازگویی پاسخ‌اند» is the direct consequence.

### 1.1 What R10 already built

[`persian_script_writer.py:18`](../../src/thesisound/services/persian_script_writer.py:18) defines `SpeakerBalancePolicy` with three floors, calibrated so that all four segments of the 2026-08-09 script fail at least one:

| Rule | Threshold |
|---|---|
| F1 editorial word ratio | ≤ 25% per segment, ≤ 35% for the opening |
| F2 speaker B substantive | ≥ 1 non-editorial B turn when the segment has ≥ 2 claims |
| F3 turns per claim | ≤ 2 |

These are enforced **during writing**, with a retry: a violation raises `DeterministicValidationError` while attempts remain. On the final attempt the writer degrades — [`persian_script_writer.py:168`](../../src/thesisound/services/persian_script_writer.py:168), "a stylistic floor must never abort a script build. Record it instead" — and the violations become `severity="low"` issues.

`ScriptCheckReport` also already carries `editorial_word_ratio`, `speaker_a_word_count`, `speaker_b_word_count`, `speaker_b_substantive_turn_count`, and `claims_per_segment_minute`. **They are computed and stored, and no check compares any of them to anything.**

So the spec below is mostly not new measurement. It is making measurement that exists count.

### 1.2 Why the gate stays silent

`verdict` is `reject` on `blocking` and `revise` on `high`/`medium` ([`script_checks.py:243`](../../src/thesisound/services/script_checks.py:243)). `low` never binds. Four checks are relevant and all four miss:

| Check | Severity | Why it does not fire |
|---|---|---|
| `speaker_balance` | `low` | F1/F2/F3 violations recorded but non-binding |
| `restatement` | `low` | speaker **A** only, `startswith` only, 4 fixed phrases |
| `speaker_pattern` | `low` | needs > 3 consecutive same-speaker turns; strict alternation never trips it |
| `repetition` | `high` | requires a **byte-exact** duplicate turn; real filler is near-duplicate |

`restatement`'s scoping is backwards for this script: «دقیقاً» appears in 5 A turns and 3 B turns, and `_AFFIRMATIVE_OPENERS` only matches at position 0 of an A turn.

`repetition` is the one high-severity check in this family, and exact-match makes it effectively dead — no two turns in any real script are byte-identical.

## 2. Design

Five changes, in dependency order. C1 and C2 are threshold work on existing numbers; C3–C5 add detection.

### C1 — Make the R10 floor binding

Promote recorded `speaker_balance` violations from `low` to `high`, so a script that violates F1/F2/F3 on the final attempt lands in `revise` instead of shipping as `pass`.

Keep the writer's degrade-instead-of-abort behaviour exactly as it is. The distinction that matters: **the writer should not crash a build over style, and the gate should not ship a script that failed style.** Those are compatible, and today only the first half is implemented.

Opening-segment relief (35%) stays, and stays scoped to the opening segment only.

### C2 — Add whole-script thresholds

Per-segment floors do not bound the script. A script whose segments each land just under 25% still reads as filler end to end. Add to `ScriptChecker`, using fields it already computes:

| Check | Threshold | Severity |
|---|---|---|
| `editorial_ratio` | `editorial_word_ratio` > 0.25 | `high` |
| `speaker_skew` | `max(a,b) / min(a,b)` > 2.0 words | `high` |
| `speaker_b_substantive` | `speaker_b_substantive_turn_count` < 25% of B's turns | `high` |

Thresholds are calibrated to fail the 2026-08-09 script, matching the R10 method: 31.4% editorial, 2.13× skew, 1 of 11 substantive B turns. All three fire.

Add `editorial_ratio`, `speaker_skew` and `speaker_b_substantive` to the `issue_type` literal in [`script.py:71`](../../src/thesisound/script.py:71).

### C3 — Widen `restatement`

Three changes to the existing check:

1. Apply to **both** speakers, not A only.
2. Match a filler phrase anywhere in the first sentence, not only at string position 0.
3. Extend `_AFFIRMATIVE_OPENERS` into a `_FILLER_PHRASES` lexicon. Seed from measured occurrences — «دقیقاً», «بله، دقیقاً», «دقیقاً همین‌طور است», «کاملاً درست است», «همین‌طور است», «درست است», «نکته جالب», «بسیار خوب», «در واقع» — and keep it as a reviewable module-level tuple.

Severity `medium` when a turn opens with filler; `high` when filler appears in more than 20% of turns. The current script hits 36% and would be `high`.

A filler phrase inside a substantive turn is normal speech. Only opening a turn with one, or a script-wide rate, is a defect. The rule must not punish a turn that carries a claim and happens to contain «در واقع».

### C4 — Near-duplicate repetition

Replace the exact-match `Counter` on normalized turn text with a similarity pass:

- Normalize: collapse whitespace, strip ZWNJ variants, casefold.
- Compare every turn pair by token trigram Jaccard.
- ≥ 0.6 → `repetition`, `high`.
- Also flag a repeated **opening**: two turns sharing their first four tokens → `repetition`, `medium`.

22 turns is 231 pairs; a 60-minute script is bounded by turn count and stays well inside a deterministic check's budget. No model call.

Keep the exact-duplicate case as `blocking` — an exact repeat is a pipeline fault, not a style fault.

### C5 — Dropped-content check

The pipeline already extracts every point that must survive into the episode, and already cross-references it: `MustNotBeLostReview` in [`episode.py:213`](../../src/thesisound/episode.py:213), with `unused_count` and per-item `reflected_in_claims` / `used_in_plan`.

That model is documented as "Non-blocking by construction — this is a human-review surface, not a gate." **That decision is correct for the plan stage and this spec does not reverse it.** What is missing is the script stage: a point can survive into the plan and still never reach a turn.

Add a `dropped_content` check to `ScriptChecker`:

- Input: the `MustNotBeLostReview` for the project, plus the claim IDs actually cited across all turns.
- For each review item with `used_in_plan = true`, check whether any of its `reflected_in_claims` appears in some turn's `claim_ids`.
- Report unreached points as `dropped_content`, `medium`, listing up to 4 by text prefix.
- `high` when more than 25% of plan-used points reach no turn.

`medium` rather than `blocking`: a point can legitimately be cut for duration, and the reviewer needs the list, not a wall. `high` above a quarter, because at that rate the script is no longer covering the plan it was written from.

**Dependency:** this check reads `must_not_be_lost`, and 75 of those points are currently unreadable. C5 cannot be implemented before [`01-evidence-artifact-schema-upgrade.md`](01-evidence-artifact-schema-upgrade.md) lands.

### 2.1 Prompt work is downstream, not instead

The prompt at `prompts/persian_script_segment/1.1.0` should state the F1/F2/F3 floors and the C2 thresholds in its own words, so the writer aims above the floor rather than discovering it through retries. But prompt text is not the mechanism — a deterministic check that binds is. Ship C1–C5 first, then tune the prompt against a gate that can actually reject.

## 3. Non-goals

- Rewriting the two-speaker format. The format is fine; unbounded editorial turns are the defect.
- A model-based naturalness judge. Every check here is deterministic and free. A judge is a separate decision with its own cost case — see [`06-operations/01-server-mono-process-adoption.md`](../06-operations/01-server-mono-process-adoption.md) item 13.
- Retuning duration or coverage policy.
- Changing `MustNotBeLostReview`'s non-blocking role at the plan stage.

## 4. Acceptance criteria

1. The stored 2026-08-09 script, re-checked under this spec, yields `verdict != "pass"` with at least one `high` issue from each of C1, C2, C3.
2. `editorial_ratio` fires at 31.4% and does not fire at 24%.
3. `speaker_skew` fires at 757:355 and does not fire at 600:500.
4. `restatement` counts «دقیقاً» in both A and B turns, and does not flag a substantive turn containing «در واقع» mid-sentence.
5. `repetition` flags two near-duplicate turns at trigram Jaccard ≥ 0.6 and keeps exact duplicates `blocking`.
6. `dropped_content` reports a plan-used must-not-be-lost point that reaches no turn's `claim_ids`.
7. A clean synthetic script — ≤ 20% editorial, balanced speakers, no filler openers, all plan points reached — still returns `pass`. **This is the regression that matters most: the gate must reject the known-bad script without rejecting everything.**

## 5. Test plan

| Test | Asserts |
|---|---|
| `test_speaker_balance_violation_blocks_verdict` | C1 — recorded violation ⇒ `revise` |
| `test_writer_still_completes_on_final_attempt` | C1 — degrade behaviour unchanged |
| `test_editorial_ratio_threshold` | C2 — fires at 31.4%, silent at 24% |
| `test_speaker_skew_threshold` | C2 — fires at 2.13×, silent at 1.2× |
| `test_restatement_detects_both_speakers` | C3 — B turns counted |
| `test_restatement_ignores_midsentence_filler_in_substantive_turn` | C3 — no false positive |
| `test_repetition_near_duplicate` | C4 — Jaccard path |
| `test_repetition_exact_duplicate_is_blocking` | C4 — severity preserved |
| `test_dropped_content_flags_unreached_point` | C5 |
| `test_clean_script_still_passes` | §4.7 |

Store the 2026-08-09 script as a frozen fixture. It is the only real specimen of the defect and it is the calibration reference for every threshold in this spec.

## 6. Sequencing

C1 → C2 → C3 → C4 → C5. C1 and C2 are threshold changes over numbers that already exist and are worth shipping alone: together they reject the known-bad script. C5 is gated on spec 01.

## 7. Related

- [`01-evidence-artifact-schema-upgrade.md`](01-evidence-artifact-schema-upgrade.md) — blocks C5.
- [`07-conditional-glossary-and-verification.md`](07-conditional-glossary-and-verification.md) — the `glossary_inconsistency` check interacts with making glossary conditional.
- [`02-pipeline/06-persian-script-pipeline.md`](../02-pipeline/06-persian-script-pipeline.md) — the stage this gate guards.
- [`01-foundations/05-quality-evaluation.md`](../01-foundations/05-quality-evaluation.md) — quality dimensions and the NotebookLM comparison this spec's defects map to.
