# 09 — Degrade Instead of Fail

Date: 2026-08-13 · Status: implemented · Effort: M · Source: nine consecutive user-visible build failures on 2026-08-12, every one caused by an imperfect model output that the pipeline could already have resolved

Note: failures 7 (JSON escape repair) and 8 (turn_id compare) are silent correct repairs with no listener impact — no `QualityNote`. Failures 3–6 emit notes.

A deterministic validator that raises stops the whole build and parks the project in `FAILED_RETRYABLE`. That is the correct response to a defect the pipeline cannot resolve. It is the wrong response to a defect the pipeline **can** resolve, and the second case is the overwhelming majority of what actually fires.

This spec establishes the rule that separates the two, applies it to the audited set, and makes the classification a stated property of each validator rather than something rediscovered every time a new one fires in production.

## 1. Measured problem

Nine distinct failures reached a user as `FAILED_RETRYABLE` in one day, across four projects:

| # | Error surfaced to the user | Stage | Safe fallback existed? | Could the user act? |
|---|---|---|---|---|
| 1 | `Okian request timed out.` | `document_map` | Yes — stream instead of block | No |
| 2 | `Evidence extraction lost 84% of planned source tokens` | `evidence_extraction` | Partly — salvage path exists | No |
| 3 | `Selected claims must be used or deliberately omitted: clm-4fdd919…` | `episode_plan` | **Yes** — `deliberately_omitted_claims` is a modelled, supported outcome | No |
| 4 | `Revision introduced new claim IDs in turn seg-004-turn-001` | `script_reviser` | **Yes** — drop the invented ID, keep the real ones | No |
| 5 | `Revised script failed deterministic checks; the original script was kept.` | `script_pipeline` | **Yes** — the message says so itself | No |
| 6 | `Revised substantive turn seg-004-turn-001 lost grounding.` | `script_reviser` | **Yes** — fall back to the original turn | No |
| 7 | `Okian output did not match SegmentScriptDraft: Invalid JSON: invalid escape` | okian adapter | **Yes** — repair the escape | No |
| 8 | `zip() argument 2 is longer than argument 1` | `script_pipeline` | **Yes** — match by `turn_id` | No |
| 9 | `Not Acceptable` (HTTP 406, transient) | `persian_script_segment` | Yes — retry | No |

**The user could act on none of them.** Several name internal identifiers (`clm-4fdd919…`, `seg-004-turn-001`) that have no meaning in the product surface. Failure 5 states in its own message that a usable artifact was preserved, and then fails anyway.

### 1.1 The recovery machinery mostly already exists

These are not missing capabilities. Each fallback below was already implemented and simply not reached:

| Existing mechanism | Location | Why it did not fire |
|---|---|---|
| `is_better()` / `comparison_key()` | [`script_quality.py:8`](../../src/thesisound/services/script_quality.py:8) | A `raise` above it returned first (failure 5) |
| `_materialize_revision` falls back to the original turn | [`script_reviser.py:138`](../../src/thesisound/services/script_reviser.py:138) | Validator raised before merge (failures 4, 6) |
| `deliberately_omitted_claims` | [`episode.py:99`](../../src/thesisound/episode.py:99) | Validator demanded the model populate it (failure 3) |
| `_salvage_draft_inplace` | [`evidence_extractor.py`](../../src/thesisound/services/evidence_extractor.py) | Only on the final attempt, and the retry budget was consumed early |
| `StageRetryPolicy` contract repairs | [`model_retry.py:53`](../../src/thesisound/services/model_retry.py:53) | `error_fingerprint` collided on a constant message, ending repairs a turn early |

The defect is not capability. It is that **`raise` is the default and recovery is the exception**, when the evidence says it should be the other way round.

## 2. Design

### D1 — The classification rule

A validator failure is **recoverable** when a fallback exists that is safe without user input. Concretely, all three must hold:

1. A defined artifact remains that satisfies every downstream contract.
2. Producing it needs no information the user holds.
3. The degradation is describable in one sentence a listener-facing reviewer would understand.

Otherwise it is **structural** and must stop the build.

Applying the rule to the audited set: failures 3–8 are recoverable. Failure 2 is recoverable up to the retention floor and structural past it. Failures 1 and 9 are transport, handled by [`10-automatic-run-recovery.md`](10-automatic-run-recovery.md).

### D2 — Recoverable failures degrade and record

A recoverable failure must not raise. It must:

- apply the fallback,
- append a `QualityNote` (defined in [`11-failure-disclosure-and-stop-criteria.md`](11-failure-disclosure-and-stop-criteria.md)) naming what was degraded and why,
- let the stage return normally.

Silent degradation is explicitly **not** acceptable — that trades a visible dead end for an invisibly worse episode, which is a worse deal for an evidence-grounded product. The note is the price of not stopping.

### D3 — Scope the remedy to the scope of the breach

`severity="blocking"` is **not** by itself a reason to stop the build. This was the original error in this spec, caught by `Script rejected: Substantive turn has no evidence linked to its claim IDs.` surviving every rule above.

An integrity breach means *do not ship the offending thing*. It does not mean *destroy the episode*. Most blocking checks in [`script_checks.py`](../../src/thesisound/services/script_checks.py) record a `turn_id` and `segment_id` — the breach is scoped to one turn, so the remedy must be too. Apply the first rung that holds:

| Rung | When | Result |
|---|---|---|
| 1. **Repair** | The correct value is derivable from data the pipeline already holds | Fix it, note it |
| 2. **Excise** | Not derivable, but removing the unit leaves a valid, still-grounded artifact | Drop the unit, note it |
| 3. **Stop** | Neither — the breach is script-wide, or excision leaves nothing coherent | Raise |

Rung 3 is the exception, not the default. Reaching for it requires stating why rungs 1 and 2 do not apply.

#### Worked example — `missing_grounding`

[`script_checks.py:179`](../../src/thesisound/services/script_checks.py:179) fires when a substantive turn's `evidence_ids` do not intersect the evidence of the claims it cites. `expected_evidence` is built from `claim.evidence_ids`, so **the grounding exists in the ledger** — the model mislabelled the link, it did not assert something unsupported. That is rung 1: set the turn's evidence to the recorded provenance of the claims it actually cites. The same repair clears `evidence_unlinked_to_claim` ([`script_checks.py:192`](../../src/thesisound/services/script_checks.py:192)), which is the mirror image of the same defect.

Only when a cited claim carries **no** evidence at all is there a real grounding absence — and that is an upstream data fault, not a script fault.

### D3.1 — What genuinely stops the build

After the ladder, these remain fatal:

| Check | Location | Why no lower rung applies |
|---|---|---|
| Coverage insufficient for duration | [`episode_planner.py:52`](../../src/thesisound/services/episode_planner.py:52) | Needs the user to narrow scope or add sources |
| Deterministic budget insufficient | [`episode_planner.py:55`](../../src/thesisound/services/episode_planner.py:55) | Same |
| `prompt_leakage` | [`script_checks.py:240`](../../src/thesisound/services/script_checks.py:240) | Not derivable; excision unsafe when leakage is pervasive |
| Unknown claim IDs across the whole draft | [`episode_planner.py:139`](../../src/thesisound/services/episode_planner.py:139) | Nothing to repair against; no grounded artifact remains |
| Plan approval mismatch | [`script_run.py:223`](../../src/thesisound/services/script_run.py:223) | Consent gate |
| Missing must-include claims | [`episode_planner.py:179`](../../src/thesisound/services/episode_planner.py:179) | Silently dropping them defeats prioritisation |

Excision has a floor: if repeated excision would leave a segment with no substantive turn, or the script under its duration band, that is rung 3. The degradation ceiling in spec 11 D4 is what prevents excision from quietly hollowing out an episode.

