# Candidate ranking and recommendations

These are recommendations for independent review, not accepted sources. `H13`–`H15` are holdouts and must remain excluded from ordinary prompt iteration if later frozen.

## Ranking method

Each package is scored from 1 (poor) to 5 (excellent) on the required criteria. Scores are intentionally unweighted so that a high-authority source cannot hide an access or licensing failure.

| Code | Criterion | What a high score means |
|---|---|---|
| A | Authority | Primary, peer-reviewed, scholarly publisher, or official institutional source. |
| P | Provenance | Edition/version and chain from record to text are explicit. |
| S | Semantic challenge | Material strongly exposes the intended reasoning failure. |
| F | Failure-mode fit | Challenge is focused rather than merely difficult. |
| R | Stable reproducibility | A later evaluator can retrieve the same version or pin it cleanly. |
| X | Accessibility | Full text is actually obtainable without brittle access. |
| L | Licensing practicality | A lawful durable fixture is practical. |
| C | Corpus size/cost | Size is proportionate to the case, except where long-source scale is intentional. |
| N | Low unnecessary noise | Most included material bears on the case; deliberate decoys count as signal. |
| I | Independence | The package adds information not already covered by another case. |

## Package scores

| Case | Rank | Package | A | P | S | F | R | X | L | C | N | I | Total / 50 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| C01 | 1 | C01-A Gutenberg + LoC | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | **50** |
| C01 | 2 | C01-B Wikisource + LoC | 5 | 5 | 5 | 5 | 4 | 5 | 4 | 5 | 5 | 4 | 47 |
| C02 | 1 | C02-A Ebadi–Emdadi Masouleh | 4 | 5 | 5 | 5 | 4 | 5 | 2 | 5 | 4 | 5 | **44** |
| C02 | 2 | C02-B Akbarian–Saeedimehr–Sadeghi | 4 | 5 | 4 | 4 | 4 | 5 | 2 | 5 | 4 | 5 | 42 |
| C03 | 1 | C03-A Woolf | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 4 | 4 | 5 | **48** |
| C03 | 2 | C03-B Wollstonecraft | 5 | 5 | 4 | 4 | 5 | 5 | 5 | 3 | 3 | 4 | 43 |
| C04 | 1 | C04-A *Souls* + SEP | 5 | 5 | 5 | 5 | 5 | 5 | 3 | 4 | 4 | 5 | **46** |
| C04 | 2 | C04-B “Strivings” + SEP | 5 | 5 | 4 | 4 | 5 | 5 | 3 | 5 | 5 | 4 | 45 |
| C05 | 1 | C05-A accessible triptych | 5 | 5 | 5 | 5 | 4 | 4 | 2 | 4 | 4 | 5 | **43** |
| C05 | 2 | C05-B versions of record | 5 | 5 | 5 | 5 | 3 | 2 | 2 | 4 | 4 | 5 | 40 |
| C06 | 1 | C06-A Commission + OECD | 5 | 5 | 5 | 5 | 4 | 5 | 2 | 3 | 4 | 5 | **43** |
| C06 | 2 | C06-B UNDP + OECD | 5 | 5 | 4 | 4 | 5 | 5 | 2 | 2 | 3 | 4 | 39 |
| C07 | 1 | C07-A 2024 hybrid RCT | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 4 | 5 | **49** |
| C07 | 2 | C07-B 2015 WFH RCT | 5 | 5 | 5 | 5 | 5 | 5 | 2 | 4 | 4 | 5 | 45 |
| C08 | 1 | C08-A primary + two decoys | 5 | 5 | 5 | 5 | 5 | 5 | 4 | 4 | 5 | 5 | **48** |
| C08 | 2 | C08-B primary + one decoy | 5 | 5 | 4 | 4 | 5 | 5 | 4 | 5 | 3 | 4 | 44 |
| C09 | 1 | C09-A Darwin first edition | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 2 | 3 | 5 | **45** |
| C09 | 2 | C09-B Darwin sixth edition | 5 | 5 | 5 | 4 | 5 | 5 | 5 | 2 | 3 | 4 | 43 |
| C10 | 1 | C10/11-A Ostrom lecture | 5 | 5 | 5 | 5 | 5 | 5 | 2 | 4 | 4 | 4 | **44** |
| C10 | 2 | C10/11-B Ostrom book | 5 | 5 | 5 | 4 | 3 | 2 | 1 | 1 | 2 | 4 | 32 |
| C11 | 1 | C10/11-A Ostrom lecture | 5 | 5 | 5 | 5 | 5 | 5 | 2 | 4 | 4 | 4 | **44** |
| C11 | 2 | C10/11-B Ostrom book | 5 | 5 | 5 | 5 | 3 | 2 | 1 | 2 | 3 | 4 | 35 |
| C12 | 1 | C12-A Persian laws + Iranica | 5 | 5 | 5 | 5 | 3 | 4 | 2 | 4 | 4 | 5 | **42** |
| C12 | 2 | C12-B Persian laws + Browne | 5 | 5 | 4 | 4 | 4 | 5 | 4 | 2 | 3 | 4 | 40 |
| H13 | 1 | H13-A UNESCO + NIST | 5 | 5 | 5 | 5 | 5 | 5 | 4 | 4 | 4 | 5 | **47** |
| H13 | 2 | H13-B OECD + NIST | 5 | 5 | 4 | 4 | 5 | 5 | 2 | 5 | 5 | 4 | 44 |
| H14 | 1 | H14-B IPCC + Bellprat et al. | 5 | 5 | 5 | 5 | 5 | 5 | 4 | 3 | 4 | 5 | **46** |
| H14 | 2 | H14-A IPCC + NASEM | 5 | 5 | 5 | 5 | 4 | 5 | 2 | 1 | 2 | 5 | 39 |
| H15 | 1 | H15-A Khanlari + Iranica | 5 | 5 | 5 | 5 | 2 | 2 | 1 | 5 | 4 | 5 | **39** |
| H15 | 2 | H15-B manuscript + Iranica | 5 | 5 | 4 | 4 | 2 | 4 | 5 | 2 | 2 | 5 | 38 |

