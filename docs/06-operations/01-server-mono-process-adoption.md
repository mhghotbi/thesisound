# 01 — What Thesisound Adopted From server-mono

Date: 2026-08-09 · Source read: `classplus/server-mono` (NestJS / TypeScript / OpenAI) · Target: Thesisound MVP (Python / Gemini)

A process-adoption study, not a code-reuse study. The stacks share nothing at the code level. What transfers is the operating shape: how a run is scored, how a failure is contained, how a human enters the loop, and what gets recorded so a claim about quality can be defended later.

**Items 1–10 are implemented.** Item 9 produced [`03-production-sop.md`](03-production-sop.md); item 6 produced [`../../benchmarks/eval/`](../../benchmarks/eval/). Items 11–14 remain open.

**Second study (2026-08-19), items 15–24 below**, read the AQT Maker / KMS knowledge-graph side of `server-mono` (`apps/aqt-maker/src/pdf-aqt/`, `libs/lxd-engine/`, `libs/mission-engine/`, `libs/database/prisma/schema.prisma`) for the personal-learning pivot. Those items are **planned**, not implemented; their implementation home is [`../01-foundations/10-personal-learning-companion-development-plan.md`](../01-foundations/10-personal-learning-companion-development-plan.md) (P1–P3). Items 11–14 and 15–24 together are the live part of this document.

## Weight definition

Each item was scored on two axes; the final tier is **the higher of the two**.

| Tier | Axis A — implementation cost | Axis B — model runtime cost per episode |
|---|---|---|
| Light | under a day, no migration, one or two files, no contract change | zero extra calls; deterministic logic |
| Medium | one to three days, one new service or simple migration | ~one extra call per stage, or under 20% more tokens |
| Heavy | over three days, new subsystem, architecture change, queue/worker, or data migration | multiple passes, regeneration, or an independent judge; over 20% more tokens or noticeable latency |

## Status

| # | Item | Tier | Status |
|---|---|---|---|
| 1 | Reviewer route ≠ writer route | Light | **Done** — `gemini_reviewer` profile; `script_verifier` routed to it; self-grading blocks the verifier and the script-scope preflight |
| 2 | Pre-model gates in the discovery path | Light | **Done** — URL probe before capture; query-level search cache |
| 3 | Graded quality score, not just a verdict | Light | **Done** — per-dimension weighted score on the script manifest |
| 4 | Revision delta + keep-the-better | Light | **Done** — re-score after revision; accept only on improvement |
| 5 | Run-level rollup row | Light | **Done** — `pipeline_runs` table alongside the per-call ledger |
| 6 | Golden-set eval with numeric gates | Medium | **Done** — `thesisound eval` over frozen cases with `gates.toml` |
| 7 | Three-way script outcome instead of raise | Medium | **Done** — failing script lands in review instead of killing the project |
| 8 | Per-item failure isolation in fan-out | Medium | **Done** — per-block skip with reason instead of aborting the batch |
| 9 | Written production SOP with human-only gates | Medium | **Done** — [`03-production-sop.md`](03-production-sop.md) |
| 10 | Operator readiness view running the real algorithm | Medium | **Done** — `thesisound readiness` + web view re-run gate logic without model calls |
| 11 | Ensemble / majority-vote verification | Heavy | Open — single verifier |
| 12 | Auto-approve gate + self-disabling breaker | Heavy | Open |
| 13 | Per-turn scoring and acceptance | Heavy | Open — revision is per-turn, scoring is whole-script |
| 14 | Async jobs + SSE + orphan recovery | Heavy | **Rejected** — keep deferring |

## Open items

### 11. Ensemble verification with a deterministic-first ladder

**Source.** `libs/question-quality/src/answer-verifier.service.ts:61` toggles ensemble mode; `:394-401` is the majority vote. The escalation order matters: normalize, then deterministic mapping (`:285-333`), and only then an LLM semantic mapping as fallback (`:352-393`).

**Cost.** A: medium. B: heavy — two to three times the verifier calls per episode.

**If adopted.** Run the ensemble only when the single verifier's score lands in a band near the threshold. That bounds axis B and targets the region where disagreement actually lives.

### 12. Auto-approve gate with a self-disabling circuit breaker

