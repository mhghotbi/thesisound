# Proposed 15-case matrix

No row defines a correct answer. Research Briefs are prompts for a later benchmark implementation, not gold content.

## Core regression cases

### C01 — `james_genuine_option_en_fa`

- **Capability / failure mode:** conceptual distinctions; English sources to Persian output.
- **User scenario:** A Persian-speaking philosophy student wants a short orientation before reading William James.
- **Proposed Research Brief:** Explain how James distinguishes live/dead, forced/avoidable, and momentous/trivial options, how these combine into a “genuine option,” and why the distinctions matter to the essay's argument. Preserve James's limits and do not turn the essay into a generic defense of believing anything.
- **Languages:** English source; Persian output.
- **Topology:** one primary philosophical essay, with a first-edition scan used only for verification.
- **Approximate corpus:** 30–35 book pages; about 12k–18k words.
- **Why non-redundant:** isolates a compact network of contrastive concepts and their Persian renderings without multi-source reconciliation.
- **Failures exposed:** merged distinctions, unstable translations, lost conditions, overbroad thesis, or commentary not found in the text.

### C02 — `putnam_fact_value_fa_fa`

- **Capability / failure mode:** conceptual distinctions in Persian academic prose; Persian sources to Persian output.
- **User scenario:** A Persian philosophy student needs a spoken explanation of a Persian scholarly article.
- **Proposed Research Brief:** Explain the article's distinction between a fact/value distinction and a fact/value dichotomy, and reconstruct how that distinction functions in its account of Putnam's criticism and constructivism. Keep the article's terminology stable.
- **Languages:** Persian source; Persian output.
- **Topology:** one peer-reviewed Persian article.
- **Approximate corpus:** 31 PDF pages; relevant core about 20–25 pages.
- **Why non-redundant:** tests native Persian scholarly syntax and terminology rather than translation from English; its conceptual contrast is not James's modal taxonomy.
- **Failures exposed:** normalizing two technical Persian terms into one, importing an English textbook account, dropping the article's qualifications, or treating its reconstruction as Putnam's own wording.

### C03 — `woolf_argument_qualifications`

- **Capability / failure mode:** argument plus qualifications/caveats; rhetorical and fictional examples.
- **User scenario:** A literature student wants an argument map rather than a plot-like summary.
- **Proposed Research Brief:** Reconstruct the central argument of *A Room of One's Own*, explaining the role and limits of its material conditions, counterfactual figures, and narrative framing. Distinguish assertion, qualification, historical claim, and illustrative fiction.
- **Languages:** English source; Persian output.
- **Topology:** one primary book-length essay, curated by chapters.
- **Approximate corpus:** three non-contiguous chapter ranges, about 85–95 pages.
- **Why non-redundant:** tests whether narrative devices and hypothetical examples are correctly typed inside an argument.
- **Failures exposed:** quoting fictional narration as historical evidence, reducing a qualified argument to a slogan, missing the role of counterexamples, or flattening shifts in voice.

### C04 — `dubois_primary_commentary`

- **Capability / failure mode:** primary source versus secondary interpretation.
- **User scenario:** A social-theory student wants to understand both Du Bois's formulation and how a specialist reference article analyzes its development and ambiguity.
- **Proposed Research Brief:** Present Du Bois's own formulation of double consciousness, then explain how the scholarly commentary distinguishes possible meanings and historical developments. Attribute each layer and identify where interpretation goes beyond explicit primary wording.
- **Languages:** English sources; Persian output.
- **Topology:** primary work plus scholarly commentary.
- **Approximate corpus:** 15–25 primary pages plus 20–30 reference pages.
- **Why non-redundant:** source-role attribution, not merely agreement or disagreement, is the central challenge.
- **Failures exposed:** putting a commentator's taxonomy in Du Bois's mouth, using the primary as proof of later interpretation, or omitting ambiguity.

### C05 — `replication_competing_interpretations`

