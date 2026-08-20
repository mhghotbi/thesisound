# 12. Prompt Anchor Register and Experiment Plan

Status: **register, not a decision.** Nothing here has been applied to a shipping prompt except the
`must_not_be_lost` rewrite already in `evidence_extraction/2.1.0` (anchor `EX-6`, variant D), which is
itself re-examined below. No code was changed to produce this document.

Written: 2026-08-20. Author: overnight analysis session. Parent: doc 10 §8 (prompt audit).

---

## 0. What this document is

An **anchor** is a short piece of prompt text — often one clause — that silently decides a large,
measurable property of the output. It is not the same as a rule. Most prompt rules are inert: the
model would have behaved that way anyway. An anchor is a rule that is *load-bearing*, so that
changing five words changes the artifact.

The `must_not_be_lost` sentence in `evidence_extraction` was the first one found. Rewriting one
sentence moved the flag rate from **40.2%** of all claims to **4.4%** and then to a middle value —
without touching a single line of code. That is the signature of an anchor: enormous leverage,
invisible in review, unversioned in the sense that nothing fails when it drifts.

This register lists **every candidate found in all 17 prompt stages**, with:

- the exact quoted text and its location,
- why it is load-bearing (the mechanism),
- what real runs already show about it,
- the failure it causes when it misfires, and
- a concrete experiment that would settle it.

Section 3 lists the **numeric constants in code** that are paired with these anchors — a word and a
number that only mean something together. Those are listed for completeness; the code was not
touched.

### Read this before believing any single number in §4

The last experiments of the night were controls: **the same prompt, run three times, on each of two
corpora.** On the 9-block corpus those runs quoted only 43–57% of the same text and gave flag counts
of 10, 8 and 5 — every prompt variant tested falls inside that band. On the 38-block corpus the same
metric is stable (15.8% ± 1.4). **Corpus size, not prompt wording, decided whether a result was
readable.**

So the honest summary of this document is in two halves:

- **What is solid** — anything measured over many artifacts or sitting at 0% / 100%: the degenerate
  channels (§4.13), the 85% required-section rate (M1), the Persian failure rate (M16), the verifier's
  15-of-15 perfect scores (M5), the boilerplate omission reasons (M6). These are not close calls.
- **What is not** — the single-run A/B comparisons made on the 9-block corpus. One of them (`EX-2a`,
  §4.7) has an effect large enough to survive; the rest sit inside the noise. Two conclusions written
  earlier in the night were **retracted** by the control, and both retractions are left in place
  rather than edited away, because the failure mode they illustrate is the main practical risk in this
  kind of work.
- **The one result that the control made *stronger*** is `EX-6a` (§4.8), because it was replicated on
  38 blocks: three runs of D leave 10, 15 and 12 blocks unprotected and **all 37 of them are argument
  or definition blocks**, while `EX-6a` and the pre-D baseline both leave 0.

The register in §2 is therefore best read as *what to test*, not *what is broken*, except where a
measurement in §1 is cited.

### The two product modes every anchor is judged against

Thesisound turns academic sources into Persian audio for one listener — the owner. There are two
modes, and an anchor can be safe in one and harmful in the other:

| Mode | Owner's words | What must not break |
| --- | --- | --- |
| **Coverage** | «گاهی زمان برام مهم نیست و عمق و پوشش مهمه» | Nothing essential in the source may be lost. Time and cost are free. |
| **Fixed time** | «گاهی می‌خوام مفاهیم مهم رو در یه زمان مشخص داشته باشم» | The most important concepts must survive compression, and the episode must actually be the requested length. |

Coverage mode is `lesson_intent = source_coverage`; fixed-time mode is `focused_question`. Anchors
that decide *what is dropped* hurt fixed-time mode. Anchors that decide *what is read at all* hurt
coverage mode. Both are called out per anchor.

---

## 1. Measured tonight — findings that need no further experiment

These came out of real artifacts already on disk plus two live runs. They are stated first because
several of the "candidate experiments" below are already answered by them.

| # | Finding | Evidence | Verdict |
| --- | --- | --- | --- |
| **M1** | `required_for_global_understanding` is set on **283 of 333 sections (85.0%)** across 15 real document maps; 6 maps are at 100%. Split by whether the model was ever told anything about the field: **94.3% where no instruction exists** (10 non-partitioned maps — `document_map` never mentions it) vs **80.7% where merge says "conservatively"** (5 partitioned maps). | every `document-map.json` in `workspaces/` | The instruction is on the wrong prompt for two thirds of real maps, and is too weak even where it lands. §2.5 |
| **M2** | Because of M1, the block-ranking score is degenerate. On the 41-section Arendt map, **36 of 41 sections (88%) share the identical score 175**; on the 10-section map, 90% share one score. | `_FUNCTION_WEIGHT` + `+100` for required, computed over real maps | Which blocks get read is close to arbitrary. |
| **M3** | The `inferential` support kind is **never used**: 0 of 189 claims in the 38-block Arendt run. | `base-arendt38` snapshot | A whole schema channel is dead. |
| **M4** | `more_claims_available` is true on **37 of 38 blocks (97%)**, and **37 of 38 blocks returned exactly the cap** (5 claims). | same run | The signal is constant, so it carries no information; the dense second pass it drives cannot discriminate. |
| **M5** | The script verifier returned `pass`, **zero issues**, `unsupported_claim_ratio 0.0`, and **exactly 1.0 on all five quality dimensions**, in every run on disk (5 verdicts, 3 with scores). `actionable_feedback` was empty each time. | every `script/verification.json` | The adversarial verifier is not discriminating. This is the weakest link in the grounding chain. |
| **M6** | `deliberately_omitted_claims` carries a *concrete editorial reason* in **5 of 64 entries**; the other **59 are the identical string** "Deferred claim omitted due to time budget limits." | `9c4e58b0` episode plan | The must-not-be-lost accounting is nominally satisfied and informationally empty. |
| **M7** | Scripts land **under** their target length in all three runs: ratios **0.71 / 0.86 / 0.88** against `plan_minutes × 130 wpm`. The prompt asks for "within roughly 15 percent". | `script-draft.json` vs `episode-plan.json` | A "30-minute" episode is really 21–26 minutes. Directly damages fixed-time mode. |
| **M8** | One script is at **31.7% editorial words** against a stated 25% cap. The deterministic check exists but is recorded at severity `low` (non-blocking) by explicit MVP policy. | `f781a5c7`; `script_checks.py:396` | The cap is advisory in both prompt and code. |
| **M9** | Document-map `depends_on_section_ids` is the **immediately preceding section in 268 of 349 edges (76.8%)** — reading order restated as dependency. | all maps | The dependency graph is mostly not a graph. |
| **M10** | The mapper frequently produces **one section per block** (41 sections / 41 blocks; 10/10; 9 of 10 single-block). No anchor in the prompt constrains section size or count. | all maps | The "section" layer often adds no grouping. |
| **M11** | **The Persian path is barely passable at extraction.** On a real Persian academic PDF the verbatim rule rejects excerpts with `ExcerptNotFoundError` at 35× the English rate (see M16). Cause: the parse contains **1,805 kashida/tatweel characters (one per 30 chars, 16.3% of all words)**, **zero ZWNJ**, and mixed orthography (616 Arabic yeh vs 3,057 Persian yeh). | live run, project `5a7cd1c9` | See §1.1. The single highest product risk found. |
| **M12** | That same Persian document passed the parse gate as `safe_for_claim_extraction: true`, verdict `warning`. A second Persian PDF parsed into pure mojibake (Arabic presentation forms as literal text) and **also** returned `safe_for_claim_extraction: true`. | `FA-1`, `FA-2` in `test-01/` | The parse gate does not see Persian-specific damage. |
| **M13** | Variant D, re-run on all 38 Arendt blocks, cuts `must_not_be_lost` from **40.2% to 17.4%** and raises the qualification rate from **12.7% to 21.1%** — but leaves **10 of 38 blocks with zero flagged claims** where the baseline left none. | live run tonight | D works, and needs a floor. §4.1 |
| **M14** | Across **three** replicated D runs, **all 37 zero-flag blocks are `argument` (33) or `definition` (4)**. **Not one is narrative, list, or example**, in any run. Two carry chapter theses. The count varies (10, 15, 12); the composition does not vary at all. | live runs + document map | D does not drop protection at random — it drops it from the blocks carrying the argument. |
| **M15** | One floor sentence added to D (`EX-6a`) takes zero-flag blocks to **0**, against **10, 15 and 12** in three replicated D runs, and **0** in the baseline. Across six D runs on two corpora, **none has ever produced 0**. | live runs tonight | **The floor restores the protection D removed.** §4.8 |
| **M16** | The verbatim rule fails on **28.0% of Persian model attempts (45 of 161)** against **0.8% on Arendt-38 (3 of 393)** and **0.0% on Arendt-9 (0 of 173)** — same prompt, same model. Cost: **380k output tokens** on an 11-block Persian source vs 305k on a 41-block English one. | live runs tonight, classified by error type | ~35× the failure rate on Persian. §4.2 |
| **M17** | The Persian cliché blacklist has **0 exact hits and 1 near-variant** across 3 scripts. | existing scripts | An anchor that works. Useful as a control: concrete prohibitions are obeyed; abstract ones (`DM-1`, `EP-2`) are not. |
| **M18** | Analogies in `editorial_only` turns: **0**. Another dead channel, alongside `inferential` (M3) and `confidence` (M21). | existing scripts | The sanctioned-hallucination hatch is unused, not abused. |
| **M19** | Hand-audit of 16 `direct` claims: **2 clear mislabels**, plus **3 excerpts that open with an unresolved pronoun** the claim silently resolves from outside the excerpt. | Arendt-38 | ~12% mislabel, ~31% including anaphora. Motivates the new anchor `EX-11`. |
| **M20** | **Claim reconciliation is skipped outright on single-source projects** — including every large one (190, 81, 18 evidence items). Where it *did* run, it merged **1 of 121 items (0.8%)**, and **1 of 410 claims cites more than one evidence ID**. | every `claim-ledger.json`; `claim_reconciler.py:555` | The `CR-*` anchors are largely untested at scale, and near-inert where tested. §4.9 |
| **M21** | `support_status` is **`strong` on all 410 claims**, because it is a deterministic function of the model's `confidence` field — and **not one of 554 evidence items scored below 0.75**; 93% are 0.95 or 1.0. The extraction prompt **never mentions `confidence`**. | `claim_reconciler.py:559-566` + all evidence items | The writer, verifier and planner all branch on `support_status`. Every branch is dead, and the cause is an unanchored schema field. New anchor `EX-12`. |
| **M22** | `max_supported_minutes` **equals the requested duration exactly** in all three corpora with different evidence volumes: 20→20, 10→10, 30→30. Also, `audit-coverage` returns a cached result on repeat calls (identical `model_run_id` across 5 invocations), so the estimate is computed once and never re-checked. | coverage reports; CA-1a/CA-1b | The gate mirrors the request rather than assessing the corpus. |
| **M23** | **On the 9-block corpus, three runs of the *identical* prompt agree on only 43–57% of the text they quote and give flag counts of 10, 8, 5** — every prompt variant tested falls inside that band. On the **38-block** corpus the same metric is stable (rates 17.4 / 14.7 / 15.3%). | 3-run controls on both corpora, §4.5 and §4.8 | **The governing result for all of §4.** Nine blocks cannot resolve anything smaller than a 4× effect; 38 can. Two conclusions in this document were retracted because of it. |
| **M24** | Both Persian verbatim variants finish in **3 passes vs the baseline's 5**, at ~62 attempts vs 172 and ~239k tokens vs 452k, with **0 blocks left rejected** vs 1. `EX-4b` cuts median excerpt length **167 → 69 chars** — the one anchor tonight whose stated mechanism was directly observed firing — but halves `excerpt_char_coverage`; `EX-4a` raises it. | live runs tonight | **Adopt `EX-4a`.** §4.12 |
| **M25** | Persian `excerpt_char_coverage` is **0.069–0.134** against **0.29–0.31** on English. | same | Any `thin_extraction` threshold calibrated on English flags *every* Persian block. Calibrate per language, not only per depth tier. |
| **M26** | **`concept-map --chapters` crashes unconditionally.** The pipeline passes the *whole* block list as `blocks` but only the *selected* chapters' blocks as `partitions`; the receiving assertion requires them to match. 8 attempts, 8 identical `AssertionError`s. | live runs; `concept_map_pipeline.py:182-196` vs `document_mapper.py:397` | Engineering defect, not an anchor. It is why §2.2–2.4 have no data. |
| **M27** | The **whole-book** concept map path works (succeeded on retry 6). It produced the first concept map ever built here: **15 chapters, 107 cells, 145 edges, 688 implied spoken minutes** for *The Human Condition*. | live run | Confirms M26 is confined to the `--chapters` branch, and unlocks §2.2–2.4. |
| **M28** | **22 of 107 cells (20.6%) come from non-content chapters** — 12 from the endnotes, 6 from the index, 4 from the copyright and title pages. `eligible_blocks` drops front-matter and note-like blocks, but it lives in `analysis_profile.py` and only the *extraction* path calls it; the concept-map path never does. | cached concept map; `analysis_profile.py:168` vs `concept_map_builder.py` | In coverage mode the system would plan lessons about the index. |
| **M29** | **Every chapter title is an EPUB internal filename** — `9780226924571 08 ch1`, `… 16 not`, `… 17 ind`. All 15 chapters came from the ToC detector with `detection_agreement: toc_only`; the heading detector never agreed once. | same | The human-facing review surface of P1 is unreadable, and front/back matter is indistinguishable from chapters by title. |
| **M30** | **`CC-3` confirmed: `example` is 1 cell of 107 (0.9%)**, `objection` 2, `response` 1, while `argument` takes **54.2%**. The never-split-worked-examples prohibition beats the `example` kind listed two lines later. | same | Canonical cases get absorbed into their parent and lose their own budget. Same degeneracy as `document_map`'s 80%-`argument` function field. |
| **M31** | **`CC-2` partially confirmed.** Tier 1 lands at **31.8%** — comfortably inside the 15–45% the prompt demands — but tier 3 is **8.4%, below the stated 10% floor**. 15 cells were promoted by *code*, not by the model. | same | The window the prompt names is the window the output occupies; the floor it names is missed. |
| **M32** | **`CC-1` holds tightly.** `estimated_minutes` is mean 6.4, median 5.0, and only **2 of 107 cells (1.9%) fall outside the stated 3–15 window**; the maximum is exactly 15.0. | same | A concrete numeric range in a prompt is obeyed. Contrast with `DM-1`'s abstract "conservatively" at 85%. |
| **M33** | **In one sentence, the floor is obeyed and the ceiling is ignored.** `concept_edges` says *"a strong prerequisite ≥ 0.8; a weak related ≤ 0.4"*. Prerequisite: **37/37 comply** (min 0.80). Related: **4/41 comply** (mean 0.69, max 0.90). | same | Lower bounds bind; conditional upper bounds do not. Also: **0 of 66** prerequisite/`depends_on` edges fall below `part_packer`'s 0.35 cut, so `CE-2`'s feared disagreement is moot. |
| **M34** | **The `EX-12` prediction, measured as a natural experiment.** Same model, same codebase, same 0–1 `confidence` field: where the prompt **defines** it (`concept_edges`) the values reach down to **0.50** (n=145, mean 0.878); where it **never mentions** it (`evidence_extraction`) the minimum across **732** items is **0.90**. | cached map + all evidence items | An unanchored required field collapses to near-certainty. Strongest support for `EX-12a`. |
| **M35** | **`CE-2a` works.** Rewriting *"a strong prerequisite ≥ 0.8; a weak related ≤ 0.4"* as a band per edge type (`prerequisite 0.8–1.0; extends and depends_on 0.5–0.7; related 0.1–0.4; …`) moved compliance with the intended bands from **7 of 18 (39%) to 12 of 14 (86%)**. Baseline weights all sat in 0.75–0.90 regardless of type; the rewrite spans 0.50–0.80 and separates the types. | live A/B, chapter 2 | **Bounds attached to a type bind; bounds attached to an adjective do not.** Confirms the §4.13 rule. |
| **M36** | **`CC-3a` does not work.** Explicitly exempting canonical cases from the never-split rule left `example` cells at **0 of 24** (baseline 0 of 21). Cell count rose 21→24 and tier 1 rose 7→10, but the kind stayed absent. | live A/B, chapter 2 | A negative result: the `example` kind is not recoverable by narrowing the prohibition alone. |
| **M37** | **The document-map cache silently defeats prompt A/B testing.** `DocumentMapCache` keys on a content hash plus `builder_version` — **not the prompt version**. A first `DM-1a` run returned byte-identical maps for two different prompts and made **zero `document_map` calls**. | `document_map_cache.py:93`; model-run stage counts | Any future map-prompt experiment must move `workspaces/_shared/document-maps` and `document-map-parts` aside first, or it will measure nothing. |
| **M38** | **`DM-1a` is the largest anchor effect measured in this project.** Replacing *"mark globally required sections conservatively"* with a definition plus an expected share (*"only when a listener who skipped it would misunderstand a later section… expect roughly N/5; more than a third means you are using the wrong test"*) took the required rate from **41 of 41 (100%) to 7 of 41 (17%)** on a cold cache. 17% is almost exactly the N/5 asked for. | live cold-cache A/B, Arendt-38 map | One sentence. §4.14 |
| **M39** | **It fixes half the ranking degeneracy, and names the other half.** Selecting the top 10 blocks: baseline had 3 sections above the cutoff and **37 tied** competing for 7 slots; `DM-1a` has **7 above** and 34 tied for 3. The residual tie is `DM-4` — 37 of 41 sections are still labelled `argument`, so the function weight contributes nothing. | same | `DM-4a` (the function vocabulary) is now the obvious next experiment. |
| **M40** | **Reconciliation, finally run with the model enabled** (a 2-source project, so `skip_model` is False): 125 evidence items → 122 claims = **2.4% merged**, 3 claims citing more than one evidence id, 0 unresolved. One source merged 0 of 38. | live run, project `ab87511f` | The `CR-*` anchors are not set too high — the stage is near-inert even when it runs. §4.14 |
| **M41** | **`support_status` is `strong` on all 122 claims even when the model chooses it.** The constant is therefore not just the deterministic skip-path formula (M21) — the model itself never marks anything contested or uncertain. | same | Rules out the simplest explanation for M21; the field is dead at both ends. |
| **M42** | **`DM-1` decomposed, after the first attempt was found to be biased.** Baseline "conservatively" over 3 runs: **98 / 100 / 90%**. The *criterion alone*, no number: **59 / 54 / 37%**. Adding "expect roughly N/5": **20%** (1 run). | live A/B, 3 runs per arm, cold cache | Defining the test is worth ~2× and is real; the quota's extra push is the model echoing the number it was given. §4.15 |
| **M43** | **`EX-12a` is refuted.** Defining `confidence` in the extraction prompt — including an explicit "returning the same confidence for every claim means you have not judged them" — left the minimum at **0.90**, produced **zero** values below 0.75, and *reduced* distinct values from 6–8 to **3** (74 of 90 claims at exactly 0.95). | live run, 18 of 38 blocks | Retracts the prediction drawn from M34. §4.16 |
| **M44** | **M34 was confounded by task difficulty, not by the anchor.** `concept_edges` reaches confidence 0.50 and `evidence_extraction` never goes below 0.90 — but that gap survives defining the field in both. Judging whether an edge exists between two cells is genuinely more uncertain than judging whether a block, whose text is in hand with a verbatim excerpt, states a claim. | M34 + M43 | A cross-prompt comparison is not an experiment. The register's one "natural experiment" did not hold up. |
| **M45** | **Nothing in any ledger is a near-duplicate.** Across 579 claims in 11 ledgers, **0 pairs** exceed 0.55 word-overlap — including 339 claims where reconciliation never ran. On the 190-claim ledger the maximum over 17,955 pairs is **0.294**, and the top pairs are genuinely distinct propositions. | deterministic scan, 0 model calls | Reconciliation is not lazy; extraction leaves it nothing to do. §4.17 |
| **M46** | **`SV-1a`: the verifier passed a deliberately sabotaged script.** Three defects were planted in a script it had already passed — a fabricated date (۱۹۵۸), a fabricated figure (73 archival documents), and an invented comparison in a *substantive* turn. Verdict: **pass, 0 issues, ratio 0.0, all five scores 1.0** — identical to the clean control. | live run, both arms, project `9c4e58b0` | **The verifier detects nothing.** §4.18 |
| **M47** | Worse than silence: on the sabotaged script it wrote *"All turns are fully grounded in the provided source evidence and maintain high fidelity to the text."* It does not abstain — it affirms. | same | A reviewer that certifies fabrications is worse than no reviewer. |
| **M48** | **The free deterministic checker did better than the model.** It flagged the planted date `۱۹۵۸`. But it added it to an *existing* issue rather than raising a new one — issue count stayed at 9 in both arms — and it missed the other two defects. | `ScriptChecker`, clean vs dirty diff | The one real detection is invisible in the issue count. |
| **M49** | Those 9 deterministic issues are mostly false positives: `unsupported_specifics` fires on ordinary Persian terminology including **the book's own title** (وضع بشر), حیات فعال, ماهیت انسان. All at `medium`, which does not block. | same | The real signal sits in a list with four false ones, at a severity nothing acts on. |