**Source.** `docs/content-completion-playbook.md:53-62` — off by default; auto-approval requires three simultaneous conditions (judge actually verified rather than skipped, pedagogical score above 0.70, blended 45/35/20 score above 0.75), and every auto-approval is written with `reviewer_type='auto'` so it stays traceable. `:65` — if 20% or more of the last 20 auto-approvals were later rejected by a human (minimum 5 samples), auto-approve disables itself for that chapter, computed continuously with no manual flag. `:68` describes a pilot → staging → production rollout.

**Cost.** A: heavy (needs a reviews table). B: light — the gate itself adds no calls.

**For MVP.** Take the audit-trail half now: record who approved, on what score, and why. The breaker needs a stream of human rejections that an MVP will not have.

### 13. Score and accept per turn, not per script

**Source.** server-mono's unit of work is one card: validate → critique → oracle → revise → re-score, each independently (`cell-content-pipeline.service.ts:322-424`), so one bad card never sinks the chapter.

**Ours.** Revision is already targeted per turn (`services/script_pipeline_service.py:246`), but scoring and acceptance remain whole-script.

**Cost.** A: medium. B: heavy — verification cost scales with turn count instead of one call per script.

### 14. Async jobs, SSE, orphan recovery — do not adopt

**Source.** `libs/planner-ai-core/src/draft-jobs.ts:3-28` (status/phase enums, 15-minute orphan threshold), `planner-job-sse-hub.ts:19-67` (replay-buffered fan-out), and `PLANNER-OPS.md` on why this cannot run under PM2 cluster mode without a shared queue.

**Ours.** Every stage already resumes from persisted artifacts via `load_*_optional`, and stage callbacks plus tracing spans already report phases. **Recommendation: do not adopt.** The one genuinely missing piece is cancellation, which is far cheaper on its own than the job subsystem around it.

## Second study — concept-graph and curriculum patterns (2026-08-19)

Scope: how AQT Maker turns a textbook into cells, a semantic graph and teaching sessions, and what of that transfers to "learn one humanities source completely, in parts". Same tiering as above. Status "Planned (P<n>)" refers to the phases of doc 10.

| # | Item | Source (server-mono) | Tier | Status / where |
|---|---|---|---|---|
| 15 | Chapter-first hierarchy: chapters → per-chapter passes; chapter titles "exactly as printed, do not guess" | `multi-pass-orchestrator.service.ts:423-1366`, `pdf-structure.prompt.ts:2-12` | Medium | Planned (P1, Pass 0–1) — deterministic chapter detection from `heading_path`/TOC; document map partition = chapter |
| 16 | Formal unit definition + split/merge criteria + "split forbidden" list + banned titles + self-check + `granularityRationale` | `extract-cells.prompt.ts:57-147` | Medium | Planned (P1, `concept_cells/1.0.0`) — humanities version: *assessable* → *traceable* |
| 17 | Progressive chapter awareness in extraction (accepted titles, remaining budget, tightening line); chapter budget = f(section count) | `extract-cells.prompt.ts:15-31`, `chapter-budget-formula.util.ts` | Light | Planned (P1) |
| 18 | Deterministic granularity validation: smell titles, Jaccard ≥ 0.85 merge, sole-cell rewrite; chapter and book title registries | `validate-cell-granularity.pass.ts`, `chapter-cell-dedup.util.ts` | Light | Planned (P1, Pass 2.5) |
| 19 | Consolidate pass `keep \| merge \| remove` to a target "without losing coverage", metadata only | `consolidate-cells.prompt.ts` | Light | Planned (P1, Pass 3) |
| 20 | Chapter gate: critical vs `needs_review`; every TOC section covered; sampled lexical grounding ≥ 0.15 | `chapter-validation.pass.ts`, `content-grounding.service.ts:41-80` | Light | Planned (P1, Pass 5) |
| 21 | Typed edges with `weight`, `confidence`, `rationale`, `created_by ai\|user`; graph prompt rules (real edges only, cap `min(2N,60)`, no cycles, no self-loops) | `schema.prisma:357-378`, `cell-graph.prompt.ts:26-64` | Medium | Planned (P1, Pass 4) — **plus** deterministic cycle/orphan checks, which AQT never implemented |
| 22 | Deterministic session packer: topological readiness + affinity + textbook-order prior; honest `graph_backed`; median for missing minutes; measured warning that the LLM graph is too sparse to sequence alone (46–66 % graph-backed) | `session-planner.service.ts:28-101`, `session.types.ts:35-84`, `session-plan.service.ts` | Medium | Planned (P3, part packer) — owner's fill rule (≥ 0.8 × target) replaces "stop early" |
| 23 | Two extraction modes: *extraction* (follow the book) vs *design* (restructure, content only from text) | `extract-cells.prompt.ts:151-207` | Light | Planned (P1) — default *extraction*; *design* later |
| 24 | Per-chapter checkpoint / resume via phase sentinels; forced spread of importance | `aqt-phase.constants.ts`, `cell-enrichment.prompt.ts` | Light | Planned (P1) — checkpoint file per chapter; tier distribution constraint |

