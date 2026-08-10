# Independent adversarial review of the Phase-1 Semantic Golden Set

Reviewer: Opus 5, acting as an independent adversarial reviewer of a Phase-1 design produced by GPT-5.6 Sol.
Independent review: 2026-08-10 · Reconciliation pass: 2026-08-10
Status: **review only. Nothing frozen. No gold authored.**

Phase-1 artifacts were read in the prescribed order and were not modified.

> **Reading order and anchoring control.** `SOURCE-RECOMMENDATIONS.md` was **deliberately withheld** during the first pass to
> prevent anchoring on Sol's preferred packages and numeric scores. All fifteen case verdicts in §3 were formed before it was
> read. It was supplied afterwards; §11 records the reconciliation. My earlier criticism that the ranking was "unauditable" was
> a consequence of the withholding, not a Phase-1 defect — **blocker B15 is withdrawn**. The file is currently untracked in git;
> committing it is an audit-trail task, not a design defect.
>
> **Path note.** The task named `benchmarks/eval-design/v1/`. That directory does not exist; the Phase-1 artifacts are in
> `benchmarks/eval/v1/`, and this review is written beside them.
>
> **Structure of this document.** §§1-10 are the original independent judgment, preserved. §11 is the reconciliation against
> Sol. §§12-15 are the reconciliation-pass decisions: the 20/40 duration pair, the C05 and C12 replacements, the holdout
> architecture, and the R13 validation procedure. Disagreement history is preserved rather than rewritten.

---

## 1. Executive verdict

**The proposed 15-case set is not a valid measurement instrument for Thesisound as currently implemented, and must not be frozen.** The case *ideas* are mostly good. The failure is that Phase 1 designed against the documentation's aspirations rather than against the running system, and did not verify that the chosen source files are machine-usable.

Four findings drive the verdict. Three are mine, established from the code and from the source files themselves, and none appear anywhere in Phase 1.