### 1.1 M11 in detail — why the Persian path fails

The block text handed to the model looks like this (real, from `FA-2`):

> `تحلیـل` `ایـن` `اسـت` `بسـیاري` `اندیشـمند` `ظهـور`

Those are ordinary Persian words stretched with **kashida** (U+0640) because the PDF is
justified. The extraction prompt says:

> `supporting_excerpt must be copied character-for-character from the target block. Whitespace
> differences are acceptable; punctuation differences are not. … never normalize Persian or Arabic
> letters, digits, or zero-width joiners.`

So the model must reproduce every kashida in the right place, in text that also has all its ZWNJ
stripped and its word order partly scrambled by RTL column extraction. It mostly cannot, and the
deterministic check rejects the whole block. Observed failures carried excerpts like:

> `، اصلی دوران مدرنه مسئل، برای آرنت »جهـان  از   بیگـانگی «او`

The mangling is visible: `مسئل،` and inconsistent kashida. One attempt burned **7,469 output tokens**
before being rejected.

This is a *joint* failure of a parser and an anchor, and both halves are worth separating:

- the parser produces damaged Persian and does not flag it (M12);
- the anchor makes damage unrecoverable rather than tolerable, because the model's natural repair
  instinct is exactly what the rule forbids and the checker punishes.

Experiments `EX-4a` and `EX-4b` below test the anchor half in isolation.

---

## 2. Anchor register — prompt text

IDs are stable. Quotes are verbatim from the active prompt version. "Mode" says which product mode
the anchor endangers.

### 2.1 `evidence_extraction` / `evidence_extraction_batch` 2.1.0

The most anchor-dense prompt in the system. Everything downstream is built from its output.

---

**`EX-1` — the budget tie-breaker** · `system.md:8` · **mode: fixed time**

> "If the block supports more distinct claims than the budget allows, **extract the most central
> ones** and set more_claims_available to true"

*Mechanism.* This single phrase decides which claims survive when the budget binds — and the budget
binds on 37 of 38 blocks (M4). It is therefore the primary compression rule of the whole product,
and "central" is undefined.

*Risk.* "Central" plausibly resolves to "topic-like" rather than "load-bearing", so qualifications
and the claims that reverse a reading are dropped first — the opposite of what a careful reader
would keep.

*Experiment `EX-1a`.* Replace with an explicit ordering: *"extract the ones the block's other claims
depend on first, then the author's own positions, then everything else."* Fixed 9-block corpus,
`deep`, `max_claims=5`. Metric: **set overlap of surviving claims** against baseline, plus
claim-type mix and qualification rate. A change in *which* claims survive at constant *count* is the
result to look for. → **run tonight, see §4.**

---

**`EX-2` — the depth tiers, in one sentence** · `system.md:10` · **mode: both**

> "A brief profile preserves only the most central positions, definitions and distinctions. A deep
> or extended profile preserves qualifications, conceptual dependencies and material examples."

*Mechanism.* Four depth tiers (`brief`/`standard`/`deep`/`extended`) exist in code, but the prompt
distinguishes only two states and never mentions `standard` at all. The tier also arrives as JSON in
`ANALYSIS_PROFILE_JSON`.

*Risk.* The observable difference between tiers may be entirely produced by `max_claims_per_block`
(2/3/5/7), with the word contributing nothing. If so, "deep" is a lie: it buys more claims, not
deeper ones. Evidence for this: at `deep` the qualification rate is only **12.7%** (24/189) even
though this sentence explicitly promises qualifications at that tier.

*Experiment `EX-2a`.* Delete the sentence; hold everything else constant. If output is
indistinguishable, the depth word is decorative and the tier system is a claim-count system.
Metric: qualification rate, mean claim length, claim-type mix. → **run tonight, see §4.**

*Experiment `EX-2b` (not run).* Cross the profile: send `depth: "brief"` with `max_claims=7` and
`depth: "extended"` with `max_claims=2`. Whichever variable moves the output owns the tier.

---

**`EX-3` — the standing-and-instruction split** · `system.md:5` · **mode: coverage**

> "Section and neighbor context may clarify interpretation, but must never supply a claim or
> supporting excerpt."

*Mechanism.* `neighbor_context_blocks` is 0 at brief/standard, 1 at deep, 2 at extended. This clause
is the only thing preventing neighbor text from leaking into excerpts.

*Risk.* Two-sided. If it holds too well, neighbor context is inert and the extra tokens at
`extended` are wasted. If it leaks, excerpts fail the verbatim check against the *target* block and
the block is rejected — the same failure mode as M11, but from a different cause.

*Experiment `EX-3a`.* Run the same corpus at `neighbor_context_blocks` 0 and 2 with everything else
fixed. Metric: (a) does any output change at all, (b) rejection rate, (c) for rejected excerpts,
whether the text is findable in a *neighbor* block. That last check separates "inert" from "leaking".

---

**`EX-4` — the verbatim rule** · `system.md:24` · **mode: both — the main tax on Persian**

> "supporting_excerpt must be copied character-for-character from the target block. Whitespace
> differences are acceptable; punctuation differences are not. Never convert curly quotes to
> straight quotes, never replace dashes or ellipses, **never normalize Persian or Arabic letters,
> digits, or zero-width joiners**."

*Mechanism.* This is the grounding guarantee of the entire product — every claim is auditable
because its excerpt is byte-findable in the source. It is also, per M11/M16, the reason a Persian PDF
costs roughly 35× the retries of an English one: it eventually completes (9 of 10 blocks, in five
passes), but it fails the check on 28% of attempts against 0–0.8% on English.

*Risk.* It is written for clean digital text. On machine-extracted Persian it forbids exactly the
repair the model would otherwise make, and it gives no guidance on what damage to expect.

*Experiment `EX-4a` — name the damage.* Add a clause listing the artifact classes the block may
contain (kashida/tatweel, missing ZWNJ, Arabic-for-Persian letters, line breaks inside words,
scrambled word order) and instruct: copy them as they appear, do not repair, do not skip the claim
because its span is damaged. Hypothesis: naming the artifact class raises the success rate, because
the failure is currently the model *silently normalizing* something it does not know it must
preserve. → **run tonight, see §4.**

*Experiment `EX-4b` — shrink the span.* Add: *"Copy the shortest span that still supports the claim.
One clause is better than one sentence… A long excerpt is not stronger evidence; it is only more to
copy wrongly."* Hypothesis: per-excerpt failure probability scales with length, so shorter spans
survive. → **run tonight, see §4.**

*Experiment `EX-4c` (not run, needs a code change).* Relax the deterministic checker for Persian
only: compare after stripping U+0640 and normalizing yeh/kaf, while storing the model's literal
string. This is the alternative to fixing the prompt, and it belongs in the same decision.

---

**`EX-5` — the bibliography escape hatch** · `system.md:25` · **mode: coverage**

> "If the target block is a list of bibliographic notes, citations or references rather than prose,
> return an empty claims list."

*Mechanism.* A legitimate way to spend zero effort on a block. Also the only sanctioned way to
return nothing.

*Risk.* Over-application. A dense scholarly block with many inline citations resembles the
description. A block silently zeroed this way is indistinguishable from a block that genuinely holds
nothing, and coverage mode would lose it without any warning. Note that empty blocks were **0 of 38**
in the Arendt run, so there is currently no evidence of misfire on English — but Persian academic
papers carry far heavier inline citation.

*Experiment `EX-5a`.* Count empty-claim blocks per corpus and read every one by hand. Metric: false
zero rate. Cheap; needs no new run on English, and should be the first thing checked on any Persian
run that completes.

---

**`EX-6` — `must_not_be_lost` (already changed; re-examined)** · `system.md:30` · **mode: fixed time**

Current text, variant **D**, shipped in 2.1.0:

> "Set must_not_be_lost to true only when the rest of the block cannot be understood without this
> claim: another claim you extract here depends on it, or it states the qualification that reverses
> how the block should be read. **Being important, central, or memorable is not sufficient on its
> own.**"

*History.* Baseline (2.0.0) flagged **40.2%** of claims. Variant C collapsed it to **4.4%**. Variant
D was chosen as the middle path. The earlier round measured D on a 9-block corpus only.

*Why it still needs re-examination.* Three reasons, in order of seriousness:

1. **D has never been validated at scale.** The 9-block result does not tell you what D does across
   38 blocks of continuous argument, where the "another claim you extract here depends on it" clause
   interacts with the 5-claim cap: if the cap already removed the dependent claim, the anchor claim
   stops qualifying. → **run tonight, see §4.**
2. **The flag survives merging by OR** (`claim_reconciler.py:518`), so reconciliation can only ever
   *increase* the rate. Whatever D produces at extraction is a floor, not the final number.
