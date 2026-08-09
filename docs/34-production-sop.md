# Production SOP

## Purpose

This is the procedure a single operator follows to produce one defensible episode. It is an operating sequence, not a feature list. A step is complete only when the named gate has passed and the produced artifact is bound to the inputs that were reviewed.

## The twelve gates

| Step | Code | Actor | Reads | Writes | Enforced at | If blocked |
|---:|---|---|---|---|---|---|
| 1 | `brief-confirmed` | Human | Project brief | Source-collection state | `src/thesisound/web/app.py:787` | Correct or narrow the brief, then confirm it. |
| 2 | `source-selection-confirmed` | Human | Selected-source manifest | Queued corpus build | `src/thesisound/web/source_routes.py:610` | Review source relevance and inclusion, then confirm the set. |
| 3 | `parse-quality` | Machine | Parsed documents | Parse-quality verdicts | `src/thesisound/services/parse_quality.py:15` | Re-parse, OCR, or replace unsafe sources. |
| 4 | `evidence-validation` | Machine | Extractions and source text | Validated evidence | `src/thesisound/services/evidence_validator.py:51` | Repair the extraction or remove unsupported material. |
| 5 | `evidence-retention` | Machine | Planned blocks and outcomes | Source-analysis manifest | `src/thesisound/services/source_analysis_service.py:292` | Restore enough planned evidence or reduce the source scope. |
| 6 | `coverage-duration` | Machine | Coverage report and current brief | Planning eligibility | `src/thesisound/services/coverage_auditor.py:13` | Add sources or reduce the requested duration. |
| 7 | `episode-plan-approval` | Human | Episode Plan | Named, hash-bound approval | `src/thesisound/services/plan_approval.py:57` | Review and approve the current plan; edited plans require new approval. |
| 8 | `script-checks` | Machine | Script and bound artifacts | Deterministic check report | `src/thesisound/services/script_checks.py:185` | Correct blocking structure or grounding defects. |
| 9 | `independent-verification` | Machine | Script and evidence packs | Verification report | `src/thesisound/services/script_verifier.py:30` | Revise unsupported claims or send the non-blocking result to human review. |
| 10 | `script-review-decision` | Human | Review-required script | Named decision and reason | `src/thesisound/web/script_routes.py:114` | Accept with a reason or send the script back for drafting. |
| 11 | `audio-qa` | Machine | Audio QA report | Accepted audio manifest | `src/thesisound/services/audio_pipeline_service.py:205` | Regenerate, fix segmentation, or explicitly accept manual review. |
| 12 | `final-listen` | Human | Final assembled audio | Release decision | Unenforced | Listen before release. Attribution and enforcement remain a known gap. |

## The five steps no model may perform

Steps 1, 2, 7, 10, and 12 are human-only. Replacing the operator at any of them would turn a recorded human judgment into another model output and invalidate the auditability claim: the brief and corpus define intent, the Episode Plan defines editorial structure, script review accepts residual risk, and the final listen accepts the delivered experience.

## Why fewer, better-audited episodes win

Audit cost is fixed and irreducible. Output produced by skipping source selection, approval, verification, or listening is not additional defensible throughput; it is unpriced review debt. The correct optimization target is audited episodes per unit of operator effort, not raw generations per hour.

## What is recorded, and what is not

The operator identity is captured for Episode Plan approval in `EpisodePlanApproval.approved_by` and for a script review decision in `ScriptReviewDecision.reviewer`. It is not yet captured for brief confirmation, source confirmation, or the final listen. This is a known attribution gap rather than evidence of complete human accountability.

## Failure handling

Use [the local live end-to-end runbook](26-local-live-e2e-runbook.md), especially section 7, for retry, recovery, and artifact inspection. This SOP defines decision gates; it does not duplicate operational recovery instructions.