Their messages are rewritten under spec 11.

### D4 — State the classification at the raise site

Every `DeterministicValidationError` gains a required stance in its immediate context: either a comment naming the fallback that was applied instead, or a comment naming why no safe fallback exists. This is the anti-recurrence mechanism — a new validator cannot be written without its author deciding which side it is on.

### D5 — Fix `error_fingerprint` collisions

[`model_retry.py:89`](../../src/thesisound/services/model_retry.py:89) fingerprints on the stringified message. Constant messages collide, so `identical_repair` ends the repair budget one attempt early even when each attempt failed differently. Any validator message that can recur for different inputs must include the offending value. `ExcerptNotFoundError` is already fixed this way; the rest of the constant-message raises need the same treatment.

## 3. Non-goals

- Weakening `script_outcome()`. The final gate on the shipped artifact is unchanged.
- Removing `FAILED_RETRYABLE`. Structural failures still use it.
- Catch-all exception handling. Every degradation is a named, reviewed decision with a named fallback; a bare `except` is the opposite of this spec.
- Changing the quality thresholds themselves (`speaker_skew`, `duration_mismatch`, retention floors). What changes is whether tripping one kills the build, not where it sits.

## 4. Acceptance criteria

1. Each of failures 3–8, replayed from its recorded input, completes the build and emits a `QualityNote` instead of raising (7 and 8 repair silently, per the note at the top).
2. Each structural check in D3.1 still raises on its own trigger.
3. A turn whose `evidence_ids` miss its claims' evidence is repaired (rung 1) and the build completes; a turn citing a claim with no evidence at all still stops.
4. No `severity="blocking"` check stops the build without a stated reason why rungs 1 and 2 do not apply.
5. A revision that trips a blocking check loses `is_better()` and the original ships — no `raise` on the path between them.
6. Two different bad excerpts in one stage produce two different `error_fingerprint` values.
7. A clean run emits zero `QualityNote`s. **This is the regression that matters most: recovery must not become the normal path.**

## 5. Test plan

| Test | Asserts |
|---|---|
| `test_unaccounted_claim_is_auto_omitted_with_a_note` | D2 on failure 3 |
| `test_invented_claim_id_is_dropped_not_fatal` | D2 on failure 4 |
| `test_ungroundable_revised_turn_falls_back_to_original` | D2 on failure 6 |
| `test_revision_failing_checks_is_ranked_not_raised` | D2 on failure 5 |
| `test_invalid_json_escape_is_repaired` | D2 on failure 7 |
| `test_mislinked_turn_evidence_is_repaired_not_rejected` | D3 rung 1, §4.3 |
| `test_claim_with_no_evidence_at_all_still_stops` | D3 rung 3, §4.3 |
| `test_excision_floor_stops_when_segment_would_empty` | D3 excision floor |
| `test_insufficient_coverage_still_raises` | D3.1, §4.2 |
| `test_prompt_leakage_still_blocks` | D3.1, §4.2 |
| `test_distinct_bad_excerpts_have_distinct_fingerprints` | D5, §4.6 |
| `test_clean_run_emits_no_quality_notes` | §4.7 |

## 6. Sequencing

D1 (rule) → D3 (remedy ladder — it changes which failures D2 even applies to) → D2 (apply to the audited set) → D5 (fingerprints) → D4 (annotate). D3.1 is an audit, not a change. D2 depends on `QualityNote` from spec 11 landing first, or on a temporary warning list if spec 11 is deferred.

## 7. Related

- [`10-automatic-run-recovery.md`](10-automatic-run-recovery.md) — handles what remains fatal after this spec.
- [`11-failure-disclosure-and-stop-criteria.md`](11-failure-disclosure-and-stop-criteria.md) — defines `QualityNote` and the user-facing stop rule.
- [`02-script-dialogue-quality-gate.md`](02-script-dialogue-quality-gate.md) — the checks whose severities this spec deliberately does not change.
