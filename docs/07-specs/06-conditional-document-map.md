# 06 — Conditional Document Map

Date: 2026-08-12 · Status: **implemented** (2026-08-12, same day as this revision) · Effort: S–M · Source: [MVP readiness audit](../thesisound-mvp-readiness-audit-fa.html), "Simplify / Change before MVP" — *document map only for long documents*

Skip the document-map model call when the map provably cannot change the extraction plan, and fall back to a deterministic single-section map so every downstream consumer keeps its contract.

## 1. Position

**Adopt, with the threshold derived rather than guessed.** The audit is right that mapping a three-block PDF is waste. But "long document" is not a property the code can act on; the actionable question is narrower and answerable: *does the map change the selection?*

## 2. What the map is actually for

`DocumentMap` has exactly one consumer: [`episode_preparation_service.py:535`](../../src/thesisound/services/episode_preparation_service.py:535) passes it to `plan_evidence_extraction`. Inside [`analysis_profile.py:150`](../../src/thesisound/services/analysis_profile.py:150) it does two things and nothing else:

1. **Ranking** — `section_by_block` feeds `_block_score`, which orders blocks for selection.
2. **Seeding** — sections with `required_for_global_understanding` become guaranteed seeds under a 60% sub-budget (`_REQUIRED_SEED_BUDGET_SHARE`).

Both matter only when the plan has to *choose*. When every eligible block is selected anyway, ranking is a no-op and seeding is a no-op.

## 3. Measured corpus

Every source currently in `workspaces/`:

| Source | Blocks | Tokens | Map sections | Selected | Coverage |
|---|---|---|---|---|---|
| `5136911e/dd3a2676` | 3 | 3,318 | 3 | 3,318 | **1.00** |
| `5136911e/f6f4d511` | 3 | 3,068 | 3 | 1,206 | 0.39 |
| `1296f949/4c598a0d` | 198 | 258,737 | 68 | 70,576 | 0.27 |
| `f781a5c7/98863830` | 198 | 258,194 | 47 | 55,913 | 0.22 |

All four ran at `depth=brief`, 10 minutes, `evidence_input_token_budget=18000`.

Two things this table settles:

- `dd3a2676` selected **everything**. Its 3-section map cost a model call and changed nothing.
- `f6f4d511` is equally tiny and still selected only 1 of 3 blocks. **Size alone does not predict whether selection happens.** A block-count threshold would have skipped the map on a source where the map still had a job.

That is why the rule below is expressed in tokens against the profile, not in blocks.

## 4. Design

### 4.1 The skip condition

`plan_evidence_extraction` computes:

```python
coverage_tokens = ceil(total_tokens * profile.block_coverage_target * (1 + _SELECTION_HEADROOM))
target_tokens   = min(total_tokens, coverage_tokens, profile.evidence_input_token_budget)
```

**Skip the map when `target_tokens >= total_tokens`** — the plan will take every eligible block, so no ranking and no seeding can alter the outcome. With `_SELECTION_HEADROOM = 0.10` this requires both `block_coverage_target >= 1/1.1` and `total_tokens <= evidence_input_token_budget`.

This condition is duration-aware for free: a 3,000-token source that is partially sampled for a 10-minute episode is read whole for a 30-minute one, and the map is skipped only in the second case. That is the correct behaviour, and a block-count threshold cannot express it.

Extract the arithmetic into a shared predicate so the skip decision and the plan cannot drift apart:

```python
def selection_is_exhaustive(profile: AnalysisProfile, blocks: list[SourceDocumentBlock]) -> bool
```

Call it from `source_analysis_service.map_document` before the model call, and from `plan_evidence_extraction` to compute `target_tokens`. One function, two callers, no duplicated formula.

### 4.2 Deterministic fallback map

When skipped, write a real `DocumentMap` artifact — do not leave a hole. Every consumer, the readiness gates, and the archive keep a well-formed artifact.