3. **D is a definition of "load-bearing", and the planner uses the flag as an integrity gate.** If D
   under-flags, the gate protects nothing and M6-style boilerplate omission becomes the norm; if it
   over-flags, the gate throws `integrity_breach` on ordinary compression.

*Experiment `EX-6a` — the floor variant.* D plus one sentence: *"A block that states a position or
argument almost always contains at least one such claim; a block that only narrates, lists or
illustrates may contain none."* This is the direct answer to the owner's red-line question
(«آیا نباید یه خط قرمزی هم داشته باشیم؟»): it does not raise the rate globally, it prevents the
specific failure of a *reasoning* block returning zero flags. Metric: number of blocks with zero
flags, split by whether the block argues or narrates. → **run tonight, see §4.**

---

**`EX-7` — the inferential guardrail** · `system.md:27` · **mode: both**

> "A direct claim is explicitly expressed by the block. An inferential claim must **follow closely**
> from the supplied text and be marked inferential."

*Mechanism.* "Closely" is the entire boundary between grounded extraction and paraphrase-drift.

*Observed.* **0 of 189 claims were inferential** (M3). The channel is unused, which means either
(a) the model treats everything as direct, including things that are not, or (b) it genuinely never
needed to infer. (a) is much more likely and much worse: an inferential claim mislabelled `direct`
is a grounding failure that no downstream check can catch, because the verifier only checks the
excerpt, and the excerpt is real.

*Experiment `EX-7a`.* Sample 20 claims labelled `direct` and check by hand whether the excerpt
*states* the claim or merely *supports* it. Metric: mislabel rate. Zero new model calls. This is the
cheapest high-value audit in the register.

*Experiment `EX-7b`.* Add one worked contrast to the prompt (one direct example, one inferential
example from the same sentence). Metric: does the inferential rate leave 0%.

---

**`EX-8` — the dead type suppression** · `system.md:31` · **mode: none**

> "Do not create editorial_explanation claims."

*Mechanism.* `EDITORIAL_EXPLANATION` still exists in `ClaimType` (`domain.py:87`) but is forbidden
here. It is the mirror image of the `objection`/`response` case already removed in 2.1.0: schema
that the prompt cannot produce.

*Risk.* Low, but the rule costs attention and invites the model to reason about a type it must not
use. Note this is *not* the same as the removed types: `editorial_explanation` is deliberately
reserved for the writer stage, so the enum entry is justified — only the extraction-side prohibition
is under question.

*Experiment `EX-8a`.* Remove the line. Metric: does any `editorial_explanation` claim appear. If
none, the line is inert and can go; if some appear, the line is load-bearing and should stay.

---

**`EX-9` — `more_claims_available`** · `system.md:8` and `user.md` · **mode: coverage**

> "If the budget cut off distinct claims the block supports, set that entry's more_claims_available
> to true."

*Mechanism.* This boolean is the trigger for the dense second pass
(`dense_second_pass_block_ids`), which is the mechanism coverage mode relies on to recover claims
the budget dropped.

*Observed.* True on **97% of blocks** (M4). A flag that is almost always true cannot select
anything. Combined with `EX-1`, this means coverage mode currently knows that it lost claims
everywhere and has no way to prioritise recovery.

*Experiment `EX-9a`.* Ask for a count instead of a boolean: *"set more_claims_available to true and
report approximately how many further distinct claims the block supports."* A number is testable
against a second pass; a boolean is not. Metric: distribution of the count, and correlation with
what the second pass actually finds.

---

**`EX-10` — batch budget scoping** · `evidence_extraction_batch/2.1.0/system.md`, batch rules ·
**mode: coverage**

> "The analysis budget applies to each block separately, not to the call as a whole."

*Mechanism.* One call carries up to `_MAX_BATCH_SOURCE_TOKENS = 12_000` of source across several
blocks; each block is entitled to its own `max_claims_per_block`.

*Risk.* Position bias. A model producing 8 blocks × 5 claims in one response tends to shorten later
entries. The prompt asserts the rule but nothing measures it.

*Experiment `EX-10a`.* Run one corpus twice, once per-block (`workers=1`, per-block prompt) and once
batched. Metric: **claims per block as a function of position within the batch**, and mean excerpt
length by position. A downward slope proves the anchor is not holding. This is a clean, decisive
experiment and does not need a prompt change.

---

### 2.2 `concept_cells` 1.0.0

> **§2.2–2.4 now have data — one map.** A concept map was built for this register (M27): *The Human
> Condition*, **15 chapters, 107 cells, 145 edges, 688 implied spoken minutes**. Findings M28–M33 come
> from it, and the per-anchor entries below are annotated with what it showed. It is **one map of one
> book**, so treat every number as a first observation, not a rate.
>
> **Getting it required working around a crash.** `concept-map --chapters` fails unconditionally
> ([`concept_map_pipeline.py:182-196`](../../src/thesisound/services/concept_map_pipeline.py)):
> chapter selection filters `partitions` to the requested chapters but still passes the **whole**
> document as `blocks`, and `_resolve_partitions`
> ([`document_mapper.py:397`](../../src/thesisound/services/document_mapper.py)) asserts the two must
> match. Eight attempts, eight identical `AssertionError: Chapter partitions changed block order or
> coverage`. The whole-book path does not take that branch and succeeded on retry 6.
>
> That is an engineering defect, not an anchor, and **no code was changed to record it**. It matters
> here because it means the only affordable way to exercise the concept map on a real book — a chapter
> or two at a time — does not run, which is why this section had no data until now.

---

**`CC-1` — the granularity anchor** · `system.md:4, 11, 12` · **mode: both**

> "…that a lesson can explain in **3 to 15 minutes** without unstated context"
> "…would need more than about **15 minutes** to explain, or carries more than about three separable ideas"
> "Merge blocks into one cell when they are meaningless apart or need less than about **3 minutes** together."

*Mechanism.* The cell is the unit of the whole coverage-mode pipeline: cells drive selection, part
packing and the segment skeleton. Two numbers in prose decide how many cells a book has, and
therefore how long a full-coverage course runs and what it costs.

*Measured (M32).* **The anchor holds tightly.** `estimated_minutes` came back mean 6.4, median 5.0,
with only **2 of 107 cells (1.9%) outside the 3–15 window** and a maximum of exactly 15.0. Set against
`DM-1`'s abstract "conservatively" failing at 85%, this is the clearest evidence in the register that
**a concrete numeric range is obeyed and an abstract adjective is not.**

*Remaining tension.* `_OVERSIZE_CELL_MINUTES = 30.0` tolerates cells twice the stated maximum — dead
tolerance, since nothing reached even 16.

*Experiment `CC-1a`.* Rebuild the same book at 2–8 and 5–20 minutes. Metric: cell count, total implied
minutes (688 at 3–15), and — the real question — whether the *concepts* change or only their packaging.
Compare the `label_source` sets.

---

**`CC-2` — the forced tier distribution** · `system.md:21` · **mode: fixed time**

> "Distribute realistically: **in a chapter with six or more cells, tier 1 is roughly 15–45 percent
> and tier 3 at least 10 percent.** Do not put everything in one tier."

*Mechanism.* Tier is what compression selects on. This sentence tells the model the answer before it
has read the chapter, and it is mirrored exactly in code (`_TIER1_SHARE_MIN/MAX`, `_TIER3_SHARE_MIN`),
so prompt and checker agree — which means a genuinely lopsided chapter cannot be reported as lopsided
by either.

*Measured (M31).* **Tier 1 landed at 31.8% — mid-window.** Tier 3 came in at **8.4%, under the stated
10% floor**, and 15 cells were promoted by *code* rather than by the model. So the window the prompt
names is the window the output occupies, while the floor it names is missed. That is consistent with
the anchor manufacturing the distribution rather than measuring one, but a single map cannot separate
"manufactured" from "the book really is like that".

*Experiment `CC-2a`.* Rebuild with the distribution sentence removed, keeping the tier definitions.
Run on this book and on an illustrative one. Metric: the natural tier-1 share of each. If they differ
widely without the sentence and both converge near 30% with it, the anchor is fabricating the
distribution. **Still the second-highest-value experiment in the register** after `EX-4`.

---

**`CC-3` — the never-split list vs. the `example` kind** · `system.md:13, 15` · **mode: coverage**

> "Never split off as their own cell: **worked examples**, footnotes, exercises, block quotations of
> other authors, restatements, transitional paragraphs."

versus, two lines later:

> "Kinds: definition · distinction · argument · position · objection · response · **example (a
> canonical case the source itself builds on)** · thread"

*Measured (M30).* **The prohibition wins, decisively.** Of 107 cells: `example` **1 (0.9%)**,
`objection` 2, `response` 1 — against `argument` at **54.2%**. Arendt's canonical cases are being
absorbed into their parents and losing their own claim budget, and the kind list is very nearly dead
schema. This mirrors `document_map`'s function field, which is ~80% `argument` for the same reason
(`DM-4`).

*Experiment `CC-3a` — now a fix, not a question.* Narrow the prohibition to *"a worked example that
only illustrates a point already made"*, leaving canonical cases eligible. Metric: the `example` share,
and whether any cell that was previously absorbed appears on its own.

---

**`CC-4` — the label self-check** · `system.md:23` · **mode: neither (quality only)**

> "Self-check for every label: **would a reader who sees only this label, without the book, know
> which concept it names?** If not, rewrite it."

*Measured.* **This one works.** 107 of 107 cells carry a `label_source`, there are **no duplicate
labels**, and a scan for structural labels ("مقدمه", "فصل", "بخش") returned only one arguable case.
Alongside `PS-4` (the cliché blacklist, M16), this is the second self-check-style anchor found to be
behaving.

*Experiment `CC-4a`.* Remove it and re-measure the same three quantities. This is the cleanest available
test of whether self-verification instructions do anything in this system — a result that would
generalise to every other prompt.

---

**`CC-5` — budget softness, and what nobody filters** · `system.md:27` · **mode: coverage**

> "Respect BUDGET as a **soft** target for the whole chapter."

Contrast `concept_cells_consolidate`: "Reach **at most** the target count." One stage is told the
budget is soft, the next that it is hard — which makes `CO-1` below inevitable.

*Measured, and worse than the softness question (M28).* **22 of 107 cells (20.6%) were built from
material that is not the book's argument**: 12 from the endnotes chapter, 6 from the index, 4 from the
copyright and title pages. A filter for exactly this exists — `eligible_blocks`
([`analysis_profile.py:168`](../../src/thesisound/services/analysis_profile.py)) drops front matter and
note-like blocks — but it is called only on the **extraction** path. The concept-map path never calls
it, and the chapter titles that would have revealed the problem to a human are EPUB filenames
(`9780226924571 16 not`, `… 17 ind`, M29).

In coverage mode this means the system would plan lessons about the index. **No prompt wording fixes
this**; it is a missing filter call, and it belongs on the same list as M26.


### 2.3 `concept_cells_consolidate` 1.0.0

---

**`CO-1` — the contradiction at the heart of consolidation** · `system.md` · **mode: coverage**

> "**keep every distinct concept.** Never let a section lose its last cell."

> "**Reach at most the target count**; if fewer already cover everything, do not invent reasons to
> keep more."

*Mechanism.* When the number of genuinely distinct concepts exceeds the target, these two rules
cannot both hold. The prompt does not say which wins, and the model resolves it silently — most
likely by declaring near-identical two concepts that are not.

*Risk.* This is the owner's red-line question, one layer up from claims: *"even if there are ten
essential things in one block, must we still delete some?"* At the cell layer, the current answer is
"yes, and without saying so."

*Experiment `CO-1a`.* Feed a chapter with N distinct cells and set the target to N/2. Read every
`merge` and `remove` action's stated reason. Metric: how many reasons are honest merges versus
"duplicate" labels applied to non-duplicates. Then re-run with an explicit precedence:
*"If you cannot reach the target without merging concepts that are genuinely distinct, stop at the
lowest count you can honestly reach and say so."* Metric: does the model use the escape hatch, and
does the final count exceed the target.

---

**`CO-2` — the last-cell floor** · **mode: coverage**

> "Never let a section lose its last cell."

The only structural floor anywhere in the concept map. Worth naming because it is the *shape* the
answer to `CO-1` should take: a floor stated in terms of source structure, not a target stated in
terms of output size.

---

### 2.4 `concept_edges` 1.0.0

---

**`CE-1` — the edge cap** · `system.md:16` · **mode: coverage**

> "Cap: at most **min(2 × N_cells, 60)** edges within a chapter; for a chapter pair, **usually 2–10**
> and never more than the supplied cap. Prefer quality over quantity."

*Mechanism.* Edges drive prerequisite closure, which decides what coverage mode must include even
when the owner did not ask for it. An under-populated graph means prerequisites are missed and
lessons assume unexplained concepts.

*Risk.* "Usually 2–10" is an anchor in the strict statistical sense: it will produce 2–10 regardless
of the two chapters' real relationship.

*Experiment `CE-1a`.* Run on two chapters known to be tightly coupled and two known to be
independent. Metric: edge count in each. If both land in 2–10, the number is the anchor, not the
source.

---

**`CE-2` — weight calibration, and the clearest anchor lesson in the register** · `system.md:19` ·
**mode: coverage**

> "weight is how strong the relation is, 0–1: **a strong prerequisite ≥ 0.8; a weak related ≤ 0.4.**"

*Measured (M33).* One sentence, two clauses, opposite outcomes:

| clause | compliance |
| --- | --- |
| "a strong prerequisite **≥ 0.8**" | **37 of 37** — mean 0.87, min 0.80 |
| "a weak related **≤ 0.4**" | **4 of 41** — mean 0.69, max 0.90 |

**The lower bound binds perfectly; the conditional upper bound is ignored.** The likely reason is that
the model reads a weight as a quality score and pushes it up, and the ceiling only applies to relations
it has already decided are "weak" — a category it rarely assigns itself to. This generalises: state a
bound as an unconditional property of the *edge type*, not as a property of a subjective adjective.

*Also settled, negatively.* `part_packer.py` cuts `prerequisite`/`depends_on` at 0.35 while the prompt
calls ≤ 0.4 weak. **0 of 66 such edges fall in that band**, so the feared disagreement never fires. One
concern closed at no cost.

*Experiment `CE-2a`.* Rewrite as *"prerequisite edges take 0.8–1.0; related edges take 0.1–0.4;
depends_on and extends take 0.5–0.7"* — bounds attached to types, not adjectives. Metric: the same
per-type histogram.

---

### 2.5 `document_map` 1.1.0 and `document_map_merge` 1.1.0

---

**`DM-1` — "conservatively", and the prompt it is missing from** · `document_map_merge/1.1.0:9` ·
**mode: coverage — highest measured failure**

> "Mark globally required sections **conservatively**."

Measured: **85.0% of 333 real sections are marked required** (M1), producing a degenerate ranking
where 88% of sections share one score (M2). The code comment in `analysis_profile.py` records that
this once produced 40 required sections of 47 and 55,913 tokens against an 18,000-token budget. That
was treated as an incident; the data shows it is the normal case.

