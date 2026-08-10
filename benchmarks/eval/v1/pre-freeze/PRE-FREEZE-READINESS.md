# Phase 2.5 pre-freeze readiness report

Date: 2026-08-11 (Asia/Tehran)  
Overall verdict: **NOT READY TO FREEZE**  
Freeze records created: **none**  
Gold or expected answers created: **none**

## Settled visible set

The 12 visible release-gating cases are C01, C02, C03, C04, C05R, C06, C07, C08, C09, C10, C11, and V15. V13 and V14 are visible non-gating challenges. H13/H14/H15 are burned as hidden holdouts. Original C05 is deferred until M8; C12 is deferred to v1.1 without force-filling. Three future hidden holdouts exist only as opaque public records plus a private-bundle interface.

Fully pre-freeze-ready cases: **C01, C03, C04, C05R, C07, C09, C10, C11**. C09 is ready under the stated gate definition but carries a material coverage caution below. Blocked core cases: **C02, C06, C08, V15**. Both visible challenges remain blocked for acquisition/rights work.

## R13 results

Every accepted ingested artifact passed the deterministic validator through the production native parser with OCR disabled. Reports record bytes, format, pages, text characters, word/token estimates, images, Unicode/controls, normalized diagnostic hash, language sanity, locators, and 20 deterministic exact-span recoveries.

| Artifact | Result | Pages | Extractable chars | Token estimate | Images | Exact spans | Key finding |
|---|---:|---:|---:|---:|---:|---:|---|
| C01 James | pass | — | 51,490 | 14,693 | — | 20/20 | clean UTF-8 |
| C02 Putnam Persian PDF | **fail** | 31 | 51,575 | 14,663 | 8 | 20/20 | 4 private-use chars: U+F02A ×2, U+F0AF ×2 |
| C03 Woolf complete essay | pass | — | 210,359 | 60,034 | — | 20/20 | complete six chapters |
| C04 Du Bois 1903 primary scope | pass | — | 83,918 | 23,928 | — | 20/20 | enlarged primary scope |
| C04 Du Bois 1897 primary | pass | — | 15,622 | 4,458 | — | 20/20 | complete article body |
| C04 SEP §§2.3, 3 | pass | — | 13,327 | 3,801 | — | 20/20 | commentary strictly bounded |
| C05R Lin | pass | 24 | 66,983 | 19,132 | 1 | 20/20 | named objections/replies |
| C06 Commission scope | pass | 32 | 106,980 | 30,510 | 0 | 20/20 | fixed source-page map |
| C06 OECD scope | **fail** | 19 | 62,474 | 17,834 | 556 | 20/20 | 291 control-code occurrences across 8 code points |
| C07 Bloom RCT | pass | — | 48,050 | 13,688 | — | 20/20 | JATS article body/methods |
| C08 Douglass primary | pass | — | 59,888 | 17,073 | — | 20/20 | neutralized headings/front matter |
| C08 NPS decoy | pass | — | 10,087 | 2,869 | — | 20/20 | neutralized headings/front matter |
| C09 Darwin scope | pass | — | 401,050 | 114,328 | — | 20/20 | exact Chapters I-IV, VI, XIV |
| C10/C11 Ostrom | pass | 37 | 112,153 | 32,032 | 0 | 20/20 | born-digital InDesign PDF, text on all pages |

The Persian C02 extraction otherwise looks healthy: 33,897 normal Arabic/Persian-script code points, zero Arabic Presentation Forms, zero replacement characters, zero mojibake markers, viable page locators, and complete exact-span recovery. R13 is conjunctive, so the private-use characters still reject it. No OCR or repaired derivative was created.

## R14 one-artifact rule

- C01 ingests only the clean James transcription. The LoC 1897 scan and its OCR remain offline collation evidence.
- C09 ingests only the scoped Gutenberg first-edition transcription. Darwin Online and page scans remain offline witnesses.
- C04 has three logical sources and exactly one candidate fixture for each: two primary works and one bounded commentary source.
- C06 has two logical sources, but the failed OECD candidate is explicitly not accepted as `ingested_fixture`.
- V15 scans are offline future collation witnesses only. No Persian semantic fixture exists yet.

## R15 and the controlled duration pair

All 14 visible cases explicitly pin duration, modes, prior knowledge, audience, output language, Research Brief, and source-bound behavior. The settlement checker proves that C10 and C11 are structurally identical after deleting `target_duration_minutes`.

The actual accepted Ostrom PDF produces a Thesisound token estimate of 32,032, so the current-code calculations are:

| Field | C10: 20 min | C11: 40 min |
|---|---:|---:|
| Analysis depth | standard | deep |
| Coverage target | 0.60 | 0.85 |
| Input budget | 36,000 | 72,000 |
| Target source tokens including planner headroom | 21,142 | 29,950 |
| Nominal selected coverage | 66.0% | 93.5% |
| Claims per block | 3 | 5 |
| Neighbor context | 0 | 1 |
| Include examples | yes | yes |
| Include objections/responses | no | yes |
| Supported-duration gate | 16 min | 32 min |
| Persian script target | 2,600 words | 5,200 words |

This verifies the intended standard/deep profile transition in the current implementation. The source is independently clean: the official Nobel-hosted PDF reports Adobe InDesign/Adobe PDF Library metadata, contains no embedded raster images, has extractable text on all 37 pages, and passes R13.

