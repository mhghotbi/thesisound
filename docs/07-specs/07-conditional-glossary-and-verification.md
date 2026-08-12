# 07 — Conditional Glossary and Model Verification

Date: 2026-08-12 · Status: **implemented (glossary + reviser)** · Effort: M · Source: [MVP readiness audit](../thesisound-mvp-readiness-audit-fa.html), "Simplify / Change before MVP" — *glossary and model verifier/reviser conditional only*

Make the model-backed half of the glossary stage conditional, without letting "conditional" become "silently absent". The glossary is load-bearing for `glossary_inconsistency`; a naive skip turns that binding check into a no-op.

**Adopted scope (2026-08-12):** §2 (deterministic glossary always, model sometimes) and §3.3 (explicit reviser skip). **§3 conditional verifier is superseded** by [audit revision 2](../thesisound-mvp-readiness-audit-2026-08-12-fa.html) — the model verifier stays unconditional; do not implement `verdict="not_required"`.

## 1. Position

**Adopt for the reviser. Adopt for the glossary only as "deterministic always, model sometimes". Do not adopt conditional verification.**

The cost case for glossary is real — the audit measured the historical glossary call at roughly 50k input tokens. But `glossary_inconsistency` treats an empty glossary as a silent pass, so "skip glossary" without a deterministic artifact would remove a binding quality check. That coupling is the substance of the shipped half of this spec.

## 2. Coupling A — an absent glossary silently disables a binding check

Two facts:

1. [`script_pipeline_service.py`](../../src/thesisound/services/script_pipeline_service.py) hard-loads the glossary in `write_script` / checks. Skipping the build raises here.
2. `ScriptChecker`'s `glossary_inconsistency` check iterates `for term in glossary.terms`. **An empty glossary produces zero issues.**

`glossary_inconsistency` is `severity="high"` — one of the few checks that can actually move the verdict (see [`02-script-dialogue-quality-gate.md`](02-script-dialogue-quality-gate.md) §1.2 for how few there are). It is also precisely the check that guards terminology and pronunciation consistency, which is the NotebookLM complaint class the audit documents under "pronunciation of names and technical terms".

So a plain "skip glossary for simple episodes" trades a measurable model cost for the silent removal of a binding quality check, in the exact dimension the product claims as a differentiator. That trade is not worth taking, and the audit's own wording already points the right way: *"deterministic first, model only when needed."*

### 2.1 Design

**The deterministic path always runs.** Build the term list without a model call from data the pipeline already has:

- Terms carried by `ExtractedDefinition` records across the corpus — term and definition, already extracted per block.
- Latin-script tokens appearing in evidence excerpts, which are the transliteration risk.
- Proper nouns already present in claim text.

The result is a `Glossary` with real `terms`, `model_run_id` recorded as the deterministic builder rather than a model run, `build_kind="deterministic"`, and confident Persian terms at `translation_status="standard"`. `glossary_inconsistency` keeps working because `terms` is non-empty when the corpus supplies confident forms.

**The model pass becomes conditional.** Invoke the model glossary path only when the deterministic pass leaves work a model can do:

| Condition | Rationale |
|---|---|
| ≥ 1 term with no confident Persian form | the actual translation decision |
| ≥ 1 unresolved Latin candidate (TTS / transliteration risk) | pronunciation / form not derivable |
| corpus contains ≥ 2 sources with conflicting forms for one term | reconciliation |

None satisfied → no call. This preserves the check, keeps the artifact well-formed, and removes the call on the episodes that never needed it.

**Distinguish empty from absent.** `build_kind: Literal["deterministic", "model"]` on `Glossary`, defaulted to `"model"` so stored artifacts still load. `corpus_had_latin_tokens` records whether the harvest saw Latin. `glossary_inconsistency` reports "glossary is empty" as a `medium` issue when `build_kind == "deterministic"`, `terms` is empty, and `corpus_had_latin_tokens` — the one case where an empty glossary is itself the defect rather than an absence of work.

Implementation: [`deterministic_glossary.py`](../../src/thesisound/services/deterministic_glossary.py), wired through [`glossary_builder.py`](../../src/thesisound/services/glossary_builder.py).

## 3. Coupling B — conditional verifier (superseded)

`readiness.py` treats a missing verification artifact as `not_reached`, then `blocked` once state advances. The original proposal here was `verdict="not_required"` so a skip remains a recorded decision.

**Not implemented.** [Audit revision 2](../thesisound-mvp-readiness-audit-2026-08-12-fa.html) retracts conditional `script_verifier`: the verifier must always run; trim inputs if cost matters. Spec 08 cites the same retraction. Sections 3.1–3.2 below are retained as historical design notes only.

### 3.1 Design (not shipped)

A skip must be **recorded as a decision**, not as a missing file. Extend the verification report with an explicit not-required outcome:

- Add `verdict: "not_required"` alongside the existing verdicts, and `skip_reason: str | None`.
- The pipeline writes a real verification artifact carrying `not_required` plus the risk inputs that justified it. Nothing is absent; the artifact records that the check was deliberately not run.
- `readiness.py` treats `not_required` as `pass` with a `detail` that says so plainly, so an operator reading the gate list sees "verification was not required for this episode" rather than a green tick that overstates what happened.