**But the interesting part is where the sentence lives.** `document_map/1.1.0` — the prompt that
produces most maps — **never mentions `required_for_global_understanding` at all.** The only
instruction about it is in `document_map_merge`, and merge runs only on sources large enough to be
partitioned. Splitting the same 333 sections by whether the model was ever told anything:

| | sections | marked required |
| --- | --- | --- |
| **10 maps, non-partitioned — no instruction exists anywhere** | 105 | **94.3%** |
| **5 maps, partitioned — merge said "conservatively"** | 228 | **80.7%** |

So "conservatively" **is** doing something — about 14 points' worth — and it is still nowhere near
enough. And two thirds of real maps never see it, because the field is set by a prompt that does not
know the field exists. This is the same shape as `EX-12`: **a schema field the model must fill and
the prompt never defines**, with the difference that here a definition exists in a neighbouring
prompt and simply never reaches the common case.

*Experiment `DM-1a`.* Two changes, testable separately:
1. **Put a criterion in `document_map` itself** — *"Mark a section required_for_global_understanding
   only when a listener who skipped it would misunderstand a later section."*
2. **Replace the adjective with a quota** in both prompts — *"In a map of N sections expect roughly
   N/5 to qualify; if you mark more than a third, you are using the wrong criterion."*

Metric: required share, on maps whose baselines are known (98%, 100%, 100%, 81%). Because the current
values sit at or near 100%, this is one of the few experiments where a single run is informative — a
ceiling is not a noisy number.

*Why this is near the top of the queue.* It is the only anchor whose failure is quantified end to
end: missing instruction → 94% flag rate → degenerate score → arbitrary block selection → coverage
mode reads the wrong blocks.

---

**`DM-2` — total partition** · `document_map/1.1.0:7` · **mode: coverage**

> "Every non-front-matter block must belong to **exactly one** section. Never list the same block_id
> in two sections."

*Risk.* Forces an arbitrary home for genuinely ambiguous boundary blocks, and — combined with the
absence of any size anchor — is likely what produces the 1-block-per-section maps of M10.

*Experiment `DM-2a`.* Add a size anchor only: *"A section normally spans 2–6 blocks. A one-block
section is correct only when that block is genuinely self-contained."* Metric: sections per block,
and whether `key_concepts` become more distinctive.

---

**`DM-3` — sequence bias** · `document_map/1.1.0:9` · **mode: coverage**

> "**Preserve the author's sequence** unless the document itself clearly signals another dependency."

Measured at M9: 76.8% of dependency edges are just "the previous section". `DM-3a`: remove the
clause and re-measure the trivial share. If it stays near 77%, the bias is the model's, not the
prompt's, and the fix belongs elsewhere.

---

**`DM-4` — the function vocabulary** · `document_map/1.1.0:10` · **mode: coverage**

> "Distinguish definitions, arguments, examples, objections, responses, transitions, and
> conclusions."

