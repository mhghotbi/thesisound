# R9 — Deciding the evidence-extraction model tier (experiment E3)

**Implementation plan. Follow it as written.**

Audience: a junior/mid-level developer on this codebase.
Source of the requirement: [`docs/thesisound-pipeline-audit.md`](thesisound-pipeline-audit.md) §10 row **R9**, §5 "اقتصاد retry", §12 experiment **E3**, §13.

> R9 🟨P2 — «۲۴٪ نرخ hallucination شاهد در مدل fast» → «آزمایش tier: `evidence_extraction` روی مدل strong، مقایسه‌ی هزینه‌ی کل (اولیه + retry + claimهای ازدست‌رفته)»
> Quality نامعلوم · Latency نامعلوم · Cost نامعلوم · **Effort کم (آزمایش)** · Risk کم · Confidence **Medium**
>
> E3 Decision: «بر اساس هزینه‌ی کل نه قیمت هر call — **پیش‌نیاز: R4، وگرنه توکن retry دیده نمی‌شود**»

**R9 is not a feature. It is a decision, and the decision is currently unmakeable.**
E3's rule — *switch if the strong model cuts the excerpt-error rate by >15 percentage
points and total cost stays ≤1.2×* — cannot be evaluated against this codebase today, for
reasons that have nothing to do with which model is better. This plan closes those
reasons, then runs the experiment.

Do not skip to §8 and run the experiment. Without §5 the numbers it produces are not the
numbers E3 asks for.

---

## 1. What is already true, and what actually blocks the decision

Everything in this section was re-measured against HEAD and the filesystem model-run store
on 2026-08-11, not copied from the audit. Where my number differs from the audit's, both
are given.

### 1.1 The baseline, re-verified

Over all `record.json` files under `workspaces/*/model-runs/` and
`workspaces/*/archive/revisions/*/model-runs/`, for `stage="evidence_extraction"`:

| Quantity | Value |
|---|---:|
| runs | 243 |
| provider attempts | 320 |
| attempts per run | 1.32 |
| resolved model | `gemini-3.5-flash-lite` on 243/243 |
| attempts carrying exactly `supporting_excerpt must be copied from the supplied source block.` | **80 (25.0%)** |
| …of those, flagged `retryable=True` | **77** — the audit's number |
| attempts-per-run distribution | 187×1, 32×2, **23×3**, 1×0 |
| runs that used all three attempts | **23, and all 23 ended `succeeded`** |
| failed attempts carrying `usage` | **0 of 81** |

Two rows matter more than the rest.

**The 23 three-attempt runs are the salvage-loss term of E3's cost formula, and its size is
unrecorded.** A run reaches attempt 3 only after two validation failures; on attempt 3
`_extract_block`'s validator stops raising and calls `_salvage_draft_inplace`, which drops
unrepairable claims and lets the run report `succeeded`
(`evidence_extractor.py:242-249`, `:371-399`). Nothing anywhere counts what it dropped. So
"how many claims did the fast model cost us" is not a number this repository can produce.

**The historical store cannot supply E3's baseline.** All 81 failed attempts have
`usage = null`, because they predate R4. So the retry term cannot be reconstructed from the
audited run — **both arms of E3 must be re-run**, and the audit's figures are context, not
a control arm.

### 1.2 Already fixed in HEAD — do not redo

| Audit item | State | Evidence |
|---|---|---|
| **R4** — usage missing on failed attempts | **done** | `model_runner.py:200-225` passes `usage=attempt_usage` with the P1/P2/P3 comment; landed in `e40bd6e` "Record billed tokens on failed model attempts" (2026-08-10), after the audited run |
| `ModelAttemptRecord.started_at` was the *end* time | **done** | `model_runner.py:134` captures it before the call; `modeling.py:71-76` documents why |
| No way to route one stage to another tier | **already existed** | `ModelRouter._resolve_unchecked` (`model_routing.py:111`) reads `Settings.model_route_overrides` per stage |

E3's stated prerequisite ("R4, otherwise retry tokens are invisible") **is satisfied**. Say
so in the PR; the audit's dependency note is stale.

### 1.3 The four things that actually block the decision

**B1 — Nothing is priced.** `config/model-pricing.toml` still ships `version = "unset"` and
zero active rows. Every call prices as unknown. Unchanged since the audit. This is
deliberate policy, not an oversight — see the file's own header — and §7 is how it gets
resolved, not by you inventing rates.

**B2 — Even with prices, retries are unpriceable by construction.** This one is new and is
the reason E3 would silently produce the wrong answer if you ran it today:

- `provider_succeeded()` (`observability.py:542-580`) writes input/output/cached tokens as
  soon as the provider answers, *before* validation. So a rejected call **does** carry
  tokens.
- `succeed()` (`:582-602`) is the only path that prices a call.
- `reject()` and `fail()` (`:666-687`) set a terminal status and never price.
- `reprice()` (`:634`) filters `status = 'succeeded'`, so a rejected call can never be
  priced later either.
