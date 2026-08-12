# 01 — Evidence Artifact Schema Upgrade

Date: 2026-08-12 · Status: implemented · Effort: M · Source: [MVP readiness audit](../thesisound-mvp-readiness-audit-fa.html), finding "readiness does not read evidence artifacts because of schema drift"

Every stored `BlockEvidenceExtraction` written before the provenance change fails validation against the current model. Two readiness gates report `unknown` on all four real projects as a result. This spec makes those artifacts readable again without inventing data, and makes the reader degrade one artifact at a time instead of one source at a time.

## 1. Measured problem

Run against the four projects in `workspaces/`:

| Artifact | Reader | Valid | Invalid |
|---|---|---|---|
| `evidence/extractions/*.json` | `load_block_extractions` | 7 | **40** |
| `evidence-extractions.jsonl` | `load_extractions` | 7 | **37** |
| `evidence-items.jsonl` | `load_evidence_items` | 78 | 0 |
| `claim-ledger.json` | `load_claim_ledger` | 3 | 0 |

The blast radius is exactly `BlockEvidenceExtraction` deserialization, reached through two methods in [`source_artifact_store.py`](../../src/thesisound/services/source_artifact_store.py). `EvidenceItem` and `ClaimLedger` are clean — claims were persisted in their final shape from the start.

### 1.1 Drift surface

Three fields, two failure modes. Nothing else in the model drifted.

| Field | Items on disk | On-disk shape | Model expects | Missing |
|---|---|---|---|---|
| `definitions` | 42 | `{term, definition, locator}` | `ExtractedDefinition` | `source_id`, `block_id` |
| `distinctions` | 34 | `{item_a, item_b, distinction, locator}` | `ExtractedDistinction` | `source_id`, `block_id` |
| `must_not_be_lost` | 75 | `str` | `MustNotBeLostPoint` | `source_id`, `block_id`, `locator` |

`examples`, `objections` and `responses` are empty in every stored artifact, so they carry no live drift. They took the same draft→record change and are specified here anyway, because a `list[str]` payload is what the old writer would have produced.

Two extraction-level keys — `references_to_other_sections` and `unresolved_context` — exist on disk and no longer exist on the model. Pydantic's default `extra="ignore"` already drops them silently. No action; recorded so a later reader does not mistake them for a second drift.

### 1.2 Why no data is lost

`source_id` and `block_id` are present on the **enclosing record**, one level above the fields that lack them. The block locator is available from `document-blocks.jsonl`, which every source directory already stores. So every missing value is recoverable by copying, and nothing has to be guessed.

For `must_not_be_lost` the recovered locator is the block's own locator. That is not a downgrade: the field is a block-level flag by definition ([`domain.py`](../../src/thesisound/domain.py), `MustNotBeLostPoint` — "Block-level content flagged important but not turned into a claim"), and `_validate_locator` in [`evidence_validator.py`](../../src/thesisound/services/evidence_validator.py) compares a point's locator against its block's locator, which a block-derived locator satisfies exactly.

### 1.3 Verified by prototype

A read-only prototype applying §2.1 to real artifacts:

```
1296f949/4c598a0d  as-is= 0  upgraded= 3  unfixable= 0  -> evidence-validation PASS
5136911e/dd3a2676  as-is= 0  upgraded= 3  unfixable= 0  -> evidence-validation PASS
5136911e/f6f4d511  as-is= 0  upgraded= 1  unfixable= 0  -> evidence-validation PASS
f781a5c7/98863830  as-is= 7  upgraded=33  unfixable= 0  -> evidence-validation PASS (36 records)
```

40 of 40 unreadable artifacts recovered, zero unfixable, all four sources moved from `unknown` to a real verdict.

## 2. Design

Three layers. Layer A restores readability, layer B stops one bad file from erasing a whole source, layer C stops drift from being reported as an evidence-quality problem.

### 2.1 Layer A — versioned upgrade in the read path