- One `DocumentMapSection` covering all eligible block IDs in document order.
- `title` from the source's own title metadata; `function = "other"`.
- `required_for_global_understanding = true` — with exhaustive selection this is trivially satisfied and keeps the seeding path well-defined.
- `working_thesis = None`, empty `cross_section_threads`.
- `warnings` carries one entry naming the skip so the artifact is self-explaining: `"Document map skipped: selection is exhaustive (N blocks, T tokens ≤ target)."`

Mark the artifact's provenance as deterministic rather than model-generated, so a later reader is never misled into treating a synthetic map as a model judgement. `DocumentMapCache` must not store or serve a synthetic map — [`document_map_cache.py`](../../src/thesisound/services/document_map_cache.py) `is_shareable_document_map` is the right place to exclude it, since sharing a synthetic map into a project whose budget *does* force selection would silently degrade that project's ranking.

### 4.3 Observability

The stage already emits cache lookups with `avoided_calls` ([`source_analysis_service.py:154`](../../src/thesisound/services/source_analysis_service.py:154)). Emit the skip on the same channel with a distinct reason so saved calls from *skipping* are not confused with saved calls from *cache hits*. Without this the cost story becomes unreadable, which is the failure the audit already names about the current ledger.

### 4.4 The tunable is deliberately not shipped

A second, softer rule — "skip for sources under N blocks" — would fire more often but has real quality cost, and `f6f4d511` is a live counterexample. Four sources, two of them the same EPUB, is not a calibration set.

If a broader skip is wanted later, validate it with the existing harness (`thesisound eval` over `benchmarks/eval/v1`) by measuring claim overlap between mapped and unmapped runs on the same source. Ship §4.1 now: it is provably lossless and needs no calibration.

## 5. Non-goals

- Skipping the map for large documents under any condition.
- Changing `block_coverage_target`, the token budget, or the depth profiles.
- Partitioned mapping and merge for very large sources — see [`04-integrations/02-source-discovery-large-docs-and-revision.md`](../04-integrations/02-source-discovery-large-docs-and-revision.md).
- Removing the `DocumentMap` model or making it optional on `plan_evidence_extraction`.

## 6. Acceptance criteria

1. `dd3a2676` (3,318 tokens, exhaustive) produces a synthetic map with zero model calls.
2. `f6f4d511` (coverage 0.39) still produces a model-generated map.
3. Both 198-block sources still produce model-generated maps.
4. An extraction plan built on a synthetic map selects exactly the same block set as one built on the real map, for any source meeting §4.1.
5. A synthetic map validates as a `DocumentMap` and is never written to `DocumentMapCache`.
6. Readiness gates for a project whose source used a synthetic map are unchanged.
7. The skip is visible in observability as a distinct reason, not as a cache hit.

## 7. Test plan

| Test | Asserts |
|---|---|
| `test_selection_is_exhaustive_true_for_small_source` | predicate, §4.1 |
| `test_selection_is_exhaustive_false_when_coverage_binds` | `f6f4d511` case |
| `test_selection_is_exhaustive_scales_with_duration` | same source, 10 vs 30 minutes |
| `test_synthetic_map_skips_model_call` | §6.1 |
| `test_synthetic_map_yields_identical_plan` | §6.4 — the correctness claim |
| `test_synthetic_map_not_cached` | §6.5 |
| `test_synthetic_map_carries_skip_warning` | artifact is self-explaining |

§6.4 is the load-bearing test. It is what makes this a cost change rather than a quality change, and it should run over both small fixtures.

## 8. Related

- [`03-inline-research-brief.md`](03-inline-research-brief.md) and [`07-conditional-glossary-and-verification.md`](07-conditional-glossary-and-verification.md) — the other two "simplify before MVP" items.
- [`02-pipeline/04-output-aware-analysis-budget.md`](../02-pipeline/04-output-aware-analysis-budget.md) — the budget model this skip condition reads from.
- [`02-pipeline/03-one-source-evidence-pipeline.md`](../02-pipeline/03-one-source-evidence-pipeline.md) — the stage sequence.
