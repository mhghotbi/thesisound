# What Thesisound Can Adopt From server-mono — MVP Scope

Date: 2026-08-09
Source repository read: `classplus/server-mono` (NestJS / TypeScript / OpenAI)
Target: Thesisound MVP (Python / Gemini)

This is a process-adoption study, not a code-reuse study. The two stacks share
nothing at the code level. What transfers is the operating shape: how a run is
scored, how a failure is contained, how a human enters the loop, and what gets
recorded so a claim about quality can be defended later.

## Weight definition

Every item is scored on two independent axes. **The final tier is the higher of
the two.**

**Axis A — implementation cost.** Dev time, number of new files or services,
schema migrations, risk to the currently working path.

| Tier | Meaning |
|---|---|
| Light | Under one working day, no migration, one or two files, no contract change |
| Medium | One to three days, one new service or a simple migration, limited contract change |
| Heavy | More than three days, a new subsystem, an architecture change, a queue/worker, or a data migration |

**Axis B — model runtime cost, per episode.** Extra model calls, extra tokens,
latency, and whether the work sits on the critical path.

| Tier | Meaning |
|---|---|
| Light | Zero extra calls; deterministic, programmed logic |
| Medium | About one extra call per stage, or under 20% more tokens |
| Heavy | Multiple passes, regeneration, or an independent judge; over 20% more tokens or noticeable added latency |

## Summary

| # | Item | Tier | A | B | Our status |
|---|---|---|---|---|---|
| 1 | Reviewer route ≠ writer route | Light | L | L | Have infra, misconfigured |
| 2 | Pre-model gates in the discovery path | Light | L | L (negative) | Missing |
| 3 | Graded quality score, not just a verdict | Light | L | L | Verdict only |
| 4 | Revision delta + keep-the-better | Light | L | L | Accepts blindly |
| 5 | Run-level rollup row | Light | L | L | Per-call only |
| 6 | Golden-set eval with numeric gates | Medium | M | M | Parser/OCR only |
| 7 | Three-way script outcome instead of raise | Medium | M | L | Hard exception |
| 8 | Per-item failure isolation in fan-out | Medium | M | L | One failure aborts batch |
| 9 | Written production SOP with human-only gates | Medium | M | L | Missing |
| 10 | Operator panel: coverage + real-algorithm readiness | Medium | M | L | Partial |
| 11 | Ensemble / majority-vote verification | Heavy | M | H | Single verifier |
| 12 | Auto-approve gate + self-disabling breaker | Heavy | H | L | Missing |
| 13 | Per-turn scoring and acceptance | Heavy | M | H | Whole-script |
| 14 | Async jobs + SSE + orphan recovery | Heavy | H | L | Deliberately deferred — keep deferring |

---

## Light

### 1. Route the verifier to a different model than the writer

- **Source.** `libs/cell-content-engine/src/quality/content-critique.service.ts:104-162`
  resolves a separate critique client and model, and `:152-156` logs
  `content critique is self-grading` when it cannot.
  `libs/question-quality/src/answer-verifier.service.ts:47,54` gives the verifier
  its own model and temperature; every call carries `role: 'verifier'` (e.g. `:274`).
- **Ours.** The router exists (`src/thesisound/model_routing.py:58`), but
  `config/model-routing.toml` sends both `persian_script_segment` and
  `script_verifier` to `gemini_strong`. The writer grades its own work. The same
  holds for `coverage_audit` and `claim_reconciliation`.
- **Change.** Add a distinct reviewer profile, route `script_verifier` to it, and
  emit a startup / `doctor` warning whenever a verifier stage resolves to the same
  profile as the stage it verifies.
- **Cost.** A: light — config plus one check in the router. B: light — call count
  unchanged; only the price per call moves.
- **Acceptance.** One recorded run shows different `model` values for
  `persian_script_segment` and `script_verifier` in the ledger.
- **Risk.** A cheaper reviewer may catch less. Not measurable until item 6 exists.

### 2. Cheap deterministic gates before spending a grounded call

- **Source.** `libs/cell-content-engine/src/discovery/link-verifier.service.ts:36-53`
  (SSRF-safe URL assertion plus an optional domain allowlist) and `:55-91` (HEAD
  first, then GET with `Range: bytes=0-0` as fallback, because some hosts reject
  HEAD). Plus `discovery-cache.service.ts:18-46`: cache keyed on `sha256(query)`
  with a configurable TTL, default 24h.
