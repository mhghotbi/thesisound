# 10 — Automatic Run Recovery

Date: 2026-08-13 · Status: proposed · Effort: M · Source: `failed_retryable` projects on 2026-08-12 that a manual retry either fixed unchanged, or could never fix

The project state is named `FAILED_RETRYABLE`. The system therefore already knows retrying may work. It then stops and waits for a human to press a button that supplies no information the system lacks. That is the system delegating its own job.

This spec makes the run retry itself for failures that a fresh attempt can plausibly fix, and — critically — makes each automatic attempt actually **differ** from the one before it. A retry that replays cached failure state is worse than no retry: same outcome, more waiting.

## 1. Measured problem

### 1.1 Manual retry was often a no-op

On 2026-08-12 the operator retried `00a0aea1` repeatedly and observed the identical failure each time, including across a server restart. Cause: the verdict was cached on disk. `checks-revised.json` retained `severity: high` from a previous code version; the retry loaded it instead of recomputing. The file's mtime never changed across those retries. Only deleting `checks.json`, `checks-revised.json`, `revision-decision.json` and `script-revised.json` let the project move.

**A retry that does not invalidate is a slower way to fail.**

### 1.2 A fresh attempt genuinely does change the output

Identical prompt, `temperature: 0`, same model, repeated calls:

| Call | Measurement | Run 1 | Run 2 | Run 3 |
|---|---|---|---|---|
| `document_map`, deepseek-v4-flash, 53k chars | stream lines | 3,112 | 5,168 | 18,940 |
| `document_map`, deepseek-v4-flash | outcome | 80.6s pass | 123.7s pass | 547.8s **`finish_reason=length`, zero answer tokens** |
| `evidence_extraction`, gemini-3.6-flash, block `dc0fd1d5fdfb` | verbatim excerpt matches | `[False, False]` | `[False, False]` | `[True, False]` |

Model output is not stable at `temperature: 0` on this provider. Retrying is not superstition here — it is the measured recovery path. The same table is also the argument for bounding it: run 3 of the first row cost 547 seconds to produce nothing.

### 1.3 Retry latency is real

| Stage | Model | Measured |
|---|---|---|
| `document_map` | gemini-3.5-flash-lite | 6.1s |
| `document_map` | gemini-3.6-flash | 21.6s |
| `document_map` | deepseek-v4-flash | 80.6–547.8s |
| `evidence_extraction`, per block | gemini-3.5-flash-lite / 3.6-flash | ~5s / ~25s |
| `persian_script_segment` | gemini-3.6-flash | 29.9s |

Three blind whole-pipeline retries can therefore cost many minutes. Recovery must be **scoped**, not a full rebuild — which is why spec 09 (degrade in place, no retry at all) is sequenced first.

## 2. Design

### D1 — Retry inside the run, not via the user

[`script_run.py:265`](../../src/thesisound/services/script_run.py:265) catches every exception, marks the project failed and returns. Insert a bounded automatic retry loop before that terminal path. The run executes in a `BackgroundTasks` callback, so the loop needs no new request and the existing `run.stage` progress reporting keeps working.

`_new_run` / `retry()` stay as they are; the manual control remains for the cases that survive automatic recovery.

### D2 — Classify before retrying

Retry only failures a fresh attempt could plausibly change:

| Class | Examples | Retry? |
|---|---|---|
| Transport | timeout, HTTP 5xx, HTTP 406 transient, disconnect | **Yes** |
| Model contract | invalid JSON, schema mismatch, invented IDs surviving spec 09 | **Yes** |
| Model quality | deterministic check tripped after spec 09 recovery | **Yes, once** |
| Structural | approval mismatch, wrong project state, insufficient coverage, missing plan, configuration error | **No — surface immediately** |

Retrying a structural failure is pure waste: it burns the retry budget and delays the message the user actually needs. This classification is the same axis as spec 09's, applied one level up, and should share its predicate rather than restating it.

### D3 — Scope invalidation to the failed stage

`run.stage` already records the stage in flight ([`script_run.py:397`](../../src/thesisound/services/script_run.py:397)). The pipeline stages are ordered and each owns known artifacts:

| Order | Stage | Artifacts invalidated on failure at or before this stage |
|---|---|---|
| 1 | `building_glossary` | `glossary.json` and everything below |
| 2 | `writing_segments` | segment drafts, `script-draft.json`, and below |
| 3 | `checking_draft` | `checks.json` and below |
| 4 | `verifying_draft` | `verification.json` and below |
| 5 | `revising` | `script-revised.json` and below |
| 6 | `checking_revision` | `checks-revised.json` and below |
| 7 | `verifying_revision` | `verification-revised.json`, `revision-decision.json` |

