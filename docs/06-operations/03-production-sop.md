# 03 — Production SOP

Origin: item 9 of [`01-server-mono-process-adoption.md`](01-server-mono-process-adoption.md).

## Purpose

This is the procedure a single operator follows to produce one defensible episode. It is an operating sequence, not a feature list. A step is complete only when the named gate has passed and the produced artifact is bound to the inputs that were reviewed.

## The thirteen gates

The `Reads`, `Writes`, `Enforced at`, and `Blocked means` cells below intentionally use the same facts as `GATE_REGISTRY`; `tests/test_gates.py` keeps the registry and this SOP synchronized.

| Step | Code | Actor | Reads | Writes | Enforced at | Blocked means | Operator action |
|---:|---|---|---|---|---|---|---|
| 1 | `brief-confirmed` | Human | Project brief | SOURCES_COLLECTING state | `src/thesisound/web/app.py:885` | The operator has not submitted the project brief (topic and, optionally, scope). | Write a topic (and, optionally, scope) and submit the project-creation form; edit the brief afterward at any time. |
| 2 | `source-selection-confirmed` | Human | Selected source manifest | CORPUS_BUILDING state and queued corpus run | `src/thesisound/web/source_routes.py:738` | The operator has not confirmed the source set. | Review source relevance and inclusion, then confirm the set. |
| 3 | `parse-quality` | Machine | Parsed documents | Parse-quality verdicts | `src/thesisound/services/parse_quality.py:27` | At least one selected source is unsafe for claim extraction. | Re-parse, OCR, or replace unsafe sources. |
| 4 | `evidence-validation` | Machine | Block extractions and source text | Validated evidence items | `src/thesisound/services/evidence_validator.py:55` | Quoted support cannot be matched or validated. | Repair the extraction or remove unsupported material. |
| 5 | `evidence-retention` | Machine | Extraction plan and block outcomes | Source-analysis manifest | `src/thesisound/services/source_analysis_service.py:63` | Less than 85% of planned token mass survived extraction, even after forgiving the largest single lost block. | Restore enough planned evidence or reduce the source scope. |
| 6 | `coverage-duration` | Machine | Coverage report and current brief | Episode-planning eligibility | `src/thesisound/services/coverage_auditor.py:13` | Coverage cannot support at least 80% of the requested duration. | Add sources or reduce the requested duration. |
| 7 | `episode-plan-approval` | Human | Episode Plan | Named approval bound to plan hash | `src/thesisound/services/plan_approval.py:81` | The plan is unapproved or changed after approval. | Review and approve the current plan; edited plans require new approval. |
| 8 | `script-checks` | Machine | Script, plan, evidence packs and glossary | Script check report | `src/thesisound/services/script_checks.py:108` | A deterministic blocking violation exists. | Correct blocking structure or grounding defects. |
| 9 | `independent-verification` | Machine | Script and evidence packs | Verification report | `src/thesisound/services/script_verifier.py:16` | Claims remain unsupported or verification did not pass. | Revise unsupported claims or send the non-blocking result to human review. |
| 10 | `script-review-decision` | Human | Review-required script artifacts | Named review decision | `src/thesisound/web/audio_routes.py:100` | A review-required script has no accepted human decision. | On the audio screen, accept with disclosed notes or send the script back for drafting. |
| 11 | `audio-start` | Human | Verified or review-accepted script | Queued audio build run | `src/thesisound/web/audio_routes.py:100` | The operator has not started audio generation. | Start audio from the audio screen (one click; direction fields optional). |
| 12 | `audio-qa` | Machine | Audio QA report | Accepted audio manifest | `src/thesisound/services/audio_pipeline_service.py:193` | Audio QA failed and no manual-review escape was used. | Regenerate, fix segmentation, or explicitly accept manual review. |
| 13 | `final-listen` | Human | Final assembled audio | Operator release decision | Unenforced | No human final-listen confirmation exists; this is a known gap. | Listen before release. |

## Planned changes for `source_coverage` projects (doc 10, not yet enforced)

[`../01-foundations/10-personal-learning-companion-development-plan.md`](../01-foundations/10-personal-learning-companion-development-plan.md) adds a second lesson intent. Until those phases land, the thirteen gates above are the only enforced ones and `GATE_REGISTRY` is unchanged. When P1–P3 land, this table is updated and `tests/test_gates.py` extended:

| Applies to | Change |
|---|---|
| new machine gate `concept-map-gate` (between 3 and 4) | Pass 5 of the concept-map build: every chapter section has ≥ 1 cell; every cell has ≥ 1 block; no ordering cycle. Critical failures block; `needs_review` flags do not. |
| gate 6 `coverage-duration` | Advisory only for `source_coverage`; replaced by the per-cell coverage check (in-scope cells with no claim are reported and carried into the completion report, never blocking). |
| gate 7 `episode-plan-approval` | The approval covers the whole parts plan (all `LessonPart`s and their segment plans) under one hash; a re-pack after a window overflow requires a new approval. |
| gates 8–12 | Enforced **per part**; a part failing script checks or verification does not block other parts, but the project is not `COMPLETE` until every part passes or has a human review decision. |
| gate 11 `audio-start` | Skipped when `delivery == text`; the state machine goes `SCRIPT_VERIFIED → COMPLETE`. |
| new report (not a gate) | `episode/report.json`: parts vs target, `graph_backed`, cells covered (extracted / planned / spoken), omitted by compression, in scope but not covered, `must_not_be_lost` outcomes, cost per stage. The operator reads it before `final-listen`. |

## The human stops on the build path

Spec 12 budgets exactly three human *blocking* stops between corpus confirmation and audio start:

- `source-selection-confirmed`: the operator owns which sources are admitted as the evidentiary corpus.
- `episode-plan-approval`: the operator accepts the editorial structure and emphasis of the current, hash-bound Episode Plan.
- `audio-start`: the operator authorises irreversible TTS spend (and voice preference).

Entry (`brief-confirmed`) and release (`final-listen`) are human but outside that budget. `script-review-decision` remains a human record when notes require review, but it is non-blocking: accept shares the audio screen as disclosure, not a separate stop.

## Why fewer, better-audited episodes win

Audit cost is fixed and irreducible. Output produced by skipping source selection, approval, verification, or listening is not additional defensible throughput; it is unpriced review debt. The correct optimization target is audited episodes per unit of operator effort, not raw generations per hour.

## What is recorded, and what is not

The operator identity is captured for Episode Plan approval in `EpisodePlanApproval.approved_by` and for a script review decision in `ScriptReviewDecision.reviewer`. It is not yet captured for brief confirmation, source confirmation, or the final listen. Those three missing identities are the known attribution gap tracked by item 12 of [`01-server-mono-process-adoption.md`](01-server-mono-process-adoption.md); they must not be presented as complete human accountability.

## Failure handling

Use [the local live end-to-end runbook](../03-web-ui/10-local-live-e2e-runbook.md), especially section 7, for retry, recovery, and artifact inspection. This SOP defines decision gates; it does not duplicate operational recovery instructions.