- **Ours.** A selected URL goes straight into `web_source_capture` and only then
  hits the parse-quality gate, so a dead or paywalled URL costs a full grounded
  model call. We cache document maps (`services/source_analysis_service.py:110`)
  and whole-corpus reuse (`services/corpus_reuse.py:38`), but there is no
  query-level cache in the discovery path.
- **Cost.** A: light. B: negative — it removes calls.
- **Acceptance.** Capture is never attempted on a URL that failed the probe; a
  repeated identical search within the TTL issues no new Search call.

### 3. Persist a graded score, not just a verdict

- **Source.** `content-critique.service.ts:69-90` — five dimensions with explicit
  weights (0.3 / 0.25 / 0.2 / 0.15 / 0.1), normalized to 0–1, plus
  `actionable_feedback`; threshold read from config at `:96-101`. Stored per
  artifact as `qualityScore` / `qualityDetails` / `qualityWarning`
  (`cell-content-pipeline.service.ts:413-423`).
- **Ours.** `VerificationDraft` carries a verdict and `unsupported_claim_ratio`
  only (`services/script_verifier.py:59`). There is no continuous quality signal
  to threshold, trend, or compare across runs.
- **Change.** Extend the `script_verifier` prompt contract (new version) with
  per-dimension scores and a weighted overall; store it on the script manifest and
  in the ledger.
- **Cost.** A: light — prompt version bump, one pydantic model, one storage field.
  B: light — same single call, slightly more output tokens.

### 4. Record the revision delta and keep the better version

- **Source.** `cell-content-pipeline.service.ts:355-357` captures the pre-revision
  score, `:389-394` re-scores after revision and computes the delta, `:395-396`
  accepts the revision only if it scored higher, `:419-420` persists both `revised`
  and `revisionDelta`.
- **Ours.** `services/script_pipeline_service.py:339-383` revises, re-checks,
  re-verifies, then replaces the script unconditionally; if the revised script
  fails deterministic checks it raises at `:364`.
- **Cost.** A: light once item 3 exists. B: zero extra calls.
- **Why it matters.** This is the only way to learn whether `script_reviser` earns
  its cost, or whether it burns a strong-model call to move sideways.

### 5. One rollup row per run

- **Source.** `libs/cell-content-engine/src/persistence/content-run.repository.ts:19-44`
  creates a run row with totals, `model_label`, `prompt_version`, `started_at`;
  `:46-75` patches `cells_done` / `cells_failed` / `tokens_in` / `tokens_out` /
  status / `error_message` / `finished_at`.
- **Ours.** The ledger is per-call — `model_calls`, `model_attempts`,
  `pipeline_spans`, `pipeline_events` (`src/thesisound/observability.py:1349`).
  Answering "what did this episode cost" means aggregating. Related:
  `src/thesisound/config.py:88` points at `config/model-pricing.toml`, which does
  not exist in `config/`, consistent with STATUS.md saying pricing-versioned cost
  is not implemented.
- **Cost.** A: light — one table plus a writer at run end. B: zero.

---

## Medium

### 6. A frozen golden set with numeric release gates

- **Source.** `libs/question-designer/eval/golden-atoms.json` plus
  `src/cli/run-golden-eval.ts:75-84` (loads a fixed case file) and `:92-98`
  (asserts against `minVerified` 0.95 / `minPed` 0.75 and prints a summary), with
  a `--dry-run` mode at `:78`. Separately, `npm run qd:agreement-report` measures
  machine-versus-teacher agreement; `eval/reports/AGREEMENT-2026-06-11.md` is
  honest that it has no human reviews yet.
- **Ours.** `benchmarks/` covers `parser`, `ocr`, and `persian_ocr` only. There is
  no fixed-case regression eval on model output, so STATUS.md's "next empirical
  work" is entirely manual inspection.
- **Change.** A `thesisound eval` command over three to five frozen mini-projects
  (small corpus, fixed brief), asserting verifier verdict rate, unsupported-claim
  ratio, coverage, and cost per output minute.
- **Cost.** A: medium. B: medium — each case is a real run; keep it text-only
  (stop before TTS) to bound it.