### Not adopted from the second study

| Their pattern | Why not |
|---|---|
| Quiz-based mastery (BKT `student__dynamic_report_bkt`, LP/EWMA `mse__learner_lp`, error types E1–E4, forgetting curve) | The owner is not a student and the product is not an educational platform; a distinction cannot be quizzed. Coverage is tracked, mastery is not. |
| Application paths, atom-level remedial graph, missions | School practice layer for 13-year-olds. |
| Two coexisting mastery models; `spaced_repetition` declared in a taxonomy but never scheduled | Lesson: one model, simple; do not name what is not built. |
| **Text truncation** — chapter text cut to 25–30k chars, microtopic text to 8k with `[... متن قطع شده ...]`, topics located by keyword or proportional slicing, no text IDs (only page ranges) | Thesisound's no-truncation, block-ID discipline is the stronger design and stays. |
| Destructive graph rebuild (deletes owner-authored edges; no snapshot) | Owner edits live in a per-project overlay; the AI map is immutable and content-addressed. |

### What AQT Maker claims versus what it has

Read before copying anything else from it: no cycle detection exists anywhere ("0 inconsistent cycles" on the marketing page is produced by no code path; the investor dossier `03-advantage-and-moat-map.md:75-81` calls the graph "Overstated"); the personalisation engine (`mission-engine`) has zero references to `aqt__cell_relations`; there is no learner-facing graph view; `libs/knowledge-tree-read` has no traversal. Realistic expectation for us: the concept map is a coverage ledger and local sequencer, not a learning-path engine.

## Already had — rejected

| Their pattern | Our equivalent |
|---|---|
| Draft retry loop on bad JSON | `services/model_retry.py` — stage- and error-class policy: provider/timeout/rate-limit still back off; contract repairs are capped per prompt (evidence unlimited within `max_attempts`, document_map/default one repair, episode/glossary/verifier/reviser none). Identical `(error_type, message)` fingerprints stop further repairs. |
| `promptVersion` on every run row | `prompt_loader.py:99`, `services/model_run_store.py:36` — versioned contracts with content hash |
| Skip-if-exists and TTL cache | `services/corpus_reuse.py:38` — sha256 plus identical extraction plan; document map cache |
| Structural validator and math oracle | `services/script_checks.py:53-190` — ten deterministic issue types, three-way verdict; `services/excerpt_matching.py:101` locates excerpts verbatim |
| Role-based client resolution | `model_routing.py:58` — per-stage profiles |
| `mapWithConcurrency` | `services/evidence_extractor.py:122-134` — bounded pool with contextvar binding |
| `onProgress` phase events | `stage(...)` callbacks plus tracing spans |
| `resumeRunId` | artifact-presence resume at every stage |

## Out of MVP scope — rejected

PM2 cluster mode and the shared rate-limit store; per-teacher hourly limits and the HTTP throttle guard; S3 artifact upload (a local workspace is the point of this product); multi-tenant school scoping. All assume many concurrent tenants; our MVP is one local operator.

## Conditional — before routing a stage to a local model

`config/model-routing.toml` defines `okian_qwen` and `okian_gemma`. The moment a stage is routed to one, the failure mode at `cell-content-pipeline.service.ts:177-180` becomes ours: local qwen/gemma intermittently returned truncated or invalid JSON under concurrency, causing a ~23% cell-failure rate, fixed with a bounded draft-retry loop plus a JSON escape repair pass (`repair-llm-json-escapes.util.ts:6-18`, whose comments also document what over-correcting does). Our retry covers half of that; the escape repair is only worth writing once a stage is actually routed to a local model.

## Caveats on this study

Item 6 was load-bearing: items 1, 4, 11 and 12 all change quality/cost trade-offs that could not be measured before the eval harness existed. `answer-verifier.service.ts` and `math-content-oracle.service.ts` were read by outline rather than line by line — the cited patterns are at the cited lines, but their full logic was not audited.