- `cost_breakdown()` (`observability_rollup.py:118`) filters `status = 'succeeded'`.

Net effect: the tokens burned by the 24% excerpt-failure retry loop are recorded and then
excluded from every cost view. E3's formula is `initial + retry + salvage-loss`; today the
tooling can only produce `initial`. **Comparing arms on `initial` alone would flatter the
fast model precisely in proportion to how much it retries** — i.e. it would answer the
opposite of the question.

**B3 — Salvage-loss is not counted.** Per §1.1.

**B4 — The ledger has never been proven on a real run.** The audit found 14 real provider
calls in `ledger.sqlite3` against 365 in the filesystem store, with
`workflow_run_id` / `pipeline_trace_id` / `parent_span_id` NULL on all 358 rows. HEAD reads
those from contextvars, but the audit's own verdict is `Code-supported inference` — no run
has exercised it. Every cost view in this plan reads the ledger. So §6 is a cheap
pre-flight that proves the ledger captures a real evidence extraction **before** you spend
on E3.

### 1.4 What R9 is not

- Not a change to the default model. `THESISOUND_MODEL_FAST` stays `gemini-3.5-flash-lite`
  unless E3 says otherwise, in a later PR.
- Not a routing refactor. The override mechanism already exists and is what a positive
  result would ship.
- Not a fix for the salvage behaviour. R9 makes silent claim loss *visible*; whether to
  keep dropping claims silently is a separate question with its own evidence bar.
- Not the full eval harness (`services/eval_harness.py`). That runs an entire episode
  through twelve gates; E3 varies one stage and must not pay for or be confounded by the
  other eleven.

---

## 2. Scope

R9 runs in four phases. Phases 1 and 5 are code. Phases 0, 2 and 3 need a human decision or
provider spend, and you must stop and ask before each.

| Phase | What | Provider spend | Needs approval |
|---|---|---|---|
| **0** | Prove the ledger captures a real evidence extraction (§6) | ~3k input tokens | **yes** |
| **1** | Instrumentation: price every terminal status, count salvage and excerpt failures, ship the report command (§5) | none | no |
| **2** | Put real rates in `config/model-pricing.toml` (§7) | none | **yes — the user supplies the rates** |
| **3** | Run E3 and fill in the decision worksheet (§8) | ~70k input tokens | **yes** |

Phase 1 is worth doing on its own even if E3 is never run: B2 and B3 are audit §13's top
two "critical — without these a large part of this audit is not reproducible" items.

### In scope (Phase 1)

| # | Change | File |
|---|---|---|
| 1 | Price calls that end `rejected` or `failed`; keep the succeeded number's meaning | `src/thesisound/observability.py` |
| 2 | Widen `reprice()` past `succeeded` | `src/thesisound/observability.py` |
| 3 | Split delivered vs wasted cost in the rollup | `src/thesisound/services/observability_rollup.py`, `src/thesisound/observability.py` (the summary models) |
| 4 | Show wasted spend in `thesisound cost` | `src/thesisound/observability_cli.py` |
| 5 | `ExcerptNotFoundError`, salvage/excerpt counters, `corpus.evidence_attempts` event | `src/thesisound/services/evidence_extractor.py` |
| 6 | `thesisound evidence-tier-report` | `src/thesisound/observability_cli.py`, `src/thesisound/services/observability_rollup.py` |
| 7 | Document the E3 protocol | `.env.example`, this file's §8 |
| 8 | Tests | `tests/test_observability.py`, `tests/test_observability_rollups.py`, `tests/test_observability_cli.py`, `tests/test_evidence_salvage.py` (new) |

### Explicitly out of scope — do not touch

- **Adding price rows.** Not one. §7 is a request to the user, not a task for you. The
  project's refusal to guess prices is a documented design position
  (`services/model_pricing.py:47-64`); breaking it to make your own report look complete is
  the single worst thing you could do in this PR.
- **Changing `THESISOUND_MODEL_FAST`, `config/model-routing.toml`, or any default.**
- `_salvage_draft_inplace`'s behaviour. Count what it drops; drop exactly what it drops today.
- `model_runner.py`, `model_retry.py`, the prompt files, `analysis_profile.py`, the
  retention gate.
- R8 (evidence batching), R1, R2. See §3 D8 for the merge order if R8 is in flight.
- The `succeeded`-only semantics of `ProjectUsageSummary.total_cost_micros` — see D3.

---

## 3. Locked design decisions

Read all ten before writing code.

### D1 — Price every terminal status, not just `succeeded`

`reject()` and `fail()` gain the same `_price_call` step `succeed()` already has. The
tokens are already on the row (B2); only the pricing step is missing. A rejected call that
burned 2,800 input tokens cost real money and must carry `cost_micros`.

`running` and `provider_succeeded` are not terminal and are never priced.

### D2 — `cost_micros` means "what this call cost", for every status

Do not add a second column. The status column already says whether the money bought
anything; duplicating that into `wasted_cost_micros` at row level would let the two drift.
Aggregation splits by status (D3).