- **Capability / failure mode:** genuinely competing interpretations and direct scholarly response.
- **User scenario:** A methods student wants to understand what a landmark replication project found and why its authors and critics disagreed about what those results establish.
- **Proposed Research Brief:** Compare the Open Science Collaboration study, Gilbert and colleagues' comment, and the authors' response. Separate shared observations from disputes about design, sampling, statistical interpretation, and the strength of the conclusion.
- **Languages:** English sources; Persian output.
- **Topology:** empirical paper plus formal comment plus formal response.
- **Approximate corpus:** about 50–70 pages including appendices selected only where required.
- **Why non-redundant:** contains explicit, contemporaneous adversarial exchange over the same evidence, unlike interpretive pluralism in the literary holdout.
- **Failures exposed:** false consensus, winner-picking without evidence, confusing a methodological objection with a contrary result, or losing reply structure.

### C06 — `beyond_gdp_complementary_synthesis`

- **Capability / failure mode:** complementary multi-source synthesis.
- **User scenario:** A public-policy student wants an orientation to why GDP is insufficient and how major frameworks supplement it.
- **Proposed Research Brief:** Synthesize how the Stiglitz-Sen-Fitoussi Commission and the OECD organize well-being measurement beyond GDP. Explain their distinct but complementary roles, dimensions, and cautions without presenting either framework as a single substitute number.
- **Languages:** English sources; Persian output.
- **Topology:** two institutional reports with overlapping problem statements and complementary frameworks.
- **Approximate corpus:** 90–130 selected pages across two reports.
- **Why non-redundant:** requires constructing a joint explanatory architecture, not adjudicating a dispute.
- **Failures exposed:** source-by-source book report, conflated frameworks, invented universal index, missing current-well-being versus sustainability distinction, or duplicated evidence.

### C07 — `wfh_bounded_inference`

- **Capability / failure mode:** evidence insufficiency, bounded generalization, and correct abstention.
- **User scenario:** A manager asks a broader question than a strong randomized study can answer.
- **Proposed Research Brief:** What does the supplied evidence establish about whether hybrid working “works generally” across occupations and organizations? Give the supported finding, identify population/intervention/outcome limits, and state which broader conclusions the corpus cannot settle.
- **Languages:** English source; Persian output.
- **Topology:** one high-quality randomized empirical study.
- **Approximate corpus:** one 10–15-page article plus methods detail.
- **Why non-redundant:** the source is credible and positive, so abstention must come from scope discipline rather than weak evidence.
- **Failures exposed:** universalizing from one company and workforce, collapsing retention and performance outcomes, erasing confidence/measurement limits, or inventing evidence for other occupations.

### C08 — `douglass_relevance_filter`

- **Capability / failure mode:** irrelevant or low-value material should not enter the episode.
- **User scenario:** A rhetoric student asks about the internal argumentative progression of a speech, while the corpus also contains authoritative but peripheral biography and reception pages.
- **Proposed Research Brief:** Explain how the 1852 oration builds its argument and changes its address to the audience. Use biographical or reception material only if it is necessary to interpret that progression; otherwise omit it deliberately.
- **Languages:** English sources; Persian output.
- **Topology:** one primary speech plus two authoritative topical decoys.
- **Approximate corpus:** 40 primary pages plus 5–10 pages of decoys.
- **Why non-redundant:** explicitly rewards relevance decisions inside an otherwise trustworthy corpus rather than detecting unreliable sources.
- **Failures exposed:** biography-heavy episode, Fourth-of-July trivia, source prestige bias, loss of rhetorical sequence, or unexplained omission of central passages.

### C09 — `darwin_long_argument_dependencies`

