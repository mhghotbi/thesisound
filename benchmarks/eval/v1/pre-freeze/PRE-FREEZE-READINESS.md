# Phase 2.6 final blocker-closure readiness

Date: 2026-08-11 (Asia/Tehran)

Overall verdict: **NOT READY TO FREEZE**

Source/package freeze hashes created: **none**

Gold or expected answers created: **none**

The source settlement is internally consistent, but two release-gating core packages remain blocked. The corrected checker reports `settlement_consistent: true`, `release_gating_core_ready: false`, and `freeze_permitted: false`. V13 and V14 remain visible non-gating challenges and do not enter this blocker list.

## Core status

| Case | Status | Phase 2.6 result |
|---|---|---|
| C01 | **READY** | Unchanged: one clean James transcription; LoC witness stays offline. |
| C02 | **BLOCKED** | Canonicalization parity passes; CC BY-NC storage strategy is private; R13 fails only pending human Gate E. |
| C03 | **READY** | Unchanged complete six-chapter Woolf essay. |
| C04 | **READY** | Rebuilt to 18,738 R13 tokens; Chapters I, III, XIV and Afterthought only; scope contract passes; no Project Gutenberg boilerplate. |
| C05R | **READY** | Lin remains approved; the 197,683-byte First View artifact and real publisher/Crossref records are pinned without inventing volume or issue. |
| C06 | **READY** | The Commission source is unchanged. OECD *How's Life? 2020* Chapter 1 is the selected complementary framework; its bounded UTF-8 fixture passes R13 without OCR or source-specific repair. |
| C07 | **READY** | Unchanged observable narrowing case. |
| C08 | **READY** | Four clean sources pass R13; the LoC item is partially relevant; final R13-character decoy share is 28.62%; institutional leakage is generically removed. |
| C09 | **READY** | Correct scope and scope contract pass; `critical` is pinned; capability and later scoring contract now disclose budgeted deferral. |
| C10 | **READY** | Approved 20-minute standard-profile member; fixture tokens are read from R13 at check time. |
| C11 | **READY** | Approved 40-minute deep-profile member; fixture tokens are read from the same R13 report. |
| V15 | **BLOCKED** | Three provenance layers and scholar-derived candidates are pinned, but 1989 rights, human collation, commentary acquisition, fixture creation, and R13 remain open. |

## C02: canonicalization, Gate E, and rights

The production artifact is the canonical UTF-8 Markdown derivative, not the publisher PDF. The same shared function canonicalizes preparation and R13. Its production-ingested and R13-canonical normalized hashes are both `23dff599568173d3d5543617d48252f6e6167ae63bfee2cf4809f66093631c44`. The original four isolated marks (`U+F02A` ×2, `U+F0AF` ×2) are recorded in the private transformation packet and are no longer a blocker. No OCR or source-specific word substitution is used.

Generic preprocessing removes coordinate-confirmed repeated running heads and collects detected page-note apparatus after the body so it does not interrupt a page-spanning paragraph. R13 now passes Unicode, language sanity, exact-span, locator, production-ingestion, canonicalization-parity, and normalization gates. It still fails Gate E because the pending record has no human reviewer.

The private packet binds pages 1, 3, 4, 12, 18, and 31 to the exact fixture. A fluent reviewer must attest reading order, apparatus separation, script rendering, and meaning preservation despite zero ZWNJ. Approval has not been fabricated.

CC BY-NC 4.0 is handled conservatively: neither publisher PDF nor derivative is committed publicly. The derivative belongs in `THESISOUND_EVAL_FIXTURE_ROOT`; the public repository stores only acquisition, transformation, validation, and review metadata. Any future public distribution needs explicit noncommercial/attribution/change-notice review.

## C04 and C09 scope-fidelity closure

R13 now accepts an optional declarative scope contract and checks required markers, order/count, forbidden markers, normalized start/end boundaries, and character bounds against the production-extracted text. The settlement checker requires the recorded contract result for bounded fixtures.

- C04: 65,703 extractable characters, 18,738 estimated tokens. Chapters I, III, XIV and Afterthought are present; Project Gutenberg licence/back matter is absent.
- C09: 353,372 extractable characters, 100,881 estimated tokens. Exactly Chapters I–IV, VI and XIV are present; other chapters, index, Project Gutenberg licence, and back matter are absent.

C09's current-code profile is deep + critical: coverage target `0.95`, input cap `72,000`, five claims per block, one neighbour block, examples and objections/responses enabled. The cap gives a maximum nominal selected coverage of `0.713712`. The capability is therefore **hierarchical reconstruction under budgeted evidence selection**, not full whole-corpus reconstruction. Later scoring must consider reasoning within selected evidence, dependency preservation, `deferred_block_ids`, disclosure of important deferrals, and absence of whole-corpus claims. No gold was authored.

## C05R pin

The approved source remains Yao Lin, “Philosophy as a Normative Discipline.” It is explicitly First View/advance access. The acquired PDF is 197,683 bytes and has diagnostic pre-freeze SHA-256 `50BF7049864255E9412DCCE891F665AE60CA3AAA710E3D9691089ECE00C50EF9`; its embedded Cambridge modification timestamp is `2026-08-10T20:10:43Z`. Cambridge and Crossref records identify the DOI and publication date. No volume or issue is assigned; First View pages 1–24 are not represented as issue pagination. This byte identity is not a source/package freeze record.

