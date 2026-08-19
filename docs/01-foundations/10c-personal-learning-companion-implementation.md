# 10c. Personal Learning Companion — Implementation Plan

Part C of the plan (**how**): phases at developer detail, order, protocol, file guidance, risks, definition of done. Part A (direction, rules): [`10a-personal-learning-companion-direction.md`](10a-personal-learning-companion-direction.md). Part B (design, prompt texts): [`10b-personal-learning-companion-design.md`](10b-personal-learning-companion-design.md). Section references `B1.4`, `A4`, `App A.1` point into those parts.

Revision 3.2 (2026-08-19). Changes from 3.1: new **P0.5 grounding hotfix** (writer 1.3.0, claims in packs, must-not-be-lost review page) before P1; two-way chapter detection (P1); tier auto-promotion (P1); cell-unit batch extraction and no-migration switch-all for extraction 2.0 (P2); prerequisite closure, deterministic segment skeleton and pre-run cost estimate (P3); risk list rewritten as status table (§C-R).

Conventions for all phases: Python 3.12, Pydantic v2, `uv run pytest`; every new prompt is `prompts/<id>/<version>/{contract.json,system.md,user.md}` with bare `{{ name }}` placeholders and a Pydantic `output_model`; every model call goes through `ModelRunner.run(...)` with a deterministic `validator`; every artifact write is atomic as `WorkspaceStore` does; new pages are Jinja + HTMX; Persian labels from `docs/05-ui-redesign/03-product-language.md`. Do not touch a `focused_question` code path unless a phase says so.

---

## P0 — Product contract (docs only) — **done 2026-08-19**

`PRODUCT.md`, `STATUS.md`, `docs/01-foundations/01…09`, `docs/02-pipeline/03…06`, `docs/06-operations/*`, `docs/07-specs/05` (cut-lines), `prompts/README.md`, prompt design notes moved to `docs/02-pipeline/prompt-design-notes/`.

---

## P0.5 — Grounding hotfix (independent of everything; ship before P1)

Goal: close the largest invented-content path and the two cheapest data-visibility gaps now.

**Step 1 — `persian_script_segment/1.3.0`** exactly as App A.1 (grounding contract + 1.2.0 tone verbatim + speaker roles). `persian_script_writer.write_segment` passes `claims`, `known_concepts` (`[]` today), `part_index=1`, `part_count=1`. Update `tests/test_script_speaker_balance.py::test_latest_script_prompt_is_1_2_0_and_renders_position` to pin 1.3.0 (it currently fails on 1.2.0 because the grounding sentence is missing — that failure is the bug, not the test).

**Step 2 — `ClaimRecord` in packs (C5):** `SegmentEvidencePack.claims: list[ClaimRecord]`; `evidence_pack_builder._build_segment` fills it from `claim_by_id`; `CLAIMS_JSON` added to writer (1.3.0), `script_verifier/1.2.0` (App A.5) and `script_reviser/1.1.0` (input only).

**Step 3 — `script_checks.unsupported_specifics`** (C1, deterministic): for each substantive turn, tokens matching `\d{2,}`, 4-digit years, Latin capitalised words, and quoted spans «…»/"…" must occur (after the existing normalisation) in the union of the turn's cited excerpts and the pack's original/context blocks; otherwise a `medium` issue with the offending tokens. Persian digits normalised to ASCII before matching.

**Step 4 — Must-not-be-lost review page:** render the already-computed `MustNotBeLostReview` (`episode/must-not-be-lost-review.json`) on the episode page: point text, candidate claims, `used_in_plan`; `unused_count` in the page header. No model call.

Tests: prompt render 1.3.0 (grounding sentences present — `tests/prompts/test_grounding_sentences.py`), pack contents, `unsupported_specifics` positive/negative Persian fixtures, page renders with fixture review. Acceptance: a fixture script with a year not in the pack is flagged by checks and by the verifier; `focused_question` golden outputs change only in the script stage (documented).

---

## P1 — Concept map (passes 0–5)

**Deliverables:** `src/thesisound/concepts.py`; `services/concept_map_builder.py`; `services/concept_map_cache.py`; `services/concept_map_overlay.py`; prompts `concept_cells/1.0.0`, `concept_cells_consolidate/1.0.0`, `concept_edges/1.0.0` (App A.8–A.10); `document_mapper` chapter partitioning; CLI `thesisound concept-map`; web page `GET /projects/{pid}/sources/{sid}/concept-map`; tests `tests/concepts/`.

