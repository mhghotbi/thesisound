# 11 — Failure Disclosure and Stop Criteria

Date: 2026-08-13 · Status: proposed · Effort: S–M · Source: the same nine failures as spec 09, read as product surface rather than as control flow

Specs 09 and 10 remove most user-visible failures. That creates two new obligations, and neither is optional.

1. Degradation that no longer stops the build must become **visible somewhere**, or the product quietly ships worse episodes and calls it success.
2. The failures that legitimately remain must be **legible**, because after 09 and 10 they are the only ones left — and today they are written for engineers.

Without item 1, this programme trades an honest dead end for a dishonest success. That is a worse product, not a better one.

## 1. Measured problem

### 1.1 Every remaining message is written for an engineer

Verbatim, as shown to the operator on 2026-08-12:

| Message | Names an internal identifier? | Says what to do? |
|---|---|---|
| `Revision introduced new claim IDs in turn seg-004-turn-001` | yes | no |
| `Selected claims must be used or deliberately omitted: clm-4fdd919205d7d6bc` | yes | no |
| `Revised substantive turn seg-004-turn-001 lost grounding.` | yes | no |
| `Okian output did not match SegmentScriptDraft: … invalid escape at line 1 column 1999` | yes | no |
| `zip() argument 2 is longer than argument 1` | — | no |
| `Evidence extraction lost 84% of the planned source tokens across 5 rejected and 0 skipped block(s); at least 85% must survive…` | no | **partly** |
| `Coverage is insufficient for the requested duration; narrow scope or add evidence.` | no | **yes** |

Only the last is a usable product message. It is also the only one describing a condition the user can change. That correlation is the rule this spec formalises.

### 1.2 There is currently nowhere to put a soft quality signal

`ScriptCheckReport` carries issues, but the review surface treats them as gate input, not as disclosure. `MustNotBeLostReview` is explicitly documented as "a human-review surface, not a gate" — the right instinct, with no counterpart for degradations decided during a build. After spec 09 there will be many such decisions and no place for them.

## 2. Design

### D1 — The stop rule

Stop the build and involve the user **only** when at least one holds:

1. **Information asymmetry** — the answer depends on the user's intent, which the system cannot infer. Target duration, source selection, scope.
2. **Changeable input** — the user can alter something and get a different outcome. An unparseable upload, insufficient coverage.
3. **Consent** — an irreversible or costly step needs approval. Episode-plan approval before script generation.
4. **Integrity breach** — shipping the artifact would break the product's core promise. Prompt leakage, wholly unsupported claims.

If none holds, the failure is the system's to absorb — via spec 09 (degrade) or spec 10 (retry). "The model made a mistake" is never on its own a reason to stop.

Every raise site that stops a build must map to one of these four, named explicitly.

### D2 — `QualityNote`

A structured record attached to the artifact whenever the pipeline degrades:

| Field | Purpose |
|---|---|
| `stage` | where it happened |
| `kind` | stable slug (`claim_omitted`, `turn_not_revised`, `citation_dropped`, `block_rejected`, …) |
| `subject` | internal id, for the ledger — never rendered raw |
| `listener_impact` | one plain sentence with no internal identifiers |
| `severity` | `informational` \| `notable` |

`listener_impact` is the field that matters. `Revised substantive turn seg-004-turn-001 lost grounding.` becomes *"One passage kept its original wording because the rewrite lost its source link."*

### D3 — Disclosure at review, not during the build

Notes surface **once**, on the existing script-review screen, grouped by kind, ordered by severity — never as an interruption mid-run. This is the whole trade: the user reviews quality deliberately at a natural checkpoint instead of being stopped repeatedly by errors they cannot act on.

`notable` notes must be visible without expanding anything. A reviewer approving a script is entitled to know it was degraded before they approve it.

### D4 — A degradation ceiling

Unbounded silent degradation is its own failure mode: enough individually-reasonable fallbacks compose into an episode that misrepresents its sources. Define a ceiling — a proportion of segments or claims degraded — above which the outcome becomes `review_required` rather than `verified`, regardless of how well each individual fallback behaved.

This is the honest counterweight to spec 09 and should ship **with** it, not after. Thresholds are to be set from recorded runs once notes exist, per the project's rule of changing defaults only from evidence.

### D5 — Rewrite the surviving messages

Each remaining stop gets: what happened in product terms, which of D1's four reasons applies, and the next action. Internal identifiers move to the ledger and stay out of the message.

> Before: `Selected claims must be used or deliberately omitted: clm-4fdd919205d7d6bc`
> After (if it were still a stop): *"One selected point was neither covered nor set aside. Add a segment that covers it, or shorten the episode."*

### D6 — Distinguish "degraded" from "clean" in run state

`succeeded` currently covers both a clean build and one that degraded eight times. Runs carrying `notable` notes must be distinguishable in the run record, so §1.2's blind spot does not reappear one level up and so operators can measure whether recovery is becoming the normal path.

## 3. Non-goals

- Changing which conditions are genuinely fatal — that is spec 09 D3. This spec changes their **wording** and requires their **justification**, not their existence.
- Removing the operator-facing detail. The ledger keeps full internal identifiers; only the user-facing string is rewritten.
- Localisation work beyond keeping user-facing strings translatable.
- A model-based quality judge. Every signal here is deterministic and already computed.

## 4. Acceptance criteria

1. Every build-stopping raise names which of D1's four reasons applies.
2. No user-facing failure or note string contains a claim ID, turn ID, block ID, schema name, or provider name.
3. A build that degrades once completes and shows exactly one note at review.
4. A build that exceeds the D4 ceiling ends `review_required`, never `verified`.
5. A clean build shows no notes and is distinguishable in the run record from a degraded one.
6. Every `QualityNote.kind` has a `listener_impact` sentence that reads correctly with no other context. **Regression that matters most: this is what stops disclosure from becoming noise the reviewer learns to ignore.**

## 5. Test plan

| Test | Asserts |
|---|---|
| `test_every_fatal_raise_declares_a_stop_reason` | D1, §4.1 |
| `test_no_user_facing_string_contains_an_internal_id` | D2, §4.2 |
| `test_single_degradation_surfaces_one_note_at_review` | D3, §4.3 |
| `test_degradation_ceiling_forces_review_required` | D4, §4.4 |
| `test_clean_build_is_distinguishable_from_degraded` | D6, §4.5 |
| `test_listener_impact_is_context_free_for_every_kind` | §4.6 |
| `test_coverage_stop_keeps_its_actionable_message` | D5 — the one good message must not regress |

## 6. Sequencing

D2 (`QualityNote`) first — spec 09 depends on it existing. Then D3 (review surface) → D4 (ceiling, ships with 09) → D6 (run state) → D1/D5 (audit and rewrite, mechanical once the rest is in place).

## 7. Related

- [`09-degrade-instead-of-fail.md`](09-degrade-instead-of-fail.md) — produces the notes defined here; D2 blocks it.
- [`10-automatic-run-recovery.md`](10-automatic-run-recovery.md) — what surfaces after recovery is exhausted.
- [`02-script-dialogue-quality-gate.md`](02-script-dialogue-quality-gate.md) — the gate whose verdicts this spec renders for a reader.
- [`01-foundations/05-quality-evaluation.md`](../01-foundations/05-quality-evaluation.md) — quality dimensions the ceiling should align with.