- **Dependency note.** This is the prerequisite that makes items 1 and 4 safe to
  tune.

### 7. Land a failing script in review instead of raising

- **Source.** `libs/cell-content-engine/src/promotion/promote-content-status.util.ts:15-40`
  — Approved / Rejected / Pending_Review from explicit thresholds, with a
  deterministic violation capping the score regardless of what the judge said;
  `:42-53` builds a human-readable transition reason stored with the decision.
- **Ours.** `services/script_pipeline_service.py:386` raises
  `ValueError("Script failed verification after one targeted revision.")` and the
  project dies. We already use the three-way shape elsewhere in our own code —
  parse quality (`src/thesisound/quality.py:29`) and audio QA
  (`src/thesisound/audio.py:65`, with an `accept_manual_review` escape at
  `services/audio_pipeline_service.py:189`). The script stage is the outlier.
- **Cost.** A: medium — new state, store field, UI surface. B: zero.

### 8. Isolate per-item failures in fan-out

- **Source.** `libs/cell-content-engine/src/orchestration/chapter-content.orchestrator.ts:81-119`
  wraps each cell in try/catch and returns `skipped` plus `skipReason` instead of
  throwing; `:133-149` tallies done and failed, and marks the run failed only when
  everything failed.
- **Ours.** `services/evidence_extractor.py:136-143` cancels pending work and
  re-raises on the first exception. Finished blocks are saved and skipped on
  retry, so nothing is lost — but the operator gets an abort rather than "38 of 40
  blocks extracted, 2 failed, here is why."
- **Cost.** A: medium. B: zero.

### 9. Write the production SOP, and mark the steps no model may perform

- **Source.** `docs/deep-mission-production-sop.md` §1 — an eleven-step table
  where step 7 is an independent literal solve (any blocker sends you back to step
  2 or 5) and step 8 is a genuinely independent human reviewer, annotated that no
  model can substitute for a human there. §2 argues explicitly that audit cost is
  fixed and irreducible, so fewer well-audited units beat many unaudited ones.
- **Ours.** The gates exist in code and in prompts; the operating procedure around
  them is not written down. For a thesis-grade auditability claim this is the
  highest-leverage document in the repository.
- **Cost.** A: medium (writing plus reconciling with the real gates). B: zero.

### 10. Operator views that run the real algorithm

- **Source.** `docs/content-completion-playbook.md:27-38` — a coverage tab that
  counts what exists, and next to it a slower readiness check that runs the actual
  engine algorithm per item rather than counting rows, with the explicit warning
  that a unit can look full in the coverage view and still fail readiness. Every
  panel command carries a `safe` / `readonly` / `writes` badge (`:25`), and the
  operator's name is recorded on every run (`:13`).
- **Ours.** We have `doctor` and a web UI, but no single "is this project actually
  ready to proceed, per the real gate logic" view, and no danger classification on
  CLI commands.
- **Cost.** A: medium. B: zero.

---

## Heavy

### 11. Ensemble verification with a deterministic-first ladder

- **Source.** `libs/question-quality/src/answer-verifier.service.ts:61` toggles
  ensemble mode; `:394-401` is the majority vote. Note the escalation order:
  normalize, then deterministic mapping (`:285-333`), and only then an LLM
  semantic mapping as fallback (`:352-393`).
- **Cost.** A: medium. B: heavy — two to three times the verifier calls per
  episode.
- **Recommendation if adopted.** Run the ensemble only when the single verifier's
  score lands in a band near the threshold. That bounds axis B and targets the
  region where disagreement actually lives.

### 12. Auto-approve gate with a self-disabling circuit breaker

- **Source.** `docs/content-completion-playbook.md:53-62` — off by default;
  auto-approval requires three conditions simultaneously (the judge actually
  verified rather than skipped, pedagogical score above 0.70, blended 45/35/20
  score above 0.75), and every auto-approval is written with `reviewer_type='auto'`
  so it stays traceable. `:65` — if 20% or more of the last 20 auto-approvals were
  later rejected by a human (minimum 5 samples), auto-approve disables itself for
  that chapter, computed continuously with no manual flag. `:68` describes a
  pilot → staging → production rollout.
- **Cost.** A: heavy (depends on items 3 and 7 plus a reviews table). B: light —
  the gate itself adds no calls.