**Step 1 — models** (`concepts.py`): B1.2–B1.3 exactly, plus draft models:

```text
ConceptCellDraft: label_fa, label_source|None, kind, tier, section_ids, block_ids, granularity_rationale, estimated_minutes
ConceptCellsDraft: cells: list[ConceptCellDraft], warnings: list[str]
ConsolidateActionDraft: cell_key, action: keep|merge|remove, merge_into: str|None, reason
ConceptCellsConsolidateDraft: actions: list[ConsolidateActionDraft]
ConceptEdgeDraft: source_key, target_key, type, weight, confidence, rationale_fa
ConceptEdgesDraft: edges: list[ConceptEdgeDraft], warnings: list[str]
```

**Step 2 — Pass 0 `detect_chapters(blocks, parsed_document) -> list[SourceChapter]`** (pure):
1. Detector H (headings): for depth `d` in `0, 1`, group contiguous runs of `heading_path[d]`; accept the first depth that yields ≥ 2 groups whose median size ≥ 8 blocks and whose largest group ≤ 60 % of blocks.
2. Detector T (TOC): if the parsed document exposes a TOC (Docling/MinerU headings list, EPUB nav), map entries to the first block whose heading matches (normalised).
3. Reconcile: both found and boundaries agree (≤ 20 % of blocks assigned differently, no chapter > 40 % or < 2 % of blocks) → `agreed`, use H; only one found → use it (`heading_only` / `toc_only`); both found and disagree → use T, mark every chapter `disagreed`, add `needs_review` "chapter detection disagreed: <summary>". Neither → one chapter `single`.
4. Front-matter blocks before the first chapter join chapter 0. `estimated_minutes` provisional = Σ `estimated_token_count` / 300 (replaced by Σ cell minutes after Pass 2).
Tests: Docling PDF with H1 chapters (agreed), flat-heading PDF with TOC (toc_only), EPUB nav, disagreement fixture, single-article source.

**Step 3 — Pass 1** `DocumentMapperService.map_document(..., partitions=chapter_partitions)`: new optional argument; when given, `_partition_blocks` is bypassed and each chapter is a partition (sub-partitioned by the existing size logic only if a chapter exceeds `maximum_input_characters`). Merge pass unchanged. Golden test: same source mapped both ways yields identical block coverage.

