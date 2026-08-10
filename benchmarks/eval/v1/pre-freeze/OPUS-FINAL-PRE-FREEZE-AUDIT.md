# Final pre-freeze audit of the Semantic Golden Set

Auditor: Opus 5, auditing GPT-5.6 Sol's Phase-2.5 implementation against the reconciled design in
[`OPUS-INDEPENDENT-REVIEW.md`](../OPUS-INDEPENDENT-REVIEW.md) and [`opus-decisions.json`](../opus-decisions.json).
Date: 2026-08-11 · **Nothing frozen · no gold authored · no holdout content created.**

## Global verdict

**`NOT_READY_FOR_SOURCE_FREEZE`**

Sol's own verdict — "not ready to freeze" — is correct, and the settlement work is largely faithful to the reconciled
design. But the audit does not confirm the *reasons*. Of the eight packages Sol reports as pre-freeze-ready, **two are
not** (C04, C09), and of the four Sol reports as blocked, **one is blocked for a reason that does not survive
inspection** (C02's private-use characters). Three defects were found that no artifact records:

1. **Two fixtures are contaminated with Project Gutenberg back matter.** C04's primary is **21.7 % Project Gutenberg
   licence text**; C09's is **11.8 % book index plus licence**. Both are declared as exact chapter scopes. Both were
   passed by R13, which does not check scope.
2. **The pre-freeze settlement checker returned an unqualified `pass` while four release-gating core packages were
   blocked.** The distinction the audit was asked to test for did not exist in code.
3. **R13 Gate E — the human reading-order spot-check that §14 makes mandatory for every Persian fixture — was never
   implemented**, on a set whose output language is always Persian and whose only Persian fixture shows concrete
   evidence of lossy extraction.

All three are fixed or made visible in code by this audit (§8). What remains is acquisition, rebuild and human work.

---

## 1. Freeze-gate semantics — was BLOCKING, now resolved in code

**What a successful settlement check meant before this audit.** `check_pre_freeze_settlement.py` verified the
*internal consistency* of the settlement package: the 12+2 case sets, the seven pinned config fields, source-bound
behaviour, the C10/C11 controlled pair recomputed from `build_analysis_profile`, no repeated logical source, no
ingested fixture without a passing R13 report, offline references marked `ingest=false`, and three opaque holdout
slots with no semantic keys. All of that is real and all of it passes.

**What it did not mean.** It never asked whether the release-gating core was ready. Running it unmodified:

```
"status": "pass"    ← with C02, C06, C08 and V15 blocked
```

Three separate defects produced that:

| Defect | Evidence |
|---|---|
| Blocked packages are simply skipped. The readiness loop is `if case["readiness"].startswith("ready")`; a `blocked` package enters no check at all. | [check_pre_freeze_settlement.py:143](tools/check_pre_freeze_settlement.py#L143) (pre-audit) |
| `startswith("ready")` silently admits `ready_with_recorded_budget_caution` as ready — the one readiness value that exists precisely to signal an unresolved concern. | same line |
| `release_gating` is written on every package and **read by nothing**. | [source-package-manifest.json](source-package-manifest.json) |

**There is no freeze workflow anywhere in the codebase.** No command writes package hashes; the only machine signal
in the tree is this checker's `pass`. So the answer to "can a freeze proceed while a release-gating core case is
blocked?" was: nothing would stop it, and the one artifact a reader would consult said `pass`.

**Minimal fix, applied.** The checker now answers the two questions separately and refuses to conflate them:

```
"settlement_consistent":    true      ← the package is internally consistent
"release_gating_core_ready": false    ← not every gating case is ready
"freeze_permitted":          false    ← the only field a freeze may act on
"release_gating_freeze_blockers": [ 13 itemised entries ]
```

`freeze_permitted` requires both; `FREEZE_READY_READINESS` is an explicit set (`{"ready"}`) rather than a string
prefix, unknown readiness values are an error, and the exit code is **3** when settlement is consistent but the
gating core is not ready — distinguishable from `1` (inconsistent) and `0` (freeze permitted). Verified: exit 3, 13
blockers, V13/V14 correctly absent.

---

## 2. R13 — auditing the validator, not only its outputs

R13's governing question is not "is this code point standard?" but the one the audit brief states: *can canonical
text be derived by a general, deterministic, source-independent normalization that preserves semantic content,
locators and exact-span reproducibility?* The implementation did not ask it. `no_private_use_characters` and
`no_control_character_anomalies` were flat zero-tolerance counts, so a symbol-font footnote marker and a font subset
with no `ToUnicode` map were the same verdict.

**Rule adopted (implemented and tested).** A `Cc`/`Cs`/`Co` code point — `\n`, `\r`, `\t` and ZWNJ excepted — is
**canonicalizable iff it is isolated**: every neighbour is absent or whitespace. The justification is structural, not
stylistic: an isolated mark *is its own whitespace-delimited token*, so deleting it removes a token that contained no
letters and leaves every other word, page locator and excerpt span untouched. A code point pressed against a letter
or digit may *be* that text; recovering it would need source-specific substitution, which R13 forbids. The validator
now asserts losslessness directly — `word_sequence_preserved` compares the token sequence before and after — and
itemises every dropped code point so the same canonicalization can be applied to the ingested artifact rather than
assumed.

Policy on the specific classes the brief lists:

| Class | Disposition | Why |
|---|---|---|
| Private Use (`Co`) | canonicalizable **iff isolated**; fatal otherwise | No interoperable identity by definition; isolation is what makes deletion provably word-preserving |
| Control (`Cc`) other than `\n\r\t` | same rule; in practice always fatal, because a control between letters is a broken encoding | C06: 291 of 291 are letter-adjacent |
| Page/form separators | `\f`/`\v` normalise to a space through `normalize_for_match` already; isolated separators drop | Not semantic |
| Zero-width (ZWSP/ZWJ), soft hyphen, BOM, LRM/RLM | already dropped by [`normalize_for_match`](../../../../src/thesisound/services/excerpt_matching.py#L35) on both source and excerpt | Symmetric, so span recovery is unaffected |
| Persian ZWNJ | explicitly exempt from the anomaly scan; dropped symmetrically at match time | Typographic, not lexical |
| Unicode normalisation | NFC at fixture preparation; no NFKC | NFKC would fold presentation forms and mask the exact defect Gate B exists to catch |

**A validator gap this exposed, and did not previously catch.** R13 detected the OECD corruption only *incidentally*,
through the U+0003 that the broken font uses for a space. Had that font mapped space to U+0020, the corruption would
have been invisible to every gate: `language_sanity` scores `$XVWUDOLD` as 100 % Latin letters, the mojibake markers
(`Ã Â Ø Ù â€ ï¿½`) never fire on pure ASCII, and exact-span matching round-trips its own garbage at 20/20. **R13 has no
lexical-plausibility check.** Recommended (not implemented — it needs a wordlist decision): a dictionary-hit-rate
floor on the extracted text, which would have flagged this file directly rather than by luck.

**Two further R13 gaps recorded.** §14 Gate C states that *zero ZWNJ in a long Persian text is a red flag for lossy
extraction*; the implementation records it as a non-blocking warning. And §14 Step 7's provenance record lives in a
separate manifest rather than in the report, so a fixture can pass R13 with no pinned revision.

---

## 3. C02 — the four private-use characters are resolved; C02 stays blocked for better reasons

**Answer: category B.** All four are non-semantic decoration and must not block the source.

Located through the production native path:

| # | Code point | Page | Context | Neighbours |
|---|---|---:|---|---|
| 1 | U+F02A | 1 | `Ahmad Ebadi ⟨mark⟩ Associate Professor of Islamic Philosophy and Theology…` | space / space |
| 2 | U+F02A | 1 | `⟨mark⟩ Corresponding Author: a.ebadi@ahl.ui.ac.ir` | line start / space |
| 3 | U+F0AF | 3 | `احمد عبادی ⟨mark⟩ دانشیار فلسفه و کلام اسلامی، دانشگاه اصفهان…` | space / space |
| 4 | U+F0AF | 3 | `⟨mark⟩ نویسنده مسئول: a.ebadi@ahl.ui.ac.ir` | line start / space |

This is one footnote symbol used four times — twice in the English front matter, twice in its Persian mirror — always
as the corresponding-author marker, always standing alone. Both code points sit at the standard symbol-font PUA
offset (`U+F000 + 0x2A`, `U+F000 + 0xAF`), the signature of a Symbol/Wingdings glyph emitted without a Unicode
mapping. **Not one occurs in body text, and none is adjacent to a letter.**

Rerunning R13 under the corrected policy:

```
C02-putnam   dropped=4 (U+F02A ×2, U+F0AF ×2)   residual_cc=0   residual_pua=0   word_sequence_preserved=True
```

The Unicode-hygiene blocker (`PF-C02-R13`) is **withdrawn**. Sol was right to refuse to hand-repair the file and
right not to substitute C02-B silently; the error was treating `private_use_count > 0` as dispositive.

**C02 nevertheless remains BLOCKED**, on three grounds the previous pass could not see:

1. **Gate E, now fail-closed, has no record — and there is evidence it would fail.** Inspecting the eleven semantic
   blocks the pipeline actually builds: blocks 2–6, 8 and 9 each *open* with the article's Latin-script numbered
   footnote apparatus (`1. Daniel Dennett / 2. The Philosophical L…`, `1. Thomas Kuhn / 2. Harry J. Gensler`), and
   blocks 7 and 9 open with the running head `411 | فصلنامه علمی حكمت و فلسفه | سال ش…`. Page furniture and footnotes
   are interleaved ahead of body text, every block is typed `other` with an empty `heading_path`, and the recorded
   `lost_headings` quality warning agrees. Add **zero ZWNJ across a 31-page Persian article** — §14's own red flag —
   and the extraction is not demonstrably faithful. This is exactly what Gate E exists to catch, and it was never
   run because it was never built.
2. **Canonicalization parity.** C02's fixture is the PDF itself. R13 now validates canonical text, but the pipeline
   ingests the raw PDF, so without applying the same drop rule on the ingestion path — or delivering a canonicalized
   derivative — R13 would be certifying text the product never sees. One specified change, not a source problem.
3. **Licence.** `license-readiness.json` records `ready: false`: CC BY-NC 4.0 against repository redistribution is
   unresolved.

Bibliography confirms the reconciled correction: *Hekmat va Falsafeh* 17(68), 123–153, DOI
`10.22054/wph.2021.53089.1867`. The PDF masthead's "Vol. 16" survives in block 0 and remains the outlier.

---

## 4. C06 — 291 controls re-diagnosed; multi-source data flow verified

### The eight code points

| Code point | Count | Shift +0x1D | Context class |
|---|---:|---|---|
| U+0003 | 113 | `' '` (space) | between letters/digits of corrupted runs |
| U+0010 | 8 | `'-'` | word-internal (`/RQJ⟨·⟩WHUP` = "Long-term") |
| U+0011 | 92 | `'.'` | inside numeric table cells |
| U+0013 | 45 | `'0'` | inside year/value cells |
| U+0014 | 6 | `'1'` | inside year cells |
| U+0015 | 22 | `'2'` | inside year cells |
| U+001A | 1 | `'7'` | inside a year cell |
| U+001B | 4 | `'8'` | inside a year cell |

**Classification: semantic corruption, all 291.** These are not control codes at all. They are the space, hyphen,
period and digit glyphs of a **subset font with no `ToUnicode` CMap, whose glyph identifiers sit 0x1D below ASCII**.
The decoded evidence is unambiguous:

```
6RFLDO ⟨·⟩ &RQQHFWLRQV  →  "Social Connections"
(QYLURQPHQWDO ⟨·⟩ 4XDOLW\  →  "Environmental Quality"
+RXVHKROG⟨·⟩QHW⟨·⟩DGMXVWHG⟨·⟩GLVSRVDEOH⟨·⟩LQFRPH⟨·⟩SHU⟨·⟩SHUVRQ  →  "Household net adjusted disposable income per person"
$XVWUDOLD · %HOJLXP · &]HFK⟨·⟩5HSXEOLF · 9RWHU⟨·⟩WXUQ⟨-⟩RXW
```

Roughly **1,600 characters on page 12 — the chapter's country-by-indicator well-being dashboard** — extract as
gibberish. That is substantive content, precisely the material a Beyond-GDP synthesis case would cite.

**Can a general canonicalization rescue it? No.** Rerunning R13 under the corrected policy: **0 of 291 are isolated;
0 are canonicalizable; 291 residual.** Every one is letter- or digit-adjacent. A repair would have to detect which
runs are corrupted (the *same page* also contains correct ASCII prose) and apply a fixed −0x1D shift only to those —
source-specific run detection plus glyph guessing, which R13 forbids. **C06 stays BLOCKED, for a stronger reason than
recorded**: not control-character hygiene, but a broken font encoding destroying table content.

The fallback in the raw tree is not a fallback: `.thesisound/eval-v1-prefreeze/raw/c06-oecd-ch1.html` is a
5,813-byte **Cloudflare "Just a moment…" challenge page**, not the chapter. No clean OECD component was acquired.
(The same automated-access wall blocks C08's third decoy.)

### Multi-source data flow — independently traced, claim upheld

Sol's claim is **correct as stated**. In
[`episode_preparation_service._load_corpus`](../../../../src/thesisound/services/episode_preparation_service.py#L372):
every confirmed source's claim ledger, evidence items, blocks and extraction plan are loaded in turn, then flattened —
`claims = [claim for ledger in ledgers for claim in ledger.claims]` — into one pool. That single pool feeds
`audit_coverage`, `prioritize_claims`, `estimate_budget`, `plan_episode` and `build_evidence_packs`. **A model can
meaningfully compose material from both source ledgers today**: coverage auditing, prioritisation and episode planning
all see claims from both sources simultaneously, and claims retain their `source_id`.

This is **complementary composition, not cross-source reconciliation**, and nothing in the artifacts claims otherwise.
`ClaimReconcilerService.reconcile()` is still per-`source_id`, and `DisagreementGraphBuilder` still emits nodes only
from `agreeing_source_ids` / `disagreeing_source_ids` / `CONTESTED`, which per-source reconciliation cannot populate.
Finding F1 stands; C06's design correctly does not depend on M8.

---

## 5. C09 — 62.98 % is wrong, and the case is not ready

### The fixture does not contain what it claims

`PRE-FREEZE-READINESS.md` and the R13 report both record "exact Chapters I-IV, VI, XIV". It is not. `_prepare_darwin`
slices each chapter from its marker to the *next marker or end of file*, so the last chapter swallowed everything
after it:

| Segment | Tokens | Share |
|---|---:|---:|
| Chapters I–IV, VI and the real Chapter XIV | 100,882 | 88.2 % |
| Book **INDEX** | 8,248 | 7.2 % |
| **Project Gutenberg licence and boilerplate** | 5,199 | 4.5 % |
| Declared total | **114,328** | 100 % |

R13 passed it because R13 does not check scope, and **nothing else checks scope either**. The corrected chapter
profile is I 19,918 · II 8,402 · III 10,186 · IV 26,910 · VI 18,960 · XIV **16,492** (not 29,938).

**So the headline number is wrong.** Against the clean corpus, the 72,000-token cap permits **71.37 %**, not 62.98 %.

### Is the residue still selector-dominated? Yes — and worse than the ratio suggests

For the profile's own 0.85 coverage target to bind rather than the hard cap, the corpus must be ≤ 77,005 tokens; for
achieved coverage to reach 0.85, ≤ 84,705. The clean corpus is 100,882. Every available cut deletes a named link in
the chain the brief specifies — Chapter I is Darwin's domestication analogy, on which Chapter IV's argument for
natural selection is explicitly built; II and III are "variation and struggle"; VI is "major difficulties"; XIV is the
synthesis. Sub-chapter excerpting is exactly what C03 was repaired to avoid. **Option A is unavailable without
damaging the dependency chain.**

Three further facts decide the measurement question:

1. **The pinned mode set biases the selector against the chapter the brief requires.** In
   [`_block_score`](../../../../src/thesisound/services/analysis_profile.py#L279), `objection` weighs 50 and
   `response` 55, against `definition` 80, `argument` 75, `conclusion` 70 — and the compensating **+35 bonus fires
   only for `critical`/`debate` modes**. C09's pinned modes are `["explanatory"]`. At ~71 % selection the material
   most likely to be deferred is therefore **Chapter VI, the "major difficulties" the brief explicitly asks the model
   to trace** — 18,960 tokens, the lowest-weighted substantive chapter.
2. **`required_for_global_understanding` does not guarantee coverage.** Seeding takes only the *first eligible block*
   of each required section, capped at 60 % of target. A required chapter is represented by one block; the rest must
   win on rank.
3. **A model regression is not separable from selector behaviour**, because the section `function` and
   `required_for_global_understanding` flags that drive `_block_score` are themselves produced by the model-driven
   `document_mapper`. A mapping change moves the selection, which moves the evidence, which moves the episode.

### Decision: Option B, with a mandatory configuration correction

Retain the six-chapter scope (after rebuild) and **redefine the measured capability as
`hierarchical reconstruction under budgeted evidence selection`**, making selector behaviour part of the measurement.
This is the corrected form of R04 the reconciled review already adopted: coverage is budget-bounded by design, and the
benchmark tests hierarchical reasoning *within the covered span* plus *honest disclosure of deferral*. Concretely the
case must be scored against `deferred_block_ids` and `budget-report.json`, not against whole-corpus recall, and it
must stop being labelled "long hierarchical dependency reconstruction" without qualification.

**Add `critical` to C09's pinned modes.** It costs nothing — the coverage target rises 0.85 → 0.95 but the 72,000 cap
still binds — and it raises objection/response blocks to 85/90, above every other function, removing the one selector
bias that would systematically hide Chapter VI. Without it, Option B measures an artefact.

**C09 is `BLOCKED`**: rebuild the fixture, rerun R13, relabel the case, repin the modes.

---

## 6. Remaining cases

### C05R — Yao Lin: approved, with cautions

Verified **from the artifact itself**, not from a metadata record: `doi:10.1017/S0031819126101430`, © The Author(s)
2026, published by Cambridge University Press on behalf of The Royal Institute of Philosophy, and the licence stated
verbatim in the PDF front matter — *"distributed under the terms of the Creative Commons Attribution licence
(http://creativecommons.org/licenses/by/4.0)"*. **CC BY 4.0 confirmed.** R13 passes: 24 pages, 66,983 characters,
19,132 tokens, 20/20 spans, zero anomalies. Structure is real: §3 opens by naming two contrasting objections, with
**3.1 The Professional View Objection** and **3.2 The Boundary Policing Objection**, each voiced in free indirect
style ("some might protest, aren't there still…"). Distinct from C03 (rhetorical/fictional typing across a monograph)
and C09 (long-range prerequisite ordering): this is dense local dialectical voice attribution. **Approve the
replacement**; do not reopen the search.

Three cautions to record rather than resolve:

- **Partial answer-revealing.** The section-opening sentence states both objections *and their content* ("one … contends
  that the normative account is too radical, and the other … that it is too conservative"), and the subsection headings
  name them — reaching the extraction prompt through `heading_path` (finding F5). The *identification* half of the
  pinned brief is therefore cheap; the measurable residue is the **attribution** half, which is genuinely hard because
  the article contains **zero occurrences of "reply"** — Lin's replies are unlabelled prose.
- **The artifact is not reproducible on re-acquisition.** Its text layer carries a per-download stamp on all 24 pages:
  `Downloaded from https://www.cambridge.org/core. 10 Aug 2026 at 20:10:43`. Re-downloading changes the text, so
  `normalized_text_sha256`, `parsed_document_key` and `block_sequence_key` will not reproduce. The pin must be the
  byte-level artifact. (Ostrom, CMEPSP and Putnam are clean of this.)
- **No retrieved bibliographic record backs it.** The only OpenAlex payload in the raw tree
  (`c05r-openalex.json`) is for **Basu, "Bullshit philosophy"** — a different candidate. There is no volume, issue or
  page range in the PDF either: this is an advance-access copy, and the pin must say so.

### C10 / C11 — the control is machine-checked

The guarantee is genuinely mechanical, not prose: the checker pops `target_duration_minutes`, asserts the two case
objects are **structurally identical** in every other field, asserts the durations are exactly `(20, 40)`, and
**recomputes both analysis profiles from `build_analysis_profile`** against the manifest. The briefs are byte-identical;
modes `["explanatory"]`, `prior_knowledge` `introductory`, audience and `output_language` identical. Computed:
standard/0.60/36,000/3 claims/0 neighbours/no objections versus deep/0.85/72,000/5 claims/1 neighbour/objections — the
intended tier transition. The Ostrom PDF is genuinely born-digital: 37 pages, 112,153 characters, **zero embedded
images**, text on every page, R13 pass.

One caution: `shared_fixture_token_estimate: 32032` is a **hand-copied constant the checker trusts**. It is not derived
from the fixture or the R13 report, so a fixture change would silently invalidate the computed pair while the checker
still reported `pass`. Minimal fix: read it from `validation/r13/C10-C11-ostrom.json`. Rights remain
`private_fixture_or_manifest_based` — a public CI run cannot acquire the source.

### C08 — blocked, and for two reasons

Decoy share is **14.42 %** by extractable characters (10,087 of 69,975) against the agreed 25–30 %, and the
partially-relevant LoC decoy was not acquired (automated-access challenge). Confirmed blocked; the target must not be
lowered to make it pass.

**A second defect the reports do not record.** Heading neutralization worked for structural labels — both fixtures
carry only `# Source A` / `# Source B` and sequential `Section NN` — but the NPS decoy **retains its institutional
front matter as body text**: `NPS / FRDO 2169`, `Quick Facts`, `Significance:`, *"Former slave who became America's
foremost abolitionist. Suffragist, publisher, author."* The decoy still announces its origin and genre through exactly
the `heading_path`/front-matter vector the repair was meant to close. Fix this in the same pass as the decoy
acquisition.

### V15 — provenance chain stated exactly

The three layers must not be collapsed, and the earlier review collapsed them:

| Layer | What it actually is | Evidence |
|---|---|---|
| **Textual edition / editorial basis** | Qazvini & Ghani critical edition, *editio princeps* 1320 SH / 1941 | editors recorded as Wikidata Q5953296, Q3318925 |
| **Physical printing behind the scan** | **Sina, Tehran — 1989** | Wikidata Q140377339 `P577 = +1989`; index `Publisher=سینا`, `Address=تهران`, **`Year=` empty** |
| **Transcription** | Persian Wikisource index `فهرست:حافظ قزوینی غنی.pdf`, **revision 290057** (2026-06-29) | `lastrevid: 290057` |

**Do not call the scan a 1941 printing.** A 1989 Sina printing is not automatically invalid, but the fixture must say
what it is. Two further facts sharpen the position beyond what Sol recorded: the pinned index carries **`Progress=T`,
not `V`** — so the earlier review's premise that the transcription is "fully proofread and validated" is **not
supported by the pinned revision**; and the pagelist shows two volumes plus a **غلطنامه (errata) at page 531**, which
directly affects verse-level collation.

Rights are unresolved (`ready: false`): the CC BY-SA transcription and the underlying 1989 printing are separate
rights objects. No ghazal was selected by the agreed non-arbitrary procedure, no verse was human-collated, no Persian
fixture exists, and the bounded Lewis / de Bruijn passages were not acquired. **BLOCKED**, correctly. Recorded, not
blocking: V15's `prior_knowledge` is `advanced`, which adds +1 claim per block and +1 neighbour context block.

### Spot-audit of the remaining claimed-ready cases

| Case | R13 | R14 | R15 | Scope | Brief leakage | Locators | Licence | Verdict |
|---|---|---|---|---|---|---|---|---|
| C01 James | pass, 14,693 tok, clean | one artifact; LoC 1897 scan offline | pinned | bounded by the next essay title — clean | brief names James's own three axes, obtainable only from the text | unique block keys | `commit_safe` | **READY** |
| C03 Woolf | pass, 60,040 tok, six chapters | single Wikisource transcription | pinned | complete essay, clean | typing brief, no answer key | unique block keys | `commit_safe` | **READY** |
| C04 Du Bois | pass — but on a contaminated fixture | three logical sources, one fixture each | pinned | **21.7 % PG licence** | brief no longer restates SEP's contents page; SEP bounded to §§2.3+3 (3,801 tok against 23,197 primary — dominance inverted, good) | unique block keys | mixed; SEP `private_fixture` | **BLOCKED** |
| C07 Bloom | pass, 13,728 tok, JATS body | single artifact | pinned | article body/methods, clean | three objectives unanswerable **by construction** — the abstention is observable in `coverage-report.json`, not just prose | unique block keys | CC BY 4.0 verified | **READY** |

C04's contamination is not cosmetic. At 30 minutes with `critical` in modes the profile selects **100 %** of the
primary fixture (23,929 tokens against a 54,000 budget), so **5,190 tokens of Project Gutenberg licence text are
guaranteed to reach evidence extraction** in the one case whose entire purpose is distinguishing an author's position
from someone else's words.

### V13 / V14 — correctly outside the gate

Both carry `release_gating: false`, and the corrected checker accumulates freeze blockers **only** from
release-gating packages — verified: neither appears among the 13. Their blockers remain visible in
`source-package-manifest.json` and `unresolved-blockers.json`, so they surface as challenge-execution warnings without
touching the core freeze gate. This matches the reconciled architecture. Bellprat is now verified (*Nature
Communications* 10, 1732 (2019), DOI `10.1038/s41467-019-09729-2`, CC BY 4.0); UNESCO and IPCC rights remain
`ready: false`.

---

## 7. Holdout infrastructure — passes

The public tree exposes three opaque identifiers (`OH-7K2M9Q4X`, `OH-B8R3T6WY`, `OH-N5V2C7LP`), null fixture and gold
hashes, `status: unprovisioned`, an evaluator version and a null `last_run`. **No source identity, author, topic,
brief, trap, gold or semantic case name appears anywhere in the public files.** The checker enforces exactly three
slots, rejects the semantic key set, and rejects a non-null hash on an unprovisioned slot.

Accidental loading is prevented at the resolver, not by convention.
[`resolve_eval_bundle_root`](../../../../src/thesisound/services/eval_harness.py#L89) makes **core the default**,
rejects `--private-bundle` on a core run, requires an explicit bundle for `--split holdout`, and refuses any bundle
equal to or beneath the public `benchmarks/eval` tree — so an ordinary tuning run cannot enumerate private case names,
briefs, sources or expectations even as a startup side effect. Missing bundles report `skipped`, never `pass`.

**No hidden holdout semantic content was created in this audit.**

---

## 8. Tests

`pytest`: **680 passed, 1 skipped, 2 failed**. Both failures are
`RuntimeError: FFmpeg is required to build the streamable MP3` in `tests/test_audio_pipeline.py` — outside this audit
and not blocking for semantic pre-freeze readiness. **Every semantic-fixture, manifest, holdout-isolation and
readiness-gate test passes.** `ruff` clean on all touched files.

Changes made by this audit (code and tests only — no gold, no freeze record, no fixture overwritten):

| File | Change |
|---|---|
| [semantic_fixture_validation.py](../../../../src/thesisound/services/semantic_fixture_validation.py) | Canonicalization policy (isolated `Cc`/`Cs`/`Co` droppable, word-sequence-preservation assertion, itemised drop inventory, residual gates); **R13 Gate E** human-collation gate, fail-closed for `fa`/`mixed` |
| [validate_fixtures.py](tools/validate_fixtures.py) | `--collation-record` flag |
| [check_pre_freeze_settlement.py](tools/check_pre_freeze_settlement.py) | Freeze-gate separation, explicit readiness set, exit code 3 |
| [prepare_visible_fixtures.py](tools/prepare_visible_fixtures.py) | Cut Project Gutenberg back matter and the Darwin index before chapter slicing |
| [test_semantic_fixture_validation.py](../../../../tests/test_semantic_fixture_validation.py) | 5 new tests: the C02 isolated-marker shape, word-internal PUA rejection, the C06 glyph-offset shape, Gate E fail-closed, Gate E not required for English |

The corrected preparer was run to a scratch directory only; **Sol's fixtures and R13 reports were left untouched** so
the audit trail stays intact. Rebuilding them is blocker `PF-C04-SCOPE` / `PF-C09-SCOPE`.

---

## 9. Per-case result

| Case | Status | Why |
|---|---|---|
| C01 | `READY` | Clean, one artifact, pinned, `commit_safe` |
| C02 | `BLOCKED` | PUA blocker **withdrawn**; now Gate E unattested with positive evidence of interleaved footnotes/running heads and zero ZWNJ; canonicalization parity on the ingestion path; CC BY-NC redistribution unresolved |
| C03 | `READY` | Complete essay, clean, pinned, `commit_safe` |
| C04 | `BLOCKED` | 21.7 % of the primary fixture is Project Gutenberg licence text and 100 % of it is selected at the pinned profile; rebuild and rerun R13 |
| C05R | `READY_WITH_DOCUMENTED_CAUTION` | CC BY 4.0 and structure verified from the artifact; headings pre-announce the objections; advance-access copy with an embedded per-download timestamp; no retrieved bibliographic record |
| C06 | `BLOCKED` | 291/291 control code points are letter-adjacent glyphs of a subset font with no `ToUnicode`; a whole dashboard page is corrupt; no clean component acquired |
| C07 | `READY` | CC BY 4.0 verified, clean, abstention observable in the coverage artifact |
| C08 | `BLOCKED` | Decoy share 14.42 % against 25–30 %; partially-relevant decoy unacquired; NPS institutional front matter still leaks as body text |
| C09 | `BLOCKED` | Fixture is 11.8 % index + licence and its declared scope is false; real coverage 71.37 %, not 62.98 %; Option B relabel required; `critical` must be added to modes or Chapter VI is systematically deferred |
| C10 | `READY_WITH_DOCUMENTED_CAUTION` | Control machine-checked; `shared_fixture_token_estimate` is an untrusted hand-copied constant; source is `private_fixture` |
| C11 | `READY_WITH_DOCUMENTED_CAUTION` | Same |
| V15 | `BLOCKED` | 1989 Sina printing, not 1941; index `Progress=T` not validated, `Year=` empty; rights unresolved; no selection, no collation, no fixture |
| V13 | `BLOCKED` (non-gating) | Fixtures unacquired; UNESCO rights `ready: false`. Correctly outside the freeze gate |
| V14 | `BLOCKED` (non-gating) | Fixtures unacquired; IPCC CC BY-NC-ND. Correctly outside the freeze gate |

## 10. Smallest blocker list to reach freeze

| ID | Case | Action |
|---|---|---|
| `PF-C02-COLLATION` | C02 | Human reading-order collation (Gate E) resolving the footnote/running-head interleaving and the zero-ZWNJ finding |
| `PF-C02-PARITY` | C02 | Apply the R13 canonicalization on the ingestion path, or deliver a canonicalized derivative |
| `PF-C02-LICENCE` | C02 | Settle CC BY-NC 4.0 against repository redistribution |
| `PF-C04-SCOPE` | C04 | Rebuild the primary fixture with the fixed preparer (23,929 → 18,739 tokens); rerun R13 |
| `PF-C06-OECD` | C06 | Acquire a clean born-digital OECD Chapter 1 component; rerun R13 |
| `PF-C08-DECOY` | C08 | Acquire the partially-relevant decoy to reach the 25–30 % mix |
| `PF-C08-NEUTRALIZE` | C08 | Strip the NPS "Quick Facts" institutional infobox from the decoy |
| `PF-C09-SCOPE` | C09 | Rebuild the Darwin fixture (114,328 → 100,882 tokens); rerun R13 |
| `PF-C09-MEASUREMENT` | C09 | Adopt Option B: relabel the capability, score deferral disclosure, add `critical` to the pinned modes |
| `PF-C10-C11-DERIVE` | C10/C11 | Derive `shared_fixture_token_estimate` from the R13 report instead of a constant |
| `PF-C05R-PIN` | C05R | Pin the artifact at byte level (advance-access + embedded timestamp) and record a real retrieval |
| `PF-V15-PROVENANCE` | V15 | State the three-layer chain exactly; settle rights; select ghazals by the agreed procedure; human-collate; produce and validate a Persian fixture |

Recommended and not blocking: add a lexical-plausibility gate to R13 (§2), and a machine scope-fidelity check so a
manifest cannot declare a scope no artifact enforces.

---

**Stop condition observed: no source frozen, no package hash created, no gold authored, no holdout content designed.**