Low licensing scores are not waivers. A package that needs private storage remains private regardless of its total.

## Preferred package per case and adversarial objection

| Case | Preferred package | Why preferred | Strongest reason it may be a bad choice | Confidence |
|---|---|---|---|---|
| C01 | **C01-A** | Best provenance/access combination for a precise public-domain distinction case; LoC controls the later Gutenberg impression. | The working transcript is not itself the 1897 impression, so uncollated wording differences could create false gold. | High after collation |
| C02 | **C02-A** | Directly names and develops distinction-versus-dichotomy in native Persian academic prose. | The journal record and PDF disagree on year/volume, and no article reuse license was found. | Medium |
| C03 | **C03-A** | Fictional counterexample, narrative voice, and qualification make it much more diagnostic than a conventional treatise. | Non-contiguous chapter selection can manufacture an argument if excerpt boundaries are too aggressive. | High after excerpt review |
| C04 | **C04-A** | The canonical 1903 formulation plus a specialist interpretive history creates a clean primary/commentary boundary. | SEP's taxonomy is so clear that a model may reproduce it while under-reading Du Bois, turning the test into commentary summarization. | High |
| C05 | **C05-A** | A paper/comment/response triptych provides explicit stance and rebuttal links with accessible full texts. | The copies are copyrighted and not always versions of record; a durable public fixture is impractical. | Medium-high semantically; medium operationally |
| C06 | **C06-A** | The Commission supplies the conceptual diagnosis and OECD supplies an operational multidimensional framework. | Two long institutional reports create selection effects; an overly curated excerpt could predetermine the synthesis. | Medium-high |
| C07 | **C07-A** | Strong causal design, explicit boundaries, concise corpus, and CC BY licensing isolate generalization discipline. | Because the paper states external-validity caveats unusually clearly, the abstention behavior may be easier than in normal use. | High |
| C08 | **C08-A** | Two credible decoys make relevance selection robust and keep “bad source detection” out of the task. | Obvious filenames or source-role labels could let the system game the case without semantically judging relevance. | High if fixture labels are neutral |
| C09 | **C09-A** | The first edition is complete, public domain, edition-controlled, and structurally ideal for dependency testing. | Its scale and nineteenth-century exposition make cost and language difficulty potential confounds even with clean parsing. | High |
| C10 | **C10/11-A** | It is compact enough for five minutes and, crucially, identical to the 30-minute corpus. | A five-minute brief may still force omission of a term that reviewers personally consider essential, making later gold brittle. | High |
| C11 | **C10/11-A** | Same corpus permits a real controlled comparison, and the lecture contains mechanisms, evidence, examples, and caveats for deeper selection. | The lecture may not support 30 minutes at the product's evidence-density standard; the correct pipeline behavior could be to reject/narrow rather than produce the requested duration. | Medium-high; validate supported duration before freezing |
| C12 | **C12-A** | Persian primary law plus concise specialist English context best isolates bilingual source-role reasoning. | The 1907 direct PDF was not opened during automated verification, and the portal's redistribution rights are unclear. | Medium |
| H13 | **H13-A** | Rich hierarchical normative guidance paired with a mature operational framework tests mapping and source-type discipline. | UNESCO and NIST were not written as counterparts; a prompt asking for mapping may encourage false equivalence even in an excellent answer. | High as holdout after license review |
| H14 | **H14-B** | The IPCC supplies calibrated consensus while the open methods paper focuses the reliability challenge at manageable size. | The brief must specify an event class or remain explicitly methodological; otherwise “event attribution” is too broad for stable evaluation. | High after brief narrowing |
| H15 | **H15-A, conditional** | A modern critical Persian edition plus two specialists is the strongest way to test ambiguity without making OCR or manuscript reading the task. | The primary edition has not yet been lawfully acquired digitally and its redistribution status is unresolved; expert poem selection could itself bake in one interpretation. | **Low until acquisition/collation; do not freeze** |