## Case-specific settlement

### C01

The Gutenberg 1912-impression transcription is the sole semantic artifact. A word-level comparison against the LoC 1897 witness aligned 8,794 of 9,177 ingested words (sequence-match ratio 0.827904). Targeted checks found no confirmed substantive change in benchmark-critical formulations. Unmatched material was dominated by scan-OCR corruption, running headers/page numbers, hyphenation, and footnote/front matter. The fixture remains honestly labelled as the 1912-impression transcription; the 1897 scan is not ingested.

### C02

**Blocked.** The actual publisher PDF was acquired and failed R13 as described above. The publisher page corrects the Phase-1 rights uncertainty: it states CC BY-NC 4.0, and the bibliographic record is Hekmat va Falsafeh 17(68), pages 123–153, DOI `10.22054/wph.2021.53089.1867`; the PDF carries the Winter 1400/2022 issue notation. The bounded same-article search found only the same publisher file/metadata route. C02-B (Akbarian, Saeedimehr & Sadeghi 2021, DOI `10.22054/wph.2021.48451.1788`) is proposed as the first replacement to validate, not silently substituted.

### C03

The complete six-chapter essay is used. The earlier non-contiguous-chapter design remains in history but is not the final fixture.

### C04

The primary evidence is load-bearing: the brief asks which formulations in Du Bois's 1897 and 1903 texts support or resist the stated reading. SEP is limited to §§2.3 and 3 and cannot perform that primary comparison by itself. The behavior is author-position versus scholarly-interpretation attribution; no gold was authored.

### C05R

Lin replaces Mill. The bounded comparison evaluated Mill plus three real modern candidates. Lin is clearly better for the visible set because it keeps explicit single-source objection/reply structure while removing another older-English source, has peer-reviewed primary authority, CC BY 4.0 full text, stable DOI/provenance, and an actual R13 pass. Details are in `C05R-BOUNDED-ALTERNATIVE-SEARCH.md`.

### C06

Code compatibility is **confirmed only for complementary composition**: episode preparation loads claims from each source ledger into the shared corpus and planner. There is no cross-source reconciliation or disagreement graph because M8 is absent, and no artifact claims otherwise. The Commission scope passes R13; OECD fails, so C06 is blocked.

### C07

The revised brief deliberately asks about hourly/frontline workers, workers without university education, and organizations outside China. Those objectives are unsupported by construction in the supplied single study, making correct narrowing observable.

### C08

The transformation removes web UI/front matter and replaces only recognized structural labels with sequential `Section NN` labels and neutral outer source labels: HTML `h1`–`h6`, NPS `section_title` spans, and short uppercase Wikisource `wst-center` labels (plus the initial document-form label). Centered quotations, paragraphs, order, punctuation, and substantive sentences are retained. This is metadata/heading neutralization, not a synthetic fixture. The primary and NPS decoy pass R13, but their decoy share is only 14.42%; the LoC partially relevant decoy could not be acquired through its automated-access challenge. The case is blocked until the approved 25–30% mix is complete.

### C09

The exact reconciled chapter scope passes R13. Under the pinned 40-minute explanatory configuration, current code computes a deep 0.85 profile and 72,000-token budget. Because the current estimator counts 114,328 source tokens, the budget caps selection at 62.98%, not the roughly 80% anticipated by Opus. This ratio does not itself trigger a deterministic gate, and the R5 planner repair bounds required-section seeding, so source size no longer guarantees a gate failure. The lower-than-anticipated coverage is nevertheless a recorded confound and must be checked during later non-gold dry runs before any freeze.

### V13 and V14

The briefs are repaired and pinned. V13 explicitly permits non-mappings and requires typed relations. V14 is heat-only. They remain visible, non-gating, and unready until bounded fixtures pass R13 and storage/licence strategies are executed. Bellprat metadata is verified as *Nature Communications* 10, 1732 (2019), DOI `10.1038/s41467-019-09729-2`, CC BY 4.0; IPCC remains CC BY-NC-ND 4.0.

### V15

**Blocked.** The Qazvini–Ghani route did not verify as assumed. The Persian Wikisource index is pinned at revision `290057` (2026-06-29), says publisher Sina/Tehran but no year, and links to Wikidata Q140377339, which records 1989. Exact printing and underlying rights therefore remain unresolved. No poem was selected, no verse was represented as human-collated, and no clean Persian fixture or bounded commentary was accepted. Ganjoor, generic web Hafez, Khanlari, and OCR were not substituted.

## Holdout separation

The public repository contains only three opaque IDs, null future fixture/gold hash slots, schema/evaluator versions, and optional aggregate run metadata. A holdout run requires an explicit private bundle path outside the public evaluation tree. Core is the default split. The public files contain no source names, authors, topics, briefs, failure descriptions, texts, or gold for future holdouts.

## Gate conclusion

The source set is structurally settled but cannot be frozen. Resolve PF-C02-R13, PF-C06-OECD-R13, PF-C08-DECOY, and PF-V15-PROVENANCE-COLLATION before all 12 core packages can pass. V13/V14 may remain non-gating but must have runnable, validated packages before they can be reported as challenge results. After any replacement or acquisition, rerun R13 and the settlement checker. Do not create package freeze hashes until then.