*Observed.* `argument` takes 37/41, 68/79, 53/68, 31/47 of real sections — roughly 80%. Since
`_FUNCTION_WEIGHT` ranks blocks by exactly this field, an 80%-`argument` map contributes almost no
ranking signal (this is the second half of M2's story). `DM-4a`: give one distinguishing question
per function value and re-measure the distribution.

---

### 2.6 `claim_reconciliation` 1.1.0 and `claim_reconciliation_merge` 1.1.0

---

**`CR-1` — the merge threshold** · `system.md:6` · **mode: both**

> "Merge evidence items only when they express **materially the same proposition** with compatible
> attribution and qualifications."

The single word doing the work is "materially". Over-merging destroys claims that fixed-time mode
would have selected differently; under-merging inflates the ledger and makes every downstream budget
tighter. `CR-1a`: measure the merge rate (input evidence count vs output claim count) across
existing runs — free — then vary the wording between "the same proposition", "materially the same
proposition", and "the same proposition, where a listener would object to hearing both".

---

**`CR-2` — the type wall** · `system.md:10` · **mode: fixed time**

> "**Never merge claims of different claim_type.** A definition never merges with a position; an
> example never merges with the concept it illustrates; criticism never merges with counterargument."

*Risk.* An absolute rule guarding against a real failure, but it means the *same* proposition stated
in two blocks and typed differently by the extractor survives twice, consuming two claim slots.
Given `distinction` was 50 of 189 claims in the Arendt run — 26% — type inflation is plausible.
`CR-2a`: find near-duplicate claim pairs that differ only in `claim_type` and count them.

---

**`CR-3` — OR-propagation of the flag** · `system.md:11` · **mode: fixed time**

> "When merging, keep the union of the members' qualifications and **set must_not_be_lost to true if
> any member has it**."

Mechanically monotone: reconciliation can only raise the flag rate. This is why `EX-6` must be
measured *after* reconciliation, not only at extraction — a point the earlier round missed.
`CR-3a`: compute the rate before and after reconciliation on the same run.

---

### 2.7 `coverage_audit` 1.0.0

---

**`CA-1` — the unanchored minute estimate** · `system.md:10` · **mode: both**

> "Estimate how many minutes of non-repetitive, evidence-grounded audio the corpus can support."

*Mechanism.* This number (`max_supported_minutes`) gates the entire pipeline through
`can_plan_episode`. There is no rubric, no claims-per-minute rate, no worked example — the model
free-hands a number that decides whether the run proceeds.

*Risk.* Unmeasured variance. In every report on disk the estimate happens to equal the *requested*
duration exactly (20 → 20, 10 → 10), which is the signature of the model anchoring on the request
rather than assessing the corpus.

*Experiment `CA-1a`.* Run `audit-coverage` **five times on the identical corpus** and record
`max_supported_minutes` each time. Five calls, no prompt change, completely decisive. If the spread
is wide, the gate is noise; if it is tight but always equals the request, the gate is a mirror.
Then add an anchor — *"a grounded minute needs roughly 3–4 distinct claims; state the arithmetic"* —
and repeat.

---

**`CA-2` — the `continue` criterion** · `system.md:11` · **mode: fixed time**

> "Recommend continue only when the requested duration can be supported **without padding**."

`CA-2a`: run the same audit against briefs requesting 10, 30, and 60 minutes on a corpus that
genuinely supports ~20. Metric: at what point does it stop saying `continue`. If it never does, the
gate is inert.

---

### 2.8 `episode_plan` 1.3.0

---

**`EP-1` — the asymmetric budget** · `system.md:14` · **mode: fixed time**

> "total segment minutes must not exceed part_target_minutes times **1.25**. **There is no lower
> bound; do not pad.**"

*Mechanism.* The only length control on the plan. It is a ceiling with an explicit statement that
there is no floor.

*Observed.* Plans land on the target exactly (10.0, 20.0, 10.0) — so the model treats
`part_target_minutes` as the target, and the "no lower bound" licence is unused at the plan layer.
But the *script* then comes in at 0.71–0.88 of that (M7), so the shortfall happens downstream, and
this anchor is the reason nothing catches it: no stage has a floor.

*Experiment `EP-1a`.* Add a floor: *"total segment minutes must be at least 0.9 × part_target_minutes
unless the corpus genuinely cannot support it, in which case say so in listener_outcome."* Metric:
plan minutes, and — the real test — whether the *script* moves toward target.

---

**`EP-2` — the must-not-be-lost escape hatch** · `system.md:10` · **mode: fixed time**

> "Every claim whose must_not_be_lost is true must appear in a segment. If it **truly** cannot be
> placed, list it in deliberately_omitted_claims with a concrete reason; never drop it silently."

*Observed.* M6: 59 of 64 omission reasons are one boilerplate string. The word "truly" and the phrase
"concrete reason" are both defeated by a template.

*Experiment `EP-2a`.* Require the reason to name the claim: *"the reason must name what the claim
says and why this part can be understood without it; a reason that would fit any other claim is not
a reason."* Metric: **unique-reason ratio** (currently 5/64 ≈ 8%). Pre-registered, trivially
measurable, no code change. → high value, low cost.

---

**`EP-3` — stale objection/response preference** · `system.md:13` · **mode: none**

> "Definitions, distinctions, examples, **objections and responses** are claims like any other…
> Prefer placing an objection and its response in the same segment."

`ClaimType.OBJECTION` and `RESPONSE` were removed in 2.1.0. No claim can carry those types any more,
so this preference can never fire. It is dead text that costs attention. (Note: `objection`/
`response` remain valid `BlockType`/`DocumentMapSection.function` and `ConceptCellKind` values — the
three vocabularies are separate, and only the claim one changed.)

*Experiment `EP-3a`.* Remove the sentence. Metric: none needed beyond confirming no regression; this
is a correctness cleanup, not an experiment. Listed here so it is not forgotten.

---

**`EP-4` — known-concept suppression** · `system.md:18` · **mode: both**

> "KNOWN_CONCEPTS lists concepts the listener already knows. Give such a concept **at most one
> reminder sentence** inside a segment's purpose; never a segment of its own."

Mirrored in the writer prompt. This is how the owner avoids re-hearing what they know, so it
directly serves the fixed-time mode. `EP-4a`: supply a `known_concepts` list containing a concept
the source treats as central, and check whether the plan degrades gracefully or drops the
dependent claims with it.

---

### 2.9 `persian_script_segment` 1.3.0

---

**`PS-1` — the attention-budget problem** · whole prompt · **mode: both**

This prompt is roughly **120 lines of tone and dialogue craft** against roughly **10 lines of
grounding contract**. The grounding rules come first, but they are outnumbered more than ten to one.

*Risk.* Not that the tone guidance is wrong — it is unusually good — but that the ratio is itself an
anchor: it tells the model what this task is mostly about. M5 (verifier always passes) means there
is currently **no independent evidence** that grounding survives the tone section.

*Experiment `PS-1a`.* Produce two scripts from the identical plan: one with the full prompt, one with
the tone section cut to ~15 lines of the same advice. Metrics: (a) deterministic `script_checks`
issues, (b) hand-audit of 20 turns for specifics not in the cited excerpts, (c) a blind listen for
whether the short-prompt version is noticeably worse to hear. If grounding improves and listenability
does not collapse, the ratio is wrong. **This is the highest-value experiment in the writer stage**,
and it cannot be run until `PS-4` gives it a trustworthy measuring instrument.

---

**`PS-2` — the length anchor** · `user.md` · **mode: fixed time**

> "Aim for the target word count **within roughly 15 percent**."

*Observed.* M7: actual/target ratios of 0.71, 0.86, 0.88 — one clear violation and two at the edge,
all in the same direction. Systematic under-production, never over.

*Experiment `PS-2a`.* Make the bound explicit and one-sided: *"TARGET_WORD_COUNT is a floor as much
as a ceiling. A segment more than 10 percent short is wrong even if it is complete."* Metric: the
same ratio. Also worth testing: state the count in *sentences* as well as words, since Persian word
counting with `.split()` under-counts compounds — the harness and the model may not be counting the
same thing.

---

**`PS-3` — the sanctioned hallucination channel** · grounding contract · **mode: both**

> "If an analogy is **genuinely needed** to make an idea followable, put it in a turn marked
> editorial_only and keep that turn free of any factual statement about the subject."

*Mechanism.* The only place the writer may invent. "Genuinely needed" is the entire limit, and the
verifier is told to accept an analogy in an editorial turn "only if it makes no factual statement" —
a judgement the same weak verifier makes.

*Experiment `PS-3a`.* Count editorial turns containing an analogy, and hand-check each for a smuggled
factual claim. Free on existing scripts. M8 already shows one script at 31.7% editorial words, so
there is material to check.

---

**`PS-4` — the cliché blacklist** · tone section · **mode: neither**

> "Do not overuse phrases like: «بیایید کمی عمیق‌تر بشیم» / «سؤال خیلی خوبیه» / «دقیقاً همینطوره» …"

*Risk.* Blacklists reliably produce near-misses («یه کم عمیق‌تر بشیم»). `PS-4a`: count exact
blacklist hits and near-variants in existing scripts. If exact hits are 0 and variants are many, the
blacklist is teaching the register rather than removing it, and a positive instruction would work
better.

---

### 2.10 `script_verifier` 1.2.0 — the weakest anchor in the system

---

**`SV-1` — the role word** · `system.md:1` · **mode: both**

> "You are an **adversarial** verifier for a Persian evidence-grounded lesson script."

---

**`SV-2` — the unanchored 0–1 scores** · `system.md:13` · **mode: both**

> "Score five quality dimensions from 0 to 1: evidence_fidelity, qualification_preservation,
> stance_and_disagreement, terminology_consistency, listenability."

---

**`SV-3` — the absolute pass bar** · `system.md` · **mode: both**

> "A pass requires no issues and an unsupported claim ratio of zero."

*Observed (M5).* Across every verification on disk: `pass`, zero issues, ratio 0.0, and **1.0 on all
five dimensions, every time**, with empty `actionable_feedback`. Five dimensions × three runs = 15
scores, all exactly 1.0.

That is not a verifier. A genuinely adversarial reader of an LLM-written Persian script built from
claim excerpts will always find *something* — a hedge dropped, a term drifting, a turn that
overstates. Perfect scores mean the instrument reads zero regardless of input.

*Why this matters most.* Every other grounding anchor in this register — `EX-4`, `EX-7`, `PS-1`,
`PS-3` — is supposed to be *caught* by this stage when it fails. If the verifier cannot fail
anything, none of those anchors have a safety net, and no experiment on them can be scored
automatically. **Fixing the verifier is a precondition for cheaply testing the rest.**

*Experiment `SV-1a` — is it the instrument or the scripts?* Take a passing script and inject three
known defects by hand: a number not in any excerpt, a hedge removed from a `contested` claim, and an
invented comparison in a substantive turn. Re-run the verifier unchanged. Metric: how many of the
three it catches. Zero or one confirms the instrument is broken and no further prompt work should be
scored by it.

*Experiment `SV-2a` — anchor the scale.* Give each dimension two worked anchors, e.g.
*"evidence_fidelity 1.0 means every substantive turn is entailed by its cited excerpts; 0.7 means one
turn adds a specific not in the excerpts; 0.4 means a turn's main assertion is unsupported."* Metric:
does any score leave 1.0 on the same scripts.

*Experiment `SV-3a` — force a finding.* Add: *"Report the single weakest turn in the script and why,
even when the verdict is pass."* This converts an all-or-nothing gate into a continuous signal, which
is what every other experiment here needs. Metric: whether the named turn is plausibly the weakest on
hand-review.

---

### 2.11 Remaining stages

**`GL-1` — glossary scope** · `glossary/1.1.0` · *"Do not add terms that will not be spoken."*
Under-generation risk: the glossary is built before the script exists, so "will be spoken" is a
prediction. `GL-1a`: compare glossary terms against the terms the finished script actually uses.

**`GL-2` — translation policy** · *"**Prefer established Persian translations** when context supports
them."* Decides whether the listener hears familiar or literal Persian for terms like *the human
condition*, *world alienation*. `GL-2a`: hand-review 20 terms against a Persian Arendt translation.

**`RB-1` — the narrowing default** · `research_brief/1.0.0` · *"**Narrow scope** rather than pretending
that a broad subject can be covered completely."* This actively fights coverage mode. In
`source_coverage` the brief is derived rather than modelled, so the conflict is currently dormant —
but any path that builds a brief from owner input will narrow by default when the owner wanted
breadth. `RB-1a`: build a brief from a deliberately broad topic and check whether the narrowing is
stated or silent.

**`RB-2` — the conservative-interpretation clause** · *"choose a conservative working interpretation
**only when it does not materially change the project**"* — an unverifiable self-assessment.

**`WS-1` — access honesty** · `web_source_capture/1.0.0` · *"Mark access as full_text **only when the
complete declared** article/page/document scope was available."* The one thing preventing an
abstract from being cited as a paper. `WS-1a`: capture three known-paywalled URLs and check the
reported access level.

**`CM-1` — merge conservatism** · `document_map_merge` · *"Prefer dependencies and threads that
**cross a partition boundary**"* — sound in principle; unmeasured, and only reachable on sources
large enough to partition.

---

## 3. Paired numeric knobs in code

Listed for completeness because several anchors above are only half a rule — the prose in the
prompt and the number in the code together decide the behaviour. **No code was changed.**

### 3.1 Directly paired with an anchor

| Constant | Value | Location | Paired anchor | Note |
| --- | --- | --- | --- | --- |
| `max_claims` per tier | 2 / 3 / 5 / 7 | `analysis_profile.py:84-102` | `EX-1`, `EX-2` | brief/standard/deep/extended. Binds on 97% of blocks. |
| `AnalysisProfile.max_claims_per_block` | `ge=1, le=12` | `source_analysis.py:65` | `EX-1` | schema ceiling |
| `_SECOND_PASS_MAX_CLAIMS_PER_BLOCK` | 12 | `analysis_profile.py:67` | `EX-9` | second pass pushes to the ceiling |
| `neighbor_context_blocks` | 0 / 0 / 1 / 2 | `analysis_profile.py:84-102` | `EX-3` | schema cap `le=2` |
| `_MAX_BATCH_SOURCE_TOKENS` | 12 000 | `evidence_extractor.py:49` | `EX-10` | batch size driver |
| `_TIER1_SHARE_MIN` / `_MAX` | 0.15 / 0.45 | `concept_map_builder.py:274-275` | `CC-2` | **same numbers as the prompt sentence** |
| `_TIER3_SHARE_MIN` | 0.10 | `concept_map_builder.py:276` | `CC-2` | idem |
| `_TIER_DISTRIBUTION_MIN_CELLS` | 6 | `concept_map_builder.py:273` | `CC-2` | the "six or more cells" clause |
| `_OVERSIZE_CELL_MINUTES` | 30.0 | `concept_map_builder.py:301` | `CC-1` | tolerates 2× the prompt's 15-minute max |
| `_INTRA_EDGE_CAP_PER_CELL` / `_MAX` | 2 / 60 | `concept_map_builder.py:292-293` | `CE-1` | the `min(2 × N, 60)` in the prompt |
| `_DEFAULT_CROSS_CHAPTER_CAP` | 10 | `concept_map_builder.py:294` | `CE-1` | the "usually 2–10" |
| `prerequisite` / `depends_on` weight floor | 0.35 | `part_packer.py:24-25` | `CE-2` | prompt says weak ≤ 0.4 — the two disagree in 0.35–0.4 |
| part budget multiplier | 1.25 | `episode_planner.py:172` | `EP-1` | ceiling only; no floor exists anywhere |
| `_EDITORIAL_RATIO_MAX` | 0.25 | `script_checks.py:62` | `PS-3` | **non-blocking** (`severity="low"`, MVP policy) |
| `episode_budget_words_per_minute` | 130 | `config.py:162` | `PS-2` | target-word-count arithmetic |
| `tts_words_per_minute` | 135 | `config.py:154` | `PS-2` | *different* number for synthesis timing |
| `_DURATION_FLOOR` | 0.8 | `script_grounding_remediation.py:28` | `PS-2` | the only floor in the system; remediation-only |

### 3.2 Unpaired but consequential

| Constant | Value | Location | Why it matters |
| --- | --- | --- | --- |
| `_FUNCTION_WEIGHT` | definition 80 · argument 75 · conclusion 70 · response 55 · objection 50 · example 30 · other 25 · transition 10 | `analysis_profile.py:51-60` | the block ranking; made degenerate by `DM-1` (M2) |
| required-section bonus | **+100** | `analysis_profile.py:549` | larger than the entire function-weight range |
| `_REQUIRED_SEED_BUDGET_SHARE` | 0.60 | `analysis_profile.py:26` | the guard added *because* `DM-1` failed once |
| `_SELECTION_HEADROOM` | 0.10 | `analysis_profile.py:19` | |
| `block_coverage_target` | 0.35 / 0.60 / 0.85 / 1.0 | `analysis_profile.py:84-102` | what fraction of the source is read at all |
| `evidence_input_token_budget` | `max(12k, min(180k, minutes × 1800))` | `analysis_profile.py:104` | |
| `BlockBuilder` | target 1200 · max 1800 · min 80 tokens | `block_builder.py:42` | the semantic block itself |
| `_JACCARD_DUPLICATE` | 0.85 | `concept_map_builder.py:272` | cell dedup |
| `_LABEL_BLOCK_OVERLAP_MIN` | 0.15 | `concept_map_builder.py:298` | pairs with `CC-4` |
| `_MIN_CHAPTER_BUDGET` / `_MAX` | 6 / 40 | `concept_map_builder.py:268-269` | cells per chapter |
| `_BUDGET_PER_SECTION` | 1.5 | `concept_map_builder.py:270` | |
| `_MIN_PLANNED_TOKEN_RETENTION` | 0.85 | `source_analysis_service.py:58` | |
| `thin_extraction` threshold | 0.35 | not yet read by any gate | measured at 0.30 mean on Arendt; 28/38 blocks below it — **needs calibration per depth tier before it gates anything** |
| `_SPEAKER_SKEW_MAX` | 2.0 | `script_checks.py:63` | observed A/B word ratios: 1.98, 1.80, 2.13 — all at or over the line |
| `_BREAKER_CONSECUTIVE_FAILURES` | 3 | `evidence_extractor.py:46` | opens the circuit breaker; fires on proxy flakiness |

---

## 4. Live experiment results — 2026-08-20

Protocol in §5. Raw snapshots are under the session scratchpad (`nx-*`, `base-arendt38`, `exp-*`).

### 4.1 `EX-6` — variant D re-validated at scale (Arendt-38)

The headline result of the night, and the reason D should **not** ship unchanged.

| | baseline (pre-D) | **D (shipped in 2.1.0)** |
| --- | --- | --- |
| blocks extracted | 38 / 38 | 38 / 38 |
| claims | 189 | 190 |
| claims at the cap | 37 | 38 |
| `must_not_be_lost` | 76 = **40.2%** | 33 = **17.4%** |
| **blocks with zero flagged claims** | **0** | **10** |
| qualifications non-empty | 12.7% | **21.1%** |
| `inferential` | 0.0% | 0.0% |
| mean `excerpt_char_coverage` | 0.302 | 0.293 |

**What D did well.** It more than halved the flag rate (40.2% → 17.4%) — the intended effect — and,
unexpectedly, **raised the qualification rate from 12.7% to 21.1%**. That is a real side benefit:
D's definition of load-bearing explicitly mentions "the qualification that reverses how the block
should be read", and naming qualifications in the flag rule appears to have made the model attend to
them everywhere. This is worth remembering as a technique: *an anchor can teach a concept it does not
directly govern.*

**What D did badly — the owner's red line, confirmed.** D leaves **10 of 38 blocks with no flagged
claim at all**, where the baseline left none. The question is whether those are harmless narrative
blocks. They are not:

| zero-flag blocks by document-map function | count |
| --- | --- |
| `argument` | **9** |
| `definition` | **1** |
| narrative / list / example | **0** |

Every unprotected block is a block the mapper classified as arguing or defining. Two of them:

- **block 00001** (`definition`, baseline flagged 2) contains the definition of *bios politikos* and
  the polis/household distinction — load-bearing content of the chapter. Zero flags.
- **block 00002** (`argument`, baseline flagged 3) contains the *zōon logon ekhon* → *animal
  rationale* mistranslation argument, one of the chapter's theses. Zero flags.

**Reading.** D is a good rule with a missing floor. It correctly stops flagging things for being
merely memorable, but its test — "another claim you extract here depends on it" — is defeated by the
claim cap: on a block where the budget already removed the dependent claim, nothing qualifies. That
is precisely `EX-6a`. **Recommendation: keep D, add the floor sentence, re-measure.**

> **How much of this survives the noise control (§4.5).** The control was run after this section and
> forces two qualifications:
>
> - **The direction is solid.** Baseline produced **0 of 38** zero-flag blocks; D produced **10**.
>   Zero is not a noisy number, so "D creates unprotected blocks where the baseline created none" holds.
> - **The count is not.** On Arendt-9, three identical D runs gave 2, 2 and **5** zero-flag blocks of
>   9 (22%, 22%, 56%). D's 10 of 38 (26%) sits inside that spread, so **treat "10" as "somewhere
>   around a quarter of blocks", not as a measurement.**
> - **The "9 argument, 1 definition, 0 narrative" split is the part worth trusting**, because it is a
>   *composition* result rather than a count: whichever blocks go unflagged on a given run, they are
>   not the narrative ones. That is the finding that answers the owner's red-line question.
>
> A three-run control of D on Arendt-38 would settle the count. It is the single cheapest way to firm
> up the headline result and should be run before the prompt is changed again.

### 4.2 `EX-4` — the Persian verbatim anchor (FA-11)

The right way to measure this is **per model attempt, by error type**, not per block: block-level
success mixes the anchor's failures with the local proxy's 406 noise, and an early reading that did
so was misleading. Classifying every recorded attempt:

| corpus | attempts | **`ExcerptNotFoundError`** | provider/proxy errors | success |
| --- | --- | --- | --- | --- |
| **FA-11 (Persian)** | 161 | **45 = 28.0%** | 65.8% | 5.0% |
| Arendt-38 (English) | 393 | **3 = 0.8%** | 65.6% + 12.7% rate-limit | 19.8% |
| Arendt-9 (English) | 173 | **0 = 0.0%** | 56.6% | 42.2% |

**The verbatim anchor fails on 28% of Persian attempts against 0–0.8% on English — roughly a 35×
difference on the same prompt, same model, same settings.** The proxy noise is high everywhere and
is an environment problem, not an anchor problem; it is the `ExcerptNotFoundError` column that
belongs to `EX-4`.

Cost of that column: **380,000 output tokens** burned on the Persian project, against 305,000 for
the four-times-larger English one. Retries do eventually recover blocks (the Persian run reached
6 of 10 by pass 3 and the rest were blocked by proxy 406s, not by the anchor), so the anchor is not
an absolute wall — it is a very expensive toll, and one that would fall on every Persian source.

See §1.1 for the mechanism (kashida, stripped ZWNJ, mixed orthography) and M11/M12 for the source
measurements.

**This remains the finding with the largest product consequence in the document.** Every other anchor
here tunes quality; this one decides what a Persian source costs, and today it costs about 35× more
retries than an English one.

### 4.3 `EX-7` — direct/inferential hand-audit (16 claims, Arendt-38)

`support_kind` takes exactly **one distinct value across all 189 claims: `direct`**. Hand-reading a
random 16:

| verdict | count | example |
| --- | --- | --- |
| correctly `direct` | 11 | claim restates the excerpt |
| **should be `inferential`** | **2** | excerpt: *"What consumer goods are for the life of man, use objects are for his world."* → claim adds "consumed to sustain human bodily life" and "provide the durable matrix for human worldliness", neither in the excerpt |
| **half unsupported** | (of those 2) | excerpt explains only *one* side of a contrast; the claim asserts both sides |
| **anaphora-dependent** | **3** | excerpt begins "This, of course, has not eliminated…" or "Without it a public realm could no more exist" — the claim silently resolves the pronoun from text *outside* the excerpt |

So roughly **12% clear mislabels and 31% including the anaphora cases**. `EX-7a` is confirmed: the
`inferential` channel is not unused because inference never happens, it is unused because inference
is labelled `direct`.

The anaphora cases are a failure mode **no current anchor covers**, and they get their own entry:

---

**`EX-11` — excerpt self-containment** *(new)* · **mode: both**

The verbatim rule guarantees an excerpt is *findable in the block*. It does not guarantee the
excerpt *stands on its own*. Three of sixteen sampled excerpts open with an unresolved pronoun, so a
reader auditing the claim against its excerpt alone cannot verify it — which is the entire promise of
the grounding contract.

*Experiment `EX-11a`.* Add: *"The excerpt must be readable on its own. If the sentence that supports
the claim opens with a pronoun or a reference to something earlier, extend the excerpt backwards to
include what it refers to."* Metric: share of excerpts opening with an unresolved pronoun (currently
~19% of the sample); also watch `excerpt_char_coverage`, which should rise.

---

### 4.4 Writer-stage audits (free, on existing scripts)

| audit | result | verdict |
| --- | --- | --- |
| `PS-4a` cliché blacklist | **0 exact hits** across 3 scripts; 1 near-stem | **The blacklist works.** No near-miss inflation. Leave it alone. |
| forbidden academic register | 1 / 4 / 1 occurrences | Partial leak — the positive list beats the negative one on clichés but not here. |
| `PS-3a` analogy in editorial turns | **0** | The sanctioned-hallucination channel is **never used** — a third dead channel alongside `inferential` and `confidence`. Not abused; also not needed. |
| editorial turn share | `f781a5c7`: **11 of 22 turns**, 31.7% of words | Over the 25% cap (M8), non-blocking by MVP policy. |
| speaker skew (A:B words) | 1.98 / 1.80 / 2.13 | All at or over `_SPEAKER_SKEW_MAX = 2.0`. |

The blacklist result is worth stating positively: **not every anchor in this system is broken.**
`PS-4` is a well-behaved one, and it is a useful control — it shows the model *does* follow explicit
prohibitions when they name concrete strings. That makes the failures elsewhere more informative:
`DM-1` ("conservatively") and `EP-2` ("a concrete reason") fail not because instructions are ignored
but because they are **abstract**.

### 4.5 Methodological finding — how to compare two variants at all

Comparing which claims survive by **exact claim text** gives **1–5% Jaccard even between runs that
produced the same count from the same blocks**. The model rephrases every claim on every run, so
text identity measures nothing.

The fix is to compare **excerpt character spans**. Excerpts are verbatim by contract, so their
offsets in the block are directly comparable across runs, and their union is "what the model chose
to look at". Measured that way:

| pair | span Jaccard per block |
| --- | --- |
| baseline 2.0.0 vs D (Arendt-9) | 51.7% |
| baseline 2.0.0 vs `EX-1a` (Arendt-9) | 52.5% |
| D vs `EX-1a` (Arendt-9) | 50.0% |
| baseline pre-D vs D (Arendt-38) | 51.0% |