- **Capability / failure mode:** long hierarchical source and dependencies across sections.
- **User scenario:** A history-of-science student wants a deep orientation to the first edition before reading it.
- **Proposed Research Brief:** Trace how the first edition of *On the Origin of Species* moves from variation and struggle to natural selection, addresses major difficulties, and later returns to classification, biogeography, and the conclusion. Make prerequisite relationships explicit and preserve Darwin's stated uncertainties.
- **Languages:** English source; Persian output.
- **Topology:** one long primary monograph.
- **Approximate corpus:** complete 1859 first edition, about 490 printed pages / roughly 150k words.
- **Why non-redundant:** the argument cannot be reconstructed from one chapter; later objections and synthesis depend on earlier mechanisms.
- **Failures exposed:** early-chapter tunnel vision, conclusion-first summary, dropped objections, edition mixing, broken prerequisite ordering, or sampling masquerading as full coverage.

### C10 — `ostrom_5min_compression`

- **Capability / failure mode:** severe but faithful compression.
- **User scenario:** A social-science student has five minutes before a seminar.
- **Proposed Research Brief:** Explain Ostrom's challenge to the markets-versus-states dichotomy and the role of polycentric governance, using only the supplied Nobel lecture.
- **Languages:** English source; Persian output.
- **Topology:** one scholarly lecture/article.
- **Approximate corpus:** exact same 32-page corpus as `C11`; target about 5 minutes.
- **Why non-redundant:** one half of a controlled experiment: selection under compression, not a separate semantic domain.
- **Failures exposed:** overcrowding, undefined essential terms, citation-list summary, loss of thesis, or exceeding duration.

### C11 — `ostrom_30min_depth`

- **Capability / failure mode:** substantially deeper treatment without padding.
- **User scenario:** The same student later requests a 30-minute preparation episode using the same evidence.
- **Proposed Research Brief:** Explain Ostrom's challenge to the markets-versus-states dichotomy and the role of polycentric governance, using only the supplied Nobel lecture.
- **Controlled configuration:** Exact Research Brief reused from `C10`; only the requested duration changes from approximately 5 to 30 minutes.
- **Languages:** English source; Persian output.
- **Topology:** the exact same single-source corpus as `C10`.
- **Approximate corpus:** same 32 pages; target about 30 minutes.
- **Why non-redundant:** tests output-aware depth by direct comparison with `C10`; the longer treatment must add distinct mechanisms, examples, evidence, objections, and qualifications.
- **Failures exposed:** padded paraphrase, repeated claims, outside knowledge, unchanged selection depth, or an episode whose supported duration is lower than requested.

### C12 — `iran_constitution_mixed_language`

- **Capability / failure mode:** mixed Persian and English corpus; primary legal text plus scholarly interpretation.
- **User scenario:** A history student wants to understand an Iranian constitutional settlement through its Persian text and an English scholarly account.
- **Proposed Research Brief:** Explain how the 1906 Fundamental Law and 1907 Supplement allocate and constrain authority among the Majles, monarch, nation, and religious oversight, then use the English scholarship to supply historical and interpretive context. Keep primary provisions and later interpretation distinct.
- **Languages:** Persian primary sources plus English secondary source; Persian output.
- **Topology:** two related primary legal texts plus scholarly commentary.
- **Approximate corpus:** 20–25 primary pages plus 6–12 secondary pages.
- **Why non-redundant:** combines cross-language evidence, legal terminology, and source roles in a Persian historical setting.
- **Failures exposed:** privileging English commentary over Persian provisions, mistranslating institutional terms, anachronism, collapsed source roles, or missing tensions between provisions.

## Holdout cases

### H13 — `ai_ethics_normative_to_operational` — HOLDOUT

- **Capability / failure mode:** mapping normative principles to an operational framework while preserving source type.
- **User scenario:** A policy team wants to relate an international ethics recommendation to a concrete risk-management framework.
- **Proposed Research Brief:** Compare the normative commitments and policy areas in UNESCO's AI ethics recommendation with the functions and practices of NIST AI RMF 1.0. Identify useful mappings and gaps without presenting either document as empirical proof that a practice works.
- **Languages:** English sources; Persian output.
- **Topology:** long international normative instrument plus operational institutional framework.
- **Approximate corpus:** about 90 pages total.
- **Why non-redundant:** adds normative-versus-operational source discipline and a cross-institution mapping problem, not another generic synthesis case.
- **Failures exposed:** normative-to-empirical category error, forced one-to-one mapping, lost institutional scope, checklist recital, or invented effectiveness claims.

