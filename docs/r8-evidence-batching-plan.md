# R8 — Batched evidence extraction with a per-block fallback

**Implementation plan. Follow it as written.**

Audience: a junior/mid-level developer on this codebase.
Source of the requirement: [`docs/thesisound-pipeline-audit.md`](thesisound-pipeline-audit.md) §10 row **R8**, §5 "پروفایل هزینه‌ی ورودی evidence extraction", §12 experiment **E2**.

> R8 🟧P1 — «۵۵.۳٪ توکن ورودی evidence، سربار تکراری است» → «چند بلوک را در یک فراخوانی batch کن، یا context ثابت را در cache مدل بگذار»
> Quality ~0 · Latency medium · **Cost high** · Effort medium · Risk medium — «ممکن است دقت استخراج را کم کند؛ **نیاز به آزمایش**» · Confidence High

This is a **cost** change. It must not change the shape of a single artifact, must not
change the default behaviour of the pipeline, and must not degrade any gate. Every design
decision below is already made; do not substitute your own. If you believe a decision is
wrong, stop and raise it before writing code — do not silently pick a different approach.

---

## 1. What the change is, and a correction to the audit

`EvidenceExtractorService.extract_source` makes **one model call per selected block**.
Every call re-sends a fixed preamble (system prompt, `working_thesis`, `analysis_profile`)
plus a per-block payload that includes fields the system prompt explicitly forbids the
model to use.

This change adds a second call shape — **K blocks in one call** — behind a setting that
defaults to the current behaviour (K = 1), plus a **per-block fallback** so a batch can
never produce a worse outcome than K = 1.

### 1.1 The audit's 55.3% is not all recoverable — measured

The audit reports "55.3% of input tokens are not source text" and an overhead factor of
2.2×. Both are correct. But **only the fixed part of that overhead can be amortised by
batching**, and it is smaller than 55%.

Re-rendering `prompts/evidence_extraction/1.3.0` with the real variables of the only real
run (project `f781a5c7`, 40 selected blocks, `workspaces/…/98863830-…/`), the mean call is
**10,050 characters**, split as:

| Component | chars/call | share | amortisable by batching? |
|---|---:|---:|---|
| `system.md` | 2,143 | 21.3% | ✅ |
| `user.md` scaffold + closing instruction | 577 | 5.7% | ✅ |
| `analysis_profile` JSON | 488 | 4.9% | ✅ |
| `working_thesis` | 329 | 3.3% | ✅ |
| `source_id` | 36 | 0.4% | ✅ |
| **fixed subtotal** | **3,575** | **35.5%** | ✅ |
| `block.text` — the actual evidence | 4,916 | 48.9% | ❌ |
| `block.source_block_keys` | 538 | 5.4% | ❌ but **removable** |
| `block.locator` | 185 | 1.8% | ❌ but **removable** |
| `block.source_id` / `block_id` / `previous_block_id` / `next_block_id` / `estimated_token_count` | 228 | 2.3% | ❌ but **removable** |
| `block.heading_path` + `block.block_type` | 61 | 0.6% | ❌ keep |
| `section_context` | 547 | 5.4% | ❌ but **trimmable** |

Two consequences you must internalise before writing code:

1. **Batching alone can never reach E2's ≥35% threshold.** Even putting all 40 blocks in
   one call only removes the 35.5% fixed share, and 39 of 40 preambles is 34.7%.
2. **The second lever is trimming the per-block payload.** `system.md` already says
   *"Do not generate IDs, source IDs, block IDs, page numbers, or locators; the
   application creates them deterministically."* We send 951 chars/call of exactly those
   fields anyway. Removing them plus `section_context.source_block_ids` /
   `section_id` / `depends_on_section_ids` / `required_for_global_understanding` shrinks
   the per-block payload from 6,475 to **5,273 chars (−18.6%)**.

Combined (trimmed payload + batching), measured on the same 40 real blocks:

| K | total chars | reduction vs today |
|---:|---:|---:|
| 1 | 366,716 | 8.8% |
| 2 | 288,816 | 28.2% |
| 3 | 265,446 | 34.0% |
| **4** | **249,866** | **37.8%** |
| 6 | 238,181 | 40.8% |
| 8 | 230,391 | 42.7% |

**E2's ≥35% threshold is met at K ≥ 4, and only with both levers.** Say this in the PR
description. Do not claim 55%.

### 1.2 What this does *not* fix, and why the fallback exists

Retries are the trap. The audit measured **1.32 attempts per `evidence_extraction` run**
and **77 of 320 attempts (24%) rejected for `supporting_excerpt must be copied from the
supplied source block`**. If a batch of 4 retries whenever *any* of its 4 blocks has a bad
excerpt, the retry probability per call rises to ~64% and each retry costs 4×. The saving
disappears entirely.

So the batch call **never retries because of a per-entry excerpt problem**. It repairs
what it can, drops what it cannot, and the blocks left with nothing go to the **existing,
proven single-block path** (§3 D6). Modelled against the honest baseline (today's cost ×
1.32 attempts):

| K | fallback rate | reduction vs today's real bill |
|---:|---:|---:|
| 4 | 10% | 42.9% |
| 4 | 15% | 37.9% |
| 4 | 24% | 28.9% |
| 8 | 10% | 46.6% |
| 8 | 15% | 41.6% |
| 8 | 24% | 32.6% |

**The fallback rate is the single unknown that decides whether R8 pays off, and it can
only be measured against a live provider.** That is what E2 is for. Your job is to ship
the capability, default it off, and make the fallback rate a first-class recorded metric
(§5 Step 4g). Your job is **not** to turn batching on.

### 1.3 Why not Gemini context caching

The audit offers it as the alternative. Do not attempt it in this PR:

- The amortisable prefix is ~3,575 chars ≈ **1,000 tokens**, at or below the explicit
  context-cache minimum, so an explicit cache is likely not even creatable.
- `config/model-pricing.toml` has `version = "unset"` and zero active rows (audit §4), so
  there is no way to price a cache hit against a normal call. The decision would be
  unfalsifiable.
- `ModelUsage.cached_tokens` is NULL on 462 of 481 recorded attempts (audit §4 item 3), so
  we cannot even tell whether implicit caching is happening today.

What you **do** owe the future decision: the batch prompt must keep all fixed content in a
contiguous block at the very start of the request, before any per-block data, so an
implicit prefix cache can match. That is already how §5 Step 2 orders the template. Do not
reorder it.

### 1.4 Already done — do not redo

- **R5** (analysis budget) is fixed: the plan is now 13 blocks / 18,307 tokens, not 40 /
  55,913. All grids above are quoted on the 40-block artifact because that is the only
  rendering evidence we have; §6.4 locks the 13-block numbers as the regression test.
- **R7** (parallel `document_map_part`) is in the working tree. `EvidenceExtractorService`
  already fans out over `max_workers`; you are changing the *unit* of that fan-out, not
  adding concurrency.
- **R1, R2, R4** are unrelated. Do not touch them.

---

## 2. Scope

### In scope

| # | Change | File |
|---|---|---|
| 1 | `BatchEvidenceEntryDraft`, `BatchEvidenceExtractionDraft` | `src/thesisound/source_analysis.py` |
| 2 | New versioned prompt `evidence_extraction_batch/1.0.0` | `prompts/evidence_extraction_batch/1.0.0/{contract.json,system.md,user.md}` |
| 3 | Route row for the new prompt id | `config/model-routing.toml` |
| 4 | Batch planning, batch call, per-entry validation, per-block fallback, unit-level breaker | `src/thesisound/services/evidence_extractor.py` |
| 5 | `evidence_extraction_batch_size` setting | `src/thesisound/config.py` |
| 6 | Wire the setting at both composition roots | `src/thesisound/web/corpus_runtime.py`, `src/thesisound/source_cli.py` |
| 7 | Document the knob | `.env.example` |
| 8 | Tests | `tests/test_evidence_batching.py` (new), one addition to `tests/test_source_analysis.py` |