### D3 — `thesisound cost`'s headline number keeps its current meaning

`ProjectUsageSummary.total_cost_micros` stays **succeeded-only**. It is what someone has
already quoted in a report; silently growing it by the retry spend would be a worse sin
than not reporting the retry spend at all.

Add alongside it:

```python
    wasted_cost_micros: int = 0          # rejected + failed
    unpriced_wasted_count: int = 0
```

and render it as a second line in the CLI. Same rule in `CostBreakdownRow`: keep
`total_cost_micros` succeeded-only, add `wasted_cost_micros` and `wasted_call_count`.

An unpriced component must render as `unknown`, never as `0` — copy the existing
`_format_cost` / `priced_count` handling in `observability_cli.py:313-322` exactly. This is
the rule the whole pricing feature exists to enforce.

### D4 — The excerpt failure gets its own exception type, not a message match

Add to `evidence_extractor.py`:

```python
class ExcerptNotFoundError(DeterministicValidationError):
    """The excerpt is absent from the block even after lenient normalisation.

    A distinct type, not a distinct message: this is 25% of all evidence attempts and the
    audit had to grep `error_message` to find it. `error_type` is already persisted on
    every attempt record and every ledger row, so a subclass turns the pipeline's single
    largest retry driver into a value you can GROUP BY.
    """
```

Raise it from `_validate_claim_excerpt` in place of the generic
`DeterministicValidationError` **only for the "not present in the block" case**
(`evidence_extractor.py:362-365`). The "too short to audit" branch stays generic — it is a
different defect.

Verified safe: `decide_retry` dispatches with `isinstance(error, StructuredOutputError)`
(`model_retry.py:25`), and `ExcerptNotFoundError` is a `DeterministicValidationError` is a
`StructuredOutputError`, so retry behaviour is bit-for-bit unchanged.
`tests/test_model_runner.py:249` asserts `error_type == "DeterministicValidationError"` on
an error its own validator raises, so it is unaffected — confirm that before you run the
suite, do not "fix" it.

### D5 — Salvage is counted in the validator closure that already exists

`_extract_block` already keeps `attempt = {"n": 0}` across attempts
(`evidence_extractor.py:240`). Extend that dict; do not change `_salvage_draft_inplace`'s
signature, do not thread a counter through `ModelRunner`, and do not add a service
attribute (the service is shared across threads — a counter on `self` would race).

### D6 — One `corpus.evidence_attempts` event per block, always

Emitted for every processed block, including clean ones, so the denominator is the block
count and not "blocks that had a problem". Zero-valued events are what make a rate
computable.

Fields: `attempt_count`, `excerpt_failure_count`, `salvaged` (bool), `dropped_claim_count`,
`kept_claim_count`. Events land in `pipeline_events` and the rollup reads them the way
`cache_hit_rates` already reads `cache.lookup` (`observability_rollup.py:137-159`) — follow
that shape rather than inventing a second pattern.

### D7 — E3 switches tiers with `THESISOUND_MODEL_ROUTE_OVERRIDES`, never with `--model`

`thesisound extract-evidence` has a `--model` option, and it is the wrong lever. Passing a
non-default model takes the bypass branch in `ModelRouter._resolve_unchecked`
(`model_routing.py:108-109`): it returns a route directly and never consults a profile. That
is a code path production never takes.

The override goes through the profile, which is exactly what a positive E3 result would
ship:

```bash
THESISOUND_MODEL_ROUTE_OVERRIDES='{"evidence_extraction":"gemini_strong"}'
```

An experiment must exercise the mechanism it is recommending.

### D8 — Merge order against R8

R8 ("batched evidence extraction") also edits `evidence_extractor.py` and deliberately
leaves `_salvage_draft_inplace` untouched, copying it into `_salvage_entry_inplace`.
R9 adds counters around the single-block path. They do not conflict logically, but they
touch adjacent lines.

**Land R9 first** — it is ~40 lines in that file against R8's ~200 — and R8 rebases,
copying the same counters into its batch salvage. If R8 has already landed when you start,
add the counters to both `_salvage_draft_inplace` and `_salvage_entry_inplace`, and make
the batch path emit `corpus.evidence_attempts` per block as well. Say in the PR which order
actually happened.

### D9 — The report is a command, not a scratchpad script

The audit's own analysis scripts lived outside the repository (audit §14 Appendix B), which
is why the audit is not reproducible and why its retry economics cannot be recomputed
today. E3's numbers must come from a committed command with committed tests, or R9 leaves
the project exactly where R-nothing found it.

### D10 — The report says `undecidable`, loudly, when it is

If any component of either arm is unpriced, `evidence-tier-report --compare` prints
`verdict: undecidable` and names the missing price rows. It must never fall back to
comparing token counts and calling that a cost verdict — the two models have different
per-token rates, which is the entire reason E3 exists.

---

## 4. Invariants that must not change