**Where.** A new pure module `src/thesisound/services/evidence_artifact_upgrade.py`. Not in `readiness.py`: readiness is one of several readers, and [`claim_reconciler.py:68`](../../src/thesisound/services/claim_reconciler.py:68) consumes the same records. Patching the gate would leave the pipeline broken.

**Contract.**

```python
CURRENT_EXTRACTION_SCHEMA_VERSION = 2

def upgrade_block_extraction_payload(
    payload: dict[str, Any],
    *,
    block_locator: Locator,
) -> dict[str, Any]:
    """Lift a stored extraction payload to the current schema.

    Pure. Uses only values already present in the payload and the block's own
    locator. Raises EvidenceArtifactUpgradeError if a required anchor is absent.
    """
```

Rules, applied only when the field's items are not already record-shaped:

1. `definitions`, `distinctions` — inject `source_id` and `block_id` from the record. Keep the stored `locator`.
2. `examples`, `objections`, `responses`, `must_not_be_lost` — a `str` item becomes `{text: <str>, source_id, block_id, locator: block_locator}`. A `dict` item gets `source_id`/`block_id` injected and keeps its own locator.
3. Never overwrite a value that is already present.
4. Never fabricate a locator when the block cannot be resolved — raise instead, so §2.2 can report the artifact by name.

**Versioning.** Add `schema_version: int = 1` to `BlockEvidenceExtraction`. Absent means 1 (the drifted generation); the writer emits `CURRENT_EXTRACTION_SCHEMA_VERSION`. The upgrade function dispatches on it, so the next change adds a branch rather than another shape sniff. The repo already carries additive-default precedent ([`source_analysis.py:81`](../../src/thesisound/source_analysis.py:81), "Defaulted so plans written before R5 still load"); defaults are insufficient here because the item **shape** changed, not the field set.

**Call sites.** Both `load_block_extractions` and `load_extractions` in [`source_artifact_store.py`](../../src/thesisound/services/source_artifact_store.py). Both need the block locators, so both take a new required keyword `block_locators: Mapping[str, Locator]`. Making it required rather than optional forces every call site to be reviewed once, at compile time, instead of silently keeping the old behaviour.

**Writing.** Upgrade on read only. An upgraded record is rewritten to disk exclusively by the §2.4 command, never as a side effect of a read — a readiness check must not mutate the workspace it is auditing.

### 2.2 Layer B — per-artifact degradation in readiness

Today the `try` in [`readiness.py:261`](../../src/thesisound/services/readiness.py:261) wraps the whole source loop, and its `except` at [`:354`](../../src/thesisound/services/readiness.py:354) sets **both** `evidence-validation` and `evidence-retention` to `unknown` for **all** sources. One unreadable file therefore erases the verdict for every other source and both gates. Pydantic's `ValidationError` subclasses `ValueError`, so this path is what the drift actually takes.

Required behaviour:

- Read each extraction artifact in its own `try`. An unreadable artifact is collected as `(source_dir.name, path.name, reason)` and skipped; readable ones continue to be validated.
- `evidence-validation` reports the real verdict over readable records, and names unreadable artifacts in `detail` (first 4, with a total count).
- `evidence-retention` is computed over readable records only. Because a skipped extraction lowers `kept_tokens` and could make retention look like content loss, the gate must return `unknown` — not `blocked` — whenever any artifact in that source was unreadable.
- A source whose artifacts are entirely unreadable reports `unknown` for that source alone and does not affect the others.

### 2.3 Layer C — separate "cannot read" from "evidence is bad"

`unknown` currently means both "this artifact is from an older schema" and "this evidence may be wrong". An operator cannot tell them apart, which is why the audit could not distinguish an infrastructure fault from a quality fault.

Add `reason: Literal["schema", "io", "contract"] | None` to `GateResult` in [`readiness.py:33`](../../src/thesisound/services/readiness.py:33):

- `schema` — the payload is a known older generation. Recoverable; the fix is §2.4.
- `io` — the file is missing, truncated, or unreadable at the filesystem level.
- `contract` — the payload parsed but a deterministic invariant failed. This is the only one that is evidence quality.