### 3.2 Risk classification (not shipped)

Run the model verifier when any holds:

| Condition | Rationale |
|---|---|
| deterministic `ScriptCheckReport.verdict != "pass"` | the cheap check already found something |
| corpus has ≥ 2 sources | cross-source attribution is the known weak point |
| any claim has `support_status` other than fully supported | the case the verifier exists for |
| the disagreement graph is non-empty | competing views in the corpus |
| target duration ≥ 30 minutes | more surface, more drift |

Single clean source, deterministic checks green, no disagreement, ≤ 20 minutes → `not_required`.

This ladder is deliberately conservative. The verifier is the mechanism behind the product's central claim, and the audit already rates trust as *not proven*; the saving is one call per episode and is not worth widening the skip.

### 3.3 The reviser (shipped)

The reviser is already effectively conditional — it runs when there is something to revise. Made explicit as `revision_is_required(checks, verification)` in [`script_pipeline_service.py`](../../src/thesisound/services/script_pipeline_service.py): skip when `ScriptCheckReport.verdict == "pass"` **and** verification is `pass`. No `not_required` branch (verifier always produces a real verdict). No new artifact semantics; the reviser produces no gate input of its own.

## 4. Interaction with spec 02

[`02-script-dialogue-quality-gate.md`](02-script-dialogue-quality-gate.md) makes the deterministic script checks bind. That would have changed the input to §3.2's first condition; with §3 superseded, the interaction that matters for the shipped scope is only that stronger deterministic checks still feed the reviser via §3.3.

## 5. Non-goals

- Removing the glossary or the verifier from the pipeline.
- Making the deterministic script checks conditional. They are free and must always run.
- Conditional model verification (`not_required`) — superseded by audit revision 2.
- Ensemble or majority-vote verification — [`06-operations/01-server-mono-process-adoption.md`](../06-operations/01-server-mono-process-adoption.md) item 11.
- Auto-approval on a skipped verification.
- Retuning `unsupported_claim_ratio` thresholds.

## 6. Acceptance criteria

1. A project with no model glossary call still produces a `Glossary` with non-empty `terms` on a corpus containing Latin-script terms.
2. `glossary_inconsistency` still fires on a script that uses a source term without its preferred Persian form, when the glossary was built deterministically.
3. `load_glossary` never raises for a project that reached script drafting.
4. ~~A single-source, deterministically-clean, 10-minute episode records `verdict="not_required"`…~~ **N/A** — verifier unconditional.
5. ~~`project_readiness` reports `independent-verification` as `pass` for that skip…~~ **N/A**.
6. ~~A two-source project always runs the model verifier.~~ **N/A** — always runs for every project.
7. ~~A project whose deterministic checks report `revise` always runs the model verifier.~~ **N/A**.
8. Stored glossaries and verification reports written before this spec still load.

## 7. Test plan

| Test | Asserts |
|---|---|
| `test_deterministic_glossary_extracts_terms` | §6.1 |
| `test_glossary_inconsistency_fires_on_deterministic_glossary` | §6.2 — the coupling this spec exists to protect |
| `test_glossary_build_kind_defaults_for_legacy_artifact` | §6.8 |
| `test_model_glossary_skipped_when_no_open_decisions` | the conditional path |
| `test_model_glossary_runs_on_conflicting_forms` | multi-source trigger |
| `test_empty_deterministic_glossary_flags_latin_corpus` | empty + Latin → medium |
| `test_revision_is_required_helper` | §3.3 |
| ~~`test_verification_not_required_is_recorded`~~ | N/A — §3 superseded |
| ~~`test_readiness_treats_not_required_as_pass`~~ | N/A |
| ~~`test_verifier_runs_on_multi_source`~~ | N/A |
| ~~`test_verifier_runs_when_deterministic_checks_fail`~~ | N/A |
| ~~`test_legacy_verification_report_loads`~~ | N/A for this change |

## 8. Sequencing

[`02-script-dialogue-quality-gate.md`](02-script-dialogue-quality-gate.md) → §2 (glossary) → §3.3 (reviser). §3 verifier skip is not on the path.

## 9. Related

- [`02-script-dialogue-quality-gate.md`](02-script-dialogue-quality-gate.md) — must land first for any future risk ladder; already implemented.
- [`03-inline-research-brief.md`](03-inline-research-brief.md), [`06-conditional-document-map.md`](06-conditional-document-map.md) — the other two "simplify before MVP" items.
- [`02-pipeline/06-persian-script-pipeline.md`](../02-pipeline/06-persian-script-pipeline.md) — the stage both halves sit in.
- [`04-integrations/05-model-observability.md`](../04-integrations/05-model-observability.md) — where the avoided glossary calls must show up for the cost claim to be checkable.
- [`08-batched-claim-reconciliation.md`](08-batched-claim-reconciliation.md) — cites the verifier-unconditional retraction.