| # | Invariant | Guarded by |
|---|---|---|
| I1 | Retry/backoff behaviour is unchanged by `ExcerptNotFoundError` | `tests/test_model_runner.py`, `tests/test_source_analysis.py::test_evidence_extractor_keeps_valid_claims_after_salvage` |
| I2 | `_salvage_draft_inplace` keeps and drops exactly the same claims as today | `test_evidence_extractor_keeps_valid_claims_after_salvage`, `test_evidence_extractor_rejects_block_when_nothing_survives` |
| I3 | `succeed()`'s persisted `cost_micros` is unchanged | `test_succeed_persists_cost_from_the_configured_pricer` |
| I4 | `ProjectUsageSummary.total_cost_micros` stays succeeded-only | `test_project_summary_reports_cost_and_unpriced_count` |
| I5 | An unpriced call renders `unknown`, never `0` | `test_cost_flags_unpriced_calls_instead_of_a_silent_zero` |
| I6 | The shipped pricing table still has zero active rows | `test_checked_in_pricing_file_ships_with_no_active_prices` |
| I7 | Extraction outcomes (`extracted` / `rejected` / `skipped`) are unaffected | `tests/test_evidence_fanout.py`, unedited |
| I8 | The default resolved model for `evidence_extraction` is still `model_fast` | new, §9.5 |

**Accepted behaviour changes, and only these four.** Name all four in the PR:

1. `error_type` on excerpt-rejected attempts becomes `ExcerptNotFoundError` instead of
   `DeterministicValidationError`, in both the run store and the ledger. Historical records
   keep the old value; any query over both must accept either.
2. `rejected` and `failed` calls now carry `cost_micros` where a price row exists. They
   previously carried none. With the shipped empty table this changes nothing observable.
3. `reprice()` now touches non-succeeded calls and its returned count grows accordingly.
4. `thesisound cost` gains a wasted-spend line and two columns.

---

## 5. Implementation (Phase 1)

### Step 1 — price terminal failures · `src/thesisound/observability.py`

`succeed()` (line 582) already does the work. Extract it so all three paths share it:

```python
    def _terminal_cost_fields(self, call_id: UUID) -> dict[str, Any]:
        """Price a call that has reached a terminal status.

        Rejected and failed calls are priced too: `provider_succeeded()` already wrote
        their token counts, the provider already billed for them, and they are the retry
        spend the whole point of audit R4/R9 is to make visible. Status, not the presence
        of a price, is what says whether the money bought anything.
        """

        if self.cost_pricer is None:
            return {}
        priced = self._price_call(call_id, self.cost_pricer)
        if priced is None:
            return {}
        return {"cost_micros": priced.cost_micros, "pricing_version": priced.pricing_version}
```

`succeed()` uses it unchanged in effect. Then:

```python
    def fail(self, call_id, error, *, error_code=None) -> None:
        self._finish(
            call_id,
            status="failed",
            error_type=type(error).__name__,
            error_code=error_code,
            error_message=redact_exception_message(str(error) or type(error).__name__),
            **self._terminal_cost_fields(call_id),
        )

    def reject(self, call_id, error) -> None:
        self._finish(
            call_id,
            status="rejected",
            error_type=type(error).__name__,
            error_message=redact_exception_message(str(error) or type(error).__name__),
            **self._terminal_cost_fields(call_id),
        )
```

`_finish` already builds its UPDATE from `**fields` (`:1171-1192`), so no other change is
needed. A call with no tokens (a connection reset, where `provider_succeeded` never ran)
prices to 0 micros — correct, and distinct from `NULL`/unknown.

### Step 2 — widen `reprice()`

```python
        # Rejected and failed calls burned tokens too. Restricting this to `succeeded`
        # made the retry spend permanently unpriceable even after a price row was added.
        clauses = ["status IN ('succeeded', 'rejected', 'failed')"]
```

Nothing else in the method changes.

### Step 3 — split delivered from wasted

In `observability.py`, add to `ProjectUsageSummary` and `CostBreakdownRow` the fields from
D3. In `observability_rollup.py`:

- `project_summary`: add two aggregates —
  `COALESCE(SUM(cost_micros) FILTER (WHERE status IN ('rejected','failed')), 0)` and
  `COUNT(*) FILTER (WHERE status IN ('rejected','failed') AND cost_micros IS NULL)` — and
  change the existing `SUM(cost_micros)` to
  `SUM(cost_micros) FILTER (WHERE status = 'succeeded')` so I4 holds now that failures
  carry a price.
- `cost_breakdown`: drop the `WHERE ... AND status = 'succeeded'` filter, and make every
  existing aggregate `FILTER (WHERE status = 'succeeded')` so the succeeded columns keep
  their meaning; add the two wasted columns over the complementary set. Keep the
  `ORDER BY` on succeeded cost.

SQLite supports `FILTER` from 3.30 (2019); the codebase already uses it throughout this
file, so no compatibility question.

### Step 4 — show it · `observability_cli.py`

Under the existing total line in `cost`:

```python
        if summary.wasted_cost_micros or summary.unpriced_wasted_count:
            wasted_display = (
                _format_cost(summary.wasted_cost_micros)
                if summary.wasted_cost_micros
                else "unknown"
            )
            console.print(
                f"  of which spent on rejected/failed calls: {wasted_display} "
                f"({summary.failed_count + summary.rejected_count} call(s))"
            )
```

Add `Wasted` and `Wasted calls` columns to the breakdown table, with the same
`unknown`-not-zero rule.

### Step 5 — count the salvage · `evidence_extractor.py`

**5a.** `ExcerptNotFoundError` per D4, raised from `_validate_claim_excerpt`:

```python
    verbatim = locate_excerpt(claim.supporting_excerpt, block_text)
    if verbatim is None:
        raise ExcerptNotFoundError(
            "supporting_excerpt must be copied from the supplied source block."
        )
```

The message stays byte-identical — historical records and any operator muscle memory keep
matching.

**5b.** Extend the counter dict in `_extract_block` (line 240) and the validator:

```python
        # One dict, mutated by the validator across attempts: `_extract_block` runs on a
        # worker thread and the service instance is shared, so this must not live on self.
        counters = {"n": 0, "excerpt_failures": 0, "salvaged": False, "dropped": 0}

        def validator(draft: EvidenceExtractionDraft) -> None:
            counters["n"] += 1
            try:
                _validate_draft(draft, block=block, profile=profile)
            except ExcerptNotFoundError:
                counters["excerpt_failures"] += 1
                if counters["n"] < max_attempts:
                    raise
                before = len(draft.claims)
                _salvage_draft_inplace(draft, block=block, profile=profile)
                counters["salvaged"] = True
                counters["dropped"] = before - len(draft.claims)
            except DeterministicValidationError:
                if counters["n"] < max_attempts:
                    raise
                before = len(draft.claims)
                _salvage_draft_inplace(draft, block=block, profile=profile)
                counters["salvaged"] = True
                counters["dropped"] = before - len(draft.claims)
```

Two arms, deliberately: the excerpt case is counted separately because it is the 25% case
E3 measures, while every other deterministic failure still salvages identically. The
subclass arm must come first — Python matches the first compatible `except`, and
`ExcerptNotFoundError` is a `DeterministicValidationError`. Behaviour is unchanged: today
the second arm already catches it.

`excerpt_failure_count` counts **attempts**, not claims: `_validate_draft` raises on the
first bad claim, so an attempt with three bad excerpts scores 1. That is deliberate — it
keeps the metric directly comparable to the audit's 80-of-320-attempts baseline.
`dropped_claim_count` is the claim-level number, and it is only ever non-zero on the final
attempt, because earlier attempts discard their whole draft.

**5c.** Emit the event on every path out of `_extract_block`, including the
`StructuredOutputError` and provider-error branches, so the denominator is the block count
(D6). Put it immediately before `return record, run`:

```python
        tracing.event(
            "corpus.evidence_attempts",
            component="corpus",
            project_id=project_id,
            subject_type="block",
            subject_id=block.block_id,
            attempt_count=counters["n"],
            excerpt_failure_count=counters["excerpt_failures"],
            salvaged=counters["salvaged"],
            dropped_claim_count=counters["dropped"],
            kept_claim_count=len(record.extraction.claims),
            status=record.status,
        )
```

`counters["n"]` is validator invocations, which equals the number of attempts that reached
validation. An attempt that failed at the provider never validates, so `attempt_count` can
be lower than `len(run.attempts)` — that is correct and is why the report reads provider
attempts from `model_calls` and validation attempts from this event. Put that sentence in a
comment; someone will otherwise "fix" the discrepancy.

**5d.** While you are here, assert the contract agreement that R8's plan also flags:
`_evidence_max_attempts` reads `contract.max_attempts` independently of the value
`ModelRunner` uses from the resolved bundle. They agree only because both resolve the same
version. Prompt versions 1.0.0/1.1.0 ship `max_attempts = 2` and 1.2.0/1.3.0 ship `3`, so a
divergence silently moves when salvage happens. Cover it with the test in §6.4, do not
"simplify" either call site.

### Step 6 — `thesisound evidence-tier-report` · `observability_cli.py` + rollup

```
thesisound evidence-tier-report <project-id> [--compare <project-id>] [--json]
```

A new `ObservabilityRollup.evidence_tier_summary(project_id)` returning one dataclass, read
from `model_calls` where `stage LIKE 'evidence_extraction%'` and from `pipeline_events`
where `name = 'corpus.evidence_attempts'`:

| Field | Source |
|---|---|
| `resolved_model`, `model_profile` | `model_calls` |
| `call_count`, `provider_attempt_count` | `model_calls` |
| `validation_attempt_count`, `excerpt_failure_count` | event sums |
| `excerpt_failure_rate` | `excerpt_failure_count / validation_attempt_count` |
| `block_count`, `salvaged_block_count`, `dropped_claim_count`, `kept_claim_count` | event sums |
| `claims_per_kept_block` | events, blocks with `status='extracted'` |
| `delivered_tokens`, `wasted_tokens` | `model_calls` split by status |
| `delivered_cost_micros`, `wasted_cost_micros`, `unpriced_count` | Step 3 |
| `latency_p50_ms`, `latency_p95_ms` | `model_calls.latency_ms` |