**Finding 1 — A quarter of the set measures a subsystem that does not exist.**
`ClaimReconcilerService.reconcile()` takes a single `source_id` and only ever sees one source's evidence
([claim_reconciler.py:23-52](../../../src/thesisound/services/claim_reconciler.py#L23)). `DisagreementGraphBuilder` emits a
node only when a claim carries `agreeing_source_ids` / `disagreeing_source_ids`, or is `CONTESTED`
([disagreement_graph.py:36-49](../../../src/thesisound/services/disagreement_graph.py#L36)) — and the reconciliation prompt
is handed only `source_id` and that source's `evidence_items`, so it has no way to name another source's UUID. [`STATUS.md:64`](../../../STATUS.md#L64)
states it plainly: **"M8 Full multi-source semantic reconciliation: not implemented."**
Consequence: for a multi-source corpus the pipeline produces N independent claim ledgers, an **empty** disagreement graph,
and a script that can pass every gate while presenting the sources as unrelated topics. **C05** — whose entire purpose is a
comment/response exchange — cannot distinguish "the model collapsed a disagreement" from "the architecture has no stage that
could preserve one." It is unfalsifiable and must not enter v1.

**Finding 2 — C12's primary texts are unusable, and one of them is the wrong document.**
I downloaded both Iran Data Portal PDFs and inspected them locally.

| File | Pages | Extractable chars | Words | Embedded images | State |
|---|---:|---:|---:|---:|---|
| `30-december-1906-persian.pdf` | 12 | **0** | 0 | 12 | pure image scan |
| `7-october-1907-persian.pdf` | 26 | 3,058 | 618 | 1 | glyph-only, 626 NUL bytes, 1,453 Arabic presentation-form chars |

The 1906 law has **no text layer at all**. The 1907 supplement extracts only its ~107 article *headers* (`اصل` appears 108
times) and almost none of the article bodies; the font carries no usable `ToUnicode` mapping. Either would force Persian OCR
into a benchmark whose own [`REQUIREMENTS.md`](REQUIREMENTS.md) excludes OCR and routes it to `benchmarks/persian_ocr/`. Worse, the
glyph-normalised 1907 text contains **پهلوي** and **قاجاريه** and **ولايتعهد** — it is a *later consolidated text carrying the
1925 Pahlavi amendment*, not the 1907 settlement as enacted. Gold atoms about "the 1907 supplement" drawn from this file would
be historically false. **C12 is BLOCKED.**

**Finding 3 — C09 measures a deterministic code path, not long-range reasoning.**
`plan_evidence_extraction` caps selection at `min(total, coverage×1.1, max(12k, min(180k, duration×1800)))`
([analysis_profile.py:84,148](../../../src/thesisound/services/analysis_profile.py#L84)). Darwin's 1859 first edition is ~150k
words ≈ ~200k tokens. At a product-realistic 40 minutes the budget is **72,000 tokens — about 36% of the book**; the other ~64%
lands in `deferred_block_ids` *by design*. C09's declared failure mode, "sampling masquerading as full coverage," is therefore
**guaranteed to trip on every run**, caused by fixed code rather than by the model. C09 as scoped cannot be interpreted.

**Finding 4 — the holdouts are already burned.**
[`CASE-MATRIX.md`](CASE-MATRIX.md) publishes, in git, each holdout's Research Brief, source package, target failure mode, and an
explicit "Failures exposed" list. Withholding gold atoms later does not restore holdout value: anyone tuning prompts can read
the traps. H13/H14/H15 must now be treated as **core-visible**. A genuine holdout has to be designed privately from the start.

**What survives.** Ten core cases and two holdouts are admissible after changes. My original recommendation was **11 core + 3
holdout = 14**, with C12 deferred to v1.1. *(Superseded by §15: the reconciliation pass fills the twelfth slot without weakening
the set — see §13 and §15.)*

**One correction in Sol's favour.** Sol flagged C10/C11's risk as "may not meet the product's evidence-density gate for a full
30 minutes." I computed the actual gates. That risk is **unfounded, by orders of magnitude** — see §4.9.

---

## 2. Requirements review

[`REQUIREMENTS.md`](REQUIREMENTS.md) is well-organised and mostly traceable. Three requirements do not follow from the product
contract as implemented, and three necessary requirements are missing — the missing ones are what let C12 and C01 through.

### Requirements that overreach

| ID | Objection |
|---|---|
| **R04** | Asserts long documents are "partitioned … merged globally, and audited for coverage **rather than sampled or truncated**." True of the *document map* ([04-integrations/02 §2](../../../docs/04-integrations/02-source-discovery-large-docs-and-revision.md)). **False of evidence extraction**, which deterministically defers blocks and records `deferred_block_ids` ([02-pipeline/04](../../../docs/02-pipeline/04-output-aware-analysis-budget.md)). R04 as written silently expands the product contract and directly produced C09's flawed scope. Rewrite: coverage is *budget-bounded by design*; the benchmark tests hierarchical reasoning **within the covered span** plus **honest disclosure of deferral**. |
| **R08** | "Preserve genuine disagreement. Reconciliation must not collapse objections and responses…" Valid **intra-source only**. Cross-source disagreement has no implementing stage (Finding 1). Scope R08 to within-source objection/response typing for v1 and defer the cross-source half to M8. |
| **R09** | "…without turning different source roles into interchangeable evidence." Source *roles* are never shown to the coverage, prioritisation, or planning prompts — those templates receive briefs, claims and IDs only ([coverage_audit/1.0.0/user.md](../../../prompts/coverage_audit/1.0.0/user.md), [episode_plan/1.1.0/user.md](../../../prompts/episode_plan/1.1.0/user.md)). Role discipline is testable today only through `ClaimType` (`author_position` vs `scholarly_interpretation`) and evidence provenance. Restate R09 in those terms or it names a behaviour nothing can exhibit. |

### Requirements that are missing (add before freezing)

- **R13 — machine-usable text is a source-selection gate.** Every fixture must be born-digital, or carry an independently
  verified clean Unicode text layer, with the check recorded per source. REQUIREMENTS.md excludes OCR as a *measured concern* but
  never forbids selecting sources that *require* it. That gap is exactly how C12 reached "preferred package." This also protects
  `evidence_validator`, which demands the supporting excerpt appear **verbatim** in the block after whitespace normalisation.
  **Concrete validation procedure: §14.**
- **R14 — one ingested artifact per source.** Verification scans, facsimiles and parallel editions are *offline collation
  references* and must never be ingested alongside their transcription. C01-A currently lists both the Gutenberg transcript and
  the Library of Congress scan as package sources; ingesting both creates a near-duplicate corpus that distorts dedup, coverage
  denominators and claim reconciliation.
- **R15 — every case pins its output configuration.** `target_duration_minutes`, `modes`, `prior_knowledge` and `audience` all
  change the analysis profile deterministically: duration selects the tier, `critical`/`debate` adds **+10pp** coverage, and
  `advanced` raises claim caps and neighbour context ([analysis_profile.py:54-83](../../../src/thesisound/services/analysis_profile.py#L54)).
  [`CASE-MATRIX.md`](CASE-MATRIX.md) states a duration for **only C10 and C11**.

All three are **retained after the reconciliation pass**; §11.3 records that Sol's own rubric has matching blind spots, which is
independent support for adding them.

### Requirements that are sound

R01, R02, R03, R05, R06, R07, R10, R11, R12 follow from the product contract and need no change. R12's five-way redistribution
taxonomy is genuinely useful and I have reused it throughout.

---

## 3. Per-case verdict table (original independent judgment)

Formed **before** reading `SOURCE-RECOMMENDATIONS.md`. Preserved unchanged; §11 records what reconciliation did to each.

| Case | Verdict | Preferred package | Gold-authorable | Confidence | One-line reason |
|---|---|---|---|---|---|
| C01 | `ACCEPT_WITH_CHANGES` | accept w/ change | yes | high | Ingest one text only; the scan is a collation reference, not a source. |
| C02 | `ACCEPT_WITH_CHANGES` | accept w/ change | yes | medium | Licence is **CC BY-NC 4.0**, not "unresolved"; PDF text layer still unverified. |
| C03 | `ACCEPT_WITH_CHANGES` | accept w/ change | yes | high | Use the complete essay; non-contiguous chapters break the dependency chain being tested. |
| C04 | `ACCEPT_WITH_CHANGES` | accept w/ change | yes | medium-high | SEP dominance confirmed empirically; brief currently restates SEP's contents page. |
| C05 | `BLOCKED` | reject | no | high | Cross-source disagreement has no implementing stage (M8 not implemented). |
| C06 | `ACCEPT_WITH_CHANGES` | accept w/ change | yes | medium | Shrink corpus ~3×, pin endpoints, resolve licences. |
| C07 | `ACCEPT_WITH_CHANGES` | **accept** | yes | high | Verified CC BY 4.0; make abstention observable in the coverage artifact. |
| C08 | `ACCEPT_WITH_CHANGES` | accept w/ change | yes | medium-high | Decoys too small to cost anything; leakage vector is in-document headings, not filenames. |
| C09 | `REPLACE_SOURCE` | reject scope | yes (rescoped) | high | Full first edition exceeds the extraction budget ~3×; measures the selector, not the model. |
| C10 | `ACCEPT_WITH_CHANGES` | accept w/ change | yes | high | Pin the full brief config; acquire a born-digital copy (the JSTOR copy is a scan). |
| C11 | `ACCEPT_WITH_CHANGES` | accept w/ change | yes | high | 30 minutes is safely supportable — Sol's stated risk is unfounded. |
| C12 | `BLOCKED` | reject | no | high | 1906 = pure scan; 1907 = broken encoding **and** carries 1925 Pahlavi amendments. |
| H13 | `ACCEPT_WITH_CHANGES` | accept w/ change | yes | medium-high | Gold must license "no counterpart exists"; bound scope; UNESCO licence unverified. |
| H14 | `ACCEPT_WITH_CHANGES` | accept w/ change | yes | medium-high | Freeze one event class (**heat extremes**) — option B. |
| H15 | `REPLACE_SOURCE` | reject | yes (after swap) | medium | Khanlari unacquirable; a verified replacement critical edition exists. |

Totals: **0 accepted unchanged · 11 accepted with changes · 2 requiring a new source · 2 blocked.**

---

## 4. Detailed objections and required changes

*(Original independent judgment, preserved. §12 supersedes §4.9's duration figures only.)*

### 4.1 C01 — James, genuine option

Capability (contrastive concept network, EN→FA) is core to R10 and diagnostically clean: James's three axes are explicit,
enumerable and locatable. A model cannot pass on surface cues, because the essay's force lies in how the three conditions *combine*.

**Required changes.** (1) Ingest **one** text; the 1897 scan must be an offline collation reference only (R14). (2) Pin duration,
modes, prior_knowledge, audience (R15). (3) Record the collation result — Sol correctly flagged that the working transcript derives
from a 1912 impression.

### 4.2 C02 — Putnam, fact/value, Persian→Persian

The only case testing native Persian scholarly prose, and after C12 falls it becomes disproportionately important.

**Independent verification corrects Phase 1.** The publisher's article page states an explicit
**Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)** licence. Sol recorded `license: unresolved` and classified the
source `private_fixture`. **Reclassify as `conditional_commit`.** The publisher page also gives **volume 17, issue 68, Winter 1400,
pp. 123-153**, agreeing with DOAJ; the PDF masthead's "volume 16" is the outlier.

**Blocking sub-check.** I could not retrieve the PDF. Given what the same check revealed about C12, the Persian text layer must be
verified under R13 (§14) before acceptance.

### 4.3 C03 — Woolf

**Required changes.** Use the complete essay rather than non-contiguous chapters 1, 3 and 6: the work fits the budget whole, and
non-contiguous excerpting breaks the argument-dependency chain the case exists to test. Pin the output configuration. Gold must
constrain **typing** (assertion / qualification / historical claim / illustrative fiction) rather than segment ordering.

### 4.4 C04 — Du Bois + SEP (specifically investigated)

I fetched the SEP entry rather than reasoning from the title. The concern is **confirmed and stronger than Phase 1 states**.

The entry is *Double Consciousness* by John P. Pittman, first published 2016-03-21, **substantive revision 2023-02-16**. Its
structure is a ready-made answer key: §2 enumerates six named readings (2.1 Americanist Romantic Longing, 2.2 Color-Line
Hegelianism, 2.3 A Deflationist Reading, 2.4 An Analytic Politico-Philosophic Reconstruction, 2.5 Rousseauian Self-Estrangement,
2.6 Uses and Extensions); §3 is "Problems"; §4 tracks the concept *after Souls*. Roughly **55-60% of the entry is the taxonomy of
interpretations**, and it quotes Du Bois directly throughout.

Sol's brief asks the system to "explain how the scholarly commentary distinguishes possible meanings and historical developments."
**That is SEP's table of contents.** A model that reads only SEP produces a strong-looking answer.

**Required changes.** (1) Bound the commentary to §2.3 and §3 only, instead of "Sections 2-4." (2) Rewrite the brief so the answer
is unobtainable from SEP alone — e.g. *"Which of Du Bois's own formulations support, and which resist, reading double consciousness
as a permanent condition rather than a historically specific one?"* (3) Score primarily on `ClaimType` attribution
(`scholarly_interpretation` vs `author_position`), which is checkable today without M8.

Reject alternate `C04-B` (5 primary pages against 20-30 commentary pages maximises the dominance ratio). Credit: Sol correctly
pinned the SEP **archive** URL (`archives/sum2024/`), which handles revision drift properly.

### 4.5 C05 — Replication comment/response — `BLOCKED`

Semantically the best-conceived case in the set, and the one case the system provably cannot be measured on (Finding 1). Three
sources yield three isolated ledgers and an empty disagreement graph; a script could recite all three without relating them and
still satisfy `unsupported_claim_ratio == 0`. Operationally it is also the weakest: all three items are AAAS-copyrighted
`private_fixture`, so a public CI run cannot acquire them.

**Do not delete the design — defer it behind M8.** Replacement authored in §13.1.

### 4.6 C06 — Beyond GDP

With C05 gone, the only core case exercising multi-source composition. It degrades more gracefully than C05 because interleaving
two ledgers in the episode plan does happen without M8; only cross-source *reconciliation* is missing.

**Required changes.** Cut the corpus from 90-130 pages to roughly 40 (each report's executive summary plus one framework chapter).
Resolve both licences and pin a stable Stiglitz endpoint. Pin the output configuration.

### 4.7 C07 — Bounded WFH inference (specifically investigated)

**Verified independently:** Bloom, Han & Liang, *Hybrid working from home improves retention without damaging performance*,
**Nature 630:920-925 (12 June 2024)**, DOI `10.1038/s41586-024-07500-2`, **CC BY 4.0**; six-month RCT over **1,612** employees at
Trip.com, China, predominantly graduate-educated staff. Sol's record is accurate in every field.

**Is it too easy?** Keep it. The paper states its limits, so *prose hedging* is easy — but the behaviour that matters is the coverage
auditor's `recommendation` and `max_supported_minutes` feeding `can_plan_episode`, which requires `recommendation == "continue"`
**and** `max_supported_minutes >= round(target × 0.8)` ([coverage_auditor.py:13-28](../../../src/thesisound/services/coverage_auditor.py#L13)).
That is deterministic, non-gameable, and cannot be faked by a fluent hedging paragraph.

**Required change.** Make at least one learning objective **unanswerable by construction**, and record the expected abstention as
`not_covered` plus a `narrow_scope` recommendation in `coverage-report.json`.

### 4.8 C08 — Relevance filtering (specifically investigated)

**Good news Phase 1 missed.** Source *roles* and *titles* never reach the semantic prompts. Claims carry `source_id` UUIDs; the
coverage-audit and episode-plan templates receive only briefs, claims, priorities and IDs. **Filename- or role-based rejection is
impossible by that route.**

**The real leakage vector is different.** The evidence-extraction prompt receives the block JSON including `heading_path`
([evidence_extraction/1.3.0/user.md](../../../prompts/evidence_extraction/1.3.0/user.md)). A fixture whose H1 reads "Frederick
Douglass — Biography (National Park Service)" leaks its role through the *document's own headings*.

**A structural mismatch that must be documented.** The harness ingests every source and calls `analyze_source` on all of them
([eval_harness.py:231-257](../../../src/thesisound/services/eval_harness.py#L231)); uploaded sources are registered `full_text` +
`include` with no triage stage. C08 measures **claim-level relevance**, not source triage.

**Required changes.** Neutralise in-document headings and front matter; enlarge decoys to ~25-30% of corpus so admitting them
visibly costs episode minutes; add a **partially relevant** decoy; re-label the case. Reject `C08-B` (one decoy gives too little
diagnostic power — Sol's own assessment, and correct).

### 4.9 C10 / C11 — Duration control (specifically investigated)

*(Corpus measurements and gate arithmetic below stand. The 5/30 configuration is superseded by §12.)*

**The corpus.** I retrieved a full copy: 33 pages, **18,907 words** total, so roughly **15-16k words** of analysable body after the
JSTOR cover page and the reference list (which `_is_note_like` excludes from the coverage denominator anyway) — call it ~21k tokens.

**Is 30 minutes safely supportable? Yes, comfortably.**

1. *Evidence-density gate.* `evidence_supported_minutes = original_evidence_tokens / 20`
   ([episode_budget.py:49-53](../../../src/thesisound/services/episode_budget.py#L49)). Thirty minutes needs **600 tokens**; the
   corpus has ~21,000. Clears by ~35×.
2. *Claim-time gate.* Thirty minutes needs 450 claim-seconds, and `estimated_explanation_seconds` has a floor of 15
   ([episode.py:65](../../../src/thesisound/episode.py#L65)). Thirty claims at the floor already clear it.
3. *Output-to-source ratio.* At 130 wpm a 30-minute Persian episode is ~3,900 words against ~15,000 source words. That is
   selection and explanation, not padding — and `explanation_expansion_factor = 4.0` encodes the expectation that claim time
   *expands* for examples, transitions and dialogue.

**Sol's stated risk is unfounded.**

**The real risk is the opposite one.** Because every deterministic gate clears so easily, the only binding constraint is the
*model's own* `max_supported_minutes`. The pair needs a **defined differential metric** at gold time — distinct-claim count and
distinct-atom coverage at the long duration vs the short one, plus repetition rate — not merely "both cases passed."

**Required changes.** Pin `modes`, `prior_knowledge`, `audience`, `output_language` **identically**; a stray `critical` mode
(+10pp coverage) or `advanced` prior_knowledge (+1 claim, +1 neighbour) would silently break the control. Acquire a
**born-digital** copy: the Nobel URL returned **HTTP 403** and the freely reachable copy is a **JSTOR scan with an OCR text layer**
(33 pages, 33 embedded images). Licence unresolved → `private_fixture`.

### 4.10 C12 — Persian constitutional law — `BLOCKED`

Established in Finding 2. Sol marked the 1907 source `partially_verified` because "automated direct retrieval returned an access
error." **That specific blocker is resolved — I retrieved the file successfully.** Retrieval was never the real problem; the file's
contents are. Replacement search: §13.2.

**On Arjomand.** *Constitutional Revolution iii* is a strong, compact specialist entry and not wrong in principle. But paired with
an unreadable primary text it would guarantee the C04 dominance defect in acute form: the only legible source would be the
interpretation.

### 4.11 H13 — UNESCO + NIST (specifically investigated)

The asymmetry is real: UNESCO is normative (values, principles, policy areas); NIST AI RMF is operational (functions, practices).
Several UNESCO policy areas have no NIST counterpart and vice versa. A gold that presupposes correspondence would be **wrong**.

**Repairable and worth keeping.** (1) The brief must **license absence explicitly**. (2) Require **typed relations** —
`operationalizes` / `partially_addresses` / `no_counterpart` / `in_tension` — not a mapping table. (3) Gold must include licensed
non-mappings and explicit **must-not-assert** atoms, chiefly that neither document is evidence any practice *works*. (4) Bound the
corpus from ~92 pages to UNESCO's values/principles/policy-areas plus the NIST Core, ~45-55 pages.

**Verification gap.** UNESDOC returned HTTP 403; Sol's `CC BY-SA 3.0 IGO` is **unverified**.

### 4.12 H14 — Event attribution (specifically investigated)

**Choose B — freeze on heat extremes.** The deciding criterion is stable ground truth, not difficulty. Option A produces gold that
is effectively a methods lecture: few checkable atoms, enormous legitimate variation, and it would force one arbitrary reference
summary to become "the answer." Option B inherits AR6 WGI Ch.11's **calibrated confidence language attached to a specific event
type**, yielding exactly the atoms needed: occurrence vs changed probability vs changed intensity, an explicit likelihood term, an
explicit confidence level, quotable locators. Heat extremes carry the clearest calibrated statements, making both the correct
answer and the overclaiming failure sharply detectable. It also shrinks the corpus from 50-80 pages to the Executive Summary plus
the heat-extremes section.

**Licence caution.** IPCC material is **CC BY-NC-ND**; the no-derivatives term obstructs *transforming* text into fixtures. Bellprat
et al. 2019 is consistent with Nature Communications' standard CC BY 4.0 but my lookup resolved to a different article — **treat as
unconfirmed**.

### 4.13 H15 — Hafez (specifically investigated) — `REPLACE_SOURCE`

**Khanlari verification.** *Divān-e Hāfez*, ed. Parviz Natel-Khanlari, **Khwarazmi, Tehran, 1362 SH**, two volumes, established from
fourteen manuscripts. It is **in copyright and commercially in print**, and the only digital copies in circulation are unauthorised.
No lawful digital acquisition path exists. Sol's `unresolved` is right.

**Worth keeping the capability, not the source.** Constitutive literary ambiguity with contested terminology is exercised nowhere
else, and with C12 blocked it is one of only two remaining Persian-primary cases. A materially better package exists — §6.1.

Reject `H15-B` (manuscript MS.PERS.29): paleography would contaminate a semantic benchmark, and a single sixteenth-century witness
is not a critical edition. Sol's own risk note says the same.

**Commentary dominance.** Lewis's *Hafez viii. Hafez and Rendi* is an entry **about rendi** — it supplies the interpretive
vocabulary the brief asks the system to derive. This is the C04 defect again.

---

## 5. Independent source-verification findings

Verified by me, from primary/publisher/institutional sources or by direct inspection. I did **not** rely on Sol's `verified` labels.

| Source | Sol's claim | My finding | Effect |
|---|---|---|---|
| `iran_fundamental_law_1906_fa` | `full_text: verified`, 12 pages | 12 pages, **0 extractable chars**, 12 embedded images — **pure image scan** | **Contradicted.** OCR mandatory → C12 blocked |
| `iran_supplement_1907_fa` | `partially_verified`; retrieval error | **Retrieved successfully** (26 pp). But 3,058 chars / 618 words; 626 NULs; 1,453 presentation-form glyphs. Contains **پهلوي / قاجاريه / ولايتعهد** → consolidated text incl. **1925 amendment** | **Contradicted, both ways.** Retrieval fine; content unusable **and** wrong vintage |
| Iran Data Portal | licence `unresolved` | Confirmed: "© Syracuse University", no reuse terms | Confirms Sol |
| `ebadi_emdadi_putnam_2021` | licence `unresolved`; `private_fixture` | Publisher states **CC BY-NC 4.0**; **vol 17, iss 68, Winter 1400, pp. 123-153**; DOAJ agrees, PDF masthead is the outlier | **Corrected.** Upgrade to `conditional_commit` |
| `bloom_han_liang_hybrid_2024` | Nature 630:920-925, CC BY 4.0 | Confirmed in every field; N=1,612, Trip.com China, 6-month RCT | Confirms Sol |
| `pittman_double_consciousness_sep` | 2016, rev. 2023; scope "Sections 2-4" | Confirmed. **~55-60% is the interpretation taxonomy**; six named readings; quotes Du Bois throughout | Confirms bibliography; **substantiates the dominance objection** |
| `darwin_origin_1859` | PG #1228, 1859 first edition, PD USA | Confirmed exactly | Confirms Sol |
| `ostrom_beyond_markets_states_2009` | 32 pp; nobelprize.org listed stable | Nobel URL → **HTTP 403**. Reachable copy = **JSTOR scan + OCR layer**, 33 pp, 18,907 words, 33 images | **Reproducibility defect** |
| `hafez_khanlari_divan_1984` | `unresolved`, not lawfully acquired | Confirmed: Khwarazmi, Tehran, 1362 SH, 2 vols, 14 manuscripts; in copyright, in print | Confirms Sol |
| `unesco_ai_ethics_2021` | CC BY-NC-SA 3.0 IGO | **Unverified** — UNESDOC HTTP 403 | Mark unresolved |
| `bellprat_event_attribution_2019` | CC BY 4.0 | **Unverified** — lookup resolved to a different article | Mark unresolved |
| `hafez_qazvini_ghani` *(new, mine)* | not in Phase 1 | fa.wikisource hosts a scan-backed, **fully proofread and validated** transcription (~430 pp) of the Qazvini-Ghani critical edition | Basis for the H15 replacement |
| `mill_utilitarianism_1863` *(new, §13.1)* | not in Phase 1 | PG #11224, PD in USA, plain-text UTF-8 born-digital; ch. II is an explicit sequence of stated objections with Mill's replies | Basis for the C05 replacement |
| `laws.tehran.ir/Law/MainLawView/245` *(new, §13.2)* | not in Phase 1 | Full متمم text as **selectable HTML**, 107 articles, authentic opening formula; but all-rights-reserved footer and **unverified vintage** | Partial path for C12 |

**Unresolved and explicitly not claimed as verified:** the UNESCO licence; the Bellprat licence; the C02 PDF text layer; the
Qazvini-Ghani rights determination and exact printing; the vintage of the `laws.tehran.ir` constitutional text; every corpus
page-count estimate in `CASE-MATRIX.md` other than those above.

---

## 6. Proposed replacements

### 6.1 H15 primary — replace Khanlari

**H15-C (recommended).** *Divān-e Hāfez*, critical edition of **Muhammad Qazvini & Qasem Ghani (1320 SH / 1941)**, from the Persian
Wikisource proofread transcription pinned to a specific revision ID, plus **bounded** excerpts of Lewis, *Hafez viii*, and de Bruijn,
*Hafez iii*.

Why materially better than the preferred package:
- A genuine **critical edition** — the first scholarly critical edition of the Divan, 495 ghazals, established against the
  Khalkhali manuscript (827 AH). Not a "generic web transcription."
- The transcription is **scan-backed and fully validated** ("همهٔ برگ‌های این اثر هم‌سنجی شده و درست هستند"), giving born-digital
  clean Unicode **with page-level locators** that map to a printed edition — satisfying R13 and R03 together.
- **No manuscript paleography and no OCR.**
- The acquisition blocker disappears entirely.
- Editors died 1949 and 1952, making the rights position far more tractable than Khanlari's.

Still required: pin the Wikisource **revision ID**; human-collate the selected ghazals against the page scans; obtain a documented
rights determination; select ghazals from the *scholars'* citations rather than reviewer taste.

**H15-D (leaner variant).** Same primary, **one** secondary (Lewis). Halves commentary volume, mitigating interpretive dominance.

**H15-E (fallback).** Swap the primary to **Sa'di's *Golestan*** in a public-domain scholarly edition (Foroughi, d. 1942) plus one
specialist entry. **Not verified in detail — a named fallback, not a recommendation.**

### 6.2 C09 rescope

Darwin 1859 (PG #1228), **chapters I-IV + VI + XIV**, ~60-70k words ≈ ~90k tokens. At 40 minutes the 72k budget yields ~80%
coverage, so the system sees the prerequisite chain: mechanism defined early, objections mid-book, synthesis depending on both.

---

## 7. Holdout-integrity design *(original)*

**The current architecture does not produce holdouts.** `CASE-MATRIX.md` commits each holdout's brief, sources, capability and
"Failures exposed" to public git history. Withholding gold atoms afterwards protects almost nothing. Phase-1 design rule 6 mistakes
*gold secrecy* for *holdout integrity*.

**Consequence to accept honestly:** H13, H14 and H15 as published are **burned**.

*(The reconciliation pass adopts this conclusion as policy and specifies the replacement architecture in §15.)*

---

## 8. Dataset-level redundancy and coverage audit *(original)*

**Failure-mode coverage.** Good over evidence fidelity, qualification, compression/depth, relevance and abstention. Two real gaps:
**cross-source disagreement** (deferred to M8) and **Persian primary sources**, which collapses from three cases to two when C12
is blocked.

**Accidental redundancy.** Less than feared. C01/C02 differ on the axis the product cares about (EN→FA vs FA→FA). C10/C11 is
deliberate. C04 and a repaired H15 both test primary-vs-secondary attribution and stay distinct only if H15's secondary scope is
bounded. **C06 and H13 are the weakest-differentiated pair.**

**Language diversity.** Weak after the cuts — the set's most serious imbalance, sitting exactly where the product's risk is
highest, since the output is always Persian.

**Single vs multi-source.** Given that multi-source reconciliation is unimplemented, the tilt toward multi-source is currently too far.

**Corpus-size distribution.** Badly skewed before rescoping; C09 alone would consume roughly a quarter of suite tokens.

**Execution cost.** Selected evidence-extraction input across the set is on the order of 300k+ tokens, and extraction runs **one
model call per selected block**, so call count is the driver. This suite is a **release gate, not a per-PR check.**

**Legal and reproducibility burden.** The most under-weighted risk in Phase 1. Only C07, C09, C03, C01 and (with the NC caveat) C02
are plausibly committable; the rest need a private fixture store or a public CI run will silently degrade to "skipped."

---

## 9. Readiness for the gold-authoring phase *(original)*

**Gold-authorable after the stated changes:** C01, C02, C03, C04, C06, C07, C08, C09 (rescoped), C10, C11, H13, H14 (option B),
H15 (after source swap), and the C05 replacement.

**Not gold-authorable:** **C05** as designed — correct behaviour is a *relation between sources* the system cannot represent.
**C12** as designed — the source text is neither complete, legible, nor correctly dated.

**Cases needing care to avoid arbitrary-summary gold:** **H13** (mapping is many-to-many-to-none), **H14** (why option B is
required), **H15** (gold must specify which readings must remain *open*). C03 needs the same discipline in weaker form.

**A structural asset Phase 1 did not exploit.** Much of what this benchmark wants to measure is already representable in existing
artifacts — `ClaimType`, `support_status`, `coverage-report.json`'s per-objective status and `recommendation`,
`claim-priorities.json`, `deferred_block_ids`, `budget-report.json`. Gold should be anchored to those fields wherever possible.

---

## 10. Exact blockers before freezing *(original list; see §15 for the reconciled list)*

B1 remove C05 · B2 restate R04/R08/R09 · B3 remove C12 · B4 replace H15 primary · B5 rescope C09 · B6 verify C02 text layer ·
B7 born-digital Ostrom · B8 resolve UNESCO/Bellprat/C06 licences · B9 pin output configuration · B10 rewrite C04 brief ·
B11 rewrite H13 brief · B12 narrow H14 · B13 repair C08 fixtures · B14 apply R14 · ~~B15 missing SOURCE-RECOMMENDATIONS.md~~
**(withdrawn — see §11.1)** · B16 implement holdout structure.

---

# 11. Reconciliation against `SOURCE-RECOMMENDATIONS.md`

Read **after** all fifteen verdicts were formed. Sol's `score_total_50` values were not used as evidence at any point.

## 11.1 Status of blocker B15 — withdrawn

The file was withheld deliberately to prevent anchoring. Its absence was **not** a Phase-1 defect and B15 is withdrawn.

The ranking method turns out to be sound and auditable: ten criteria — Authority, Provenance, Semantic challenge, Failure-mode fit,
stable Reproducibility, Accessibility, Licensing practicality, Corpus size/cost, low Noise, Independence — each 1-5, **deliberately
unweighted so that a high-authority source cannot hide an access or licensing failure**, with the explicit caveat that "Low licensing
scores are not waivers." That is a better-designed rubric than I assumed in its absence, and I record that correction.

Residual, non-blocking: the file is untracked in git. Committing it is an audit-trail task.

## 11.2 Preferred-package agreement

**Sol and I selected the same preferred package in all 15 cases.** There is no case where I preferred one of Sol's alternates.
Every divergence is about *whether the agreed package is usable*, or about scope/brief repair — never about which candidate ranks first.

Confirming that independently is worth something: two models working separately from the same candidate pool converged on the same
packages, so the disagreements below are about verification depth, not taste.

## 11.3 Rubric blind spots

Three gaps explain why a well-designed rubric still passed unusable packages — and each independently supports one of my proposed
requirements.

| Blind spot | Evidence | Supports |
|---|---|---|
| **No criterion scores whether the text is machine-usable.** Accessibility (X) scores whether the file is *obtainable*, not whether it *parses*. | `C12-A` scores X=4, R=3 — defensible if only the collection page was opened. Opening the files shows 0 extractable characters and 618 words of glyph fragments. | **R13** + new criterion **T (text usability)**, scored only after opening the file |
| **No criterion scores fit against *implemented* capability.** Failure-mode fit (F) measures fit against the documented product. | `C05-A` scores F=5. The fit is perfect against the docs and impossible against the running system. | A hard precondition: a stage must exist that can exhibit the measured behaviour |
| **No criterion penalises ingesting a verification scan as a corpus source.** | `C01-A` scores **50/50** with P=5 while listing both the Gutenberg transcript and the LoC scan as package sources. | **R14** |

## 11.4 Per-case reconciliation

| Case | Sol's preferred | Same as mine? | Agree? | New evidence in Sol's reasoning? | Verdict change |
|---|---|---|---|---|---|
| C01 | C01-A (50/50) | yes | on package | No. Sol's collation risk matches mine and I adopted it. Sol did not notice the two-artifact defect. | **None** |
| C02 | C02-A | yes | on package | No. Sol's "no reuse licence found" is refuted by the publisher page (CC BY-NC 4.0). | **None** |
| C03 | C03-A | yes | yes | No, but Sol named the hypothesis first: "non-contiguous chapter selection can manufacture an argument." My "use the whole essay" is the concrete form of Sol's own concern. Credit recorded. | **None** |
| C04 | C04-A | yes | on package, not on confidence | No. Sol states the objection precisely — "SEP's taxonomy is so clear that a model may reproduce it while under-reading Du Bois" — then rates confidence **High** and lets the package pass unchanged. Naming a risk is not mitigating it. | **None** |
| C05 | C05-A | yes | no | No. Sol's objection is **operational only** (copyrighted, not always versions of record). It does not reach the architectural blocker; fixing access would not make the case measurable. | **None — stays BLOCKED** |
| C06 | C06-A | yes | yes | No. Sol's selection-effect risk matches my corpus-shrink requirement. | **None** |
| C07 | C07-A (49/50) | yes | yes | No, and Sol independently raised the "too easy" question I was asked to test. We reach the same answer for different reasons: Sol on realism, me on the deterministic coverage artifact. | **None** |
| C08 | C08-A | yes | partially | **Partially refuted.** Sol's stated vector — "obvious filenames or source-role labels" — does not exist: neither reaches the semantic prompts. The real vector is `heading_path`. Sol's confidence qualifier guards the wrong thing. | **None** |
| C09 | C09-A | yes | on source, not scope | No. Sol penalises size only as **cost** (C=2) while scoring F=5. Failure-mode fit is not 5: the planner defers ~64% deterministically, so the case cannot exhibit the behaviour it scores for. | **None** |
| C10 | C10/11-A | yes | yes | Sol's objection — a five-minute brief may force omission "that reviewers personally consider essential, making later gold brittle" — is a **good point I had not made**. It is now moot: §12 replaces 5 minutes with 20. | **Configuration changed** (§12) |
| C11 | C10/11-A | yes | on package, not on risk | **Refuted by arithmetic.** The gate needs 600 tokens for 30 minutes; the corpus carries ~21,000. Sol's reasoning is sound in principle — "the correct pipeline behaviour could be to reject/narrow" — but the premise is false here. | **Configuration changed** (§12) |
| C12 | C12-A | yes | no | No. Sol flagged the unopened 1907 PDF, which was good practice. Opening it converts one risk into two disqualifying facts plus a companion pure image scan. | **None — stays BLOCKED** |
| H13 | H13-A | yes | yes | No. Sol identifies the same artificiality — "not written as counterparts… may encourage false equivalence" — and, unlike C04, does not let it pass silently. My contribution is the specific repair. | **None** |
| H14 | H14-B | yes | yes | No. Sol poses the identical A/B choice and defers it. I chose B on gold-stability grounds. | **None** |
| H15 | H15-A *conditional* | yes | yes, fully | No new evidence, but Sol's handling is the strongest in the document: confidence **"Low until acquisition/collation; do not freeze"** already refuses the package, and Sol independently raised that expert poem selection could bake in a reading — a risk I adopted. My contribution is the replacement, not the diagnosis. | **None** |

**Net effect: zero verdicts changed on the evidence in `SOURCE-RECOMMENDATIONS.md`.** C10 and C11 change configuration, but under
§12's product-contract correction, not under Sol's reasoning.

## 11.5 Pattern

Sol's objections are **accurate wherever they rest on bibliographic reasoning**, and **miss wherever the answer required opening a
file or reading the pipeline code**. Every one of my four cross-cutting findings falls in the second category. Sol also stated the
core risk for C03, C04, C07, C08, C10, H13 and H15 — the diagnostic instinct was largely right; what was missing was the step from
naming a risk to acting on it, which shows most sharply at C04 (risk stated, confidence still High).

---

# 12. Product-contract correction: does 20/40 replace 5/30?

**Decision: yes. Adopt the 20-minute / 40-minute pair. Drop 5/30.**

The MVP contract defines output as a **20-40 minute** private episode
([01-product-scope](../../../docs/01-foundations/01-product-scope.md)). The 5-minute member tested a duration the product does not
ship. I did **not** retain 5 minutes merely because Phase 1 proposed it.

## 12.1 Computed against the current implementation

All figures from [`analysis_profile.py`](../../../src/thesisound/services/analysis_profile.py) with the measured Ostrom corpus
(~21,000 analysable tokens):

| Lever | 5 min | **20 min** | 30 min | **40 min** |
|---|---|---|---|---|
| Tier | `brief` | **`standard`** | `deep` | **`deep`** |
| `block_coverage_target` | 0.35 | **0.60** | 0.85 | **0.85** |
| `coverage_tokens` = ⌈total×c×1.1⌉ | 8,085 | **13,860** | 19,635 | **19,635** |
| `evidence_input_token_budget` | 12,000 | **36,000** | 54,000 | **72,000** |
| Effective target = min(total, cov, budget) | 8,085 | **13,860** | 19,635 | **19,635** |
| Achieved coverage | 38.5% | **66%** | 93.5% | **93.5%** |
| `max_claims_per_block` | 2 | **3** | 5 | **5** |
| `neighbor_context_blocks` | 0 | **0** | 1 | **1** |
| `include_examples` | False | **True** | True | **True** |
| `include_objections_and_responses` | False | **False** | True | **True** |
| `can_plan_episode` needs `max_supported ≥` | 4 | **16** | 24 | **32** |
| Persian script words @130 wpm | 650 | **2,600** | 3,900 | **5,200** |

## 12.2 What the comparison shows

**A finding worth stating plainly: 30 and 40 minutes produce an *identical* analysis profile.** Both fall in `deep` (26-45), so the
extraction stage cannot distinguish them at all. The entire depth contrast in a 20/40 pair comes from the **20-minute member
crossing into `standard`**; choosing 40 over 30 changes only the episode/script stage — a harder supported-duration bar (32 vs 24)
and 33% more script.

**20/40 preserves three of the four contrast levers, and the two that matter most.**

| Lever | 5/30 | 20/40 | Assessment |
|---|---|---|---|
| Token coverage spread | 38.5→93.5 (55 pp) | 66→93.5 (**27.5 pp**) | Narrower but still substantial — ~40% more source material analysed |
| Claim cap | 2→5 | **3→5** | Narrower; still a 67% increase |
| Neighbour context | 0→1 | **0→1** | **Identical — preserved** |
| Objections/responses | False→True | **False→True** | **Identical — preserved** |
| Examples | False→True | True→True | **Lost** — the only casualty |

The two preserved levers are the semantically important ones: `neighbor_context_blocks` and `include_objections_and_responses`
change **what evidence exists at all**, not merely how much. `include_examples` is the least consequential of the four, and losing
its contrast is an acceptable, documented reduction.

## 12.3 Is 40 minutes supportable? Yes

- *Evidence-density gate:* 40 × 20 = **800 tokens** required; corpus has ~21,000 — a 26× margin.
- *Claim-time gate:* 600 claim-seconds required; a `deep` run over ~40 blocks at up to 5 claims/block yields far more, and the
  per-claim floor is 15 s.
- *`can_plan_episode`:* needs model-reported `max_supported_minutes ≥ 32`. The deterministic estimator will report well over 100.
  The only real constraint is the coverage auditor's own judgement — which is precisely the interesting thing to measure.
- *Output ratio:* 5,200 Persian words from ~15,000 source words. With `explanation_expansion_factor = 4.0` encoding the expectation
  that claim time *expands* for examples, transitions and dialogue, this is comfortably selection-and-explanation, not padding.

## 12.4 Bonus the old pair did not provide

20 and 40 are the **endpoints of the MVP output band**. The pair now validates the contract's stated range directly, which 5/30
never did.

## 12.5 Adopted configuration

- `C10` → **`ostrom_20min_standard`**, `target_duration_minutes = 20`
- `C11` → **`ostrom_40min_deep`**, `target_duration_minutes = 40`
- Everything else — corpus, brief text, `modes`, `prior_knowledge`, `audience`, `output_language` — pinned **identically**. A stray
  `critical`/`debate` mode (+10 pp coverage) or `advanced` prior_knowledge (+1 claim, +1 neighbour) voids the control.
- Record the lost `include_examples` contrast in the case notes so a future reviewer does not mistake it for an oversight.
- Sol's C10 objection — that a 5-minute brief may force omissions reviewers consider essential, making gold brittle — is
  **resolved by this change**: at 20 minutes the compression is far less severe.

---

# 13. Replacements for the blocked cases

## 13.1 C05 replacement — Mill, *Utilitarianism* (verified)

The instruction was a diagnostically distinct single-source objection/response case that works with today's pipeline and **avoids
overlap with C09**. My first-pass suggestion (Darwin ch. VI) is withdrawn precisely because it overlapped C09.

**Package `C05R-A`: John Stuart Mill, *Utilitarianism* (1861/1863), Project Gutenberg #11224.**

**Verified independently:** PG #11224, "Utilitarianism", Mill (1806-1873), released 2004-02-01, last updated 2024-10-28, **public
domain in the USA**, available as **plain-text UTF-8 (179 kB) and HTML** — born-digital, no OCR, passes R13 by construction.
`commit_safe`.

**Why it fits the failure mode.** Chapter II is organised as an explicit sequence of objections stated in the objector's voice and
then answered — utility is opposed to pleasure; utilitarianism glorifies base pleasures; happiness is unattainable; impartiality is
too demanding; utilitarians will make self-serving exceptions; it makes people cold calculators. Each is *stated as someone else's
position* before Mill replies.

**Why it is measurable today.** Every relevant mechanism is single-source and implemented: the document mapper assigns `objection`
and `response` section functions; `ClaimType.COUNTERARGUMENT` exists alongside `AUTHOR_POSITION`; and the reconciler is explicitly
forbidden to merge an objection with its response or to convert criticism into an author position
([03-one-source-evidence-pipeline §5](../../../docs/02-pipeline/03-one-source-evidence-pipeline.md)). The target failure —
**attributing a stated objection to Mill as his own view** — is directly detectable in the claim ledger. No M8 dependency.

**Why it does not overlap C09.** Different source, author, century-of-argument, and domain (moral philosophy vs natural science),
and a different failure mode: C09 tests *long-range prerequisite ordering* across a long monograph; C05R tests *dense, local,
high-frequency dialectical voice attribution* in a short text.

**Scope and cost.** Whole book ~30k words ≈ ~40k tokens. At 25 minutes (`standard`): target = min(40k, 26.4k, 45k) = **26,400
tokens (66%)** — a mid-sized, cheap case.

**Residual overlap to declare, not hide.** C05R shares a *claim-typing family* with C03 (Woolf), which tests assertion vs
qualification vs illustrative fiction. The specific distinction differs — rhetorical device typing vs dialectical voice — but the
family is shared and should be recorded.

**A dataset-level caution this creates.** With C01 (James), C03 (Woolf), C05R (Mill) and C09 (Darwin), **four of twelve core cases
are Victorian-era English prose**. Domains differ, but the register does not, so a regression in archaic-English handling would hit
four cases at once and the failures would be correlated — reducing effective information. Recorded in §15; no fifth Victorian text
should be added.

## 13.2 C12 replacement search — no defensible replacement yet

I searched for a clean, provenance-controlled, machine-usable Persian primary text of the 1906/1907 laws. **Result: the "no clean
Persian text exists" problem is solved in principle, but the provenance problem is not — so C12 stays blocked.** I did not
substitute a source I could not verify.

What I established:

- **`laws.tehran.ir/Law/MainLawView/245`** carries the full متمم as **selectable born-digital HTML**, **107 articles**, opening with
  the authentic formula *«بسم الله الرحمن الرحیم اصولی که برای تکمیل قوانین اساسیه مشروطیت دولت علیه ایران…»*. It would pass R13
  where the Iran Data Portal PDFs fail catastrophically.
- **But two blockers remain.** (a) **Vintage unverified** — it is a *current* municipal legal database that also presents
  "additional clauses and amendments" and cites no source edition. Whether it reproduces the 1907 text as enacted or a consolidated
  text is exactly the defect that disqualified the Iran Data Portal file, and resolving it requires reading اصل ۳۶ against a
  scholarly edition. (b) **Rights** — the footer reserves all rights to the Tehran City Council.
- **Persian Wikisource is not a clean alternative here.** Unlike the Hafez case, where I verified a fully-proofread, scan-backed
  index, the constitutional pages are a tangle of redirects and version pages (`متمم قانون اساسی` is a redirect flagged for
  transfer; `متمم قانون اساسی مشروطه` is a versions page) with **no visible proofreading status and no scan backing**.

**Decision: leave C12 out of v1 and do not force its slot.** The capability it carried — Persian-primary + cross-language +
source-role attribution — is **substantially preserved by promoting the repaired Hafez case into the visible core** (§15), which is
Persian-primary with English secondary scholarship and an explicit primary-vs-interpretation boundary. What is genuinely lost is
narrower than it first appears: the *legal/institutional domain* and the *primary legal instrument* form, not the underlying
capability. That is a domain gap, not a coverage gap, and it does not justify freezing an unverified source.

**Bounded v1.1 task** (small, human, well-defined): determine the vintage of the `laws.tehran.ir` text by comparing اصل ۳۶ against a
scholarly edition; identify a citable source edition; resolve rights. If it proves to be the text as enacted, C12 returns with its
original design intact.

---

# 14. R13 — concrete pre-freeze text-usability validation procedure

Retained and specified. Runs once per fixture file before freezing; output is committed as `text-usability.json` beside the source
manifest. Every gate is fail-closed: a fixture that cannot be measured is rejected, never assumed clean.

**Step 0 — extract through the production path.** Use the repo's own parser route (`thesisound parse --parser auto`), not an ad-hoc
tool, so the check measures what the pipeline will actually see.

**Step 1 — record the raw profile.** Page count; extractable characters; words; embedded image count; characters per page.

**Gate A — text presence.** Reject if extractable characters ≈ 0, or if characters-per-page falls below a prose floor
(≈800 for body text). *This gate alone rejects the C12 1906 file: 0 characters across 12 pages, 12 embedded images.*

**Gate B — encoding sanity.** Reject on any of:
- NUL (U+0000) present;
- characters in **Arabic Presentation Forms-A (U+FB50-U+FDFF)** or **Presentation Forms-B (U+FE70-U+FEFF)** — these indicate
  glyph-level encoding with no proper Unicode mapping;
- Private Use Area characters (U+E000-U+F8FF);
- replacement character U+FFFD count > 0.

*This gate rejects the C12 1907 file: 626 NULs and 1,453 presentation-form characters.*

**Gate C — Persian-specific checks** (mirroring the normalisation in
[`document_identity.py`](../../../src/thesisound/services/document_identity.py)):
- **Script ratio:** ≥95% of letters in the Arabic block (U+0600-U+06FF) for Persian fixtures.
- **Letter forms:** record counts of Persian ی (U+06CC) / ک (U+06A9) versus Arabic ي (U+064A) / ك (U+0643). Mixed forms are not
  fatal but must be normalised consistently and the counts recorded.
- **ZWNJ:** record U+200C count. **Zero ZWNJ in a long Persian text is a red flag** for lossy extraction — نیم‌فاصله should appear.
- **Digits:** record the Persian/Arabic-Indic versus ASCII digit mix.
- **Bidi sanity:** confirm embedded Latin/numeric runs are not reversed.

**Gate D — round-trip excerpt matching (the decisive gate).** This is what production enforces, so it is what predicts failure.
Sample **N = 20** random 40-character spans from the extracted text and verify each matches **verbatim** in the parsed block text
after whitespace normalisation, using the repo's own `excerpt_matching` / `evidence_validator` normalisation. **Any failure rejects
the fixture.** A source that fails here would make `evidence_validator` block every claim, and the case would appear to fail
semantically while actually failing on encoding.

**Gate E — human spot-check.** A reader fluent in the fixture language confirms that three randomly chosen pages read correctly and
that reading order is right — RTL/LTR mixing, footnote interleaving, table and verse layout. Required for **all** Persian fixtures
and for any English fixture whose Gate A-D margins are thin.

**Gate F — identity pinning.** Compute and record `parsed_document_key` and `block_sequence_key` so the fixture is pinned and any
later drift is detectable.

**Step 7 — provenance record.** Alongside the gates, record: source edition, publication year, retrieval URL and date, retrieval
HTTP status, and — for wiki-hosted transcriptions — the **exact revision ID**. A mutable source without a pinned revision fails R13
regardless of text quality.

**Applied retrospectively:** C12-A fails at Gates A, B and D. C10/C11's reachable Ostrom copy fails Gate A's spirit (33 embedded
images = scan-plus-OCR) and requires the born-digital substitute. C02 is **untested** and blocking. `C05R-A` (Gutenberg plain-text
UTF-8) and C09 (PG #1228) pass by construction.

**R14** and **R15** are retained unchanged; §11.3 shows Sol's rubric has matching blind spots, which is independent support.

---

# 15. Reconciled dataset-level result

## 15.1 Proposed final visible core — 12 cases

| # | Case | Capability slot | Status |
|---:|---|---|---|
| 1 | C01 James | EN→FA conceptual distinction network | accept w/ changes |
| 2 | C02 Putnam (FA) | FA→FA conceptual distinction; native Persian scholarly prose | accept w/ changes, **R13 check blocking** |
| 3 | C03 Woolf | argument + qualification; typing rhetorical/fictional devices | accept w/ changes |
| 4 | C04 Du Bois + SEP | primary vs secondary attribution | accept w/ changes |
| 5 | **C05R Mill *Utilitarianism*** | **single-source objection/response preservation** | **new replacement (§13.1)** |
| 6 | C06 Beyond GDP | complementary multi-source synthesis | accept w/ changes |
| 7 | C07 Bloom hybrid RCT | bounded inference, narrowing, abstention | accept w/ changes |
| 8 | C08 Douglass | claim-level relevance filtering, purposeful omission | accept w/ changes |
| 9 | C09 Darwin (rescoped) | long hierarchical dependency reconstruction | rescoped (§6.2) |
| 10 | **C10 Ostrom 20 min** | duration control — `standard` member | **reconfigured (§12)** |
| 11 | **C11 Ostrom 40 min** | duration control — `deep` member | **reconfigured (§12)** |
| 12 | **V15 Hafez (Qazvini-Ghani)** | **Persian primary + cross-language + interpretive ambiguity** | **promoted from burned holdout; source replaced (§6.1)** |

Promoting the repaired Hafez case into the core is what makes twelve defensible rather than arithmetic. It is Persian-primary with
English secondary scholarship, so it carries most of C12's intended capability, and it repairs the language-diversity gap that was
the set's most serious imbalance.

## 15.2 Visible challenge tier — non-gating

`V13` (UNESCO + NIST) and `V14` (IPCC heat extremes + Bellprat), formerly H13/H14. Executed and reported on every release run but
**not release-gating**, because their designs are public and their licences are unverified. They remain valuable regression signal;
they are simply no longer holdouts. V13 is also the weakest-differentiated case in the set (overlaps C06) and is the first
candidate for removal if suite cost becomes a problem.

## 15.3 Cases still blocked

- **C05 (original triptych)** — architectural. Returns in v1.1 behind M8. Its v1 slot is filled by C05R, which measures a
  genuinely distinct and *implemented* capability rather than standing in for it.
- **C12** — source provenance. Returns in v1.1 if the bounded task in §13.2 resolves the vintage and rights of a born-digital text.

## 15.4 Treatment of H13-H15

All three are **burned as holdouts** and reclassified: H15 → visible core (#12), H13 → V13 visible challenge, H14 → V14 visible
challenge. Their published briefs, sources, capabilities and failure lists remain in git history; no attempt is made to un-publish
them, because that would not restore holdout value and would damage the audit trail.

## 15.5 Three fresh hidden holdouts — coverage slots only

Per instruction, **only the required coverage slots are defined here. No brief, source, trap or gold is designed or revealed.**

The slots deliberately target the three behaviours that are simultaneously most product-critical and most tunable, so the holdouts
guard against overfitting the visible set rather than merely adding topics:

| Slot | Required coverage | Guards against overfitting |
|---|---|---|
| **HS-1** | Persian-primary semantic fidelity: a Persian source where fluent Persian paraphrase is tempting but verbatim excerpt support must hold. | C02 and V15 — the product's highest-risk path, since output is always Persian |
| **HS-2** | Output-aware depth control on a corpus never used in any visible case. | C10/C11 — the single most directly tunable behaviour in the pipeline |
| **HS-3** | Evidence insufficiency and correct narrowing on an unseen corpus. | C07 — and it protects the product's core promise that the system "refuses to pad an episode when the selected corpus is insufficient" (`PRODUCT.md`) |

**Binding constraints on all three**, to be satisfied at design time in the private bundle:

1. Single-source or otherwise **M8-independent** — no holdout may depend on unimplemented capability.
2. Must pass **R13** (§14) including a pinned revision or edition.
3. Must be `commit_safe` or `private_fixture` **with a documented acquisition procedure**, so release runs can actually execute.
4. **No source, author, publisher or corpus reused from any visible case**, or the holdout inherits visible-set tuning.
5. Sized for cost: none should exceed the median visible-case corpus.

**Public manifest — the maximum that may be committed.** `benchmarks/eval/holdout-manifest.json`, containing per case only:
opaque `case_id` (e.g. `HS-A1`, carrying no semantic hint), bundle **SHA-256**, bundle byte size, bundle schema version,
`created_at`, `last_executed_at`, runner version, and gate outcome (`pass` / `fail` / `skipped`). **Never** the brief, sources,
capability slot assignment, traps or gold. The slot *set* above is public; the *mapping* from slot to case ID stays private, so
coverage is auditable without revealing what any given holdout tests.

**Execution architecture** (small, no enterprise access control):

1. Holdout design and gold live in a **private git submodule** at `benchmarks/eval/holdout/`; the public repo commits only the
   submodule pointer. One `.gitmodules` entry, no new infrastructure, provenance stays version-controlled.
2. `thesisound eval --split core` (default) and `--split all`; `all` requires `THESISOUND_HOLDOUT_PATH`. When the bundle is absent,
   holdout gates report **`skipped`, never `pass`** — reusing the convention `evaluate_gates` already implements for unknown cost
   ([eval_harness.py:384-392](../../../src/thesisound/services/eval_harness.py#L384)), so this extends existing behaviour rather
   than inventing a mechanism.
3. Run holdouts **on release tags only**, with the bundle mounted from a CI secret. Publish per-case pass/fail and gate status only.
   **Never publish per-atom diffs** — that is the leak channel that would let ordinary tuning optimise against holdout design.
4. **Rotation:** a holdout is partly consumed the first time its failures are debugged. Budget one rotation per release cycle and
   keep at least one reserve case designed but unreferenced.
5. A CONTRIBUTING note that prompt changes must not be authored while reading holdout outputs. Unenforceable alone — which is why
   step 3 matters.

## 15.6 Does 20/40 replace 5/30?

**Yes.** Adopted. See §12 for the full computation. It stays inside the MVP contract, preserves the two qualitative depth levers
(`neighbor_context_blocks` 0→1 and `include_objections_and_responses` False→True) plus a 27.5 pp coverage spread and a 3→5 claim
cap, sets a harder supported-duration bar (32 vs 24 minutes), and validates the contract's stated output endpoints. The only loss is
the `include_examples` contrast, which is documented and accepted.

## 15.7 Replacement work required

| Item | Work | Size |
|---|---|---|
| C05R | Author brief; pin scope and output configuration | small — source verified, `commit_safe` |
| V15 | Pin Wikisource revision; human-collate selected ghazals; rights determination; bound secondary scope | medium — the largest remaining human task |
| C09 | Rescope to chs. I-IV + VI + XIV | small |
| C10/C11 | Reconfigure to 20/40; acquire born-digital Ostrom | small + one acquisition |
| C02 | Run R13 (§14) on the Persian PDF | small, **blocking** |
| C04, C08, V13, V14 | Brief rewrites and fixture neutralisation | small each |
| C06 | Shrink corpus; resolve licences; pin endpoint | medium |
| Licences | UNESCO, Bellprat, C06 ×2, Qazvini-Ghani | medium, human |
| C12 (v1.1) | Vintage + rights determination for a born-digital Persian legal text | bounded, deferred |

## 15.8 Reconciled blocker list

Withdrawn: **B15** (§11.1). Superseded: **B1** and **B3** are now satisfied by replacement rather than removal alone.

Remaining before freeze: **B2** (restate R04/R08/R09) · **B4** (V15 source swap + collation) · **B5** (C09 rescope) · **B6**
(C02 R13 check) · **B7** (born-digital Ostrom) · **B8** (licences) · **B9** (pin output configuration everywhere; identical across
C10/C11) · **B10** (C04 brief) · **B11** (V13 brief) · **B12** (V14 narrowing) · **B13** (C08 fixtures) · **B14** (R14 applied to
C01 and C09) · **B16** (holdout submodule + manifest + runner split) · **B17** *(new)* author C05R's brief · **B18** *(new)* adopt
R13's procedure as a committed pre-freeze check.

## 15.9 Ready for source freeze?

**No.** `ready_for_source_freeze: false`.

The set is now *structurally* sound — 12 visible core with no case measuring an unimplemented subsystem, no case depending on an
unusable file, a duration pair inside the product contract, and a holdout architecture that can actually hold something back. What
remains is execution: one source swap with human collation, one text-usability check that is blocking, one acquisition, several
brief rewrites, and a licence pass.

**Stop condition observed: no source frozen, no hashes created, no gold authored.**