Invalidate **from the failed stage downward only**. The expensive upstream work — glossary, and per-segment drafts that cost one model call each — survives, which is what keeps automatic retry affordable. `clear_pipeline_artifacts` ([`script_artifact_store.py:42`](../../src/thesisound/services/script_artifact_store.py:42)) wipes everything and is the wrong tool here; a stage-scoped counterpart is needed.

This is also the fix for §1.1 in the manual path: `retry()` should use the same scoped invalidation instead of relying on the operator to delete files by hand.

### D4 — Budget

- **2 automatic attempts** after the first (3 total), per run.
- Exponential backoff seeded from `provider_retry_base_seconds`, so a transient 406 is not retried instantly.
- A **wall-clock ceiling** for automatic recovery. Given §1.3, a run that has already spent minutes retrying should stop and report rather than continue; the ceiling matters more than the attempt count.
- Attempts are per-run, not per-stage: this loop sits above the per-call provider retries in [`model_retry.py`](../../src/thesisound/services/model_retry.py) and the two must not multiply into a large hidden call count.

### D5 — Record every attempt

`ScriptBuildRun` gains an attempt history: stage, error, classification, invalidation scope, duration. Without it, automatic recovery makes the ledger *less* legible than manual retry, because the intermediate failures disappear. The final surfaced error must be the last real one, never a generic "retries exhausted".

### D6 — Apply to the other run services

The identical pattern exists in [`corpus_building.py:238`](../../src/thesisound/services/corpus_building.py:238), [`episode_planning_run.py:203`](../../src/thesisound/services/episode_planning_run.py:203) and [`audio_run.py:156`](../../src/thesisound/services/audio_run.py:156). Ship `script_run` first — every failure observed on 2026-08-12 was in it — then lift the shared parts.

## 3. Non-goals

- Unbounded retry. The `document_map` run that burned 547 seconds to return nothing is the counter-example.
- Retrying structural failures.
- Replacing spec 09. Degrading in place is instant and deterministic; retry is the fallback for what cannot be degraded, and is strictly the more expensive tool.
- Removing manual retry. It stays for post-exhaustion cases.
- Cross-run persistence of attempt counts. The budget is per run.

## 4. Acceptance criteria

1. A transport failure on the first attempt completes the build automatically, with no `FAILED_RETRYABLE` ever written.
2. A structural failure surfaces on attempt 1 with zero automatic retries.
3. Failure at `checking_revision` invalidates the revision artifacts and **not** `glossary.json` or the segment drafts.
4. Replaying §1.1 — a stale `checks-revised.json` — recomputes rather than reloading it, with no manual file deletion.
5. After the budget is exhausted the project reaches `FAILED_RETRYABLE` carrying the **last real** error message.
6. A run that succeeds on attempt 1 performs no extra model calls. **Regression that matters most: recovery must not silently multiply cost on the happy path.**
7. The attempt history records every attempt with its classification.

## 5. Test plan

| Test | Asserts |
|---|---|
| `test_transient_transport_failure_recovers_without_user_action` | D1, §4.1 |
| `test_structural_failure_is_not_retried` | D2, §4.2 |
| `test_invalidation_is_scoped_to_the_failed_stage` | D3, §4.3 |
| `test_stale_revision_checks_are_recomputed_on_retry` | D3, §4.4 |
| `test_exhausted_budget_surfaces_the_last_real_error` | D4, §4.5 |
| `test_successful_first_attempt_makes_no_extra_calls` | §4.6 |
| `test_wall_clock_ceiling_stops_recovery` | D4 |
| `test_attempt_history_records_classification` | D5 |

## 6. Sequencing

Spec 09 first — it removes most of what would otherwise be retried, and retrying is the more expensive answer. Then D2 (classification, shared with 09) → D3 (scoped invalidation, which also repairs manual retry) → D1 (loop) → D4 → D5 → D6.

D3 is worth shipping alone: it fixes the observed "retry changes nothing" behaviour even with no automatic loop present.

## 7. Related

- [`09-degrade-instead-of-fail.md`](09-degrade-instead-of-fail.md) — must land first.
- [`11-failure-disclosure-and-stop-criteria.md`](11-failure-disclosure-and-stop-criteria.md) — what the user sees once recovery is exhausted.
- [`06-operations/01-server-mono-process-adoption.md`](../06-operations/01-server-mono-process-adoption.md) — run execution model.
