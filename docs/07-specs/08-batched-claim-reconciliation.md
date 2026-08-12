# 08 — Batched Claim Reconciliation

Date: 2026-08-12 · Status: proposed · Effort: M · Source: user-reported timeout on `claim_reconciliation` during a multi-source run, 2026-08-12 — a follow-up gap in the MVP readiness audit's Action 4, which is already shipped ([`source_analysis_service.py:547`](../../src/thesisound/services/source_analysis_service.py:547): skip the model call when `len(project.sources) == 1`)

Bound `claim_reconciliation`'s per-call prompt size by partitioning one source's evidence into batches and adding a small claim-level merge pass, mirroring the partition/merge shape `DocumentMapperService` already uses for the identical class of problem.

## 1. Position

**Adopt.** The audit's Action 4 ("skip reconciliation when `len(sources) == 1`") is already implemented and handles the cheap case for free. It does nothing for the case that is actually timing out: a project with two or more sources, where reconciliation still runs per source and one of those sources — commonly the one that is a full book rather than an article — has enough extracted evidence to blow the per-call prompt budget on its own. Source count was never the right proxy for prompt size; it just happened to be the only lever the audit had data for.

This is a new gap, not a re-litigation of anything already decided. It does not touch `script_verifier` — the audit's own "conditional verifier" recommendation was separately retracted in the audit document; that stage stays unconditional and out of scope here.

## 2. What is actually growing

`ClaimReconcilerService.reconcile` is called **once per source**, not once per project. The caller, [`source_analysis_service.py:515`](../../src/thesisound/services/source_analysis_service.py:515) `build_claims(project_id, source_id, ...)`, loads only that source's extractions ([`:535-540`](../../src/thesisound/services/source_analysis_service.py:535)) and passes them to [`:541-548`](../../src/thesisound/services/source_analysis_service.py:541):

```python
ledger, run = self.claim_reconciler.reconcile(
    project_id=project_id,
    source_id=source_id,
    extractions=extractions,
    model=model,
    prompt_version=prompt_version,
    skip_model=len(project.sources) == 1,
)
```

`skip_model` is keyed on the **project's** source count, not this source's evidence volume. So the moment a project has a second source — even a two-page abstract alongside a full book — every source in that project, including the book, loses the free pass and pays full, uncapped cost for whatever evidence it has.

Inside [`claim_reconciler.py:106`](../../src/thesisound/services/claim_reconciler.py:106), the whole evidence list for that one source goes into a single call with no batching:

```python
variables = {
    "source_id": str(source_id),
    "evidence_items": [item.model_dump(mode="json") for item in evidence],
}
```

`EvidenceItem` ([`domain.py:286`](../../src/thesisound/domain.py:286)) carries `claim`, `supporting_excerpt`, and a `locator` per item — the prompt in [`prompts/claim_reconciliation/1.0.0/user.md`](../../prompts/claim_reconciliation/1.0.0/user.md) is essentially this JSON array plus four lines of instruction. There is no `evidence_extraction_batch_size`-style cap the way there is for evidence extraction ([`config.py:106`](../../src/thesisound/config.py:106)); the array grows one-to-one with the source's claim-bearing evidence, unbounded.

**The only real measurement we have** is the single historical run the audit captured, from before `skip_model` existed: one source, 23,140 input tokens, 5,303 output tokens, 115s ([audit §6](../thesisound-mvp-readiness-audit-fa.html)). That run *succeeded*, comfortably under the 180s default ([`config.py:76`](../../src/thesisound/config.py:76) `model_timeout_seconds`). No multi-source run is captured anywhere in `workspaces/` — the audit says so explicitly, and a search for one while writing this spec found nothing either. So the reported timeout has no logged reference point; §3.5 below is sized by reasoning from the one number we do have, not by calibration, and should be checked against a real large-source fixture once one exists.

One more thing this reading settles: because `reconcile` runs per source, it only dedupes claims *within* one source's evidence. `agreeing_source_ids` on a `ClaimRecord` is derived from `EvidenceItem.source_id` ([`claim_reconciler.py:193-196`](../../src/thesisound/services/claim_reconciler.py:193)), but every item passed into one call already shares the same `source_id` — cross-source agreement/disagreement is evidently built elsewhere (`DisagreementGraphBuilder`), not by this service. This spec does not touch that; see §4.

## 3. Design