### Explicitly out of scope — do not touch

- **Turning batching on by default.** `evidence_extraction_batch_size` ships as `1`.
  Changing it is E2's decision, made on E2's evidence, in a later PR.
- **`prompts/evidence_extraction/1.[0-3].0`.** Not one byte. In particular do **not**
  create `evidence_extraction/1.4.0` with the trimmed payload: `PromptLoader._resolve_version_dir`
  picks the *highest* version when `prompt_version is None`, and production passes `None`,
  so a new version directory would silently become the production prompt with no code
  change and no provider A/B. That is a separate, deliberate PR (§8.4).
- `document_map_merge` (R1), `audio_qa` (R2), `model_runner.py` usage recording (R4),
  `script_verifier` routing (R6), `document_mapper.py` (R7).
- `analysis_profile.py`, `plan_evidence_extraction`, the retention gate constants in
  `source_analysis_service.py`, `evidence_validator.py`, `excerpt_matching.py`.
- `ModelRunner`. The batch path uses it exactly as the single-block path does. Do **not**
  add "change the variables between attempts" — that would touch every stage.
- Gemini context caching, prompt-size limits, model tier selection (that is R9/E3).

---

## 3. Locked design decisions

Read all ten before writing code.

### D1 — Default `batch_size = 1`, and K = 1 is byte-identical to today

At `batch_size == 1` the service must take the existing `_extract_block` path, with the
existing prompt, the existing stage string, the existing variables. Not "equivalent" —
identical. This is not politeness; it is what keeps ~30 existing tests green without
edits. `FakeRunner` (`tests/test_source_analysis.py:113`), `SelectiveRunner`
(`tests/test_evidence_fanout.py:43`) and `ProviderSkippingRunner` all read
`variables["block"]` and would raise `KeyError` on a batch payload. If you find yourself
editing those doubles, you have broken D1.

### D2 — A separate prompt id, not a new version of the old one

`evidence_extraction_batch` is a new prompt id with its own contract, its own
`output_model`, its own `max_attempts`, and its own observability stage string. Reasons:

- `PromptLoader` resolves the highest version of a *name*; a new name cannot capture the
  existing name's default resolution (§2, out of scope).
- The audit's `model-runs/` stage table stays comparable across the change: `stage="evidence_extraction"`
  keeps meaning "one block, one call", and `stage="evidence_extraction_batch"` is new mass.
  E2 needs exactly that separation.
- `ModelRunner` asserts `bundle.contract.output_model == output_type.__name__`, so the two
  shapes cannot be confused at runtime.

### D3 — Attribution is by ordinal index, and block IDs are never sent

Each element of the `blocks` payload carries `"index"`, 1-based, its position **in this
call**. Each returned entry carries `block_index`. The application maps
`entry.block_index → unit[block_index - 1]`.

Do **not** ask the model for a `block_id` and do not zip entries positionally.

- Not `block_id`: the system prompt forbids the model from producing IDs, and sending them
  would re-add the payload we are removing. An ID the model can echo is an ID the model
  can hallucinate.
- Not positional zip: a positional zip silently mis-attributes when the model reorders,
  and mis-attribution here means a claim carrying another block's `locator` into the
  claim ledger. In an auditability-first product that is the worst possible failure.

The index set is validated (D4). Excerpt validation against the mapped block is the second
net: a mis-attributed claim quotes text that is not in the block it was mapped to, so it is
dropped rather than persisted.

### D4 — Structural failures retry; per-entry failures do not

Two distinct validation classes inside the batch validator:

| Class | Examples | Action |
|---|---|---|
| **Structural** | entry count ≠ K; `block_index` outside 1..K; a duplicated `block_index` | `raise DeterministicValidationError` → `ModelRunner` retries the batch |
| **Per-entry** | excerpt not locatable in its block; editorial claim; duplicate claim inside one entry; over `max_claims_per_block`; examples/objections the profile did not allocate | repair in place if possible, otherwise **drop that item**, never raise |

Structural failures are rare, cheap to detect, and a retry usually fixes them. Per-entry
failures are the measured 24% case; retrying the whole batch for one of them is what
destroys the economics (§1.2). The per-entry rules are exactly the ones
`_salvage_draft_inplace` already applies on the final single-block attempt — you are
applying them on the first attempt instead of the third, and paying for the difference
with the fallback. The batch gets its own copy of that function (§5 Step 4h), not a
shared refactor: the single-block path is E2's control arm and must not move.

### D5 — Per-entry budget checks are per entry, never per call

`max_claims_per_block` means per block. In a batch of 4 with `max_claims_per_block = 2`,
the legal maximum is 2 per entry, not 8 in the call. Same for `include_examples` and
`include_objections_and_responses`. Apply the same rules once per entry, against that
entry's own block — never against the call as a whole, and never against a concatenation
of the unit's blocks.

### D6 — A batch never produces a worse outcome than K = 1

This is the invariant that makes batching safe to ship. A block falls back to
`self._extract_block(...)` — the untouched single-block path, prompt
`evidence_extraction`, full 3-attempt retry with repair instruction — when:

| Batch outcome | Fallback? |
|---|---|
| Entry present, produced ≥1 claim or any auxiliary content | ❌ keep the batch result |
| Entry present but empty after salvage | ✅ that block only |
| Call raised `StructuredOutputError` (incl. `DeterministicValidationError` after retries) | ✅ every block in the unit — the provider answered, so it is alive |
| Call raised `ModelProviderError` / `ModelSafetyError`, **and some block has already succeeded** | ✅ every block in the unit |
| Call raised `ModelProviderError` / `ModelSafetyError`, **and nothing has succeeded yet** | ❌ record every block `skipped` and let the breaker decide (D8) |
| Fallback itself fails | ❌ record its outcome; **never a third call** |

Fallback runs sequentially inside the worker that owned the unit. It is already parallel
across units; do not open a nested pool.

Consequence you must state in the PR: **a whole batch lost with no fallback is the only
way batching can make the `evidence-retention` gate worse than today.** With a 13-block
R5 plan and K = 4, one un-recovered batch is 30.8% of planned tokens — retention 69%, below
the 75% hard floor in `source_analysis_service.py:43`, so the source fails. D6 confines
that to "the very first unit failed at the provider and nothing has succeeded yet", which
is precisely the case the breaker already aborts on.

### D7 — Batch composition: consecutive, capped by count *and* by source tokens

Units are consecutive slices of `pending` in document order. A unit closes when it holds
`batch_size` blocks **or** adding the next block would push its source tokens over
`_MAX_BATCH_SOURCE_TOKENS = 12_000`. A single block larger than the cap becomes a unit of
one.

- Consecutive, not "grouped by section": on the real run **all 40 selected blocks sit in
  40 distinct sections** (R5 seeds one block per required section), so a section key would
  produce 40 batches of one. Verified against `document-map.json`; do not re-derive it.
- 12,000 is chosen so the cap does not silently override the configured `batch_size` for
  ordinary blocks: the largest observed block is 1,679 tokens and the mean is 1,398, so
  K = 8 fits under the cap in the normal case and the cap only bites on pathological blocks.
- Output length is the other reason for a cap: K entries × `max_claims_per_block` claims.
  If the model truncates, the structured output is invalid → `StructuredOutputError` →
  every block falls back (D6). Correct, but expensive; the cap keeps it rare.

### D8 — The circuit breaker counts *units*, not records

`_BREAKER_CONSECUTIVE_FAILURES = 3` stays at 3, and the probe arithmetic in the fan-out
loop stays exactly as it is. The only change: `consecutive_skipped` increments **once per
unit whose every block ended `skipped`**, and resets when any block in a unit did not.