## Recommendation summary

The preferred MVP set is:

1. `C01-A` — James, Gutenberg transcript checked against LoC first edition.
2. `C02-A` — Ebadi and Emdadi Masouleh on Putnam's fact/value distinction.
3. `C03-A` — selected chapters of Woolf's *A Room of One's Own*.
4. `C04-A` — Du Bois, *Souls* Chapter I, plus Pittman's SEP entry.
5. `C05-A` — OSC study, Gilbert et al. comment, and Anderson et al. response.
6. `C06-A` — Stiglitz-Sen-Fitoussi Commission report plus OECD *How's Life?*.
7. `C07-A` — Bloom, Han, and Liang 2024 hybrid-work RCT.
8. `C08-A` — Douglass's 1852 oration plus NPS and LoC decoys.
9. `C09-A` — complete first edition of Darwin's *Origin*.
10. `C10/11-A` — Ostrom's Nobel lecture, reused exactly for both durations.
11. `C12-A` — Persian 1906/1907 constitutional laws plus Arjomand.
12. `H13-A` — UNESCO AI ethics recommendation plus NIST AI RMF 1.0.
13. `H14-B` — IPCC AR6 WGI Chapter 11 plus Bellprat et al.
14. `H15-A` — Khanlari Hafez edition plus Lewis and de Bruijn, **conditional and not yet ready**.

The list has fourteen bullets because the Ostrom package serves two distinct case configurations.

## Unresolved acquisition and licensing issues

- `C02`: resolve the journal/PDF date and volume mismatch; obtain permission or keep the article private/manifest-based.
- `C04`: SEP full text is not a public fixture; design a stable archive manifest and a lawful excerpt policy.
- `C05`: all three *Science* items need private fixture or retrieval-manifest handling and version normalization.
- `C06`: establish a stable original or institutional snapshot of the Commission report and review both reports' reuse terms.
- `C10/C11`: confirm whether the Nobel-hosted lecture may be stored privately and whether its evidence density supports 30 minutes.
- `C12`: successfully reacquire the 1907 Persian PDF, record exact edition provenance, and resolve portal/transcription rights.
- `H13`: confirm project compatibility with UNESCO's CC BY-NC-SA 3.0 IGO terms; independently resolve the OECD instrument's reuse terms if the alternate is retained.
- `H14`: treat the IPCC chapter's CC BY-NC-ND terms conservatively; do not create a transformed committed excerpt without rights review.
- `H15`: obtain the Khanlari edition lawfully, resolve rights, choose poems only after reading the edition and scholarship, and manually collate every Persian line.

## Stop condition

No package in this document is frozen or approved. The next permitted action is independent source/case review. This phase must not create fixtures, hashes, gold atoms, reference scripts, thresholds, evaluator code, or Thesisound runs.
