# 03 — Production SOP

Origin: item 9 of [`01-server-mono-process-adoption.md`](01-server-mono-process-adoption.md).

## Purpose

This is the procedure a single operator follows to produce one defensible episode. It is an operating sequence, not a feature list. A step is complete only when the named gate has passed and the produced artifact is bound to the inputs that were reviewed.

## The twelve gates

The `Reads`, `Writes`, `Enforced at`, and `Blocked means` cells below intentionally use the same facts as `GATE_REGISTRY`; `tests/test_gates.py` keeps the registry and this SOP synchronized.

| Step | Code | Actor | Reads | Writes | Enforced at | Blocked means | Operator action |
|---:|---|---|---|---|---|---|---|
| 1 | `brief-confirmed` | Human | Project brief | SOURCES_COLLECTING state | `src/thesisound/web/app.py:787` | The operator has not confirmed the brief. | Correct or narrow the brief, then confirm it. |
| 2 | `source-selection-confirmed` | Human | Selected source manifest | CORPUS_BUILDING state and queued corpus run | `src/thesisound/web/source_routes.py:610` | The operator has not confirmed the source set. | Review source relevance and inclusion, then confirm the set. |
| 3 | `parse-quality` | Machine | Parsed documents | Parse-quality verdicts | `src/thesisound/services/parse_quality.py:15` | At least one selected source is unsafe for claim extraction. | Re-parse, OCR, or replace unsafe sources. |
| 4 | `evidence-validation` | Machine | Block extractions and source text | Validated evidence items | `src/thesisound/services/evidence_validator.py:51` | Quoted support cannot be matched or validated. | Repair the extraction or remove unsupported material. |
| 5 | `evidence-retention` | Machine | Extraction plan and block outcomes | Source-analysis manifest | `src/thesisound/services/source_analysis_service.py:292` | Less than 85% of planned token mass survived extraction. | Restore enough planned evidence or reduce the source scope. |
| 6 | `coverage-duration` | Machine | Coverage report and current brief | Episode-planning eligibility | `src/thesisound/services/coverage_auditor.py:13` | Coverage cannot support at least 80% of the requested duration. | Add sources or reduce the requested duration. |
| 7 | `episode-plan-approval` | Human | Episode Plan | Named approval bound to plan hash | `src/thesisound/services/plan_approval.py:57` | The plan is unapproved or changed after approval. | Review and approve the current plan; edited plans require new approval. |
| 8 | `script-checks` | Machine | Script, plan, evidence packs and glossary | Script check report | `src/thesisound/services/script_checks.py:185` | A deterministic blocking violation exists. | Correct blocking structure or grounding defects. |
| 9 | `independent-verification` | Machine | Script and evidence packs | Verification report | `src/thesisound/services/script_verifier.py:30` | Claims remain unsupported or verification did not pass. | Revise unsupported claims or send the non-blocking result to human review. |
| 10 | `script-review-decision` | Human | Review-required script artifacts | Named review decision | `src/thesisound/web/script_routes.py:114` | A review-required script has no accepted human decision. | Accept with a reason or send the script back for drafting. |
| 11 | `audio-qa` | Machine | Audio QA report | Accepted audio manifest | `src/thesisound/services/audio_pipeline_service.py:205` | Audio QA failed and no manual-review escape was used. | Regenerate, fix segmentation, or explicitly accept manual review. |
| 12 | `final-listen` | Human | Final assembled audio | Operator release decision | Unenforced | No human final-listen confirmation exists; this is a known gap. | Listen before release. |

## The five steps no model may perform

These five gates are human-only because replacing their judgment with another model output would invalidate the auditability claim:

- `brief-confirmed`: the operator owns the intended question and scope; a model cannot confirm the operator's intent on their behalf.
- `source-selection-confirmed`: the operator owns which sources are admitted as the evidentiary corpus; a model selecting itself as authoritative would collapse source choice into generation.
- `episode-plan-approval`: the operator accepts the editorial structure and emphasis of the current, hash-bound Episode Plan.
- `script-review-decision`: the operator, not the verifier, accepts any residual non-blocking grounding or qualification risk and must record a reason.
- `final-listen`: the operator accepts the delivered listening experience; another automated judgment cannot substitute for that release decision.

## Why fewer, better-audited episodes win

Audit cost is fixed and irreducible. Output produced by skipping source selection, approval, verification, or listening is not additional defensible throughput; it is unpriced review debt. The correct optimization target is audited episodes per unit of operator effort, not raw generations per hour.

## What is recorded, and what is not

The operator identity is captured for Episode Plan approval in `EpisodePlanApproval.approved_by` and for a script review decision in `ScriptReviewDecision.reviewer`. It is not yet captured for brief confirmation, source confirmation, or the final listen. Those three missing identities are the known attribution gap tracked by item 12 of [`01-server-mono-process-adoption.md`](01-server-mono-process-adoption.md); they must not be presented as complete human accountability.

## Failure handling

Use [the local live end-to-end runbook](../03-web-ui/10-local-live-e2e-runbook.md), especially section 7, for retry, recovery, and artifact inspection. This SOP defines decision gates; it does not duplicate operational recovery instructions.