`--compare` prints the E3 worksheet: the two arms side by side, then

```
excerpt-failure rate:  A 25.0%  →  B  x.x%   Δ = -yy.y pp   threshold > 15 pp   PASS/FAIL
total cost:            A ...    →  B ...     ratio = z.zz×  threshold <= 1.20×  PASS/FAIL
claim yield/block:     A 1.94   →  B x.xx    ratio = z.zz×  (context, not a gate)
latency p50:           A ...    →  B ...                    (context, not a gate)

verdict: switch | keep | undecidable (<reason>)
```

`undecidable` whenever `unpriced_count > 0` on either arm, naming the exact
(provider, model, operation) tuples that need rows (D10). No percentile library — sort the
latencies and index; n is in the tens.

### Step 7 — `.env.example`

In the **Model routing** block, after `THESISOUND_MODEL_ROUTE_OVERRIDES={}`:

```
# Experiment E3 (audit R9): route evidence extraction to the strong model to compare the
# excerpt-error rate and total cost against the fast default. This is the mechanism a
# positive result would ship -- do not use `extract-evidence --model`, which bypasses
# profile resolution entirely. Measure with `thesisound evidence-tier-report`.
# THESISOUND_MODEL_ROUTE_OVERRIDES={"evidence_extraction":"gemini_strong"}
```

---

## 6. Tests

### 6.1 Pricing terminal failures — `tests/test_observability.py`

Extend the existing pricer-backed fixtures in that file rather than building new ones.

- **P1** a call that reaches `reject()` with a configured price carries `cost_micros` and
  `pricing_version`.
- **P2** same for `fail()`.
- **P3** a rejected call with **no** price row leaves `cost_micros` NULL — not 0.
- **P4** a call that failed before `provider_succeeded()` (no tokens) prices to `0`, and
  `0` is distinguishable from NULL in the row.
- **P5** `succeed()`'s persisted value is byte-identical to before (I3) — the existing test
  must pass unedited.
- **P6** `reprice()` now updates rejected and failed rows, and its returned count includes
  them.
- **P7** `reprice(since=...)` still respects the cutoff on the widened status set.

### 6.2 Rollup split — `tests/test_observability_rollups.py`

- **R1** `project_summary.total_cost_micros` excludes rejected/failed spend (I4), and
  `wasted_cost_micros` equals exactly that spend.
- **R2** `cost_breakdown` groups a stage that has both succeeded and rejected calls into
  **one** row with both columns populated — not two rows.
- **R3** a stage with only rejected calls appears in the breakdown with
  `total_cost_micros = 0` and a non-zero `wasted_cost_micros`. Before this change it was
  invisible; that is the bug.
- **R4** `unpriced_wasted_count` counts rejected/failed calls with NULL cost.

### 6.3 CLI — `tests/test_observability_cli.py`

- **C1** `cost` prints the wasted line when there is wasted spend.
- **C2** `cost` prints `unknown`, not `0`, when the wasted calls are unpriced (I5).
- **C3** `cost` output for a project with no failures is unchanged from today — assert
  against the existing expected text.
- **C4** `evidence-tier-report` on a single project prints every field in the Step 6 table.
- **C5** `evidence-tier-report --compare` with both arms fully priced prints a `switch` or
  `keep` verdict and both threshold lines.
- **C6** `evidence-tier-report --compare` with **one** unpriced call on either arm prints
  `undecidable` and names the missing (provider, model, operation). This is D10 and is the
  most important CLI test in the PR.
- **C7** `evidence-tier-report` on a project with no evidence calls exits cleanly with a
  message, like `cost` does.

### 6.4 Extraction counters — `tests/test_evidence_salvage.py` (new)

Build on `SalvagingFakeRunner` and `AlwaysBadExcerptRunner`
(`tests/test_source_analysis.py:656,718`) — model them, do not import them; `tests/` is not
a package.

- **S1** a clean block emits `corpus.evidence_attempts` with `attempt_count=1`,
  `excerpt_failure_count=0`, `salvaged=False`, `dropped_claim_count=0`.
- **S2** a block whose first attempt has one bad excerpt and whose second is clean emits
  `excerpt_failure_count=1`, `salvaged=False`, `dropped_claim_count=0`.
- **S3** a block that fails every attempt emits `salvaged=True` and a
  `dropped_claim_count` equal to the number of claims `_salvage_draft_inplace` actually
  removed. Assert the surviving claims are identical to today's (I2).
- **S4** every processed block emits exactly one event, including provider-skipped and
  contract-rejected blocks (D6). Assert `len(events) == len(pending)` over a mixed fixture.