If you leave the counter incrementing per record, a single failed batch of 3+ blocks trips
the breaker on its own and one transient 503 aborts an entire source. Today three separate
blocks must fail. Preserve that.

**Do not add a "probe with a singleton batch first" scheme.** It was considered and
rejected: it costs 3 unbatched blocks on every healthy run (−6 percentage points of saving
on a 13-block plan) to protect against a case that costs nothing in tokens — a 429/503/
connection-reset is not billed. The breaker exists here to fail fast, not to save money.

### D9 — One run record per call, deduplicated

`extract_source` returns `list[ModelRunRecord]`, and `SourceAnalysisService.extract_evidence`
does `manifest.model_run_ids.extend(run.run_id for run in runs)`. A batch produces one
record shared by K blocks. If you build `runs` per block as the current code does
(`evidence_extractor.py:206`), the manifest gets K copies of one run id. **Deduplicate by
`run_id`, preserving first-seen order.**

### D10 — Neighbour context excludes blocks that are in the same unit

`profile.neighbor_context_blocks` is 0 for `brief`/`standard`, 1 for `deep`, 2 for
`extended`. In a batch of consecutive blocks the neighbours *are* the siblings, so
including them would send the same text twice **and** contradict the system prompt, which
says context "must never supply a claim or supporting excerpt" while that same text is a
target block in the same call. Filter out any neighbour whose `block_id` is in the unit.

---

## 4. Invariants that must not change

Each row is enforced by a test that already exists, or by one you will write in §6.

| # | Invariant | Guarded by |
|---|---|---|
| I1 | `batch_size=1` calls the model with `variables["block"]` and stage `evidence_extraction` | every existing test in `test_evidence_fanout.py` and `test_source_analysis.py`, unedited |
| I2 | Returned records are in `blocks` order and contain at most one record per block | `validate_evidence_collection`; §6.2 B2 |
| I3 | Every claim's `supporting_excerpt` is verbatim in **its own** block | `validate_evidence_extraction`; §6.2 C5 |
| I4 | `evidence_id` is deterministic from (source_id, block_id, claim, excerpt) | `_evidence_id`, unchanged; §6.2 B1 |
| I5 | `on_extraction` is called exactly once per processed block | §6.2 B3 |
| I6 | A block that produced nothing is `rejected`; a block the provider never answered for is `skipped` | `test_contract_failure_is_still_rejected_not_skipped`, §6.2 E1/E2 |
| I7 | The breaker aborts after 3 consecutive failed units with zero successes | `test_breaker_aborts_after_three_consecutive_provider_failures`; §6.2 E3 |
| I8 | `ModelConfigurationError` propagates out of `extract_source` | `test_configuration_error_aborts_the_batch`; §6.2 E6 |
| I9 | Already-extracted blocks are never re-called | `test_skipped_blocks_are_retried_on_the_next_attempt`; §6.2 A6 |
| I10 | `manifest.model_run_ids` has one entry per model call | §6.2 B4 |
| I11 | Spans nest under the submitting thread's span | `tests/test_tracing_propagation.py`; §6.2 G2 |

**Accepted behaviour changes, and only these three.** Name all three in the PR description:

1. At `batch_size > 1`, `runs` contains one record per call rather than per block. Nothing
   asserts the old count.
2. At `batch_size > 1`, a block may be model-called twice (batch, then fallback). Bounded
   at two by D6.
3. `corpus.extract_evidence` spans are emitted only for single-block calls and fallbacks;
   batched blocks are covered by one `corpus.extract_evidence_batch` span. At the default
   `batch_size = 1` nothing changes.

---

## 5. Implementation

### Step 1 — `src/thesisound/source_analysis.py`

Directly **after** `EvidenceExtractionDraft` (line 173):

```python
class BatchEvidenceEntryDraft(BaseModel):
    """One block's extraction inside a batched call.

    ``block_index`` is 1-based and refers to this block's position in THIS call's
    TARGET_BLOCKS_JSON list. It is the only attribution channel -- block IDs are not
    sent to the model at all, so an entry cannot claim a block the call did not
    contain, and a reordered response is still attributed correctly.
    """

    block_index: int = Field(ge=1)
    extraction: EvidenceExtractionDraft


class BatchEvidenceExtractionDraft(BaseModel):
    entries: list[BatchEvidenceEntryDraft] = Field(default_factory=list)
```

Nested, not inherited. A flattened variant would put `block_index` alongside 10 draft
fields in the generated JSON schema; the audit already records
`additionalProperties is not supported in the Gemini API` breaking `episode_plan`
(§5, retry drivers). Keep the shape shallow and boring.

### Step 2 — `prompts/evidence_extraction_batch/1.0.0/`

**`contract.json`:**

```json
{
  "id": "evidence_extraction_batch",
  "version": "1.0.0",
  "model_tier": "fast",
  "output_model": "BatchEvidenceExtractionDraft",
  "max_attempts": 3,
  "retry_schema_errors": true,
  "system_file": "system.md",
  "user_file": "user.md"
}
```

**`system.md`:** copy `prompts/evidence_extraction/1.3.0/system.md` verbatim, change the
first line to say *blocks*, and append a `Batch rules` section. Do not reword any existing
grounding rule — E2 must not be confounded by a rewritten prompt.

```markdown
You extract auditable evidence from a numbered list of semantic document blocks under an
explicit analysis budget.

<... every existing rule from 1.3.0, unchanged ...>

Batch rules:
- Return exactly one entry per target block, including blocks that support nothing. An
  entry for an unsupported block has an empty claims list.
- entries[i].block_index must equal the `index` field of the block that entry describes.
  Never renumber, never merge two blocks into one entry, never emit an index twice.
- Each entry's claims, excerpts, definitions and distinctions must come only from the
  block with that entry's index. Never quote one block in another block's entry.
- The analysis budget applies to each block separately, not to the call as a whole.
```

**`user.md`:**

```markdown
<SOURCE_ID>
{{ source_id }}
</SOURCE_ID>

<WORKING_THESIS>
{{ working_thesis }}
</WORKING_THESIS>

<ANALYSIS_PROFILE_JSON>
{{ analysis_profile }}
</ANALYSIS_PROFILE_JSON>

<TARGET_BLOCKS_JSON>
{{ blocks }}
</TARGET_BLOCKS_JSON>

Extract evidence for every target block at the depth allowed by the analysis profile.
Return exactly {{ block_count }} entries, one per block, each carrying that block's
`index` value as its block_index. Claims and supporting excerpts must be grounded only in
the block they are attributed to. If a block does not support a substantive claim, return
its entry with an empty claims list and preserve useful unresolved context within the
allocated budget.
```

Placeholder order is load-bearing: everything fixed comes first and `{{ blocks }}` last, so
the whole preamble is a contiguous prefix an implicit cache could match (§1.3). Do not
reorder.

`{{ block_count }}` is a separate variable, not derived in the template — `_render`
(`prompt_loader.py:150`) is a plain substitution with no expressions, and after R1 it
raises `PromptRenderError` on anything else.

### Step 3 — `config/model-routing.toml`

Directly after the `evidence_extraction` row (line 42):

```toml
evidence_extraction_batch = "gemini_fast"
```

An unrouted stage falls back to `ResolvedModelRoute(provider="gemini", model=requested_model)`
(`model_routing.py:115`), so this is not strictly required — but without it
`THESISOUND_MODEL_ROUTE_OVERRIDES` cannot reach the batch path and the two shapes could
silently diverge onto different models mid-experiment.

### Step 4 — `src/thesisound/services/evidence_extractor.py`

**4a. Imports and constants.**

```python
from thesisound.source_analysis import (
    AnalysisProfile,
    BatchEvidenceExtractionDraft,          # new
    BlockEvidenceExtraction,
    EvidenceClaimDraft,
    EvidenceExtractionDraft,
    EvidenceExtractionPlan,
    SourceDocumentBlock,
)
```