### H14 — `climate_event_attribution_uncertainty` — HOLDOUT

- **Capability / failure mode:** consensus synthesis with probabilistic methods and calibrated uncertainty.
- **User scenario:** A science-policy listener asks what scientists can and cannot attribute about a particular class of extreme events.
- **Proposed Research Brief:** Explain the logic and limits of extreme-event attribution using the IPCC assessment and a methods paper. Distinguish event occurrence, changed probability or intensity, event classes, confidence, and causal wording.
- **Languages:** English sources; Persian output.
- **Topology:** large consensus assessment plus focused peer-reviewed methods/reliability paper.
- **Approximate corpus:** 50–80 selected assessment pages plus a 10–15-page paper.
- **Why non-redundant:** scientific uncertainty must be communicated without either false balance or overclaiming; it is not an evidence-scarcity case.
- **Failures exposed:** “caused by” overstatement, confusion of probability and intensity, confidence laundering, decontextualized headline claims, or treating methods critique as denial of attribution.

### H15 — `hafez_interpretive_ambiguity_mixed` — HOLDOUT

- **Capability / failure mode:** Persian primary language, competing interpretation, literary ambiguity, and contested terminology.
- **User scenario:** A Persian literature student wants a careful account of how a small edition-controlled group of Hafez ghazals bears on scholarly readings of `رند` and related terms.
- **Proposed Research Brief:** Using only the selected Persian poems and two English scholarly articles, explain how poetic ambiguity supports and constrains interpretations of `رند`, `ریا`, `زاهد`, and wine imagery. Keep the poem, editorial text, and scholars' interpretations distinct; do not resolve ambiguity by fiat.
- **Languages:** Persian primary source plus English scholarship; Persian output.
- **Topology:** a small edition-controlled primary selection plus two complementary/partly competing specialist interpretations.
- **Approximate corpus:** 3–5 ghazals plus 15–25 secondary pages.
- **Why non-redundant:** tests ambiguity that is constitutive rather than merely uncertain, with terminology whose translation can predetermine interpretation.
- **Failures exposed:** paraphrase presented as textual fact, one reading declared final, unstable Persian terms, verse supplied from an unverified web transcription, or commentary placed in Hafez's voice.
- **Readiness warning:** this case remains conditional until an authoritative Persian edition is acquired, rights are resolved, and every selected verse is manually collated. It must not use web summaries or OCR as evidence.

## Coverage and redundancy audit

| Required capability | Case(s) |
|---|---|
| English conceptual distinctions → Persian | C01 |
| Persian conceptual distinctions → Persian | C02 |
| Argument plus qualifications/caveats | C03 |
| Primary versus secondary | C04, C12 |
| Genuine competing interpretations | C05; H15 uses a structurally different literary form |
| Complementary synthesis | C06; H13 adds source-type mapping |
| Evidence insufficiency / abstention | C07 |
| Irrelevant or low-value material | C08 |
| Long hierarchical dependencies | C09; H13 is a multi-institution holdout rather than a clone |
| Mixed Persian + English | C12; H15 holdout |
| Compression | C10 |
| Deeper controlled treatment | C11 |
| Important nontrivial combinations | H13, H14, H15 |

Two material gaps were added without increasing the 15-case target: source-type discipline (normative guidance is not empirical evidence) in `H13`, and literary/terminological ambiguity in `H15`. These are recurrent evidence-fidelity failures not fully exercised by topical diversity alone.

The main deliberate overlap is `C10`/`C11`, which is required for a controlled duration experiment. `C04` differs from `H15` because it tests primary/commentary attribution around a concept, while `H15` tests irreducible literary ambiguity and contested Persian terms. `C05` is a direct methodological comment/response exchange; `H15` is not. `C06` combines complementary measurement frameworks; `H13` maps different document types and must resist treating normative language as an observed result.