- **S5** `ExcerptNotFoundError` is raised for a missing excerpt and a plain
  `DeterministicValidationError` for a too-short one; both are `StructuredOutputError`
  instances, so `decide_retry` returns `should_retry=True` for both (I1).
- **S6** the recorded `error_type` on a retried attempt is `ExcerptNotFoundError` while the
  `error_message` is byte-identical to the historical string.
- **S7** `_evidence_max_attempts(runner, version)` equals
  `PromptLoader().load_contract("evidence_extraction", version=version).max_attempts` for
  **every** shipped version — parametrise over `["1.0.0", "1.1.0", "1.2.0", "1.3.0", None]`.
  This is 5d; the 1.x split between 2 and 3 attempts is exactly the divergence it catches.
- **S8** counters are per block under fan-out: run 8 blocks at `max_workers=4` where blocks
  3 and 6 salvage, and assert only those two events have `salvaged=True`. Repeat 10 times —
  a counter accidentally hung off `self` passes once and fails under load.

### 6.5 Default routing is untouched

```python
def test_evidence_extraction_still_resolves_to_the_fast_model_by_default() -> None:
    settings = Settings(environment="test")
    router = load_model_router(settings)
    route = router.resolve(
        stage="evidence_extraction",
        requested_model=settings.model_fast,
        model_tier="fast",
    )
    assert route.model == settings.model_fast
    assert route.profile == "gemini_fast"
```

and its counterpart proving the override works, since D7 depends on it:

```python
def test_the_route_override_moves_evidence_extraction_to_the_strong_profile() -> None:
    settings = Settings(
        environment="test",
        model_route_overrides={"evidence_extraction": "gemini_strong"},
    )
    route = load_model_router(settings).resolve(
        stage="evidence_extraction",
        requested_model=settings.model_fast,
        model_tier="fast",
    )
    assert route.model == settings.model_strong
    assert route.profile == "gemini_strong"
```

Put both in `tests/test_model_routing.py`.

### 6.6 Hygiene

- No test may add a price row to `config/model-pricing.toml`. Build pricers from
  `tmp_path` TOML files, as `tests/test_model_pricing.py` already does. I6 guards the
  shipped file.
- No `sleep()`; S8 uses repetition, not timing.

---

## 7. Verification (Phase 1)

```bash
uv run ruff check .
```

```bash
uv run pytest tests/test_observability.py tests/test_observability_rollups.py tests/test_observability_cli.py tests/test_model_pricing.py tests/test_evidence_salvage.py tests/test_model_routing.py tests/test_source_analysis.py tests/test_evidence_fanout.py tests/test_model_runner.py -v
```

```bash
uv run pytest
```

```bash
for i in 1 2 3 4 5 6 7 8 9 10; do uv run pytest tests/test_evidence_salvage.py -q || break; done
```

Then by hand:

- [ ] `git diff config/model-pricing.toml` is empty.
- [ ] `git diff config/model-routing.toml` is empty.
- [ ] `grep -n "status = 'succeeded'" src/thesisound/services/observability_rollup.py` — every
      remaining hit is inside a `FILTER`, not a `WHERE` that hides failures.
- [ ] `grep -rn "model_fast" src/thesisound/config.py` — default unchanged.
- [ ] `_salvage_draft_inplace`'s body is unchanged; only its callers count.
- [ ] `thesisound cost <any-project>` on the existing workspace still runs and still says
      unknown everywhere.
- [ ] `thesisound evidence-tier-report f781a5c7-9b58-4acb-99af-90b2b265e4f6` runs and
      reports what the ledger actually holds — which for this project is almost nothing
      (audit §4). That is the expected, correct output, and it is also the evidence for
      why Phase 0 exists.

---

## 8. Phases 0, 2 and 3 — the experiment

**Stop here and ask before any of the following.** Each spends money or needs a decision
that is not yours.

### 8.0 Phase 0 — prove the ledger before spending on it (~3k input tokens)

B4 says no run has ever exercised the ledger's correlation path. Verify it on one block
before committing to a two-arm experiment whose entire readout comes from that table.

1. Create a throwaway project, ingest any small text file, build blocks, map the document.
2. Run `extract-evidence` on it.
3. Then check:

```sql
SELECT COUNT(*) FROM model_calls WHERE stage='evidence_extraction' AND workflow_run_id IS NOT NULL;
SELECT COUNT(*) FROM model_calls WHERE stage='evidence_extraction' AND pipeline_trace_id IS NOT NULL;
SELECT name, COUNT(*) FROM pipeline_events WHERE name='corpus.evidence_attempts' GROUP BY 1;
SELECT status, input_tokens, cost_micros FROM model_calls WHERE stage='evidence_extraction';
```

All four must return live rows, and `input_tokens` must be non-NULL on any `rejected` row.
**If they do not, stop.** Fixing the ledger's capture path is a prerequisite, not a
footnote, and E3 run blind against a half-empty table would produce a confident wrong
answer.

### 8.1 Phase 2 — the price rows (a question for the user, not a task)

