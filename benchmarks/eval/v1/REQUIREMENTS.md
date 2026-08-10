# Repository-grounded benchmark requirements

This document translates existing Thesisound behavior into benchmark requirements. It does not introduce a new product contract.

## What the semantic Golden Set must measure

| ID | Requirement | Repository trace | Source-selection implication |
|---|---|---|---|
| R01 | Measure whether the episode is an orientation aid grounded in the selected corpus, not a generic summary or substitute for the originals. | `README.md`; `PRODUCT.md`; `docs/01-foundations/01-product-scope.md` | Use sources with enough structure and locatable claims to expose source-bound versus generic treatment. |
| R02 | Admit substantive claims only from acquired full text that was explicitly selected. Search results, snippets, metadata, and abstracts are discovery aids, not evidence. | `docs/01-foundations/04-document-and-source-strategy.md`; `docs/04-integrations/02-source-discovery-large-docs-and-revision.md`; `docs/02-pipeline/03-one-source-evidence-pipeline.md` | Every candidate needs an obtainable full text and a direct acquisition reference. An abstract-only candidate is unresolved, not usable. |
| R03 | Preserve exact source support, locators, attribution, negation, scope, certainty, and qualifications. Direct and inferential claims must remain distinguishable. | `docs/02-pipeline/03-one-source-evidence-pipeline.md`; `prompts/evidence_extraction/1.3.0/system.md`; `src/thesisound/services/gates.py`; `src/thesisound/services/script_verifier.py` | Prefer stable pagination, headings, or paragraph anchors. Include cases with caveats and inferential temptations. |
| R04 | Cover the full argumentative scope of long documents and retain dependencies across sections. Large documents are partitioned on semantic/heading boundaries, merged globally, and audited for coverage rather than sampled or truncated. | `docs/01-foundations/04-document-and-source-strategy.md`; `docs/04-integrations/02-source-discovery-large-docs-and-revision.md`; `docs/02-pipeline/04-output-aware-analysis-budget.md`; `STATUS.md` | Include at least one genuinely long hierarchical source whose conclusion depends on earlier machinery and later objections. Keep parsing/OCR clean so the case isolates semantics. |
| R05 | Test output-aware selection: duration, audience, and mode change extraction depth and claim budget while the document substrate stays stable. | `docs/02-pipeline/04-output-aware-analysis-budget.md`; `src/thesisound/services/analysis_profile.py`; `src/thesisound/services/episode_budget.py` | Use one exact-corpus, exact-brief 5/30-minute pair. The long member must unlock distinct arguments, evidence, objections, and qualifications—not longer wording. |
| R06 | Test coverage against each central question and objective, including correct narrowing or requests for more evidence when the corpus cannot support the requested scope or duration. | `src/thesisound/services/coverage_auditor.py`; `src/thesisound/services/gates.py`; `prompts/coverage_audit/1.0.0/system.md` | Include a high-quality but bounded empirical study paired with an intentionally broader user question. |
| R07 | Test purposeful omission. Material that is topical but low-value for the brief must not displace central evidence, and omitted supporting material should have a reason. | `docs/02-pipeline/05-episode-preparation.md`; `prompts/episode_plan/1.1.0/system.md`; `docs/01-foundations/04-document-and-source-strategy.md` | Include authoritative biographical/reception decoys alongside a primary text when the brief asks about the text's internal argument. |
| R08 | Preserve genuine disagreement. Reconciliation must not collapse objections and responses, or differences in scope, certainty, method, and attribution. | `prompts/claim_reconciliation/1.0.0/system.md`; `src/thesisound/services/script_verifier.py`; `docs/01-foundations/05-quality-evaluation.md` | Include a direct scholarly comment/response exchange and a different kind of interpretive disagreement in holdout. |
| R09 | Synthesize complementary sources without turning different source roles into interchangeable evidence. Normative, conceptual, historical, and empirical statements require appropriate attribution. | `docs/02-pipeline/03-one-source-evidence-pipeline.md`; `prompts/claim_reconciliation/1.0.0/system.md`; `src/thesisound/services/script_verifier.py` | Include complementary measurement frameworks and a holdout pairing normative principles with an operational risk framework. |
| R10 | Produce natural spoken Persian directly, with useful two-speaker pedagogy, stable terminology, preserved contrasts, and explicit treatment of contested translations. | `docs/02-pipeline/06-persian-script-pipeline.md`; `prompts/glossary/1.0.0/system.md`; `prompts/persian_script_segment/1.0.0/system.md`; `src/thesisound/services/script_quality.py` | Mix English→Persian, Persian→Persian, and mixed-corpus cases. Favor sources with important contrastive terms rather than merely difficult vocabulary. |
| R11 | Remain compatible with deterministic gates for known claims/evidence, evidence linkage, prompt leakage, repetition, speaker balance, glossary consistency, and duration. | `src/thesisound/services/gates.py`; `src/thesisound/services/script_checks.py`; `src/thesisound/services/script_verifier.py`; historical `benchmarks/eval/README.md` in Git | Case design should expose semantic behavior while allowing future deterministic checks. This phase does not set new thresholds or implement the evaluator. |
| R12 | Respect the product's privacy and copyright model: access does not imply redistribution rights, and long copyrighted quotations should not be committed by default. | `docs/01-foundations/08-security-privacy-copyright.md`; `PRODUCT.md` | Classify every source as commit-safe, private-fixture-only, manifest/excerpt, or unresolved. Preserve attribution and license notices for open material. |