**Every pair lands at ~50–52%**, including pairs whose prompts differ in ways we expect to matter.
That is the signature of a noise floor, so the control was run: **the same prompt (D), three times,
on the same corpus.**

| pair | prompts | span Jaccard |
| --- | --- | --- |
| **D-run1 vs D-run2** | **identical** | **56.9%** |
| **D-run1 vs D-run3** | **identical** | **49.2%** |
| **D-run2 vs D-run3** | **identical** | **43.4%** |
| D vs `EX-1a` | differ | 50.0% |
| D vs `EX-2a` | differ | 48.9% |
| D vs `EX-6a` | differ | 43.3% |
| D vs baseline 2.0.0 | differ | 51.7% |

> ### The result that governs everything else in §4
>
> **Same-prompt noise floor: 43.4%–56.9%. Every treatment falls inside it — 43.3% to 51.7%.**
>
> **No span-overlap number in this document distinguishes an anchor effect from re-running the same
> prompt.** Two identical runs disagree about 43–57% of the text they choose to quote; a prompt
> change produces the same spread. This retracts the earlier reading in this section, written before
> the third control run, which treated `EX-6a`'s 43.3% as "meaningfully separated" — D-run2 vs
> D-run3 scored 43.4% with **no prompt change at all**.

The control also shows which per-run metrics are stable, and the answer is: almost none of them.

| metric | D-run1 | D-run2 | D-run3 | stable? |
| --- | --- | --- | --- | --- |
| flagged claims | `[2,1,1,2,0,1,2,0,1]` = **10** | `[2,1,1,1,0,1,1,0,1]` = **8** | `[1,1,2,0,0,1,0,0,0]` = **5** | **no — 5 to 10, a 2× spread** |
| blocks with zero flags | **2** | **2** | **5** | **no** |
| qualified claims | 8 | 10 | 8 | ±25%, tighter |

**A second retraction.** The two-run version of this table showed the same two blocks unflagged in
both runs, and this document briefly concluded that the zero-flag block *set* was reproducible even
though the rate was not. The third run has 5 zero-flag blocks. It is not reproducible either. Every
§4 result that leans on a zero-flag count — including §4.1 and §4.8 — inherits that uncertainty and
is annotated accordingly.

**What survives the control.** Two things, and they survive because their effect sizes are far
outside the band:

1. **`EX-2a`'s qualification collapse.** Control range is 8–10 qualified claims; `EX-2a` produced
   **2**. Four times below the floor of same-prompt variation. §4.7 stands.
2. **Everything in §4.13** — the degenerate channels are at 0% or 100%, not at the margin.

**What this means for further work.** On a 9-block corpus, single-run A/B on this pipeline can only
resolve effects of roughly `EX-2a`'s size (4×). Anything smaller needs **at least 3 runs per arm** and
preferably a corpus of 38 blocks or more. Budget for that before designing the next experiment: the
temptation is to run ten variants once each, and the result would be ten numbers that mean nothing.

### 4.6 `EX-1a` — making the budget tie-breaker concrete