Mirror [`DocumentMapperService`](../../src/thesisound/services/document_mapper.py) ([`:37-71`](../../src/thesisound/services/document_mapper.py:37)), which already solves this exact shape of problem: partition on a character budget, map each partition independently, reduce with a separate, much smaller merge call, and skip the merge entirely when there was only ever one partition.

### 3.1 Partition evidence, not just count it

```python
def _partition_evidence(
    evidence: list[EvidenceItem],
    maximum_characters: int,
) -> list[list[EvidenceItem]]
```

Same shape as [`_partition_blocks`](../../src/thesisound/services/document_mapper.py:360): sum each item's serialized size (`len(item.model_dump_json())`, matching what actually goes in the prompt), greedily pack items in their existing order into batches under the budget, and return `[evidence]` unchanged — one batch — when the total already fits. Evidence order is whatever `extractions` already provides (block order within the source); there is no heading structure to preserve the way there is for document blocks, so no smarter grouping is proposed.

Immediately after partitioning, assert `{item.evidence_id for batch in batches for item in batch} == {item.evidence_id for item in evidence}` — the same deterministic flattened-ID check `_partition_blocks` already does — so a partitioning bug fails loudly before any model call, not as a mysterious missing claim later.

### 3.2 Batches reuse the existing call, unchanged

Each batch runs through the *existing* `claim_reconciliation` prompt and the *existing* `_validate_draft` ([`claim_reconciler.py:138`](../../src/thesisound/services/claim_reconciler.py:138)) — only the evidence-ID universe passed to the validator narrows to the batch. No new prompt, no new schema, no behavior change for this half. When `_partition_evidence` returns exactly one batch — the common case today — reconciliation runs exactly as it does now: one call, one validated draft, one materialized ledger, no merge step. This is what makes §5.1 a real non-regression guarantee rather than an aspiration.

### 3.3 A narrow merge pass, only when there is more than one batch

When there are ≥ 2 batches, materialize each one into `ClaimRecord`s first (reusing `_materialize_ledger` per batch, unchanged), *then* merge at the claim level — not the evidence level. The merge model never sees excerpts; it sees already-reconciled claims, which is why this payload stays small the same way `document_map_merge`'s section-metadata payload does ([`document_mapper.py:61-65`](../../src/thesisound/services/document_mapper.py:61), the "two separate budgets on purpose" comment — merge payload size tracks batch *count*, not evidence *volume*).

New prompt contract `claim_reconciliation_merge`, new output schema:

```python
class ClaimMergeGroup(BaseModel):
    claim_ids: list[str] = Field(min_length=2)

class ClaimMergeDraft(BaseModel):
    merge_groups: list[ClaimMergeGroup] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

The model's only job is to name groups of claim IDs (from different batches) that are the same proposition. A claim ID absent from every group is left standing on its own — the model restates nothing.

Deterministic materialization of the merge (no model involvement):

- every `claim_id` in every group must exist among the batches' materialized claims — unknown ID raises `DeterministicValidationError`, same pattern as `_validate_draft`'s unknown-evidence-ID check;
- a `claim_id` may appear in at most one group;
- for each group, union `evidence_ids` and `agreeing_source_ids` (dedup, sort), and take `claim` text, `claim_type`, and `support_status` from whichever member appears first in batch order — first-seen-wins, the same tie-break rule this file already uses for `_dedupe_definitions`, `_dedupe_distinctions`, and `_dedupe_points`;
- recompute the merged claim's `claim_id` via the existing `_claim_id()` ([`claim_reconciler.py:270`](../../src/thesisound/services/claim_reconciler.py:270)) over the unioned evidence IDs — no signature change needed, since every item in one `reconcile()` call already shares one `source_id`;
- every batch's `unresolved_evidence_ids` and `warnings` concatenate into the final ledger unchanged.

### 3.4 Concurrency

Run batch calls for one source concurrently, mirroring `_fan_out_partitions` ([`document_mapper.py:256`](../../src/thesisound/services/document_mapper.py:256)). New setting `claim_reconciliation_workers: int = Field(default=4, ge=1, le=16)`, following the exact precedent of `document_map_workers` ([`config.py:103`](../../src/thesisound/config.py:103)) and `evidence_extraction_workers`. This does not shrink any individual call — it shrinks wall-clock for a source that needs several batches, which is the same reason those two settings exist.

### 3.5 Batch size default

Constructor parameter on `ClaimReconcilerService`, e.g. `maximum_batch_characters: int = 60_000`, in the same spirit as `DocumentMapperService.maximum_input_characters` (a constructor default, not an env setting — §2's document_map precedent doesn't expose its budget as a `Settings` field either). 60,000 characters is roughly a quarter of the single known-good 23,140-token run, chosen to leave real headroom under the 180s timeout on the `strong` tier even accounting for JSON structural overhead — a reasoned starting point, explicitly not a calibrated one (see §2's last paragraph and §4).

### 3.6 Routing

Add `claim_reconciliation_merge` to `config/model-routing.toml`, defaulting to the same profile as `claim_reconciliation` (`okian_deepseek_pro`). No independence requirement applies — this is not a reviewer pair — but nothing stops a later change to a cheaper profile once the merge payload's real size is observed.

## 4. Non-goals

- Changing `skip_model`'s single-source condition, or its trigger (project source count). That is Action 4 and is already shipped.
- Cross-source claim merging. `agreeing_source_ids`/`disagreeing_source_ids` spanning multiple real sources is apparently `DisagreementGraphBuilder`'s job, not `ClaimReconcilerService`'s — this spec found that boundary but does not move it.
- Raising `model_timeout_seconds` or `provider_max_attempts` as the fix. Either masks the symptom on today's run and fails again on the next larger source; bounding the prompt is the only fix that doesn't re-grow with corpus size.
- A dynamic or model-chosen batch size. Ship the fixed default in §3.5 first.
- Calibrating §3.5's number against real data. No multi-source fixture with a large source exists yet to calibrate against; validate with `thesisound eval` (per [`06-conditional-document-map.md`](06-conditional-document-map.md) §4.4's approach) once one does, and adjust then.
- Touching `evidence_extraction`'s own batching (`evidence_extraction_batch_size`) — unrelated stage, already has a cap.

## 5. Acceptance criteria

1. A source whose evidence fits under `maximum_batch_characters` in one batch produces the same call count, the same validated draft, and the same materialized `ClaimRecord`s as today — byte-identical behavior change of zero for the common case.
2. A source whose evidence exceeds the budget produces N batch calls plus exactly one merge call, and never a single call carrying the source's full evidence set.
3. The deterministic partition check (§3.1) fails before any model call if batching ever drops, duplicates, or double-counts an evidence ID.
4. A claim whose evidence was split across two batches, and which both batches' models reconciled as the same proposition, appears exactly once in the final ledger with the union of its evidence IDs and agreeing source IDs.
5. A merge group naming an unknown or already-used `claim_id` raises `DeterministicValidationError` before the ledger is materialized or saved.
6. Batch calls for one source run concurrently, bounded by `claim_reconciliation_workers`.
7. `skip_model=len(project.sources) == 1` behavior is untouched — this spec changes what happens when the model call runs, not when it is skipped.

## 6. Test plan

| Test | Asserts |
|---|---|
| `test_partition_evidence_single_batch_when_under_budget` | §3.1 shortcut |
| `test_partition_evidence_splits_on_character_budget` | §3.1 packing |
| `test_partition_evidence_covers_every_id_exactly_once` | §5.3 |
| `test_reconcile_single_batch_matches_current_output` | §5.1 — the non-regression guarantee |
| `test_reconcile_multi_batch_issues_one_merge_call` | §5.2 |
| `test_merge_group_unifies_evidence_and_source_ids` | §5.4 |
| `test_merge_group_ties_break_first_seen` | §3.3 tie-break rule |
| `test_merge_rejects_unknown_claim_id` | §5.5 |
| `test_merge_rejects_claim_id_in_two_groups` | §5.5 |
| `test_batches_run_concurrently_up_to_worker_limit` | §5.6 |
| `test_skip_model_condition_unchanged` | §5.7 |

## 7. Related

- [`06-conditional-document-map.md`](06-conditional-document-map.md) — the partition/merge pattern this spec reuses, including the "measure before shipping a threshold" discipline §3.5 explicitly falls short of and flags for follow-up.
- [`07-conditional-glossary-and-verification.md`](07-conditional-glossary-and-verification.md) — the sibling "simplify before MVP" item; also turns an unconditional model call into a bounded one without silently degrading a downstream consumer.
- [`04-integrations/02-source-discovery-large-docs-and-revision.md`](../04-integrations/02-source-discovery-large-docs-and-revision.md) §2 — the prose description of the large-document partitioning behavior this spec mirrors.
- [MVP readiness audit](../thesisound-mvp-readiness-audit-fa.html) — Action 4 (shipped) and the backend-efficiency numbers cited in §2.