## C06 acquisition result

The rejected 2011 OECD candidate remains preserved: its current official DAM PDF is 4,929,748 bytes with SHA-256 `F7594D4C5104190E93FDE9288CEA5548D1590C3320FB551DB10CDE5AE3959C23`, byte-identical to the failed source, and its dashboard text remains glyph-shifted. It was not repaired, OCRed, or accepted.

The narrow replacement search evaluated one serious candidate: OECD (2020), *How's Life? 2020: Measuring Well-being*, OECD Publishing, DOI `10.1787/9870c393-en`, PDF ISBN `978-92-64-72844-8`. The official 247-page born-digital PDF was acquired directly from OECD (7,530,615 bytes; diagnostic pre-freeze SHA-256 `66CC4C24A2BF59A5C26D042FC64A9B5EB2199DCAE25089EBFC63025BB181816E`). The fixture contains complete printed pages 18–30 and 43–55: the framework/current-well-being section and the sustainability/resources section. It has 19,536 R13 tokens, 9.54% more than the rejected candidate's 17,834, so corpus scale and intended difficulty are materially unchanged.

The clean fixture is canonical UTF-8 Markdown with explicit printed-page and source-PDF-page headings. Preparation selects whole pages, uses the production-native PDF extraction path, and applies only R13's shared isolation rule. That rule removes 26 isolated `U+F07C` page separators and three isolated `U+F0B7` bullets while preserving the complete source-word sequence; it performs no glyph mapping, word substitution, OCR, or source-specific character repair. Final R13 results are 68,567 extractable characters, 10,922 words, zero control/private-use/replacement/mojibake characters, 100% locator coverage, production parity pass, and 20/20 exact-span recovery.

The fixture contains the 11 current well-being dimensions; average, inequality, and deprivation treatment; the four future resource categories; the headline/full-dashboard distinction; and the GDP-growth comparison. It therefore operationalises the Commission's conceptual diagnosis without introducing disagreement adjudication or another capability.

OECD's current Terms & Conditions permit use, copying, distribution, and adaptation of OECD-owned written content published before 1 July 2024 with citation and an adaptation disclaimer, subject to third-party-content checks. The benchmark uses the conservative known strategy: keep the text-only derivative in `THESISOUND_EVAL_FIXTURE_ROOT`, retain the official PDF as a private/offline witness, and commit only provenance and validation metadata. Public redistribution would additionally require the OECD attribution/adaptation notice and third-party review.

Current-code compatibility remains the already-audited **complementary multi-source composition** at episode preparation. No M8/cross-source-reconciliation claim is made.

## C08 final mix

All percentages use R13 `extractable_character_count`:

| Fixture | Role | Characters | R13 |
|---|---|---:|---|
| Douglass speech | Primary | 59,888 | pass |
| NPS biography | Decoy | 9,711 | pass |
| LoC July 2020 article | Partially relevant decoy | 4,767 | pass |
| National Archives Declaration transcript | Credible related decoy | 9,530 | pass |

The decoys total 24,008 of 83,896 characters: **28.62%**. Generic filtering drops figures/site chrome and NPS `Person__Facts` infobox nodes, replaces structural headings with neutral sequence labels, and preserves substantive text. The tested behavior remains claim-level relevance filtering rather than source triage.

## C10/C11 stale-metadata closure

The checker joins C10 and C11 through their one shared `r13_report` and reads `metrics.token_estimate` at runtime. The value is 32,032. A test changes that report value and proves the derivation changes with it; no copied `shared_fixture_token_estimate` remains in configuration.

## V15 status

The provenance chain is recorded without conflation:

1. textual/editorial basis — Qazvini–Ghani critical edition, first edition 1320 SH / 1941;
2. physical printing behind the scan — Sina, Tehran, 1989;
3. transcription — Persian Wikisource index revision 290057, `Progress=T`, not claimed fully validated.

The non-arbitrary selection is the overlap of examples cited by both Franklin Lewis and J. T. P. de Bruijn: Khanlari 344 and 347. Mapping by incipit yields Qazvini–Ghani 352 and 355, main revisions 168472/168356, Page revisions 111788/109048, scan sequences 372/374, and printed pages 242/244. The errata at scan sequence 531 has no entry for printed page 242 or 244.

A private packet contains all 17 verse rows and exact locators. Human collation is **pending**; no clean Persian fixture was created and R13 was not run. The 1989 scan's reuse status remains unresolved and it is restricted to private/offline collation with no repository redistribution. Wikisource transcription rights are separately CC BY-SA. Lewis/de Bruijn official pages and narrow bounds are verified, but automated local acquisition currently returns the publisher's access challenge, so no commentary fixture exists.

## Validator hardening

Machine scope fidelity is implemented and tested. Zero ZWNJ remains a strong warning that forces Persian Gate E review. A lexical-plausibility gate was not added because no low-false-positive multilingual method was identified; a naive English dictionary would be brittle for technical, philosophical, and Persian academic text.

## Gate conclusion

Current checker output:

```json
{
  "settlement_consistent": true,
  "release_gating_core_ready": false,
  "freeze_permitted": false
}
```

Open core blockers are C02 human Gate E and V15 1989-printing rights determination, human verse collation, lawful bounded commentary acquisition, Persian fixture creation, and R13. No freeze is permitted.
