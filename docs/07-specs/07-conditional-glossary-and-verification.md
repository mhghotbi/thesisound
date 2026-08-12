# 07 — Conditional Glossary and Model Verification

Date: 2026-08-12 · Status: proposed · Effort: M · Source: [MVP readiness audit](../thesisound-mvp-readiness-audit-fa.html), "Simplify / Change before MVP" — *glossary and model verifier/reviser conditional only*

Make the model-backed halves of the glossary and verification stages conditional, without letting "conditional" become "silently absent". Both stages are load-bearing for gates elsewhere, and a naive skip turns a binding check into a no-op and a release gate into a permanent block.

## 1. Position

**Adopt for the verifier and reviser. Adopt for the glossary only as "deterministic always, model sometimes".**

The cost case is real — the audit measured the historical glossary and verifier calls at roughly 50k input tokens each, on an episode whose reconstructed floor was about $1.09. But each stage has a downstream consumer that treats a missing artifact as a pass or as a block, and neither behaviour is what "conditional" is supposed to mean. Those two couplings are the substance of this spec.

## 2. Coupling A — an absent glossary silently disables a binding check

Two facts:

1. [`script_pipeline_service.py:114`](../../src/thesisound/services/script_pipeline_service.py:114) hard-loads the glossary: `glossary = self.script_store.load_glossary(project_id)`. Skipping the build raises here.
2. `ScriptChecker`'s `glossary_inconsistency` check iterates `for term in glossary.terms`. **An empty glossary produces zero issues.**

`glossary_inconsistency` is `severity="high"` — one of the few checks that can actually move the verdict (see [`02-script-dialogue-quality-gate.md`](02-script-dialogue-quality-gate.md) §1.2 for how few there are). It is also precisely the check that guards terminology and pronunciation consistency, which is the NotebookLM complaint class the audit documents under "pronunciation of names and technical terms".

So a plain "skip glossary for simple episodes" trades a measurable model cost for the silent removal of a binding quality check, in the exact dimension the product claims as a differentiator. That trade is not worth taking, and the audit's own wording already points the right way: *"deterministic first, model only when needed."*

### 2.1 Design

**The deterministic path always runs.** Build the term list without a model call from data the pipeline already has:

- Terms carried by `ExtractedDefinition` records across the corpus — term and definition, already extracted per block.
- Latin-script tokens appearing in evidence excerpts, which are the transliteration risk.
- Proper nouns already present in claim text.

The result is a `Glossary` with real `terms`, `model_run_id` recorded as the deterministic builder rather than a model run, and `translation_status` set to a deterministic value. `glossary_inconsistency` keeps working because `terms` is non-empty.

**The model pass becomes conditional.** Invoke `GlossaryBuilderService` only when the deterministic pass leaves work a model can do:

| Condition | Rationale |
|---|---|
| ≥ 1 term with no confident Persian form | the actual translation decision |
| ≥ 1 term needing a pronunciation hint | TTS-facing, not derivable |
| corpus contains ≥ 2 sources with conflicting forms for one term | reconciliation |

None satisfied → no call. This preserves the check, keeps the artifact well-formed, and removes the call on the episodes that never needed it.

**Distinguish empty from absent.** Add `build_kind: Literal["deterministic", "model"]` to `Glossary`, defaulted to `"model"` so stored artifacts still load. `glossary_inconsistency` may then report "glossary is empty" as a `medium` issue when `build_kind == "deterministic"` and `terms` is empty on a corpus that contains Latin-script tokens — the one case where an empty glossary is itself the defect rather than an absence of work.

## 3. Coupling B — a skipped verifier blocks the release gate

`readiness.py` treats the verification artifact three ways:

| Situation | Result |
|---|---|
| `load_latest_verification` raises `FileNotFoundError` | `independent-verification` → `not_reached` ([`readiness.py:466`](../../src/thesisound/services/readiness.py:466)) |
| state is `SCRIPT_VERIFIED` or later and the artifact set is incomplete | → **`blocked`** ([`readiness.py:536`](../../src/thesisound/services/readiness.py:536)) |
| verifier passed with `unsupported_claim_ratio == 0` | → `pass` |

So an episode whose verifier was skipped as low-risk cannot reach a green gate. It sits at `not_reached` until the state advances, and then flips to `blocked` because the verified artifact set is incomplete. **Conditional verification, implemented naively, is a permanently blocked release.**