Next to `_BREAKER_CONSECUTIVE_FAILURES`:

```python
# A batched call carries K blocks of source text plus K entries of output. The cap is
# set above the largest observed block (1,679 tokens) times the largest allowed
# batch_size, so it does not silently override the configured batch size for ordinary
# blocks -- it only splits a pathologically large block into its own call, where a
# truncated response cannot take K-1 healthy blocks down with it.
_MAX_BATCH_SOURCE_TOKENS = 12_000
```

**4b. Constructor.** Add a keyword-only `batch_size: int = 1`, validated beside
`max_workers`:

```python
    def __init__(
        self,
        model_runner: ModelRunner,
        *,
        max_workers: int = 1,
        batch_size: int = 1,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1.")
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1.")
        self.model_runner = model_runner
        self.max_workers = max_workers
        self.batch_size = batch_size
```

**4c. `extract_source`: batch the pending list, keep everything else.**

Replace the `if not pending: return [], []` block and everything down to the end of the
fan-out with the version below. The changes are mechanical: `pending` (blocks) becomes
`units` (lists of blocks), `work` returns a list of outcomes, and `hand_over` aggregates.

```python
        if not pending:
            return [], []

        units = _plan_units(pending, self.batch_size)
        results: dict[str, tuple[BlockEvidenceExtraction, ModelRunRecord | None]] = {}
        handover = Lock()
        consecutive_skipped = 0
        succeeded = 0

        def any_block_succeeded() -> bool:
            with handover:
                return succeeded > 0

        def work(
            unit: list[SourceDocumentBlock],
        ) -> list[tuple[str, tuple[BlockEvidenceExtraction, ModelRunRecord | None]]]:
            if len(unit) == 1:
                block = unit[0]
                with tracing.span(
                    "corpus.extract_evidence",
                    component="corpus",
                    subject_type="block",
                    subject_id=block.block_id,
                    detail="verbose",
                ):
                    outcome = self._extract_block(
                        project_id=project_id,
                        source_id=source_id,
                        block=block,
                        section=section_by_block.get(block.block_id),
                        blocks=blocks,
                        index_by_id=index_by_id,
                        document_map=document_map,
                        profile=profile,
                        model=model,
                        prompt_version=prompt_version,
                        max_attempts=max_attempts,
                    )
                return [(block.block_id, outcome)]
            with tracing.span(
                "corpus.extract_evidence_batch",
                component="corpus",
                subject_type="block_batch",
                subject_id=f"{unit[0].block_id}+{len(unit) - 1}",
                detail="verbose",
            ):
                return self._extract_batch(
                    project_id=project_id,
                    source_id=source_id,
                    unit=unit,
                    section_by_block=section_by_block,
                    blocks=blocks,
                    index_by_id=index_by_id,
                    document_map=document_map,
                    profile=profile,
                    model=model,
                    prompt_version=prompt_version,
                    max_attempts=max_attempts,
                    fallback_allowed=any_block_succeeded,
                )

        def hand_over(
            outcomes: list[tuple[str, tuple[BlockEvidenceExtraction, ModelRunRecord | None]]],
        ) -> str | None:
            nonlocal consecutive_skipped, succeeded
            with handover:
                for block_id, outcome in outcomes:
                    results[block_id] = outcome
                    if on_extraction is not None:
                        on_extraction(outcome[0])
                records = [outcome[0] for _, outcome in outcomes]
                # Per unit, not per record: one failed batch of four must not spend the
                # breaker's whole budget, or a single 503 aborts the source where three
                # separate block failures are required today.
                if records and all(record.status == "skipped" for record in records):
                    consecutive_skipped += 1
                else:
                    succeeded += 1
                    consecutive_skipped = 0
                if succeeded == 0 and consecutive_skipped >= _BREAKER_CONSECUTIVE_FAILURES:
                    return records[0].rejection_reason or "provider failure"
            return None
```

The fan-out loop below is unchanged except that `pending` becomes `units`,
`block.block_id` keys become the unit index, and `hand_over(block_id, outcome)` becomes
`hand_over(outcomes)`:

```python
        workers = min(self.max_workers, len(units))
        if workers == 1:
            for unit in units:
                breaker_reason = hand_over(work(unit))
                if breaker_reason is not None:
                    raise ModelProviderError(...)          # message unchanged
        else:
            bound_work = tracing.bind_context(work)
            next_index = 0
            futures = {}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                initial = (
                    len(units)
                    if len(units) <= workers
                    else min(len(units), _BREAKER_CONSECUTIVE_FAILURES)
                )
                ...                                        # body unchanged, `units` for `pending`
```

Do **not** change the breaker's exception message. `test_breaker_aborts_after_three_consecutive_provider_failures`
matches `"circuit breaker"`.

The trailing assembly (`for block in blocks: results.get(...)`) stays, with one addition
for D9:

```python
        records: list[BlockEvidenceExtraction] = []
        runs: list[ModelRunRecord] = []
        seen_runs: set[UUID] = set()
        for block in blocks:
            outcome = results.get(block.block_id)
            if outcome is None:
                continue
            records.append(outcome[0])
            run = outcome[1]
            # A batched call yields one record shared by K blocks; the manifest must not
            # list the same run id K times.
            if run is not None and run.run_id not in seen_runs:
                seen_runs.add(run.run_id)
                runs.append(run)
        return records, runs
```

**4d. `_plan_units`** — a module-level function, next to `_neighbor_context`:

```python
def _plan_units(
    pending: list[SourceDocumentBlock],
    batch_size: int,
) -> list[list[SourceDocumentBlock]]:
    """Consecutive slices of `pending`, capped by count and by source tokens.

    Consecutive rather than grouped by section: on the only real run all 40 selected
    blocks sat in 40 distinct sections, because the plan seeds one block per required
    section, so a section key produces batches of one and saves nothing.
    """

    if batch_size <= 1:
        return [[block] for block in pending]
    units: list[list[SourceDocumentBlock]] = []
    current: list[SourceDocumentBlock] = []
    current_tokens = 0
    for block in pending:
        if current and (
            len(current) >= batch_size
            or current_tokens + block.estimated_token_count > _MAX_BATCH_SOURCE_TOKENS
        ):
            units.append(current)
            current = []
            current_tokens = 0
        current.append(block)
        current_tokens += block.estimated_token_count
    if current:
        units.append(current)
    return units
```

The `if current` guard is what lets a single block above the cap form its own unit instead
of producing an empty one.

**4e. `_block_payload`** — the trimmed per-block payload, module-level:

```python
def _block_payload(
    index: int,
    block: SourceDocumentBlock,
    section: DocumentMapSection | None,
    neighbors: list[dict[str, object]],
) -> dict[str, object]:
    """What the model actually needs to read one block.

    Everything omitted here is either forbidden by the system prompt ("Do not generate
    IDs, source IDs, block IDs, page numbers, or locators") or unusable without the rest
    of the document (`source_block_keys`, `depends_on_section_ids`). Measured on the real
    run, the omitted fields were 951 chars per block payload plus 308 chars of section
    IDs -- 12.5% of every call, spent on data the model was told to ignore.
    """

    return {
        "index": index,
        "block_type": block.block_type,
        "heading_path": block.heading_path,
        "text": block.text,
        "section_context": None
        if section is None
        else {
            "title": section.title,
            "function": section.function,
            "key_concepts": section.key_concepts,
            "unresolved_context": section.unresolved_context,
        },
        "neighbor_context": neighbors,
    }
```

**4f. `_extract_batch`** — a method on the service, placed directly after `_extract_block`:

```python
    def _extract_batch(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        unit: list[SourceDocumentBlock],
        section_by_block: dict[str, DocumentMapSection],
        blocks: list[SourceDocumentBlock],
        index_by_id: dict[str, int],
        document_map: DocumentMap,
        profile: AnalysisProfile,
        model: str,
        prompt_version: str | None,
        max_attempts: int,
        fallback_allowed: Callable[[], bool],
    ) -> list[tuple[str, tuple[BlockEvidenceExtraction, ModelRunRecord | None]]]:
        """One call for `unit`; blocks it could not serve go to the single-block path."""

        unit_ids = {block.block_id for block in unit}
        variables = {
            "source_id": str(source_id),
            "working_thesis": document_map.working_thesis,
            "analysis_profile": profile.model_dump(mode="json"),
            "block_count": len(unit),
            "blocks": [
                _block_payload(
                    position,
                    block,
                    section_by_block.get(block.block_id),
                    [
                        neighbor
                        for neighbor in _neighbor_context(
                            block, blocks, index_by_id, profile.neighbor_context_blocks
                        )
                        # A sibling in this call is already a target block; sending it
                        # again as context duplicates its text and contradicts the rule
                        # that context may never supply an excerpt.
                        if neighbor["block_id"] not in unit_ids
                    ],
                )
                for position, block in enumerate(unit, start=1)
            ],
        }

        stats = {"dropped_claims": 0, "cross_block_excerpts": 0}

        def validator(draft: BatchEvidenceExtractionDraft) -> None:
            _validate_batch_structure(draft, unit)
            for entry in draft.entries:
                block = unit[entry.block_index - 1]
                _salvage_entry_inplace(entry.extraction, block, unit, profile, stats)

        fallback_ids: set[str] = set()
        outcomes: dict[str, tuple[BlockEvidenceExtraction, ModelRunRecord | None]] = {}
        try:
            execution = self.model_runner.run(
                project_id=project_id,
                stage="evidence_extraction_batch",
                prompt_name="evidence_extraction_batch",
                variables=variables,
                output_type=BatchEvidenceExtractionDraft,
                model=model,
                prompt_version=prompt_version,
                validator=validator,
            )
            for entry in execution.output.entries:
                block = unit[entry.block_index - 1]
                extraction = _materialize_extraction(entry.extraction, block)
                validate_evidence_extraction(extraction, block)
                if not extraction.claims and not _has_auxiliary_content(extraction):
                    fallback_ids.add(block.block_id)
                    continue
                outcomes[block.block_id] = (
                    BlockEvidenceExtraction(
                        source_id=source_id,
                        block_id=block.block_id,
                        extraction=extraction,
                        status="extracted",
                    ),
                    execution.record,
                )
        except (ModelProviderError, ModelSafetyError) as exc:
            if not fallback_allowed():
                # Nothing has succeeded yet: this looks like a dead provider, so do not
                # pay for K more calls before the breaker gets to decide. Emit the batch
                # event first -- an aborted run must still show how many blocks the batch
                # was carrying, or the fallback-rate denominator is wrong for E2.
                _emit_batch_event(
                    project_id, unit, fallback_block_count=0, stats=stats
                )
                return [
                    (
                        block.block_id,
                        (
                            BlockEvidenceExtraction(
                                source_id=source_id,
                                block_id=block.block_id,
                                extraction=EvidenceExtraction(segment_function="rejected"),
                                status="skipped",
                                rejection_reason=str(exc)[:1_000] or type(exc).__name__,
                                failure_kind="provider",
                            ),
                            None,
                        ),
                    )
                    for block in unit
                ]
            fallback_ids = set(unit_ids)
        except StructuredOutputError:
            # The provider answered; only the shape was unusable. The single-block path
            # has a narrower task and a repair-instruction retry, so give it the work.
            fallback_ids = set(unit_ids)

        _emit_batch_event(
            project_id, unit, fallback_block_count=len(fallback_ids), stats=stats
        )

        for block in unit:
            if block.block_id not in fallback_ids:
                continue
            outcomes[block.block_id] = self._extract_block(
                project_id=project_id,
                source_id=source_id,
                block=block,
                section=section_by_block.get(block.block_id),
                blocks=blocks,
                index_by_id=index_by_id,
                document_map=document_map,
                profile=profile,
                model=model,
                prompt_version=prompt_version,
                max_attempts=max_attempts,
            )
        return [(block.block_id, outcomes[block.block_id]) for block in unit]
```

Note what is *not* caught: `ModelConfigurationError` and anything else propagates, exactly
as in `_extract_block` (I8).

**4g. `_emit_batch_event`** — module-level, so both exit paths in `_extract_batch` report
the same shape and neither can drift:

```python
def _emit_batch_event(
    project_id: UUID,
    unit: list[SourceDocumentBlock],
    *,
    fallback_block_count: int,
    stats: dict[str, int],
) -> None:
    """The measurement E2 reads. One event per batched call, no exceptions.

    `fallback_block_count / block_count` summed over a run is the number that decides
    whether batching pays for itself (plan §1.2); `cross_block_excerpt_count` is the
    number that decides whether it is safe.
    """

    tracing.event(
        "corpus.evidence_batch",
        component="corpus",
        project_id=project_id,
        subject_type="block_batch",
        subject_id=f"{unit[0].block_id}+{len(unit) - 1}",
        block_count=len(unit),
        fallback_block_count=fallback_block_count,
        dropped_claim_count=stats["dropped_claims"],
        cross_block_excerpt_count=stats["cross_block_excerpts"],
    )
```

**4h. Validators** — module-level, next to `_validate_draft`:

```python
def _validate_batch_structure(
    draft: BatchEvidenceExtractionDraft,
    unit: list[SourceDocumentBlock],
) -> None:
    """Structural failures retry; per-entry failures never do (see plan D4)."""

    indices = [entry.block_index for entry in draft.entries]
    if sorted(indices) != list(range(1, len(unit) + 1)):
        raise DeterministicValidationError(
            f"Batched extraction must return exactly {len(unit)} entries with "
            f"block_index 1..{len(unit)}; got {sorted(indices)}."
        )


def _salvage_entry_inplace(
    draft: EvidenceExtractionDraft,
    block: SourceDocumentBlock,
    unit: list[SourceDocumentBlock],
    profile: AnalysisProfile,
    stats: dict[str, int],
) -> None:
    """Drop what this entry cannot support, and count why.

    Identical in effect to `_salvage_draft_inplace` on the final single-block attempt --
    a batched call must not retry K blocks because one of them produced one unlocatable
    excerpt (the measured 24% case, audit §5). `cross_block_excerpts` separates "the model
    quoted a sibling block in this call" from "the model invented text", which is the only
    direct read on whether batching hurts attribution.
    """
```

Write the body as a **copy** of `_salvage_draft_inplace` (`evidence_extractor.py:371`),
with two additions inside the `except DeterministicValidationError` arm before `continue`:

```python
            stats["dropped_claims"] += 1
            if any(
                sibling.block_id != block.block_id
                and locate_excerpt(claim.supporting_excerpt, sibling.text) is not None
                for sibling in unit
            ):
                stats["cross_block_excerpts"] += 1
            continue
```

Do not refactor `_salvage_draft_inplace` into a shared helper with a stats parameter. The
single-block path is the control arm of E2 and must stay byte-for-byte what was audited;
a shared helper is one careless edit away from changing both arms at once. Two similar
30-line functions is the right trade here — say so in a comment on each.

**4i. `_evidence_max_attempts`** takes the prompt name so the batch contract's
`max_attempts` is honoured:

```python
def _evidence_max_attempts(
    model_runner: ModelRunner,
    prompt_version: str | None,
    prompt_name: str = "evidence_extraction",
) -> int:
```

Call it once per prompt name in `extract_source` and thread the batch value into
`_extract_batch`. Both contracts ship `max_attempts: 3`, so this is future-proofing, not a
behaviour change — but do it, because a silent divergence between the contract file and
the salvage trigger is exactly the class of bug R1 was.