**Step 4 — Pass 2 `concept_cells/1.0.0`** (App A.8; fast tier, `ConceptCellsDraft`, `max_attempts 3`). Inputs: `SOURCE_ID`, `CHAPTER_JSON`, `SECTIONS_JSON` (the chapter's map sections incl. `function`, `key_concepts`, `required_for_global_understanding`), `BLOCKS_JSON` (full text, never truncated), `CHAPTER_AWARENESS`, `BUDGET`, `MODE=extraction`. Deterministic validator `_validate_cells_draft`: unknown `block_id`/`section_id`; cell without block; every non-`front_matter`/`transition` section has ≥ 1 cell; banned/smell label regex (Persian and English lists in `concepts.py`); duplicate labels (Jaccard ≥ 0.85 → error on attempts 1–2, auto-merge on the final attempt); count ≤ `budget × 1.5`; tier distribution (B1.4). Chapter budget = `clamp(ceil(non_front_matter_sections × 1.5), 6, 40)`. Cell keys assigned after validation in block order.

**Step 5 — Pass 2.5** `normalise_cells(cells)` (pure): near-duplicate merge (union blocks/sections, keep earliest key, warn); source-level registry catches the same label in two chapters (warn, record `related` candidate for Pass 4; do not merge across chapters).

**Step 6 — Pass 3 `concept_cells_consolidate/1.0.0`** (App A.9): only when a chapter's count > budget; metadata only; validator: keys exist, merge target is `keep`, no section loses its last cell, count ≤ budget.

**Step 7 — Pass 4 `concept_edges/1.0.0`** (App A.10): per chapter, then per consecutive chapter pair within window 2 — **always built** (owner decision; no graph-sparsity cutoff). Validator `_validate_edges`: unknown keys; invalid type; clamp; dedup `(src,dst,type)`; **cycle detection** over `prerequisite/depends_on/extends` → attempts 1–2: error listing the cycle; final attempt: drop the lowest-weight edge of each cycle, warn; cap by keeping highest weight.

**Step 8 — Pass 4.5 tier promotion** `promote_tiers(cells, edges, sections) -> cells` (pure; B1.3): `required_for_global_understanding` or prerequisite out-degree ≥ 2 → tier ≤ 2; out-degree ≥ 4 → tier 1; `tier_promoted = true`, `statistics.promoted_cell_keys`; owner overrides win.

**Step 9 — Pass 5** `compute_statistics(map)` (pure): counts per B1.3; orphans (report, not error); `needs_review`: `label_source` present and lexical overlap with block text < 0.15; cells/sections ratio > 3 or < 0.5; single-tier chapter; oversize cell (> 30 min); chapter-detection `disagreed`. Critical (raise): a section with no cell after consolidation; a cell with no block; unknown IDs.

**Step 10 — builder orchestration** `ConceptMapBuilder.build(project_id, source_id, blocks, document_map, parsed_document, *, model_fast) -> SourceConceptMap`: cache lookup by fingerprint and per-chapter sub-entries (`emit_cache_lookup` events); per-chapter loop with checkpoint `sources/<sid>/concept-map.partial.json`; write the source-level cache only when all chapters and Pass 5 succeed. `ConceptMapOverlayService.apply(map, overlay)` and `record_edit(...)`.

**Step 11 — CLI** `thesisound concept-map <path> [--chapters 1,3] [--rebuild] [--json]`: parse, map, build; print chapters (with `detection_agreement`), cells per tier, promoted cells, edges, statistics, and **estimated tokens per pass** (first use of `cost_estimate`, B1.8).

**Step 12 — web page** (read-mostly): chapters with detection flag; cell table (label, kind, tier + promoted marker, minutes, blocks → source trace); edge list with rationale and `created_by`; statistics and `needs_review`; forms to add/remove a cell or edge and to override a tier (overlay). No graph-drawing library yet (P5).

**Tests** (`tests/concepts/`): `test_detect_chapters.py` (both detectors, reconcile, disagreement), `test_cells_validator.py` (each rule), `test_consolidate_validator.py`, `test_edges_validator.py` (cycle repair, cap, dedup), `test_tier_promotion.py`, `test_statistics.py`, `test_cache_overlay.py` (incl. per-chapter sub-entries), `test_builder_resume.py`, `test_prompt_render.py`, CLI smoke.

**Acceptance:** one real humanities source builds end to end; every section has a cell; no cycles; tier spread holds or is flagged; a prerequisite-cycle fixture is repaired with a warning; a disagreement fixture is flagged and uses TOC; promoted cells listed; overlay survives `--rebuild`; per-chapter cost visible in `thesisound observability <project>`; `focused_question` fixtures untouched.

---

## P2 — Evidence completeness (prompt audit C2–C4, C6–C9)

**Owner decision:** extraction 2.0 replaces 1.4.0 for **all** intents; no read-path migration for pre-2.0 artifacts (no real projects exist; existing workspaces are fixtures and are regenerated). Golden fixtures are re-baselined once with a reviewed diff.

**Step 1 — models:** `EvidenceClaimDraft` += `must_not_be_lost: bool = False`, `term: str|None`, `contrast: tuple[str,str]|None`, `responds_to_excerpt: str|None`; `EvidenceExtractionDraft` −= the five aux lists, += `more_claims_available: bool = False`; `ClaimType` += `definition, distinction, example, objection, response`; `EvidenceItem`/`ClaimRecord` += `must_not_be_lost, term, contrast`; `EvidenceExtractionPlan` += `excerpt_char_coverage: dict[block_id, float]`. Remove the aux-list code paths (`claim_reconciler._dedupe_*`, planner aux inputs, `MustNotBeLostReview` builder → replaced by claim-level accounting; the P0.5 page switches to claims with `must_not_be_lost`). `evidence_artifact_migration.py` gains no 2.0 branch; loading a pre-2.0 artifact raises a clear "regenerate" error.

**Step 2 — extractor:** prompts `evidence_extraction/2.0.0`, `evidence_extraction_batch/2.0.0` (App A.2); validator keeps excerpt/duplicate/editorial rules; new `_validate_claim_type_fields` (`definition` requires `term`; `distinction` requires `contrast`); `more_claims_available` → `_second_pass_for_block` when `lesson_intent == source_coverage` and the block belongs to a tier ≤ 2 in-scope cell; `excerpt_char_coverage` via `locate_excerpt` spans; cap 12 for `source_coverage`.
**Cell-unit batches (B2):** for `source_coverage`, the extraction unit is a cell: all its blocks go in one `evidence_extraction_batch` call (attribution by `block_index` as today); fall back to per-block calls when the cell's blocks exceed the batch token budget; `plan_evidence_extraction` groups selected blocks by cell.

**Step 3 — reconciler:** type-aware merge guard (deterministic pre-filter: never propose or accept merges across `claim_type`); `claim_reconciliation/1.1.0`, `claim_reconciliation_merge/1.1.0` (App A.3); merge returns `canonical_claim_id`; ledger carries `must_not_be_lost`.

**Step 4 — planner 1.3.0** (App A.4): inputs per C4 incl. `SEGMENT_SKELETON_JSON` (always `[]` until P3); validator adds must-not-be-lost integrity and skeleton identity; `known_concepts` handling; `part_index` on segments (1 until P3).

**Step 5 — verifier/reviser:** `script_verifier/1.2.0` (App A.5) if not already shipped in P0.5 — it is; this step adds `PLAN_MUST_INCLUDE_JSON` plumbing from the plan.

**Step 6 — glossary:** deterministic seed from cells when a concept map exists; `needs_model` per C6; `glossary/1.1.0` (App A.6).

**Step 7 — `document_map/1.1.0`** (App A.7) + `key_concepts` validator; **`web_source_capture`** raw fetch + `capture_divergence` (C9).

**Step 8 — docs:** `prompts/README.md` lists the new versions; `docs/02-pipeline/03`, `05`, `06` revision notes updated to "implemented".

**Tests:** extraction 2.0 validator (type fields, second pass, coverage metric, cell-unit batching and fallback); reconciler type guard; planner must-not-be-lost integrity; glossary seed; prompt-render tests; **golden re-baseline** with `tests/golden/CHANGELOG.md` explaining every changed line.

**Acceptance:** on the P1 source, `must_not_be_lost` claims appear in the plan or in `deliberately_omitted_claims` with a reason — never silently absent; a Persian-source fixture yields a non-empty glossary; a dense-block fixture triggers the second pass and gains claims; cell-unit extraction on a 3-block cell makes one call.

---

## P3 — `source_coverage` end to end

**Deliverables:** `Project` fields (B1.1) + validation; derived brief; scope + compression + **prerequisite closure**; extraction seeding; claim ↔ cell linkage; per-cell coverage; `services/part_packer.py`; `services/segment_skeleton.py`; `EpisodePlan.parts`; per-part loops in planning, script and audio services; the five intent-conditional points; `services/cost_estimate.py` on the creation form; `services/lesson_report.py`; UI options and parts list.

**Step 1 — derived brief** `build_source_coverage_brief(project, map, in_scope_cells) -> ResearchBrief`: `normalized_topic` = source title (+ chapter titles when scoped); `topic_type = work`; `central_question` = "What does <source> argue and distinguish in <scope>?" in Persian; `learning_objectives` = up to 5 grouped labels (by chapter, then kind); `cell_keys` = all in-scope keys; `target_duration_minutes` = round(Σ cell minutes) clamped to the schema (informational); `modes = [explanatory, critical]`. No model call.

**Step 2 — in-scope selection** `select_cells(map ⊕ overlay, scope, compression) -> (in_scope, omitted_by_compression)`: tier filter, then **prerequisite closure** (BFS over `prerequisite` edges backwards, cap 25 hops, cycle-safe); closure cells carry `in_scope_reason`.

**Step 3 — cost estimate** `cost_estimate.estimate(project, map, in_scope)` (B1.8) shown on the creation form after scope/compression are chosen and stored in the report.

**Step 4 — extraction seeding:** `plan_evidence_extraction(...)` gains `seed_cells` (blocks grouped by cell for cell-unit batches) and `force_depth="extended"`; selected = seeds, deferred = the rest.

**Step 5 — linkage** `link_claims_to_cells(claims, evidence_items, cells) -> dict[claim_id, list[cell_key]]` (evidence `block_id` → cells; primary = earliest in book order). Coverage levels: `extracted` / `planned` / `spoken`.

**Step 6 — packer** `pack_parts(cells, edges, target_minutes, minutes_by_cell) -> list[LessonPart]`:

```text
constants (part_packer.py, one place, KMS tuning note copied):
  SAME_PART_PULL = {related:1.0, contrasts:1.0, objects_to:1.0, responds_to:1.0, instance_of:0.8, prerequisite:0.35, depends_on:0.35}
  NEXT_PART_PUSH = {extends:-0.5}
  SIBLING_PULL = 0.7   ADJACENCY_PULL = 0.5, ADJACENCY_WINDOW = 3
  FILL_MIN = 0.8, FILL_MAX = 1.0, BOUNDARY_BONUS = 0.3 (chapter change), 0.15 (section change)
algorithm:
  order = book order of in-scope cells; placed = ∅; parts = []
  while unplaced:
    part = []; minutes = 0
    loop:
      ready = [c ∉ placed | all ordering-prereqs of c ∈ placed or ∉ in_scope]
      fitting = [c ∈ ready | minutes + m(c) ≤ FILL_MAX·T]
      if not fitting:
        if part empty: place min-minutes ready cell, flag "oversize_cell"; break
        else break
      if minutes ≥ FILL_MIN·T and boundary(part, best(fitting)): break
      c = argmax_{fitting} [Σ_{p∈part} affinity(p,c) + adjacency(part,c) + sibling(part,c)]  tie → book order
      part.append(c); minutes += m(c)
    parts.append(part)
  graph_backed(part) = any edge between two cells of the part, or any cell placed before a book-earlier unplaced cell because of readiness
```
Last part may be < `FILL_MIN·T` (flag `short_last_part`); a non-last part < `FILL_MIN·T` is a bug → test.

**Step 7 — segment skeleton** `segment_skeleton.build(part, cells, claims)` (B1.6): one segment per cell in packer order; `claim_ids` = linked claims in block order; `speaker_dynamic` by kind; recap editorial segment appended for parts with ≥ 3 segments; `prerequisite_claim_ids` from earlier prerequisite cells in the part.

**Step 8 — planning per part:** `EpisodePlanningRunService` loops parts: priorities (`must_include` = claims linked to the part's cells; others `deferred`), planner 1.3.0 with `PART_JSON` + `SEGMENT_SKELETON_JSON`; validator rejects deviations from the skeleton; window: upper `T × 1.25` → re-pack that part into two (re-run packer on its cells with `T/2` budget) and re-plan; segments get `part_index`. Coverage audit runs once for the whole scope, advisory.

**Step 9 — script/audio per part:** `ScriptBuildRun` and `AudioBuildRun` iterate parts; artifacts under `script/parts/<n>/` and `audio/parts/<n>/`; existing chunking/TTS/ASR/QA/assembly per part.

**Step 10 — the five conditional points** (each a small `if project.lesson_intent == "source_coverage"` at `analysis_profile.build_analysis_profile`, `claim_prioritizer.prioritize`, `coverage_auditor.can_plan_episode`, `episode_planner._validate_draft` window, `episode_planning_run` gate) — never restructure surrounding code.

**Step 11 — report** `LessonReport` (`episode/report.json` + page): parts (minutes vs target, `graph_backed`, flags); cells by coverage level incl. `in_scope_reason`; omitted by compression; in scope but not covered (reason: no claim / planned but excised / thin extraction); `must_not_be_lost` outcomes; estimated vs actual cost per stage.

**Step 12 — UI:** creation form fields (B1.1) with Persian labels and the cost estimate; parts list on script/audio pages; report page.

**Tests:** packer (fill rule, boundary preference, last-part exception, readiness, oversize, `graph_backed`, determinism); closure (cycle-safe, cap, reason labels); skeleton (dynamics by kind, recap rule, prerequisite claims); derived brief; selection; seeding and cell grouping; linkage; five conditional points (intent-off/on pairs); planning loop with re-pack; cost estimate; report; two-part integration fixture through script verification.

**Acceptance:** the P1 source at `standard`/20 min yields N parts each within `[16, 20]` minutes except the last; every part passes verification; the planner never changes the skeleton (fixture asserts); `concise` pulls in prerequisites and lists them with reasons; report lists omitted and not-covered cells and estimated vs actual cost; `focused_question` unchanged except the P2 re-baseline.

---

## P4 — Text delivery

`ProseLessonDraft` (+ validator); prompt `persian_lesson_prose/1.0.0` (App A.11); `script_checks` speaker rules skipped when `delivery == text`; verifier/reviser unchanged (turn ↔ paragraph); `pipeline.py` transition `SCRIPT_VERIFIED → COMPLETE` when `delivery == text`; page `/projects/{id}/lesson/{part}` + Markdown export with evidence footnotes; `both` runs prose then dialogue.
Tests: draft validator; prompt render; transition; export; a `text` project completes without audio artifacts.

---

## P5 — Owner UI consolidation

Concept-map page gains a 2D graph view (vendored Cytoscape + dagre, no CDN) with coverage overlay after completion (covered / omitted / not covered / prerequisite-closure / known); project overview shows intent, scope, compression, target, parts, estimated vs actual cost; one UI mode; operator surfaces behind "technical details". Acceptance: the owner can go from upload to report without leaving the project pages.

---

## P6 — Evaluation on one real source, then cleanup

Run one full source at two compressions; record per-pass and per-part cost from `_observability/ledger.sqlite3` and compare with the pre-run estimate (recalibrate multipliers); parts' minutes vs target; `graph_backed` share (report only — edges stay on regardless); not-covered, thin-extraction, promoted-tier and closure counts; verifier outcomes; chapter-detection agreement rate; human review of two parts against the source for completeness and precision. Then: remove dead `subquestions` usage; collapse the five duration bounds; update `README.md`, `STATUS.md`, SOP; simplify Simple/Operator duplication where evidence shows it unused.

Hard release gates: nothing but current evidence supports a claim; changing compression/target/scope after planning marks downstream stale; multi-part output is never less verifiable than a single episode; the planner cannot alter a skeleton.

---

## C-O. Implementation order

```text
P0 (done) → P0.5 grounding hotfix → P1 concept map → P2 evidence completeness → P3 source_coverage → P4 text → P5 UI → P6 evaluation
```

P0.5 first because it is a day of work, independent, and closes the largest hallucination path. P2 before P3 because packing and coverage accounting are only as good as the inventory they count. Cost checks after P1 and after P3 (estimate vs ledger).

---

## C-P. Agent execution protocol

Before each phase: read `PRODUCT.md`, `STATUS.md`, 10a/10b/10c, the affected pipeline docs, current models and prompts; inspect call sites before changing schemas; write acceptance criteria into working notes. During: one phase at a time; additive; new prompt = new version directory; deterministic gates first; log what is capped or dropped. Before completing: fixtures pass; `focused_question` behaviour unchanged except the documented P0.5 (script stage) and P2 (extraction) re-baselines; docs index and `STATUS.md` updated. Stop if any change lets cells, packer, skeleton, `known_concepts`, prose stage or continuity supply a claim without evidence, or hard-codes course vocabulary.

---

## C-F. File-level guidance

Docs: `PRODUCT.md`, `STATUS.md`, `docs/README.md`, `prompts/README.md`, revision notes in `docs/02-pipeline/03…06`.

New runtime: `src/thesisound/concepts.py`, `services/concept_map_builder.py`, `services/concept_map_cache.py`, `services/concept_map_overlay.py`, `services/part_packer.py`, `services/segment_skeleton.py`, `services/cost_estimate.py`, `services/lesson_report.py`, `web/concept_routes.py`, templates `web/templates/concepts/`.

Touched (additive): `domain.py`, `source_analysis.py`, `episode.py`, `script.py`, `pipeline.py`, `services/document_mapper.py`, `services/evidence_extractor.py`, `services/claim_reconciler.py`, `services/evidence_pack_builder.py`, `services/deterministic_glossary.py`, `services/analysis_profile.py`, `services/claim_prioritizer.py`, `services/coverage_auditor.py`, `services/episode_planner.py`, `services/episode_planning_run.py`, `services/episode_preparation_service.py`, `services/script_checks.py`, `services/persian_script_writer.py`, `services/script_verifier.py`, script/audio build services, `web/app.py` (creation form), episode template (must-not-be-lost review).

Prompts (new versions): `persian_script_segment/1.3.0`, `script_verifier/1.2.0`, `script_reviser/1.1.0` (P0.5); `concept_cells/1.0.0`, `concept_cells_consolidate/1.0.0`, `concept_edges/1.0.0` (P1); `evidence_extraction/2.0.0`, `evidence_extraction_batch/2.0.0`, `claim_reconciliation/1.1.0`, `claim_reconciliation_merge/1.1.0`, `episode_plan/1.3.0`, `glossary/1.1.0`, `document_map/1.1.0` (P2); `persian_lesson_prose/1.0.0` (P4). Do not fork the writer prompt per intent.

Tests: `tests/concepts/`, `tests/prompts/test_grounding_sentences.py`, intent-off/on fixture pairs, `tests/golden/CHANGELOG.md`.

---

## C-R. Risks — status after the 2026-08-19 decisions

All of these are **residual** risks of the implemented system (none is "solved" in advance); each has a built-in mitigation and a measurement point.

| # | Risk | Mitigation in the plan | Residual / decision | Status |
| --- | --- | --- | --- | --- |
| R1 | Cost — each chapter is read by the map, the cell pass and extraction; `full` extracts nearly all blocks; 2.0 yields more claims | Content-addressed caches (source and per-chapter); lazy extraction on in-scope cells; cell-unit batches (fewer calls); pre-run cost estimate shown before spending; ledger read after P1 and P3 | The map stays despite the extra read (**owner: quality over cost**; estimated 5–10 % of a source's cost at fast tier, against a real loss in claim typing and tiering if dropped) | Decided — keep; measure in P6 |
| R2 | Planner at scale | **Deterministic segment skeleton** — the model fills narrative only; per-part planning; re-pack on window overflow | A single cell with very many claims still yields a long segment; the writer's per-segment word target bounds it | Mitigated; measure in P6 |
| R3 | Chapter detection without confirmation | **Two detectors + disagreement flag**, TOC preferred on disagreement; `detected_from`/`detection_agreement` on the map page | Both detectors can agree on a wrong split on exotic layouts; no owner gate by decision | Mitigated; agreement rate measured in P6 |
| R4 | Tier tagging quality | Distribution constraint; **deterministic tier promotion** (required sections, prerequisite out-degree); **prerequisite closure** in compression | Subtle mis-tiering of leaf cells; only human review catches it | Mitigated; P6 review |
| R5 | LLM graph sparsity | Book order is the prior; packer never depends on the graph; `graph_backed` reported | Edges (incl. cross-chapter) are **always built** by owner decision; sparsity only affects how much the graph helps, never correctness | Accepted |
| R6 | Extraction 2.0 changes `focused_question` outputs | Golden fixtures re-baselined once with a reviewed diff | **Owner decision: switch all intents in P2; no migration of old artifacts** (no real projects exist) | Decided |
| R7 | Skeleton rigidity — a cell with a poor claim set makes a poor segment | Planner may still omit claims with reasons; owner can edit cells/tiers in the overlay and re-run | A bad cell boundary is visible in the report as a weak segment, not hidden | New in 3.2; P6 review |

---

## C-D. Definition of done

```text
1. Owner creates a project on one source with intent source_coverage, scope, compression, episode length, delivery — and sees the cost estimate first.
2. The system builds a reviewable, owner-editable concept map (chapters with detection flags → tiered cells with promotions → edges) with statistics.
3. Evidence is extracted over the in-scope cells (tier filter + prerequisite closure) as one audited inventory; must_not_be_lost is honoured or explicitly omitted.
4. Lessons come out as parts ≤ the target and near-full (last part excepted), with a deterministic segment skeleton the planner cannot alter, each verified; the writer and verifier prompts carry the grounding rules.
5. Delivery is audio, grounded prose, or both, per part.
6. The completion report lists cells covered (extracted / planned / spoken), omitted by compression, in scope but not covered, closure cells, and estimated vs actual cost.
7. A focused question about a source still runs as today (re-baselined once in P0.5/P2).
8. One real humanities source has been completed end to end and its cost recorded from the ledger.
```

> **The owner can learn a chosen source completely — at the compression they choose, in episodes of the length they choose, in audio or text — without reading all of it, with every statement traceable to the source and nothing important silently lost.**
