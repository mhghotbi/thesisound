# 10a. Personal Learning Companion — Direction, Current State, Rules

Part A of the plan (**why**, and what must not change). Part B is the target design ([`10b-personal-learning-companion-design.md`](10b-personal-learning-companion-design.md)); Part C is the implementation plan ([`10c-personal-learning-companion-implementation.md`](10c-personal-learning-companion-implementation.md)). Entry and section map: [`10-personal-learning-companion-development-plan.md`](10-personal-learning-companion-development-plan.md).

Status: approved direction — revision 3.2 (2026-08-19). Cross-project memory is out of scope → [`11-course-memory-future-phase.md`](11-course-memory-future-phase.md).

---

## A0. Owner decisions that shape the plan

1. **One project at a time.** The owner keeps the course (axes, reading lists, field map) outside the system. `research/decolonial-ai/` is the first real use, never an input; nothing in `src/`, `prompts/`, `config/`, `tests/` reads it and nothing will.
2. **Projects are independent.** Nothing carries between projects except content-addressed caches (parsed documents, document maps, concept maps), which describe the source, not the learner.
3. **Two intents, one pipeline:** `focused_question` (today's behaviour) and `source_coverage` (cover all concepts of a source or a chosen part of it).
4. **Episode length is a packing reference, not a project cap.** "20-minute episodes, cover everything" → as many parts as needed, each ≤ 20 min and close to it; only the last part may be short.
5. **Compression is a project setting.** Cells are tagged in three tiers at extraction; the owner picks the compression; the plan reports what it left out. A compressed lesson still carries the prerequisites of what it includes (B1.4).
6. **Chapter-first extraction** (as AQT Maker); no owner confirmation of chapters for now — detection disagreements are flagged, not gated (B2, Pass 0).
7. **Not an educational platform:** no quizzes, self-check questions, transcripts, mastery scores, spaced repetition.
8. **Evidence rigor unchanged; text delivery wanted; humanities focus; quality over cost** — the document map stays in the `source_coverage` path even though it costs a second read of each chapter (C-risks, R1).

---

## A1. Product decision

### A1.1 The job

> Take one source the owner has chosen and turn it — completely, at the compression the owner wants, in parts no longer than the owner's episode length — into evidence-grounded Persian lessons (audio or text), so the owner learns the source without reading all of it. Or, for one focused question about the source, answer that instead. Every statement stays traceable to the source.

### A1.2 Owner flow (one project)

```text
create project → upload / URL source(s)
  → intent
      focused_question → Research Brief → existing pipeline, unchanged
      source_coverage  → scope (whole source | chapters), compression (concise | standard | full),
                         episode_target_minutes (e.g. 20), delivery (audio | text | both),
                         known_concepts (optional free-text list: "do not explain these from scratch")
                         → cost estimate shown before anything runs
  → chapters → document map per chapter → concept cells (tiered) → edges → gate
  → evidence extraction over in-scope cells (cell-unit batches) → claim ledger
  → per-cell coverage check (advisory)
  → packer: cells → parts (≤ target, near-full) → deterministic segment skeleton per part
  → plan narrative per part → script and/or prose per part → verify → audio per part
  → COMPLETE + report: parts; cells covered (extracted / planned / spoken); omitted by compression; in scope but not covered
```

### A1.3 Explicit non-goals

Educational-platform features; multi-user, public product, billing, Simple-Mode polish; any cross-project memory (doc 11); vector memory; a chatbot; a separate pipeline per intent; hard-coding the owner's topic into prompts.

---

## A2. Current state versus target

### A2.1 Three assumptions in the code that conflict with `source_coverage`

**(a) The unit of work is a question.** `ResearchBrief.central_question` (`src/thesisound/domain.py:98`) drives everything but reaches the corpus only as a bag of words intersected with section `key_concepts` (`services/analysis_profile.py:390-399`). Coverage is scored against 2–5 `learning_objectives` (`services/research_brief.py:104-110`, `services/coverage_auditor.py:93-104`), never against the source. **No quantity "what fraction of this source is covered" exists.**

**(b) `target_duration_minutes` parameterises the whole pipeline.** 5–120 bound in five models (`domain.py:101`, `source_analysis.py:62`, `episode.py:71,157`, `services/episode_planning_run.py:48`); depth and token budget derived from it (`analysis_profile.py:68-120`); claim cut-lines `/3, /2, /4` (`claim_prioritizer.py:55-66`); the 80 % supported-duration gate in three places (`coverage_auditor.py:13-28`, `episode_planner.py:58-59`, `episode_planning_run.py:375-380` + `episode_preparation_service.py:399-403`); plan window ±10 % (`episode_planner.py:131-139`).

**(c) One project = one episode, one script.** `Project` holds one `episode_plan` and one `script` (`domain.py:461-471`). No notion of *parts* of one lesson.

### A2.2 Assets to keep untouched

| Asset | Why |
| --- | --- |
| Document map (`domain.py:206-239`) + content-addressed cache (`services/document_map_cache.py`) | Structural input to concept cells; `working_thesis` and section `function` are what let extraction tell the author's position from a reported view; paid once per source |
| Evidence taxonomy `claims / definitions / distinctions / examples / objections / responses / must_not_be_lost` (`domain.py:242-307`); `ClaimType`; `support_status` up to `contested`; disagreement graph | What a humanities "concept" is; disagreement preserved (B5 changes *how* these are carried, not *that* they are) |
| Verbatim-excerpt validation (`services/evidence_extractor.py:641-665`), claim ledger → checks → independent verifier → grounding remediation (repair → excise → stop) | The "nothing not in the source" guarantee |
| Block IDs never invented; 100 % block coverage in the map; **no truncation anywhere**; locators; merge pass sees metadata only; untrusted-content rule; versioned immutable prompts (`prompts/README.md`) | Discipline AQT Maker lacks — keep |
| Rewind with archive; artifacts bound to plan/script hashes; model-call ledger | Reproducibility, cost |

### A2.3 Why the humanities focus changes the design

A KMS "cell" is the smallest self-contained, meaningful and *assessable* unit (`extract-cells.prompt.ts:59-65`). In the humanities the unit is a **definition, distinction, argument, position, objection/response or canonical example**, understood when it can be *explained and traced*, not quizzed. Thesisound already extracts these with locators; the concept cell is built from that taxonomy. Edge types add `objects_to / responds_to / instance_of`; `applies` is dropped. Sources disagree, so a "complete" lesson covers the author's position *and* the objections the author engages.

---

## A3. Lessons from KMS / AQT Maker (`classplus/server-mono`)

The line-by-line study is [`../06-operations/01-server-mono-process-adoption.md`](../06-operations/01-server-mono-process-adoption.md) items 15–24. Summary:

### A3.1 Borrow

| From AQT / KMS | Here |
| --- | --- |
| Chapter-first, then per-chapter passes; chapter titles "exactly as printed, do not guess" | Pass 0 chapters (deterministic, two detectors with disagreement flag); all later passes per chapter |
| Formal cell definition + split/merge + "split forbidden" + banned titles + self-check + `granularityRationale` | `concept_cells` prompt (B-App A.8) |
| Progressive chapter awareness; chapter budget = f(section count) | Same |
| Deterministic granularity validation (smell titles, Jaccard ≥ 0.85, sole-cell rewrite; registries) | Pass 2.5 |
| Consolidate `keep \| merge \| remove` "without losing coverage" | Pass 3 |
| Chapter gate critical vs `needs_review`; section coverage; sampled lexical grounding | Pass 5 |
| Typed edges with `weight, confidence, rationale, created_by`; graph prompt rules | Pass 4 + deterministic cycle/orphan checks AQT never implemented |
| Prerequisite closure ("reference slice", BFS ≤ 25 hops) | Compression selection (B1.4) |
| Deterministic session packer; honest `graph_backed`; median for missing minutes; measured sparsity warning | Part packer (B1.5) with the owner's fill rule |
| Two modes *extraction* vs *design* | Default *extraction*; *design* later |
| Forced spread of importance; per-chapter checkpoint | Tier distribution; checkpoint |
| "Show the price before spending" (content panel) | Pre-run cost estimate (B2) |

### A3.2 Do not borrow

Quiz-based mastery, application paths, remedial atom graph, missions, two mastery models, declared-but-unbuilt features — and **truncation** (AQT slices chapter text to 25–30k chars, microtopic text to 8k; no text IDs). Thesisound's no-truncation, block-ID discipline stays.

### A3.3 What AQT Maker actually has versus what it claims

No cycle detection ("0 inconsistent cycles" is marketing); rebuild deletes owner edges; the personalisation engine never reads the graph; no learner-facing graph. Expectation here: the concept map is a **coverage ledger of one project and a local sequencer**, not a learning-path engine.

---

## A4. Non-negotiable rules

1. **Do not rewrite the evidence pipeline.** Source confirmation, extraction, reconciliation, verification, audio QA stay. Cells, compression, packing, delivery influence scope, order and format only. (B5 tightens prompts; it does not bypass stages.)
2. **`Project` remains the execution unit** — one scope of one source, with parts inside it.
3. **Nothing but current evidence supports a claim.** `known_concepts` is a scoping hint.
4. **Preserve disagreement; do not hard-code the topic.** Prompt regression test: no course-specific terms in any prompt file.
5. **Keep auth; freeze public-product expansion.**
6. **Reproducibility.** Concept map, plan, scripts bound by hashes; changing compression / target / scope after planning marks downstream stale via existing rewind semantics.
7. **Honesty flags are computed, never authored:** `graph_backed`, cells not covered, cells omitted by compression, part minutes vs target, chapter-detection disagreement, pre-run cost estimate.
8. **Quality before cost.** Where a cheaper path measurably degrades claim typing, tiering or coverage, the plan keeps the expensive path and records the cost; cost decisions are made from the ledger in P6, not in advance.