- **For MVP.** Take the audit-trail half now: record who approved, on what score,
  and why. The breaker needs a stream of human rejections that an MVP will not
  have.

### 13. Score and accept per turn, not per script

- **Source.** server-mono's unit of work is one card: validate → critique → oracle
  → revise → re-score, each independently
  (`cell-content-pipeline.service.ts:322-424`), so one bad card never sinks the
  chapter.
- **Ours.** Revision is already targeted per turn
  (`manifest.revision_count += len(draft.revised_turns)`,
  `services/script_pipeline_service.py:246`), but scoring and acceptance are
  whole-script.
- **Cost.** A: medium. B: heavy — verification cost scales with turn count instead
  of one call per script.

### 14. Async jobs, SSE, orphan recovery — keep deferring

- **Source.** `libs/planner-ai-core/src/draft-jobs.ts:3-28` (status and phase
  enums, 15-minute orphan threshold), `:57-61` (cancellation error),
  `planner-job-sse-hub.ts:19-67` (replay-buffered fan-out, kept 60s for late
  subscribers), `:69-81` (human-readable phase messages), and `PLANNER-OPS.md` on
  why this cannot run under PM2 cluster mode without a shared queue.
- **Ours.** M10 is explicitly unimplemented, and we already get most of the
  benefit for free: every stage resumes from persisted artifacts via
  `load_*_optional`, and stage callbacks plus tracing spans already report phases.
- **Cost.** A: heavy. B: zero.
- **Recommendation.** Do not adopt. The one piece genuinely missing is
  cancellation, which is far cheaper on its own than the job subsystem around it.

---

## Already have — rejected

| Their pattern | Our equivalent |
|---|---|
| Draft retry loop on bad JSON (`cell-content-pipeline.service.ts:181-190`) | `services/model_retry.py:25` — retry with a repair instruction on contract failure |
| `promptVersion` on every run row (`content-run.repository.ts:12`) | `prompt_loader.py:99` and `services/model_run_store.py:36` — versioned contracts with content hash |
| Skip-if-exists and TTL cache (`cell-content-pipeline.service.ts:91-105`) | `services/corpus_reuse.py:38` — sha256 plus identical extraction plan; document map cache |
| Structural validator and math oracle (`structural-validator.service.ts:17-53`) | `services/script_checks.py:53-190` — ten deterministic issue types, three-way verdict; `services/excerpt_matching.py:101` locates excerpts verbatim |
| Role-based client resolution | `model_routing.py:58` — per-stage profiles |
| `mapWithConcurrency` | `services/evidence_extractor.py:122-134` — bounded pool with contextvar binding |
| `onProgress` phase events | `stage(...)` callbacks plus tracing spans through the script pipeline |
| `resumeRunId` | Artifact-presence resume at every stage |

## Out of MVP scope — rejected

PM2 cluster mode and the shared rate-limit store (`PLANNER-OPS.md`, "AI rate
limiting"); per-teacher hourly limits and the HTTP throttle guard
(`openai-planner.ts:14,24-40`); S3 artifact upload
(`cell-content-pipeline.service.ts:497-513`), since a local workspace is the point
of this product; multi-tenant school scoping throughout. All of these assume many
concurrent tenants; our MVP is one local operator.

## Conditional — worth knowing before flipping a switch

`config/model-routing.toml` already defines `okian_qwen` and `okian_gemma`
profiles. The moment a stage is routed to one, the failure mode documented at
`cell-content-pipeline.service.ts:177-180` becomes ours: local qwen/gemma
intermittently returned truncated or invalid JSON under concurrency and caused a
roughly 23% cell-failure rate, which they fixed with a bounded draft-retry loop
plus a JSON escape repair pass
(`libs/question-quality/src/repair-llm-json-escapes.util.ts:6-18`, whose comments
also document what over-correcting does). Our retry already covers half of that;
the escape repair is only worth writing if and when a stage is actually routed to
a local model.

## Caveats on this study

Item 6 is load-bearing. Items 1, 4, 11, and 12 all change quality and cost
trade-offs that we currently cannot measure, so doing them before the eval harness
means tuning blind.

`answer-verifier.service.ts` and `math-content-oracle.service.ts` were read by
outline rather than line by line. The patterns cited from them are at the cited
lines, but their full logic was not audited.