E3 cannot produce a verdict without these. Ask for, exactly:

> For **`gemini-3.5-flash-lite`** and **`gemini-3.6-flash`**, operation `structured_text`,
> on your account and region: the input, output and cached-context rates, in your currency
> per one million tokens, and the date they took effect.

Then add two `[[prices]]` blocks in the shape the file already documents, set
`version` to something dated like `"2026-08-account-list"`, and run
`thesisound observability-reprice`. **Do not source these from a public pricing page and do
not interpolate** — the file's header explains why, and a wrong rate here produces a
confident wrong verdict rather than an honest `undecidable`.

If the user cannot supply rates, E3 still runs and still answers the *quality* half
(excerpt-failure rate, claim yield, salvage loss); the cost half stays `undecidable` and
the recommendation is explicitly partial. Say that rather than guessing.

### 8.2 Phase 3 — run E3 (~70k input tokens)

**Two projects, not two runs of one.** `extract_evidence` skips blocks already recorded as
`extracted` (`source_analysis_service.py:236-237`), so a second run on the same project
would call the model zero times.

**Both projects need the same `ResearchBrief`** — not just any brief. `extract_evidence`
refuses to run without one, and `plan_evidence_extraction(project.brief, document_map,
blocks)` derives the analysis profile, the token budget and therefore the whole block
selection from it. Two arms with different `target_duration_minutes` are two different
experiments. Copy the audited run's brief verbatim from
`workspaces/f781a5c7-…/project.json` into both, so the plan also matches the 13-block
fixture the §6 tests lock.

The document map is free. `workspaces/_shared/document-maps/` already holds the
47-section map for this EPUB, content-keyed, and `map_document` consults that shared cache
before calling the model — I verified its section list is identical to the real run's. So
each arm pays for evidence extraction only, and both arms get a **byte-identical document
map and therefore a byte-identical 13-block plan**. That equality is the experiment's
control; assert it before spending.

```bash
# Arm A -- current default
thesisound build-blocks <project-a> <ingestion.json>
thesisound map-document <project-a> <source-a>     # shared-cache hit, no provider call
thesisound extract-evidence <project-a> <source-a>
```

```bash
# Arm B -- strong tier, via the production mechanism (D7)
THESISOUND_MODEL_ROUTE_OVERRIDES='{"evidence_extraction":"gemini_strong"}' thesisound extract-evidence <project-b> <source-b>
```

Before the second arm, confirm the control:

```bash
diff <(jq -S .selected_block_ids workspaces/<project-a>/sources/<source-a>/evidence-extraction-plan.json) \
     <(jq -S .selected_block_ids workspaces/<project-b>/sources/<source-b>/evidence-extraction-plan.json)
```

Empty output, or the arms are not comparable and the run is void.

Also confirm from `map-document`'s output that neither arm made a `document_map*` model
call. If one did, the map cache missed and the arms may differ — stop and find out why
before extracting.

Then:

```bash
thesisound evidence-tier-report <project-a> --compare <project-b>
```

### 8.3 The decision

E3's rule, unchanged from the audit: **switch if the strong model reduces the
excerpt-failure rate by more than 15 percentage points *and* total cost is at most 1.20×.**

Three honest outcomes, and you must be willing to write any of them:

| Report says | Do |
|---|---|
| `switch` | Open a follow-up PR that sets the route in `config/model-routing.toml`, not an env var. Quote the worksheet in the description. |
| `keep` | Write it down in this file and in the audit's R9 row. A measured "no" is the whole point of an experiment; it is not a failed PR. |
| `undecidable` | Report the quality half, name the missing price rows, and stop. Do not estimate. |

Whatever the outcome, record in the PR: both arms' project ids, the pricing `version`
string in force, the prompt version resolved, and `n = 13 blocks, 1 corpus, 1 language,
1 duration`. The audit's Constraint 1 applies to this experiment as much as to the audit:
**n = 1 is not a representative sample of the pipeline**, and a single passing arm is
evidence that the strong model did better *on this book*, not that it is better.

---

## 9. Definition of done

**Phase 1 (this PR):**

1. Steps 1–7 implemented exactly as specified.
2. §6.1–6.6 written and passing; ten consecutive clean runs of `tests/test_evidence_salvage.py`.
3. Full `uv run pytest` and `uv run ruff check .` green.
4. §7 checklist walked.
5. PR description states: the four accepted behaviour changes from §4; that R4 and the
   `started_at` bug are **already fixed** in HEAD so E3's stated prerequisite is met; that
   B1 (no price rows) is unresolved and why that is deliberate; the merge order agreed with
   R8 (D8); and that no experiment was run.

**Phases 0/2/3 (later, with approval):** the completed §8.3 worksheet, both arms' project
ids, and the outcome written back into R9's row of the audit — including if the outcome is
`keep` or `undecidable`.

**Do not** change the default model, add price rows, bundle R8, or "improve"
`_salvage_draft_inplace` while you are in the file. One recommendation, one PR.