### Step 5 — `src/thesisound/config.py`

Directly **after** `document_map_workers` (line 79):

```python
    # Blocks per evidence_extraction call. 1 is the shipped default and the exact
    # behaviour audited on 2026-08-09: one block, one call, prompt evidence_extraction.
    # Above 1 the batch prompt is used and a block the batch could not serve falls back
    # to the single-block path, so a batch can only be cheaper, never worse. Measured
    # prompt-size reduction on the real run: 28% at 2, 38% at 4, 43% at 8 -- but the real
    # saving depends on the fallback rate, which needs a live run (audit E2). Do not
    # raise this without that evidence.
    evidence_extraction_batch_size: int = Field(default=1, ge=1, le=8)
```

`le=8` is E2's largest variant. Do not invent a wider range.

### Step 6 — Composition roots

`src/thesisound/web/corpus_runtime.py:55`:

```python
            evidence_extractor=EvidenceExtractorService(
                runner,
                max_workers=settings.evidence_extraction_workers,
                batch_size=settings.evidence_extraction_batch_size,
            ),
```

`src/thesisound/source_cli.py:200`: the same three lines.

These are the only two production constructions — confirm with:

```bash
grep -rn "EvidenceExtractorService(" src/
```

### Step 7 — `.env.example`

In the **"Provider execution and retry policy"** block, directly after
`THESISOUND_DOCUMENT_MAP_WORKERS=4`:

```
# Blocks per evidence-extraction call. 1 is one call per block, the audited behaviour.
# Raising it amortises the fixed prompt preamble over K blocks; a block the batch cannot
# serve is retried alone, so the result is never worse, only cheaper. Leave at 1 until
# experiment E2 has measured claim yield and excerpt-error rate against a live provider.
THESISOUND_EVIDENCE_EXTRACTION_BATCH_SIZE=1
```

Nothing else in `.env.example` changes.

---

## 6. Tests

**Put every new test in `tests/test_evidence_batching.py`**, except §6.5 which belongs in
`tests/test_source_analysis.py` because it needs the full `SourceAnalysisService`.

Do not edit `tests/test_evidence_fanout.py` or the existing evidence tests in
`tests/test_source_analysis.py`. If you need to, D1 is broken.

### 6.0 Preparation

`tests/` is not an importable package, so the new module needs its own doubles. Build them
on the shape of `SelectiveRunner` (`test_evidence_fanout.py:24`) — copy the `_fixture`
helper and adapt it; a 40-line duplicated helper is cheaper than making `tests/` importable.

```python
class BatchRunner:
    """Answers both call shapes. Thread-safe: units run concurrently."""

    def __init__(self, behavior: Callable[[str], str] | None = None) -> None:
        self.behavior = behavior or (lambda _: "success")
        self.calls: list[list[str]] = []      # block ids per call, in call order
        self.stages: list[str] = []
        self._lock = Lock()

    def run(self, *, project_id, stage, variables, output_type, model, validator=None, **_):
        ...
```

Requirements on `BatchRunner`:

- Assert `output_type is BatchEvidenceExtractionDraft` when `stage == "evidence_extraction_batch"`
  and `EvidenceExtractionDraft` when `stage == "evidence_extraction"`.
- On the batch shape, read `variables["blocks"]`, take each block's `text[:40]` as the
  excerpt, and return one entry per block with `block_index` set from `"index"`.
- Record `self.calls.append([...])` and `self.stages.append(stage)` under the lock.
- Run `validator(output)` when given, letting `DeterministicValidationError` escape (the
  service must see structural failures). Do **not** copy `FakeRunner`'s 5-attempt retry
  loop — it hides exactly the retry behaviour these tests are checking.

Because the batch runner has no block IDs to key off, tests that need per-block behaviour
address blocks by their **text**, which `_fixture` makes unique per block.

### 6.1 Batch assembly — `_plan_units`, no model involved

| # | Test | Assertion |
|---|---|---|
| A1 | `batch_size=1` | one unit per block, order preserved, `_plan_units(p, 1) == [[b] for b in p]` |
| A2 | `batch_size=4`, 10 blocks | unit sizes `[4, 4, 2]`, concatenation equals `pending` |
| A3 | one block above `_MAX_BATCH_SOURCE_TOKENS` | that block is alone in its unit, neighbours unaffected |
| A4 | tokens sum exactly to the cap | they stay in one unit; one more token splits |
| A5 | `batch_size=4`, 3 blocks | a single unit of 3 |
| A6 | `skip_block_ids` + a `front_matter` block | filtered before batching — assert `runner.calls` contains no skipped id and unit sizes are computed on the survivors |

### 6.2 Service behaviour

> Test ids in this section (A1, E2, F1 …) are local labels for this document only. They
> have nothing to do with the audit's experiment ids (E1–E5 in §12 there), which are
> referred to here only as "experiment E2".

**B — happy path**

- **B1 (the single most important test): equivalence.** Run `extract_source` twice over
  the same 12-block fixture with `batch_size=1` and `batch_size=4`, using `BatchRunner`
  configured to return the same excerpt for the same text in both shapes. Assert the two
  `list[BlockEvidenceExtraction]` are equal after `model_dump(mode="json")` — same order,
  same `block_id`s, same `evidence_id`s, same statuses. If this fails, nothing else matters.
- **B2** records come back in `blocks` order, not unit order (shuffle unit completion by
  making unit 2 return first via a `Barrier`, or simply assert order with `max_workers=4`
  over 10 repeated runs).
- **B3** `on_extraction` is called exactly once per pending block, and the set of
  `block_id`s passed to it equals the set of pending ids.
- **B4** `len(runs) == len(runner.calls)` at `batch_size=4` — one record per call, not per
  block (D9). Also assert `len({run.run_id for run in runs}) == len(runs)`.

**C — attribution integrity**

- **C1** runner returns K−1 entries. The double runs the validator once and lets the
  `DeterministicValidationError` escape `run()` — that is what "`ModelRunner` exhausted its
  attempts" looks like from the service's side, since the double *is* the runner and owns
  retrying. `_extract_batch` catches it as `StructuredOutputError` → whole unit falls back.
  Assert `runner.stages == ["evidence_extraction_batch"] + ["evidence_extraction"] * K` and
  every block ends `extracted`.
- **C2** duplicate `block_index` (e.g. `[1, 1, 3]` for K=3) → same outcome as C1.
- **C3** `block_index = K+1` → same outcome as C1. Separately, `block_index = 0` is rejected
  by `Field(ge=1)` at model construction, so assert `pydantic.ValidationError` on
  `BatchEvidenceEntryDraft(block_index=0, ...)` directly rather than through the service.
- **C4 (no positional zip)** runner returns entries in reversed index order with
  block-specific claims. Assert each claim landed on the block whose text it quotes —
  i.e. every record's excerpt is a substring of its own block's text.
- **C5 (cross-block bleed)** in a unit of 3, entry 2 quotes block 3's text. Assert: block 2's
  claim is dropped, block 2 falls back and blocks 1 and 3 do **not**, and the
  `corpus.evidence_batch` event carries `cross_block_excerpt_count == 1` and
  `fallback_block_count == 1`. Use the `recording_tracer` fixture.

**D — per-entry budget (D5)**

- **D1** `max_claims_per_block=2`, an entry returns 3 claims → salvaged to 2; sibling
  entries keep their claims; **no error escapes the validator** — assert
  `runner.stages == ["evidence_extraction_batch"]`, i.e. no fallback call at all. This is
  the test that proves D4: a per-entry budget breach must not cost a second call.
- **D2** `include_examples=False` → examples stripped per entry, objections untouched in a
  profile that allows them.
- **D3** one entry empty after salvage → only that block falls back; assert the sibling
  blocks are absent from the second call's block list.