`reason` stays `None` for `pass` / `blocked` / `not_reached`. Surface it in the readiness CLI ([`readiness_cli.py`](../../src/thesisound/readiness_cli.py)) and the web view ([`readiness_routes.py`](../../src/thesisound/web/readiness_routes.py)) as a short label, and in `projects/overview.html` as a distinct chip so a drifted project does not read as a failing project.

### 2.4 Backfill command

`thesisound migrate evidence-artifacts [--project ID] [--dry-run]`

Applies the same §2.1 function and rewrites both `evidence/extractions/*.json` and `evidence-extractions.jsonl`. `--dry-run` is the default and prints a per-source table matching §1.3. Writes are atomic per file (temp + replace) and the command is idempotent — re-running an upgraded workspace reports `as-is=N upgraded=0`.

The command exists because §2.1 alone leaves every read paying the upgrade cost forever and leaves the stored bytes disagreeing with the model. It does not replace §2.1: an artifact from an older generation can still arrive from an archive or a restored backup after the migration has run.

## 3. Non-goals

- Re-running extraction to recover the two dropped keys (`references_to_other_sections`, `unresolved_context`). They are not read by any current consumer.
- Changing `EvidenceItem`, `ClaimLedger`, or the claim path. Measured clean.
- A general artifact migration framework. Two call sites and one model; a framework here would be larger than the problem.
- Any change to what the gates *mean*. This spec restores the ability to evaluate them; it does not retune thresholds.

## 4. Acceptance criteria

1. `project_readiness` returns a non-`unknown` verdict for `evidence-validation` and `evidence-retention` on all four projects in `workspaces/`.
2. `load_block_extractions` and `load_extractions` return equal-length record lists for every source that has both artifacts.
3. A deliberately corrupted single extraction file leaves the other artifacts in its source validated, and its own source's `evidence-retention` at `unknown` with the file named in `detail`.
4. `upgrade_block_extraction_payload` is idempotent: applying it to an already-current payload returns an equal payload.
5. An upgraded record round-trips — `model_dump` then `model_validate` with no loss.
6. Reading never writes: a readiness run over a workspace leaves `git status` and all mtimes unchanged.
7. `thesisound migrate evidence-artifacts --dry-run` reports 40 upgradable and 0 unfixable before migration, and 0 upgradable after.

## 5. Test plan

| Test | Asserts |
|---|---|
| `test_upgrade_lifts_string_must_not_be_lost` | bare `str` → `MustNotBeLostPoint` with block locator |
| `test_upgrade_injects_ids_into_definitions` | stored `locator` preserved, ids injected |
| `test_upgrade_is_idempotent` | current payload in → equal payload out |
| `test_upgrade_refuses_unknown_block` | raises rather than fabricating a locator |
| `test_upgrade_preserves_present_values` | never overwrites an existing `source_id` |
| `test_readiness_isolates_one_corrupt_artifact` | other sources keep real verdicts (§2.2) |
| `test_readiness_retention_unknown_when_artifact_skipped` | skipped record does not read as token loss |
| `test_gate_result_reason_schema_vs_contract` | §2.3 labels are distinguishable |
| `test_migrate_is_idempotent` | second run reports zero upgrades |

Add one drifted extraction artifact per failure mode to the test fixtures, copied from real stored payloads with text truncated. The fixtures are the regression surface — without them, a future model change silently reintroduces this.

## 6. Sequencing

Layer A → Layer B → Layer C → §2.4. Each is independently shippable, and A alone already restores the two gates. Do not start Layer C before B: the `reason` field is only meaningful once failures are attributed to a single artifact.

## 7. Related

- [`02-script-dialogue-quality-gate.md`](02-script-dialogue-quality-gate.md) — depends on this spec. The 75 `must_not_be_lost` points that this drift makes unreadable are the input to that spec's dropped-content check.
- [`02-pipeline/03-one-source-evidence-pipeline.md`](../02-pipeline/03-one-source-evidence-pipeline.md) — the pipeline stage that writes these artifacts.
