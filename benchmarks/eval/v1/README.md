# Thesisound Semantic Golden Set — Phase 1 design

Status: **proposal; not accepted or frozen**
Design version: `v1`
Verification date: 2026-08-10

This directory contains the source-discovery and case-design artifacts for a proposed 15-case MVP semantic Golden Set: 12 core regression cases and 3 holdouts. It is intentionally separate from both eventual frozen fixtures and the independent OCR/parser benchmarks.

## Scope

This phase defines what the semantic benchmark must measure, proposes cases, records verified real-source candidates, ranks candidate packages, and recommends one package per case for independent review.

It does **not** contain source fixtures, hashes, gold atoms, reference scripts, expected answers, score thresholds, evaluator code, generated source material, or Thesisound outputs. No source package is accepted merely because it is recommended here.

The following independent benchmark trees are out of scope and must remain unchanged:

- `benchmarks/ocr/`
- `benchmarks/parser/`
- `benchmarks/persian_ocr/`

## Artifact map

- [REQUIREMENTS.md](REQUIREMENTS.md) — requirements traced to repository behavior and documentation.
- [CASE-MATRIX.md](CASE-MATRIX.md) — 12 core and 3 holdout case specifications, without answers.
- [SOURCE-CANDIDATES.md](SOURCE-CANDIDATES.md) — verified source packages, acquisition and redistribution notes, and risks.
- [SOURCE-RECOMMENDATIONS.md](SOURCE-RECOMMENDATIONS.md) — explicit ranking rubric, package rankings, recommendations, and adversarial objections.
- [sources.json](sources.json) — machine-readable source, package, and verification metadata.

## Design rules

1. The benchmark is semantic: understanding, evidence fidelity, qualification, coverage, synthesis, relevance, abstention, argument structure, and Persian script preparation.
2. Search snippets, abstracts, metadata, AI summaries, generic summaries, and unverified transcriptions are not substantive evidence.
3. OCR, parser robustness, source discovery quality, TTS, ASR, and audio quality are tested elsewhere. Semantic cases should start from clean, verified text unless source form itself is part of the semantic question.
4. Copyrighted material may be suitable as a private fixture or retrieval manifest without being suitable for repository redistribution.
5. The 5-minute and 30-minute Ostrom cases are one controlled duration experiment. They deliberately reuse the same corpus and brief.
6. Holdout package metadata is designed now, but eventual holdout gold must be separately stored and excluded from ordinary prompt iteration.

## Proposed corpus at a glance

| Split | Cases | Notes |
|---|---:|---|
| Core | 12 | Includes conceptual distinctions in both source-language directions, qualifications, source roles, disagreement, synthesis, abstention, relevance, long-document dependencies, mixed-language synthesis, and the controlled duration pair. |
| Holdout | 3 | Adds normative-to-operational source discipline, probabilistic scientific attribution, and Persian literary ambiguity with competing scholarship. |
| Total | 15 | Fourteen cases have a preferred package ready for independent review; `H15` is conditional on acquiring and validating an edition-controlled Persian primary text. |

## Acceptance gate after this phase

Independent review should challenge the case necessity, source relevance, bibliographic verification, licensing classification, and redundancy analysis before anything is frozen. In particular, `H15` must not advance until the Khanlari edition or an equivalently authoritative edition is legally acquired and the selected Persian verses are manually verified.