**E — failure paths (D6)**

Use `max_workers=1` for E1/E2/E4 so unit order is deterministic; E3 is parametrised.

- **E1** provider error on unit 2, unit 1 already succeeded → all four of unit 2's blocks
  fall back and end `extracted`. Assert unit 2's block ids appear in exactly two calls
  each (the batch, then their own single-block call).
- **E2** provider error on the **first** unit, everything after it healthy → no fallback:
  those four blocks end `skipped` with `failure_kind="provider"` and appear in exactly
  **one** call. The later units still complete normally — the breaker counter is at 1, not
  3, so the run must not abort.
- **E3 (breaker counts units, D8)** dead provider, `batch_size=4`, **20 blocks (5 units)** →
  `pytest.raises(ModelProviderError, match="circuit breaker")` and `len(runner.calls) == 3`.
  Twenty, not twelve: with exactly three units every unit would be called anyway and the
  assertion would pass without the breaker doing anything. Parametrise over
  `max_workers=[1, 4]`.
- **E4** unit 1 succeeds; units 2 and 3 fail at the provider **and so do their fallback
  calls** → **no** breaker, the run completes, and those 8 blocks end `skipped`. Note the
  runner must fail both shapes here: with `succeeded > 0`, D6 sends a failed batch to the
  fallback, so failing only the batch shape would produce `extracted` records and prove
  nothing. Proves `succeeded > 0` disarms the breaker permanently.
- **E5** `StructuredOutputError` on a unit (provider alive) → every block falls back and
  ends `extracted`, not `rejected`.
- **E6** `ModelConfigurationError` on the batch call propagates out of `extract_source`.
- **E7** a block falls back and the fallback also fails → the block ends `rejected` (or
  `skipped`), and its block id appears in exactly **two** entries of `runner.calls`. No third.

**G — concurrency and tracing**

- **G1** units overlap. Model it on `_BarrierRunner` (`tests/test_source_analysis.py:1514`)
  — the structure, not the code: that one extends `FakeRunner` and reads
  `variables["block"]`, so it cannot serve the batch shape. `Barrier(3, timeout=5.0)` over
  3 units at `max_workers=4`; a serial implementation raises `BrokenBarrierError` in 5 s
  instead of hanging.
- **G2** with `recording_tracer` and a parent span: exactly one
  `corpus.extract_evidence_batch` span per unit, all with
  `parent_span_id == parent.context.span_id` (this is what `tracing.bind_context` buys —
  see `tests/test_tracing_propagation.py::test_threadpoolexecutor_orphans_children_without_bind_context`),
  and `corpus.extract_evidence` spans only for blocks that fell back.

**J — the measurement contract**

This is the output E2 consumes; if it is wrong the experiment is unreadable, and no other
test covers the shape.

- **J1** at `batch_size=4`, one `corpus.evidence_batch` event per unit, each carrying all
  of `block_count`, `fallback_block_count`, `dropped_claim_count`,
  `cross_block_excerpt_count`, and `sum(event.block_count) == len(pending)`.
- **J2** at `batch_size=1`, **zero** `corpus.evidence_batch` events — the default path must
  stay silent so the event's presence in a real run means "batching was on".
- **J3** the aborted path still reports: a first-unit provider failure (the **E2** setup
  above) emits the event with `block_count == 4` and `fallback_block_count == 0` before the
  records are returned. Without this the fallback-rate denominator silently loses a whole
  batch.

### 6.3 Prompt and contract

- **H1 (the R1 lesson).** Render `evidence_extraction_batch/1.0.0` through `PromptLoader`
  with a realistic variables dict and assert the result contains no `{{`. A prompt that no
  test ever renders is a prompt that can silently become a no-op — that is exactly how the
  `document_map_merge` bug survived.
- **H2** `PromptLoader().load_contract("evidence_extraction_batch")` has
  `output_model == "BatchEvidenceExtractionDraft"`, `model_tier == "fast"` and
  `max_attempts == 3`. Then, using the real-`ModelRunner` harness in
  `tests/test_model_runner.py`, assert that running this contract with
  `output_type=EvidenceExtractionDraft` raises `ValueError` — that mismatch guard
  (`model_runner.py:80`) is the only thing stopping the two call shapes from being confused.
- **H3 (the trim is asserted, not assumed).** Render a batch prompt for a block whose
  `block_id`, `source_id`, `source_block_keys` and section id are distinctive strings, and
  assert **none of them appear** in `bundle.user_prompt`. Assert `heading_path`, the
  section `title` and the block `text` **do** appear.
- **H4** `evidence_extraction/1.3.0` still renders unchanged: assert its rendered length
  for a fixed variables dict equals a locked constant. This is the guard against someone
  "tidying" the old prompt while in the area.

### 6.4 Prompt-size regression (the offline half of E2)

Reuse the committed fixture `tests/fixtures/analysis_profile/real_run_selection.json` —
it already carries all 198 real blocks with real `estimated_token_count`s and all 47 real
sections, and it contains no book text, so nothing copyrighted enters the repo. Build the
blocks exactly as `tests/test_analysis_budget.py::_real_run_inputs` does, but give each
non-note block filler text of length `estimated_token_count * 3.5` (the `estimate_tokens`
heuristic is `ceil(len(normalized) / 3.5)`), then run `plan_evidence_extraction` to get the
real 13-block plan.

```python
@pytest.mark.parametrize(
    ("batch_size", "expected_calls", "max_chars"),
    [(1, 13, 118_000), (2, 7, 94_000), (4, 4, 83_000), (8, 2, 76_000)],
)
def test_batching_shrinks_the_rendered_prompt_on_the_real_plan(...):
```

Assert the number of calls and that the summed rendered `system_prompt + user_prompt`
length is **at or below** `max_chars`, with the K=1 figure as the baseline. Measured
values on this fixture: 117,945 / 93,640 / 82,903 / 75,745 chars → reductions of
0% / 20.6% / 29.7% / 35.8%.

**State in a comment why these are lower than §1.1's 28.2% / 37.8% / 42.7%:** the fixture
gives every block a single `source_block_key`, while the real blocks average eight
(538 chars/call), so the fixture understates what there is to trim. The fixture numbers are
the regression guard; the real-artifact numbers are the headline, and you will reproduce
those separately in §7.

Use `<=` assertions, not `==`. This test must fail when a change makes prompts bigger and
must not fail when someone shortens `system.md` by a word.

### 6.5 Retention-gate interaction — `tests/test_source_analysis.py`

Two tests, added at the end of the file under a section comment. They exist because the
gate is the thing batching could plausibly break (D6).

Build the source so **all 13 selected blocks carry the same `estimated_token_count`**, and
run with `max_workers=1`. The gate is arithmetic on token mass, so an uneven fixture makes
the result depend on which blocks happened to land in the failing unit — the test would
pass or fail for reasons unrelated to the code.

- **F1** `batch_size=4`, provider error on the second unit after the first succeeded →
  fallback recovers all four blocks, `extract_evidence` returns normally, and
  `manifest.skipped_block_count == 0`.
- **F2** the same setup but the failure is on the **first** unit (nothing has succeeded, so
  D6 forbids the fallback) → 4 of 13 equal blocks lost, retention 69% — below the 75% floor
  even after the largest single loss is forgiven — so `extract_evidence` raises
  `ValueError` matching `"lost"`, and `manifest.skipped_block_count == 4`. This test
  documents the worst case deliberately: the warning it produces is the operator's only
  signal that a whole batch was lost.

### 6.6 Config and wiring

Copy the shape of R7's §6.3 tests.