### 3.1 Design

A skip must be **recorded as a decision**, not as a missing file. Extend the verification report with an explicit not-required outcome:

- Add `verdict: "not_required"` alongside the existing verdicts, and `skip_reason: str | None`.
- The pipeline writes a real verification artifact carrying `not_required` plus the risk inputs that justified it. Nothing is absent; the artifact records that the check was deliberately not run.
- `readiness.py` treats `not_required` as `pass` with a `detail` that says so plainly, so an operator reading the gate list sees "verification was not required for this episode" rather than a green tick that overstates what happened.

### 3.2 Risk classification

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

### 3.3 The reviser

The reviser is already effectively conditional — it runs when there is something to revise. Make that explicit: skip when `ScriptCheckReport.verdict == "pass"` **and** verification is `pass` or `not_required`. No new artifact semantics; the reviser produces no gate input of its own.

## 4. Interaction with spec 02

[`02-script-dialogue-quality-gate.md`](02-script-dialogue-quality-gate.md) makes the deterministic script checks bind for the first time. That changes the input to §3.2's first condition: scripts that today report `pass` will report `revise`, and will therefore route to the model verifier.

**Sequence spec 02 first.** Landing this spec first would classify the known-bad script as low-risk and skip its verification — the opposite of the intent. With spec 02 in place, the risk ladder reads a deterministic verdict that means something.

## 5. Non-goals

- Removing the glossary or the verifier from the pipeline.
- Making the deterministic script checks conditional. They are free and must always run.
- Ensemble or majority-vote verification — [`06-operations/01-server-mono-process-adoption.md`](../06-operations/01-server-mono-process-adoption.md) item 11.
- Auto-approval on a skipped verification. `not_required` bypasses the model verifier, never the human gate.
- Retuning `unsupported_claim_ratio` thresholds.

## 6. Acceptance criteria

1. A project with no model glossary call still produces a `Glossary` with non-empty `terms` on a corpus containing Latin-script terms.
2. `glossary_inconsistency` still fires on a script that uses a source term without its preferred Persian form, when the glossary was built deterministically.
3. `load_glossary` never raises for a project that reached script drafting.
4. A single-source, deterministically-clean, 10-minute episode records `verdict="not_required"` with a populated `skip_reason` and makes no verifier model call.
5. `project_readiness` reports `independent-verification` as `pass` for that project, with a detail naming the skip.
6. A two-source project always runs the model verifier.
7. A project whose deterministic checks report `revise` always runs the model verifier.
8. Stored glossaries and verification reports written before this spec still load.

## 7. Test plan

| Test | Asserts |
|---|---|
| `test_deterministic_glossary_extracts_terms` | §6.1 |
| `test_glossary_inconsistency_fires_on_deterministic_glossary` | §6.2 — the coupling this spec exists to protect |
| `test_glossary_build_kind_defaults_for_legacy_artifact` | §6.8 |
| `test_model_glossary_skipped_when_no_open_decisions` | the conditional path |
| `test_model_glossary_runs_on_conflicting_forms` | multi-source trigger |
| `test_verification_not_required_is_recorded` | §6.4 — artifact written, not absent |
| `test_readiness_treats_not_required_as_pass` | §6.5 |
| `test_verifier_runs_on_multi_source` | §6.6 |
| `test_verifier_runs_when_deterministic_checks_fail` | §6.7 |
| `test_legacy_verification_report_loads` | §6.8 |

## 8. Sequencing

[`02-script-dialogue-quality-gate.md`](02-script-dialogue-quality-gate.md) → §2 (glossary) → §3 (verifier) → §3.3 (reviser). The glossary half is independent of the verifier half and can ship alone.

## 9. Related

- [`02-script-dialogue-quality-gate.md`](02-script-dialogue-quality-gate.md) — must land first; supplies the deterministic verdict this spec routes on.
- [`03-inline-research-brief.md`](03-inline-research-brief.md), [`06-conditional-document-map.md`](06-conditional-document-map.md) — the other two "simplify before MVP" items.
- [`02-pipeline/06-persian-script-pipeline.md`](../02-pipeline/06-persian-script-pipeline.md) — the stage both halves sit in.
- [`04-integrations/05-model-observability.md`](../04-integrations/05-model-observability.md) — where the avoided calls must show up for the cost claim to be checkable.