## What it explicitly must not measure

| Excluded concern | Why excluded here | Proper home |
|---|---|---|
| OCR accuracy, layout recovery, scanned-PDF robustness | These can change which text reaches the semantic pipeline and would confound semantic failure with extraction failure. | `benchmarks/ocr/` and `benchmarks/persian_ocr/` |
| Parser correctness and block/locator extraction robustness | The semantic corpus should enter as clean, verified text with stable locators. | `benchmarks/parser/` |
| Web search ranking or discovery quality | Candidate acquisition is curated and verified; search snippets are never evidence. | Source-discovery/integration testing |
| TTS pronunciation, voice quality, prosody, or audio rendering | The semantic harness historically stops before audio, and the product treats script and rendering as separate stages. | TTS/audio evaluation |
| ASR/transcript recovery | The benchmark evaluates the prepared script/transcript, not speech recognition. | ASR evaluation |
| Production prompt optimization or pipeline redesign | This phase is a benchmark-design activity. | A later, separately authorized engineering phase |

## Failure modes the corpus must expose

- Generic-topic fluency that is not source-grounded.
- Collapsing a distinction into two loose synonyms, especially during English-to-Persian rendering.
- Losing a qualification, negation, limited population, time horizon, or uncertainty statement.
- Presenting a fictional or rhetorical example as an empirical fact or an author's unqualified position.
- Allowing commentary to overwrite, modernize, or impersonate a primary source.
- Smoothing a genuine scholarly disagreement into false consensus.
- Listing complementary sources independently instead of synthesizing their different contributions.
- Extrapolating beyond evidence rather than narrowing or abstaining.
- Spending the episode on prestigious but irrelevant background material.
- Flattening a hierarchical argument or citing a late conclusion without its prerequisites.
- Mishandling Persian terminology, names, script, or contested translations.
- Treating a long duration request as permission to repeat, pad, or add outside knowledge.
- Treating normative guidance as empirical proof, or interpretive scholarship as settled textual fact.

## Deterministic compatibility without premature scoring

The future benchmark should retain source IDs, clean block boundaries, stable locators, source roles, language, case split, requested duration, and Research Brief. Those fields support the repository's existing evidence-linkage, coverage, duration, glossary, and script checks. This design deliberately does not define gold atoms, expected claims, pass thresholds, or scoring code.

## Source-ingestion policy for the later freezing phase

- **Commit-safe:** public-domain or permissively licensed text whose license and required notices have been verified.
- **Conditional commit:** ostensibly open material with a restriction that must be checked against repository distribution (for example non-commercial or no-derivatives terms).
- **Private fixture:** legally accessed copyrighted full text retained outside the public repository.
- **Manifest/excerpt:** commit only bibliographic/retrieval metadata and, after legal review, a short locatable excerpt; acquire the full source reproducibly at evaluation time or in a private store.
- **Unresolved:** do not accept or freeze until access, edition, provenance, or rights are resolved.