```python
def test_evidence_extraction_batch_size_defaults_to_one_and_is_bounded() -> None:
    assert Settings(environment="test").evidence_extraction_batch_size == 1
    with pytest.raises(ValidationError):
        Settings(environment="test", evidence_extraction_batch_size=0)
    with pytest.raises(ValidationError):
        Settings(environment="test", evidence_extraction_batch_size=9)


def test_evidence_extractor_rejects_a_batch_size_below_one() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        EvidenceExtractorService(BatchRunner(), batch_size=0)
```

Plus the "implemented but never wired" guard at both roots — monkeypatch
`corpus_runtime.GeminiStructuredModel` / `source_cli.GeminiStructuredModel`, build the
service with `evidence_extraction_batch_size=3`, and assert
`service.evidence_extractor.batch_size == 3`. Copy the `Settings(...)` shape from
`tests/test_runtime_reconciliation.py::_settings` rather than inventing one.

### 6.7 Test hygiene

- No `sleep()`. G1 uses a `Barrier` with a timeout so a serial implementation fails in 5 s.
- No wall-clock assertions. Overlap is proven by the barrier.
- Two deliberate conventions, do not mix them up: tests whose *result* must hold on both
  schedules (A6, B1, B4, C-group, E3) are parametrised over `max_workers=[1, 4]`; tests
  whose *setup* depends on which unit runs first (E1, E2, E4, F1, F2) pin `max_workers=1`
  and say so in a comment. A failure-ordering test left on 4 workers is a flake waiting to
  happen.
- Re-run the new module 10 times before opening the PR (§7). A fan-out test that passes
  once proves nothing.
- Do not assert on exact token counts anywhere. `estimate_tokens` is a heuristic and the
  provider's count is the source of truth; assert on characters and on `<=`.

---

## 7. Verification

Run in order. All green before the PR.

```bash
uv run ruff check .
```

```bash
uv run pytest tests/test_evidence_batching.py tests/test_evidence_fanout.py tests/test_source_analysis.py tests/test_prompt_rendering.py tests/test_analysis_budget.py tests/test_model_runner.py tests/test_tracing_propagation.py -v
```

```bash
uv run pytest
```

```bash
for i in 1 2 3 4 5 6 7 8 9 10; do uv run pytest tests/test_evidence_batching.py -q || break; done
```

Then reproduce the headline numbers against the real artifacts and paste the output into
the PR. Write a throwaway script (do **not** commit it) that loads
`workspaces/f781a5c7-9b58-4acb-99af-90b2b265e4f6/sources/98863830-8395-447c-a1ac-a3b85560cd98/`
— `evidence-extraction-plan.json`, `document-map.json`, `document-blocks.jsonl` — renders
`evidence_extraction/1.3.0` per selected block and `evidence_extraction_batch/1.0.0` per
unit, and prints total characters for K ∈ {1,2,3,4,6,8}. Expected, within ~1%:

| K | reduction |
|---:|---:|
| 2 | 28% |
| 3 | 34% |
| 4 | 38% |
| 8 | 43% |

If your numbers are materially lower, the trim in `_block_payload` is incomplete.

Then walk this checklist by hand:

- [ ] `grep -rn "EvidenceExtractorService(" src/` — both production sites pass `batch_size`.
- [ ] `git diff --stat prompts/` shows **only** additions under `prompts/evidence_extraction_batch/1.0.0/`.
- [ ] `git diff tests/test_evidence_fanout.py` is empty.
- [ ] `grep -rn "block_id" prompts/evidence_extraction_batch/` — no hits in `user.md`.
- [ ] `_salvage_draft_inplace` is unchanged and still used by the single-block path.
- [ ] `_extract_block` is unchanged apart from being called from two places.
- [ ] The breaker's exception message is byte-identical.
- [ ] `Settings().evidence_extraction_batch_size == 1` and `.env.example` says `1`.
- [ ] `extract_source`'s signature and return type are unchanged.
- [ ] `runs` is deduplicated by `run_id`.
- [ ] No change to `analysis_profile.py`, `evidence_validator.py`, `excerpt_matching.py`,
      `model_runner.py`, `audio_qa.py`, `document_mapper.py`, or any existing prompt file.

**No live provider run in this PR.** The audit was produced without provider spend and this
task does not authorise any. Running E2 is §8.3 and needs explicit approval first.

---

## 8. Rollout, rollback, and what comes next

### 8.1 Kill switch

`THESISOUND_EVIDENCE_EXTRACTION_BATCH_SIZE=1` is the shipped default and restores the exact
audited behaviour with no code change. Say so in the PR description.

### 8.2 What to check on the first real run with K > 1

In `workspaces/<project>/model-runs/` and the trace events:

1. `stage="evidence_extraction_batch"` record count equals `ceil(pending / K)` — more means
   units are being retried structurally, which is a prompt problem, not a code problem.
2. `corpus.evidence_batch` events: `sum(fallback_block_count) / sum(block_count)` is **the**
   number. Above ~24% and R8 is not paying for itself (§1.2).
3. `cross_block_excerpt_count > 0` on any batch is the direct evidence that batching hurts
   attribution. If it is non-trivial, lower K before touching anything else.
4. `stage="evidence_extraction"` records should equal the fallback count exactly. A mismatch
   means a block was called twice without being counted, i.e. D6's "never a third call" is
   broken.
5. `manifest.skipped_block_count` and the retention warning in the returned `warnings` list.

### 8.3 E2 — the experiment this PR enables (needs cost approval)

Do not run this without asking.

```
Hypothesis  batching K blocks cuts input tokens >=35% with no material loss of claim yield
Dataset     project f781a5c7's 13-block R5 plan (re-extract with skip_block_ids cleared)
Variants    K=1 (baseline, prompt 1.3.0) | K=2 | K=4 | K=8
Metrics     input tokens (provider-reported, not estimated); claims per kept block;
            fallback rate; cross_block_excerpt_count; rejected+skipped counts; wall clock
Threshold   >=35% input-token reduction; claim yield within 5% of K=1; no rise in the
            rejected-block count
Decision    the largest K meeting all three; if none does, ship the trim alone (8.4)
Cost        ~34k input tokens per variant on the post-R5 plan, ~136k total -- far below
            the audit's ~500k estimate, which predates R5 shrinking the plan from 40 to
            13 blocks
Caveat      n=1 corpus, one language, one duration. A single passing run is evidence that
            it did not break, not that it generalises.
```

`claims_per_kept_block` is already emitted by `corpus.evidence_yield`
(`source_analysis_service.py:315`) — use it rather than recomputing from artifacts.

### 8.4 The named follow-ups — separate PRs, not this one

1. **`evidence_extraction/1.4.0`, the trimmed single-block prompt.** Worth 8.8% on its own
   with no batching risk at all, and it is the fallback if E2 rejects batching. It is a
   separate PR because adding the version directory silently repoints production
   (`PromptLoader._resolve_version_dir` takes the highest version, production passes
   `None`), so it needs its own A/B and its own decision. Write `_block_payload` so that
   PR is a one-line change.
2. **Raising the default `batch_size`.** Only after E2.
3. **Explicit context caching.** Blocked on the pricing table (audit §13 item 4) and on
   `cached_tokens` actually being populated.

---

## 9. Definition of done

1. Steps 1–7 implemented exactly as specified.
2. §6.1–6.6 written and passing; ten consecutive clean runs of `tests/test_evidence_batching.py`.
3. Full `uv run pytest` and `uv run ruff check .` green.
4. §7 checklist walked, and the real-artifact measurement pasted into the PR.
5. PR description states: the kill switch; the three accepted behaviour changes from §4;
   that the default is unchanged and E2 has **not** been run; the corrected overhead figure
   (35.5% amortisable, not 55.3%) and that ≥35% needs K ≥ 4 *with* the trim; and the
   worst-case gate interaction from D6.

**Do not** bundle R1, R2, R4 or R9 into this PR, do not turn batching on, and do not
"improve" the merge, the audio QA or the analysis profile while you are in the tree.
One recommendation, one PR.