Replacing *"extract the most central ones"* with an explicit priority order (dependencies first,
then the author's own positions, then the rest):

| | D (shipped) | `EX-1a` |
| --- | --- | --- |
| claims | 45 | 45 |
| all blocks at the cap | 9/9 | 9/9 |
| `must_not_be_lost` | 22.2% | 24.4% |
| qualifications | 17.8% | 17.8% |
| mean `excerpt_char_coverage` | 0.297 | **0.308** |
| span overlap vs D | — | 50.0% |

**Verdict: no measurable effect, and the measurement cannot currently distinguish "no effect" from
"noise".** Coverage rose slightly (0.297 → 0.308), which would be consistent with the model reaching
for different spans, but 9 blocks and a 50% noise floor cannot support that reading. `EX-1a` is **unresolved**: the
control (§4.5) put same-prompt span overlap at 43–57%, and `EX-1a`'s 50.0% sits squarely inside it.
Re-run on Arendt-38 with three runs per arm — the 9-block corpus cannot answer this question.

### 4.7 `EX-2a` — deleting the depth sentence (the clearest single-anchor effect found)

Removing one line — *"A brief profile preserves only the most central positions, definitions and
distinctions. A deep or extended profile preserves qualifications, conceptual dependencies and
material examples."* — and changing nothing else:

| variant | claims | at cap | `must_not_be_lost` | **qualifications** | coverage |
| --- | --- | --- | --- | --- | --- |
| baseline 2.0.0 | 45 | 9/9 | 46.7% | 15.6% | 0.293 |
| D (shipped) | 45 | 9/9 | 22.2% | 17.8% | 0.297 |
| `EX-1a` | 45 | 9/9 | 24.4% | 17.8% | 0.308 |
| **`EX-2a` (sentence deleted)** | 45 | 9/9 | 17.8% | **4.4%** | 0.280 |

Three variants sit at 15.6–17.8% qualifications; deleting this one sentence drops it to **4.4%** — a
fourfold fall, from 8 qualified claims to 2. Nothing else moved: same claim count, same cap
behaviour, span overlap (48.9% vs D) inside the noise band.

**What this actually shows.** The depth sentence is load-bearing, but *not for depth*. It does not
change how many claims come back — the cap does that. What it changes is whether the model preserves
qualifications at all. Put next to the D result (§4.1), where naming qualifications inside the
`must_not_be_lost` rule pushed the rate the other way, 12.7% → 21.1%, the pattern is consistent and
narrow:

> **The word "qualifications" appearing anywhere in the prompt is what drives qualification
> preservation — not the depth tier, not the profile JSON, not the claim budget.**

That is a useful, transferable result: it says the tier system is a claim-count system wearing a
depth label, and that the one property people actually care about at "deep" is being carried by an
incidental mention.

*How it stands after the control.* This is the **only single-run A/B in this document whose effect
survives §4.5.** The control put same-prompt qualification counts at 8, 10 and 8 of 45 claims;
`EX-2a` returned **2**. Four times below the floor of same-prompt variation is not something a
2×-noisy metric produces by chance. It is still n = 45 on one corpus and deserves replication on
Arendt-38 before the prompt is rewritten — but unlike `EX-1a` and the 9-block `EX-6a` numbers, it is
not explained away by noise.

### 4.8 `EX-6a` — D plus the floor sentence

The floor adds one clause to D: *"A block that states a position or argument almost always contains
at least one such claim; a block that only narrates, lists or illustrates may contain none."*

**Arendt-9:**

| variant | `must_not_be_lost` | **zero-flag blocks** | qualifications | span vs D |
| --- | --- | --- | --- | --- |
| baseline 2.0.0 | 46.7% | 0 / 9 | 15.6% | 51.7% |
| D (shipped) | 22.2% | **2 / 9** | 17.8% | — |
| **`EX-6a` (D + floor)** | 35.6% | **0 / 9** | 6.7% | 43.3% |

On Arendt-9 the floor took zero-flag blocks from 2 to 0, but the flag rate rose to 35.6% and the
qualification rate appeared to collapse to 6.7% — worrying enough that this section originally
recommended against shipping the wording. **The 38-block run resolves both questions, and reverses
the second one.**

**Arendt-38, with D run three times** — the corpus and the control that matter:

| variant | claims | flagged | rate | **zero-flag blocks** | composition of those blocks | qualifications |
| --- | --- | --- | --- | --- | --- | --- |
| baseline (pre-D) | 189 | 76 | 40.2% | **0** | — | 12.7% |
| D run 1 | 190 | 33 | 17.4% | **10** | 9 `argument`, 1 `definition` | 21.1% |
| D run 2 | 190 | 28 | 14.7% | **15** | 14 `argument`, 1 `definition` | 11.6% |
| D run 3 | 190 | 29 | 15.3% | **12** | 10 `argument`, 2 `definition` | 16.3% |
| **`EX-6a` (D + floor)** | 190 | 58 | **30.5%** | **0** | — | 22.1% |

**This is the one place in the document where the control makes a result stronger rather than
weaker.**

- **D leaves 10, 15 and 12 blocks unprotected.** Never fewer than 10, never close to the baseline's 0.
- **Every one of those 37 blocks, across all three runs, is `argument` or `definition`** — 33 argument,
  4 definition, **zero** narrative, list or example. The count varies; the composition does not vary
  at all.
- **`EX-6a` and the baseline both give 0.**

That is the answer to the red-line question, measured rather than inferred: D does not drop protection
at random, it drops it from the blocks that carry the argument, and one sentence puts it back.

**A useful side result about corpus size.** D's *flag rate* across three runs is 17.4 / 14.7 / 15.3% —
a spread of 2.7 points. On the 9-block corpus the same metric swung 2× (§4.5). **38 blocks is enough
to make rate metrics stable; 9 is not.** That is the practical threshold for future experiments.

**Where the evidence is still weak, stated plainly.** Qualification rate stays noisy even at 38 blocks:
D returned **21.1 / 11.6 / 16.3%** on identical prompts. `EX-6a`'s 22.1% is just above D's range but is
one run, so the earlier claim in this section that `EX-6a` "keeps D's qualification gain" overreached.
The defensible statement is: **`EX-6a` is not worse than D on qualifications**, and both look better
than the baseline's 12.7% — itself a single run.

The Arendt-9 reading of this variant (6.7% qualifications, which briefly argued against shipping it)
was noise: same variant, 22.1% on 190 claims. A 9-block corpus could not tell those apart, and this
document drew the wrong conclusion from it — the second such correction tonight, same cause.

**One caution remains.** At 30.5% the floor is closer to the old 40.2% than to D's 17.4%. Whether that
is right depends on what the flag is *for*: as an integrity gate feeding `EP-2`, a rate near a third
of claims may be too many to be meaningful. The next iteration should try tightening "almost always
contains at least one" to "normally one, occasionally two" and check whether the zero-flag count stays
at 0 while the rate falls toward 25%.

**What is still missing:** replication of `EX-6a` itself. D now has **three** runs on this corpus
(10, 15, 12 zero-flag blocks) and three on Arendt-9 (2, 2, 5); `EX-6a` has one on each, both **0**.
**No run of D, on either corpus, has ever produced 0.** Six D runs against zero, versus two `EX-6a`
runs at zero, is a strong asymmetry — three `EX-6a` runs would make it airtight.

**Recommendation, updated.** The floor works. Ship the *idea*; tune the wording downward once the
control lands, and measure on zero-flag composition, not on the rate.

### 4.9 `CR-*` — reconciliation is mostly skipped, and inert where it runs

The first reading of this data was wrong and is worth recording, because the mistake is easy to
repeat: a ledger with the same claim count as its evidence count looks like a model that refused to
merge. It is not. `claim_reconciler.py:555` **skips reconciliation entirely for single-source
projects**, and writes the reason into `warnings`.

| | evidence items | ledger claims | merged |
| --- | --- | --- | --- |
| reconciliation **ran** (6 ledgers) | 121 | 120 | **0.8%** |
| reconciliation **skipped** (3 ledgers, single-source) | 289 | 289 | n/a — never called |

Every large corpus falls in the second row (190, 81, 18 items). So:

1. **The `CR-*` anchors are essentially untested.** They have never been exercised on a corpus large
   enough for merging to matter. Any experiment on `CR-1`'s "materially the same proposition" must
   first create a multi-source project, or the stage will not run at all.
2. **Where it did run, it merged 1 of 121.** That is consistent with an inert anchor, on a sample far
   too small to conclude anything.
3. **`must_not_be_lost` was unchanged (17.4% → 17.4%) on Arendt-38** — but only because the stage was
   skipped. `CR-3`'s OR-propagation remains unmeasured, and the concern in §2.6 stands untested.

### 4.10 `EX-12` — `confidence`, the anchor that isn't there *(new)*

Chasing why `support_status` is always `strong` led somewhere more interesting.

`support_status` is not a model output. It is computed (`claim_reconciler.py:559-566`):

```
inferential            -> MODERATE
confidence >= 0.75     -> STRONG
confidence >= 0.4      -> MODERATE
otherwise              -> UNCERTAIN
```

So it is a deterministic function of two model fields. Both are degenerate:

| field | distribution over 554 evidence items |
| --- | --- |
| `support_kind` | `direct` 100% (M3) — so the `inferential → MODERATE` branch never fires |
| `confidence` | **0 items below 0.75.** 0.95 → 56.9%, 1.0 → 36.5%, 0.9 → 4.0%, rest ≥ 0.92 |

**And the extraction prompt never mentions `confidence` at all.** It is a required schema field with
no guidance anywhere in `system.md` or `user.md`, so the model does the natural thing and reports
near-certainty on everything.

The contrast that proves the point is inside this same codebase. `concept_edges/1.0.0:19` *does*
anchor the identical concept:

> "weight is how strong the relation is, 0–1: a strong prerequisite ≥ 0.8; a weak related ≤ 0.4.
> **confidence is how sure you are the edge is correct.**"

Same field name, same 0–1 range, one prompt defines it and the other does not. Whatever the edges
prompt produces, it is at least answering a stated question. Extraction is not.

That single unanchored field is what makes `support_status` constant, and `support_status` is what
the writer (*"state a claim whose support_status … is uncertain or contested with the hedge the
ledger records"*), the verifier (*"overstated certainty"*), and the planner (*"Preserve contested or
uncertain support"*) all branch on. Three carefully written anchors in three different prompts are
guarding a road nothing travels — and it is very likely part of why the verifier passes everything
(M5): one of the defects it hunts for cannot be produced.

---

**`EX-12` — confidence has no anchor** · *absent from* `evidence_extraction/2.1.0` · **mode: both**

*Experiment `EX-12a`.* Add one calibration sentence to the extraction prompt, e.g.
*"confidence is how certain you are that the block states this claim, not how important the claim is.
Use 0.95+ only when the excerpt states it outright; use 0.5–0.7 when you are reading between the
sentences; below 0.4 do not extract it at all."* Metric: the confidence histogram, and — the point of
the exercise — whether any claim reaches the ledger as `moderate` or `uncertain`. Until one does,
the entire hedging apparatus downstream is untestable.

*Why this may be the cheapest large win in the register.* One sentence, in the prompt that is already
being edited for `EX-6a`, potentially revives three downstream anchors and one whole verifier
category.

---

### 4.11 A note on method

The correction above happened because a ledger field (`warnings`) contradicted an inference drawn
from counts. Two rules follow for anyone continuing this work:

- **Read the artifact's own warnings before interpreting its numbers.** Every service in this
  codebase records why it did what it did; the skip reason was sitting in the file the whole time.
- **A stage that produces output is not a stage that ran.** Several of these prompts have
  deterministic fallbacks. Confirm the model-run stage counts (`workspaces/<pid>/model-runs/*/record.json`)
  before attributing an output to a prompt.

### 4.12 `EX-4a` — naming the damage (Persian)

The variant adds one sentence after the verbatim rule, telling the model what kind of damage the
block will contain and that it must be copied rather than repaired:

> "The block is machine-extracted text and may contain typographic damage: kashida/tatweel stretching
> inside words, missing zero-width non-joiners, Arabic letters where Persian ones belong, hyphenation
> and line breaks inside words, and words in the wrong order. Copy the span exactly as the block
> writes it, damage included. Do not repair, re-order or normalize it, and do not silently skip a
> claim because its span is damaged."

`EX-4b` instead attacks the same problem by shrinking what has to be copied:

> "Copy the shortest span that still supports the claim. One clause is better than one sentence, and
> one sentence is better than two. A long excerpt is not stronger evidence; it is only more to copy
> wrongly."

Same 11-block Persian source, same settings, three arms run back to back:

| | baseline (D) | **`EX-4a` name the damage** | **`EX-4b` short spans** |
| --- | --- | --- | --- |
| passes to reach 9 blocks | **5** | **3** | **3** |
| model attempts | 172 | **61** | **63** |
| output tokens | 452,000 | **238,000** | **240,000** |
| blocks extracted | 9 | 9 | 9 |
| **blocks left rejected on the contract** | **1** | **0** | **0** |
| claims recovered | 29 | 31 | **33** |
| mean excerpt length (chars) | 168 | 192 | **94** |
| median excerpt length | 167 | 169 | **69** |
| **mean `excerpt_char_coverage`** | 0.100 | **0.134** | **0.069** |
| excerpts opening with a pronoun | 3.4% | 0% | 0% |
| `ExcerptNotFoundError` per attempt | 30.2% | 42.6% | 39.7% |

**Both variants beat the baseline on every completion metric**: three passes instead of five, roughly
a third of the attempts, half the tokens, more claims, and no block left failing the contract.

**`EX-4b`'s mechanism is confirmed directly, which is rare in this document.** Median excerpt length
fell from **167 to 69 characters** — a 2.4× reduction. That is not a rate that noise could produce; the
model was told to copy less and measurably copied less. It is the only anchor tested tonight whose
*stated mechanism* was observed firing.

**But `EX-4a` is the better variant, and the coverage column is why.** Shorter spans cover less of the
block: `EX-4b` halves `excerpt_char_coverage` (0.100 → 0.069) while `EX-4a` raises it (→ 0.134).
Coverage is what makes an excerpt auditable — a 69-character span is easier to copy and weaker as
evidence. `EX-4a` gets the reliability without paying for it.

**Recommendation: adopt `EX-4a`, not `EX-4b`.** Naming the damage is cost-free in coverage terms and
carries the whole cost saving. If a further push on reliability is needed later, `EX-4b` is available
but should be spent knowingly.

**Two honest caveats.**

1. **The per-attempt failure rate went *up* for both variants** (30.2% → 42.6% / 39.7%). Not a
   contradiction: the baseline spent 172 attempts, most on proxy errors and easy retries that diluted
   its rate, while the variants finished in ~62. But it does mean neither sentence made an individual
   copy more reliable in the way the hypothesis predicted — they made the run *converge*, plausibly by
   stopping the model from silently abandoning damaged spans ("do not silently skip a claim because
   its span is damaged" may be the operative clause in `EX-4a`, not the list of damage types).
2. **The arms ran back to back on a shared proxy whose error rate drifts** (56–66% across the night),
   which confounds attempt counts. The excerpt-length and coverage numbers do not depend on the proxy
   and are the trustworthy part; the cost ratios need the standard three runs per arm.

**One more thing this exposes.** Persian `excerpt_char_coverage` is **0.069–0.134** against **0.29–0.31**
on English. Whatever the eventual `thin_extraction` threshold is, if it is set from English data
(§3.2 notes 0.35, with English measuring 0.30) then **every Persian block will be flagged thin.** The
threshold has to be calibrated per language, not just per depth tier.

### 4.13 The pattern behind most of these findings

The first draft of this section, written before the concept map existed, said: *wherever a prompt
offers a discriminating option next to a safe uniform one, the output is the uniform one.* The
concept-map data refines that into something sharper and more useful, because it contains anchors that
**worked**.

**What the model ignores** — abstract adjectives and conditional bounds:

| anchor | wording | result |
| --- | --- | --- |
| `DM-1` | mark required sections "**conservatively**" | 85% of 333 sections marked (M1) |
| `EP-2` | omit with "a **concrete** editorial reason" | 59 of 64 are one boilerplate string (M6) |
| `CE-2` | "a **weak** related ≤ 0.4" | 4 of 41 comply (M33) |
| `CR-1` | "**materially** the same proposition" | 1 merge in 121 (M19) |
| `EX-7` | inferential must "follow **closely**" | 0 of 189 marked inferential (M3) |

**What the model obeys** — concrete, unconditional, checkable statements:

| anchor | wording | result |
| --- | --- | --- |
| `CC-1` | a cell is "**3 to 15 minutes**" | 105 of 107 inside the window; max exactly 15.0 (M32) |
| `CE-2` | "a strong prerequisite **≥ 0.8**" | **37 of 37** comply (M33) |
| `PS-4` | a list of exact forbidden Persian phrases | 0 exact hits, 1 near-variant in 3 scripts (M16) |
| `CC-4` | "would a reader who sees only this label know the concept?" | 0 duplicate labels, 100% carry `label_source` |
| `CC-2` | tier 1 "roughly **15–45 percent**" | landed at 31.8%, mid-window (M31) |

**And what happens with no anchor at all** — the `EX-12` natural experiment (M34). Same model, same
codebase, same 0–1 `confidence` field:

| prompt | anchors `confidence`? | n | mean | minimum |
| --- | --- | --- | --- | --- |
| `concept_edges` | **yes** — "how sure you are the edge is correct" | 145 | 0.878 | **0.50** |
| `evidence_extraction` | **no** — the word never appears | 732 | 0.960 | **0.90** |

**The rule these support.** The model is not avoiding discrimination; it is answering the question it
was actually asked. A number, a range, an explicit list, or a bound attached to a *type* gets obeyed.
An adjective — conservative, material, concrete, close, weak, truly — gets read as encouragement and
produces the median behaviour. A field nobody mentions gets filled with the least committal value that
validates.

That converts most of this register from "rewrite the sentence better" into one concrete edit rule:

> **Replace every evaluative adjective with a number, an explicit list, or a stated expected
> distribution — and give every schema field at least one sentence saying what it means.**

`CC-2` is the one place a distribution is already stated, and it is also the one place the output is
suspiciously well-behaved (M31) — which is why `CC-2a` matters: a distribution stated as a *target*
may be manufacturing the very number it reports. The safer form is to state it as a **check the model
must report against**, not a quota it must hit.

**The degenerate channels still stand**, and now read as instances of the same rule rather than a
separate phenomenon: `support_kind` 100% `direct` (M3), `support_status` 100% `strong` (M21),
`more_claims_available` 97–100% true (M4), verifier scores 15 of 15 exactly 1.0 (M5), editorial
analogies 0 (M17), `example` cells 1 of 107 (M30). Every one is a field or a category whose selection
criterion is an adjective, or is never described at all.


### 4.14 `CR-*` — reconciliation measured with the model enabled

§4.9 could only report that the stage is skipped on single-source projects. A two-source project was
built for this register (two English Arendt papers, 19 and 8 blocks) so `skip_model` is False and the
stage genuinely runs.

| source | evidence items | ledger claims | merged | claims citing >1 evidence id |
| --- | --- | --- | --- | --- |
| EN-2 | 38 | 38 | **0.0%** | 0 |
| EN-1 | 87 | 84 | **3.4%** | 3 |
| **total** | **125** | **122** | **2.4%** | **3** |

**The `CR-*` anchors are not mis-tuned; the stage barely does anything.** 2.4% merging, on two papers
about the same book by the same author, after 5–6 provider retries per source. `CR-1`'s "materially the
same proposition" is not a threshold set too high — nothing is reaching it.

**And a second result that closes off the easy explanation for M21.** `support_status` came back
**`strong` on all 122 claims** — here the *model* assigns it, not the deterministic skip-path formula
in `claim_reconciler.py:559`. So the constant is not a code artefact. The model does not mark evidence
as contested or uncertain when it decides for itself either. Every downstream anchor that branches on
that field (writer, verifier, planner) remains unreachable, and the cause is deeper than §4.10 assumed.

### 4.15 `DM-1` — a real effect, and a self-inflicted bias separated out from it

**This section's first version was wrong in a way worth keeping on the page**, because it is the same
error this register criticises `CC-2` for two sections earlier.

The first rewrite replaced the adjective with a definition **and a quota**:

> "…**In a map of N sections expect roughly N/5 to qualify**; if you are marking more than a third of
> them, you are using the wrong test."

It produced **20%** — which is N/5 almost exactly. That was reported as a four-fold win. It is not a
finding; it is an echo. Telling a model the expected share and then reporting that share back is
precisely the `CC-2` failure: the number in the output came from the prompt, not from the source.

The corrected experiment drops the quota and keeps only the test, three runs per arm:

| arm | run 1 | run 2 | run 3 | mean |
| --- | --- | --- | --- | --- |
| baseline — "mark **conservatively**" | 98% | 100% | 90% | **96%** |
| **criterion only, no number** | 59% | 54% | 37% | **50%** |
| criterion + "roughly N/5" *(1 run, biased)* | — | — | — | *20%* |

**The honest decomposition:**

- **Defining the test is worth about 2×** — 96% → 50%, and the three baseline runs (90–100%) do not
  overlap the three criterion runs (37–59%) at all. This part is real.
- **The quota's extra push, 50% → 20%, is the model obeying the number.** Discard it.

The criterion that survives is just:

> "Set required_for_global_understanding on a section only when a listener who skipped it would
> misunderstand a later section. It is not a mark of quality, interest, or how much the section
> contributes; a section can be excellent and still not be required by this test."

**And 50% is still too high to fix M2.** Half the sections marked required still leaves the ranking
mostly flat. The criterion helps and is not sufficient — the next move is a *sharper test*, not a
number. Note also that the criterion-only arm spreads much wider (37–59%, 22 points) than the pinned
arm; that spread is the model actually deciding, and it is the honest cost of removing the crutch.

**The same objection applies to `EX-6a`** (§4.8), whose floor sentence says a block that argues
"almost always contains at least one such claim". That also tells the model the answer, and the 30.5%
it produced is suspect for the same reason. It needs re-running without the expectation baked in.

**A methodological trap worth recording separately.** The very first attempt reported *no change at
all* — three byte-identical maps, and **zero `document_map` model calls**. The document-map cache keys
on block content and `builder_version` and **does not include the prompt version**, so re-running with
a different prompt silently returns the stored map. Any A/B on a map prompt must move
`workspaces/_shared/document-maps` and `document-map-parts` aside first, and anyone *editing*
`document_map/1.1.0` in place will keep getting the old map on every previously-seen source.

### 4.17 `CR-*` — the stage has nothing to merge

§4.14 measured reconciliation at 2.4% merging when it runs. The obvious next question is whether that
is laziness or an accurate reflection of the input. A deterministic scan answers it at zero cost.

Across **579 claims in 11 ledgers**, counting pairs whose claim texts share more than 0.55 of their
content words:

| | claims | near-duplicate pairs surviving |
| --- | --- | --- |
| ledgers where the model ran | 240 | **0** |
| ledgers where the model was skipped | 339 | **0** |

The skipped group is the control: nothing could have merged those, and there is still nothing to find.

**The measure is not blind.** On the 190-claim Arendt ledger it scores all 17,955 pairs and returns a
real distribution — median 0.000, p99 0.125, **maximum 0.294**. The single most similar pair in the
whole ledger is:

> **A:** "Among the modern classifications of labor, only the distinction between productive and
> unproductive labor reaches the core of the matter."
> **B:** "The distinction between productive and unproductive labor implicitly contains the more
> fundamental distinction between work and labor."

Those are two different propositions about the same distinction. Not merging them is correct.

**Conclusion: do not tune `CR-1`'s wording.** Per-block extraction with a claim cap does not produce
restatements across blocks, so the within-source merge job is already done before this stage is
reached. Two changes follow:

1. **Gate the call on a deterministic similarity scan.** If no pair clears a threshold, skip the model
   entirely. On every corpus measured here that is **zero calls**, against the 5–6 provider retries per
   source it currently costs.
2. **The case the stage was designed for has still never run.** `build-claims` is per-source, so
   everything measured here is *within* one document. Genuine cross-source agreement and disagreement
   is `claim_reconciliation_merge`, a separate stage that no run in this workspace has exercised. That
   one is worth testing; this one is worth skipping.

### 4.16 `EX-12a` — refuted, and it takes M34 with it

The prediction from M34 was that defining `confidence` would widen its distribution. The sentence
added was explicit, including a direct instruction against uniformity:

> "confidence is how certain you are that this block states this claim — not how important the claim
> is. Use 0.9 or above only when the excerpt says it outright. Use 0.5 to 0.7 when you are reading
> between the sentences… Below 0.4, do not extract the claim at all. **In a normal block some claims
> should differ from others; returning the same confidence for every claim means you have not judged
> them.**"

| variant | blocks | claims | mean | min | distinct values | below 0.75 |
| --- | --- | --- | --- | --- | --- | --- |
| D run 1 | 38 | 190 | 0.962 | 0.90 | 6 | **0** |
| D run 2 | 38 | 190 | 0.958 | 0.88 | 8 | **0** |
| D run 3 | 38 | 190 | 0.961 | 0.90 | 8 | **0** |
| **`EX-12a`** | 18 | 90 | 0.942 | **0.90** | **3** | **0** |

**No effect on the minimum, and the spread got narrower, not wider** — 74 of 90 claims came back at
exactly 0.95. The one metric that moved went the wrong way.

**This retracts the reasoning in §4.10.** M34 compared `concept_edges` (confidence anchored, minimum
0.50) against `evidence_extraction` (unanchored, minimum 0.90) and attributed the gap to the anchor.
Adding the anchor does not close the gap, so the gap belongs to **the task**: deciding whether an edge
exists between two concept cells is genuinely uncertain, while deciding whether a block states a claim
— with the block in hand and a verbatim excerpt already located — genuinely is not. The model may
simply be right at 0.95.

**The general lesson is the more useful part.** This register's one "natural experiment" — same field,
same model, two prompts — looked clean and was confounded. A comparison across two prompts is not an
experiment, because everything else about the two tasks differs too. Only the within-prompt A/Bs
(`DM-1a`, `CE-2a`, `EX-2a`) survived contact with a control.

**What this does not rescue.** `support_status` is still constant (M41), and it is now clear that
neither a prompt sentence nor the reconciliation model will move it. If hedging is wanted downstream,
it has to come from somewhere other than asking the model to be less sure.


### 4.18 `SV-1a` — the verifier passed a script with fabrications planted in it

M5 showed the verifier returning `pass`, zero issues, and exactly 1.0 on all five dimensions in every
run on disk. That is consistent with two very different worlds: the scripts really are clean, or the
instrument reads zero regardless. This settles it.

**Method.** Take the script this verifier already passed (project `9c4e58b0`, 23 turns, 81 claims,
5 evidence packs). Plant three defects the verifier's own prompt says it hunts for:

| | defect | where |
| --- | --- | --- |
| **D1** | a fabricated date and figure — *"Arendt wrote this exactly in 1958, based on a review of seventy-three archival documents"* | a substantive turn |
| **D2** | strip the hedges from a substantive turn | — |
| **D3** | an invented comparison — *"exactly like the difference between a modern car factory and a Swiss watchmaker's workshop"* | a **substantive** turn, not `editorial_only` |

Run the verifier on the sabotaged script and on the untouched original, everything else identical.

**Result.**

| | clean control | **sabotaged** |
| --- | --- | --- |
| verdict | pass | **pass** |
| issues | 0 | **0** |
| `unsupported_claim_ratio` | 0.0 | **0.0** |
| evidence_fidelity | 1.0 | **1.0** |
| qualification_preservation | 1.0 | **1.0** |
| stance_and_disagreement | 1.0 | **1.0** |
| terminology_consistency | 1.0 | **1.0** |
| listenability | 1.0 | **1.0** |

**Zero of three defects caught.** And the failure is not passive. Asked for `actionable_feedback` on
the sabotaged script, it wrote:

> "All turns are fully grounded in the provided source evidence and maintain high fidelity to the text."

It did not decline to judge. **It certified the fabrication.** A reviewer that stays silent is useless;
one that affirms is worse, because the pass verdict is what the pipeline and the owner both trust.

*(D2 turned out to be a weak defect — the target turn had no hedges to remove, which is itself M21
showing through: nothing in this ledger is ever `contested` or `uncertain`, so there is no hedging to
strip. The test therefore rests on D1 and D3, both unambiguous.)*

**The free deterministic checker did better — and that is the sharpest part of the result.**
`ScriptChecker` costs nothing, calls no model, and it *did* notice the planted date: `۱۹۵۸` appears in
the sabotaged run's `unsupported_specifics` list and not in the clean one. But:

- it **added the date to an issue that already existed** rather than raising a new one, so the issue
  count is **9 in both arms** — anything watching the count sees no change;
- it missed D3 entirely, and missed the fabricated figure;
- and of its 9 issues, most are false positives on ordinary Persian terminology — including
  **the book's own title**, وضع بشر, plus حیات فعال and ماهیت انسان;
- all at `medium`, which by explicit MVP policy does not block (M8).

So the one true detection in the entire grounding chain arrives buried in a list beside four false
ones, inside an unchanged issue count, at a severity nothing acts on.

**What this means for the rest of the register.** Every writer-stage anchor — `PS-1` (the
tone-to-grounding ratio), `PS-3` (the sanctioned analogy channel), `EX-11`, and the `EX-4` grounding
guarantee itself — was supposed to be backstopped here. None of them are. And no writer-stage
experiment can be scored automatically until this is fixed, because the only available score is a
constant.

**Priority.** This moves to the top of the shortlist, above `EX-6a`. Not because the anchor wording is
the problem — `SV-2a` (anchoring the 0–1 scales) and `SV-3a` (forcing it to name the weakest turn) are
still worth trying — but because the cheapest real improvement available today is to **raise the
deterministic checker's severity and cut its false-positive rate**, since it is the only component that
detected anything at all. Teaching it that glossary terms and the source's own title are not
"unsupported specifics" would leave a small, high-precision signal where there is currently noise.


---

## 5. Protocol

**Fixed corpora.** Comparisons are only meaningful on identical input.

| Corpus | Project | Blocks | Tier | Purpose |
| --- | --- | --- | --- | --- |
| **Arendt-9** | `2c4fece2` | 9 selected of 10 | `deep`, `max_claims=5` | fast A/B for extraction anchors |
| **Arendt-38** | `8d11f6a9` | 38 selected of 41 | `deep`, `max_claims=5` | scale validation; pre-D baseline snapshotted |
| **FA-11** | `5a7cd1c9` | 11 | `deep` | Persian; source `FA-2-Citizenship-as-Alternative-to-World-Alienation.pdf` |

**Variant naming.** Experiment prompt versions are created as `2.0.9x` directories. This matters:
`PromptLoader._resolve_version_dir` returns `max(version)` when unpinned, and `_version_key` compares
tuples, so `2.0.9x < 2.1.0` and an experiment directory can never silently become the default.
Delete them when done — they are untracked files in `prompts/`.

**Metrics.** Per run: extracted/rejected/skipped block counts, claims total and per block, claims at
the cap, `must_not_be_lost` rate, `more_claims_available` rate, `inferential` rate, qualification
rate, claim-type mix, empty-block count, `excerpt_char_coverage` mean, and — for Persian —
excerpt verbatim audit (exact / whitespace-only / Persian-normalised / not found).

**Environment.** `THESISOUND_EVIDENCE_EXTRACTION_WORKERS=1` (worker=4 causes 406 storms through the
local proxy), `THESISOUND_HTTP_PROXY=http://127.0.0.1:10808`, `PYTHONIOENCODING=utf-8`. Runs are
retried in passes; `extract-evidence` resumes and only retries non-`extracted` blocks.

**Replication, not optional.** §4.5 measured the same-prompt noise floor: **43–57% span overlap and a
2× spread in flag counts on a 9-block corpus.** Therefore:

- **three runs per arm, minimum**, and prefer Arendt-38 over Arendt-9 — the larger corpus is what let
  the `EX-6a` result (§4.8) be read at all after the 9-block version of it misled twice;
- **prefer composition metrics over rate metrics.** "Which *kind* of block goes unflagged", "which
  *values* of an enum ever appear", "how many distinct reasons were given" all held up; "what
  percentage" did not;
- **a metric that is 0% or 100% is trustworthy at n=1.** Most of §1's findings are of that shape,
  which is why they need no replication and the §4 A/Bs do.

**Scoring caution.** Until `SV-1a`/`SV-2a` establish that the verifier can fail anything (M5), no
writer-stage experiment can be scored automatically. Score those by hand or not at all.

---

## 6. Ranked shortlist

Ordered by (measured failure × product impact) ÷ cost.

> **Before running anything from this table, read §4.5.** The same-prompt noise floor on a 9-block
> corpus is 43–57% span overlap and the flag count varies 2×. Every entry below is costed at "1 run"
> for comparability, but **1 run will not answer any of them except at `EX-2a`'s effect size**. Budget
> 3 runs per arm on Arendt-38, and prefer the composition metrics (which *kind* of block, which
> *class* of value) over rate metrics, because compositions were the only per-run numbers that held up.

| Rank | Anchor | Why | Cost | Status |
| --- | --- | --- | --- | --- |
| **0** | **`SV-*`** the verifier | **DONE — it passed a script with a fabricated date, a fabricated figure, and an invented comparison planted in it, and wrote "fully grounded" in the feedback field (M46/M47).** Every other grounding anchor was supposed to be backstopped here. Cheapest real fix is not the prompt: raise the deterministic checker's severity and cut its false positives (M48/M49) — it is the only component that caught anything. | done; fix is engineering | **run — §4.18; top priority** |
| 1 | **`EX-6a`** must-not-be-lost floor | M13/M14: D leaves argument blocks — never narrative ones — with zero protection, including two carrying chapter theses. The owner's red line, measured. | 3 runs | **run tonight — §4.8; confirmed on 38 blocks** |
| 2 | **`EX-4a`** Persian: name the damage | M11/M16: the verbatim rule fails on 28% of Persian attempts vs 0–0.8% on English. M24: the variant cuts the run from **5 passes to 3**, 172 attempts to 61, 452k tokens to 238k, leaves **0** blocks rejected, and *raises* excerpt coverage. `EX-4b` matches on cost but halves coverage — prefer `EX-4a`. | 3 runs to confirm | **run tonight — §4.12; adopt `EX-4a`** |
| 3 | **`DM-1`** "conservatively" → a definition | **DONE, and partly retracted (M42).** The criterion alone moves it 96% → 50% over 3 runs per arm — real. The extra push to 20% came from a quota I put in the prompt, which is the `CC-2` mistake; discard that half. 50% is still too high to fix M2. | sharper criterion, 3 runs | **run — §4.15; adopt the criterion, not the number** |
| 5 | **`CC-2a`** forced tier distribution | M31: tier 1 landed at 31.8%, mid-window, in the one map built. Prompt and code state the same numbers, so neither can report a lopsided chapter as lopsided. Removing the sentence is the only way to tell "manufactured" from "true". | 2 runs | **a map now exists — §2.2** |
| — | ~~**`EX-12a`** anchor `confidence`~~ | **REFUTED (M43).** Defining the field left the minimum at 0.90 and *narrowed* the spread. M34, which motivated it, was confounded by task difficulty (M44). Dropped from the shortlist. | — | **run — §4.16; do not adopt** |
| 6 | **`EP-2a`** omission reasons | M6: 8% unique reasons. Trivial change; directly restores the must-not-be-lost audit trail that `EX-6` exists to feed. | 1 run | not run |
| 7 | **`EX-11a`** excerpt self-containment | M19: ~19% of sampled excerpts open with an unresolved pronoun, defeating the audit promise. | 1 run | not run |
| 8 | **`CA-1a`** minute-estimate variance | Five identical calls settle whether the pipeline's main gate is noise or a mirror of the request. | 5 calls | not run |
| 9 | **`PS-2a`** script length floor | M7: every script is 12–29% short. Fixed-time mode does not deliver the requested time. | 1 run | not run |
| 10 | **`EX-10a`** batch position bias | Decisive; needs no prompt change at all. | 2 runs | not run |

**Already answered, no experiment needed:** `EX-7a` (M19 — done by hand, free), `PS-4a` (M17 — the
blacklist works, leave it), `PS-3a` (M18 — channel unused).

**Not experiments — cleanups justified by the evidence now:** `EP-3` (the objection/response
placement preference can never fire since 2.1.0 removed those claim types), and re-checking `EX-8`
against the surviving `editorial_explanation` enum entry.

**Not anchors at all — engineering defects found while gathering this data.** Both block the concept
map, and neither is fixable by prompt wording:

1. **`concept-map --chapters` crashes unconditionally** (M26) — whole-document `blocks` against
   chapter-subset `partitions`. The map can therefore only be built by processing an entire book.
2. **The concept-map path never filters notes, index or front matter** (M28) — 20.6% of cells came
   from the endnotes, the index and the copyright page. `eligible_blocks` already implements exactly
   this filter for the extraction path; the concept-map path does not call it.

A third, cosmetic but consequential: **chapter titles are EPUB internal filenames** (M29), so a human
reviewing the map cannot tell chapter 2 from the index.

### 6.1 What to do first

**Run the controls before changing any prompt.** That is the actual first action, and it is the
lesson of §4.5: this document contains one night of single-run experiments, and the control run at
the end of that night retracted two of its own conclusions. Three runs of D on Arendt-38 costs less
than one wrong prompt change costs to discover.

**Then make one change: `EX-6a`.** Keep variant D, add the floor sentence. On the 38-block corpus it
is the only variant tested that gets everything at once (§4.8):

| | zero-flag blocks | qualifications | flag rate |
| --- | --- | --- | --- |
| baseline (pre-D) | 0 ✓ | 12.7% ✗ | 40.2% ✗ |
| D (shipped now) | **10** ✗ | 21.1% ✓ | 17.4% ✓ |
| **`EX-6a`** | **0** ✓ | **22.1%** ✓ | 30.5% ~ |

The zero-flag column is the owner's red line: those 10 blocks under D are `argument` and `definition`
sections — never narrative ones — and two of them carry chapter theses. The floor removes them
without giving back D's qualification gain.

**Tune the wording before shipping it, don't rewrite the idea.** At 30.5% the flag rate is closer to
the old 40.2% than is comfortable for something meant to be a rare integrity marker. Try "normally
one, occasionally two" in place of "almost always at least one", re-run on Arendt-38 three times, and
accept it when zero-flag stays at 0 and the rate falls toward 25%.

**One recommendation here was tested and withdrawn.** An earlier draft put `EX-12a` — define the
`confidence` field — near the top, on the strength of a cross-prompt comparison. It was run, and it
failed (§4.16): the minimum stayed at 0.90 and the spread got *narrower*. `support_status` will not be
revived by asking the model to be less certain, and the comparison that suggested otherwise was
confounded by task difficulty (M44). It stays in the register as a worked example of how a
clean-looking inference goes wrong, not as a proposal.

**What replaces it: `DM-1a`**, run in the same batch, and the largest effect measured anywhere here —
required sections fell from 76–98% to **20%**, exactly the quota the rewritten sentence names (§4.15).
Same edit rule as `EX-12a`, different anchor, and this one has the measurement behind it. Note the trap
it exposed: the document-map cache ignores the prompt version, so this A/B silently returns the stored
map unless `workspaces/_shared/document-maps` is moved aside first.

---

## 6.2 Reproducing tonight's runs

Experiment prompts were created as sibling version directories and are **deleted after use**; if any
`prompts/evidence_extraction/2.0.9*` directory still exists, it is leftover from this session and can
be removed.

| variant dir | anchor | change |
| --- | --- | --- |
| `2.0.91` | `EX-1a` | "extract the most central ones" → explicit priority order |
| `2.0.92` | `EX-2a` | depth sentence deleted |
| `2.0.93` | `EX-6a` | D + the floor sentence |
| `2.0.94` | `EX-4a` | verbatim rule + named Persian damage classes |
| `2.0.95` | `EX-4b` | verbatim rule + "copy the shortest span that still supports the claim" |

The run shape for each, with `THESISOUND_EVIDENCE_EXTRACTION_WORKERS=1`:

```bash
uv run thesisound extract-evidence <project-id> <source-id> --prompt-version 2.0.93
```

Because roughly two thirds of attempts fail on the local proxy regardless of prompt (see §4.2),
every run is a retry loop: `extract-evidence` resumes and only re-attempts non-`extracted` blocks, so
calling it repeatedly until the extracted count stops rising is the correct usage, not a workaround.

Analysis scripts used (session scratchpad): `anchor_report.py` (distribution metrics per variant),
`span_overlap.py` (§4.5 excerpt-span Jaccard), `fa_cost.py` (§4.2 error-type classification),
`zeroflag.py` (§4.1 zero-flag block analysis), `rankscore.py` (M2), `deps.py` (M9),
`script_audit.py` (§4.4), `ex7_audit.py` (§4.3).

---

## 7. What this register does not cover

- **TTS, ASR and audio QA prompts** — outside the text pipeline; not audited.
- **Interactions between anchors.** Every experiment above changes one thing. `EX-1` and `EX-6`
  plainly interact (the cap decides whether the dependency clause can fire), as do `DM-1` and
  `CC-2`. Single-variable results will not compose cleanly.
- **Model dependence.** Every measurement is against the current `fast` tier. An anchor that is
  load-bearing on one model may be inert on another; none of this transfers automatically.
- **The parser half of M11/M12.** Fixing the Persian verbatim anchor does not fix a parser that
  scrambles RTL word order and reports `safe_for_claim_extraction: true`. Both halves need owner
  decisions, and the parser half is the larger one.
