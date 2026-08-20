# 13 — Chapter Scope Before Extraction

Date: 2026-08-20 · Status: proposed · Effort: M · Source: owner question — *"is there anything today that lets me say I only want these few chapters, before the map and the script?"* The answer found in the code is: the filter exists, the control does not, and the filter runs one stage too late.

Let the owner choose which chapters of a source a lesson is built from, record that choice on the project, and apply it **before** the document map and the concept-cell pass rather than after them.

## 1. Measured problem

### 1.1 The filter exists and nothing can reach it

Every piece of chapter scoping is already written and tested:

| Piece | Where | State |
|---|---|---|
| `ProjectScope(source_id, chapter_indexes)` | [`domain.py:127`](../../src/thesisound/domain.py:127) | shipped |
| `Project.scope` | [`domain.py:536`](../../src/thesisound/domain.py:536) | shipped |
| Chapter filter + prerequisite closure | [`cell_selection.py:34`](../../src/thesisound/services/cell_selection.py:34) | shipped |
| Chapter titles in the derived brief | [`source_coverage_brief.py:88`](../../src/thesisound/services/source_coverage_brief.py:88) | shipped |
| Scoped pre-run cost | [`cost_estimate.py:97`](../../src/thesisound/services/cost_estimate.py:97) | shipped |
| Extraction seeded from in-scope cells | [`analysis_profile.py:216`](../../src/thesisound/services/analysis_profile.py:216) | shipped |
| Chapter subset in the builder | [`concept_map_builder.py:462`](../../src/thesisound/services/concept_map_builder.py:462) | shipped |
| `thesisound concept-map --chapters 1,3` | [`concept_map_cli.py:27`](../../src/thesisound/concept_map_cli.py:27) | shipped |

And **no line in `src/` ever constructs a `ProjectScope`.** The only constructors are in `tests/concepts/`. The same holds for the intent that gives scope its meaning: `LessonIntent.SOURCE_COVERAGE` is never assigned outside tests either, so `Project.lesson_intent` is always the [`FOCUSED_QUESTION`](../../src/thesisound/domain.py:532) default. The creation form ([`projects/new.html`](../../src/thesisound/web/templates/projects/new.html)) still collects topic, must-include, exclusions, audience, prior knowledge, duration and mode — no source, no intent, no scope, no compression.

This is not a missing feature so much as a missing **write**. Everything downstream of the decision is built; the decision has nowhere to be made.

### 1.2 In the built pipeline the filter runs after the passes it should have bounded

The CLI is the only path that applies `--chapters` before spending: [`concept_map_pipeline.py:168`](../../src/thesisound/services/concept_map_pipeline.py:168) detects chapters, keeps the requested ones, and partitions only their blocks for the document map, then passes `chapter_indexes` to the builder at [`:210`](../../src/thesisound/services/concept_map_pipeline.py:210).

Until 2026-08-20 it also never ran. Any strict subset raised `AssertionError: Chapter partitions changed block order or coverage.` before the first model call, because the mapper validates its partitions against the block list it is handed and the pipeline handed it the whole document alongside subset partitions ([`document_mapper.py:396`](../../src/thesisound/services/document_mapper.py:396)). Fixed in the same change as this spec, with a regression test; the defect is recorded here because it is the reason no measurement below comes from a real scoped run, and because "the control exists" and "the control works" turned out to be different claims.

The real pipeline does neither. [`source_analysis_service.map_document`](../../src/thesisound/services/source_analysis_service.py:223) calls the mapper with **no** `partitions`, so partitioning falls back to input size over the whole document, and [`_maybe_build_concept_map`](../../src/thesisound/services/source_analysis_service.py:283) calls `builder.build(...)` with **no** `chapter_indexes`. The whole book is mapped and celled; `select_cells` then discards what is out of scope.

So the output of the product is already correct — out-of-scope chapters never reach the lesson. What is wrong is that the build reads, models and reasons over chapters nobody asked for, and that no owner can say so in the first place.

(The concept-map path is also still dark: [`concept_map_on_analysis_enabled = False`](../../src/thesisound/config.py:235), "off until P3 step 18".)

### 1.3 What the chapters of a real book actually are

`detect_chapters` run over all 13 sources in `workspaces/` that have reached the block stage (pure, no model calls). Read the evidence base honestly first: those 13 entries are only **two distinct multi-chapter documents**, each analyzed in several projects, plus two partial parses of those same two files, plus six single-chapter sources.

| Source | File | Blocks | Tokens | Chapters | Detection | Largest chapter |
|---|---|---|---|---|---|---|
| `4c598a0d` ×3 projects | *The Human Condition* (epub) | 198 | 258,737 | 15 | `toc_only` | 0.20 |
| `98c6e53d` ×2 projects | Freud commentary (epub) | 111 | 134,537 | 20 | `toc_only` | 0.12 |
| `6e88837b` | **hand-cut excerpt of the first** | 41 | 57,311 | 2 | `disagreed` | 0.51 |
| `dc239ee0` | hand-cut excerpt of the second | 21 | 28,503 | 2 | `disagreed` | 0.55 |
| 6 others | pdf / txt articles | 3–13 | 3,068–17,021 | 1 | `single` | 1.00 |

Three things this settles.

**The workaround is already in the corpus.** `6e88837b` is not a second book and not a bad parse: its 41 blocks are byte-identical, in order, to the 41 blocks of chapters 2 and 3 of `4c598a0d`. Someone cut the book down to two chapters by hand and uploaded that as a separate source. The feature this spec describes is being performed manually, outside the product, with no record on the project of what was cut or why.

**The picker must be able to hide.** Chapter scope is meaningless on six of the thirteen — a single-chapter source has nothing to pick.

**Detection quality is worth showing.** The hand-cut excerpts come back `disagreed`, where the full files come back `toc_only`: cutting a book destroys the table of contents the detector relies on. A picker that shows `detection_agreement` is the first place a reader would ever see that.

Per chapter, for the largest document:

| # | Title | Blocks | Tokens | Share |
|---|---|---|---|---|
| 0–2 | copyright, title, toc | 3 | 854 | 0.003 |
| 3–5 | intro, prologue, ch1 | 16 | 19,639 | 0.076 |
| 6–10 | ch2 … ch6 | 121 | 166,149 | 0.642 |
| 11–12 | acknowledgements, publication | 2 | 472 | 0.002 |
| **13** | **notes** | **39** | **50,523** | **0.195** |
| **14** | **index** | **17** | **21,100** | **0.082** |

**28% of the tokens in this book are notes, index and imprint matter.** The single largest "chapter" in it is the endnotes. The other multi-chapter source has the same shape at smaller scale (4.4% apparatus, plus a 17-token `part2` stub that is a chapter by detection and nothing by content).

That is what makes the ordering a cost question with a quality edge, and the shape of the waste is worth stating precisely because the obvious guess is wrong. `DocumentMapSection.function` has no back-matter value ([`domain.py:260`](../../src/thesisound/domain.py:260)), so one would expect the endnotes to be classified `other` and the cell validator — which requires a cell for every section that is not `front_matter` or `transition` ([`concept_map_builder.py:277`](../../src/thesisound/services/concept_map_builder.py:277)) — to force concepts out of an index. Reading the 13 real document maps says otherwise: **the mapper already labels notes, index, acknowledgements and the publisher's note `front_matter`**, so they are exempt and no cell is ever demanded of them. The enum is missing a name, not a behaviour.

What actually happens is worse in cost and better in correctness. Seven of the 15 chapters of the largest book resolve to nothing but `front_matter` sections — 72,949 tokens, the same 28% — and the builder has no guard for that case: it calls `extract_chapter_cells` for every chapter regardless ([`concept_map_builder.py:497`](../../src/thesisound/services/concept_map_builder.py:497)), sending the chapter's full text and retrying up to three times on a chapter that cannot produce a valid label. Commit `1dee0e5` is exactly this arriving as a crash — "a front-matter chapter with no real concept keeps getting the same rejected label from the model, the retry loop gives up early" — and its fix was to drop the rejected labels on the last attempt rather than to stop asking. So the map pass reads the apparatus, the cell pass reads it again and argues with the model about it, and the output is correctly empty.

### 1.4 What scoping early is and is not worth

Honest arithmetic for `4c598a0d`, scoped to ch2+ch3 (57,311 tokens, 22% of the book), using the shipped multipliers (`map` 1.0×, `cells` 1.1×) and the fast-tier list price of $0.30 / 1M input tokens:

| | Input tokens (map + cells) | Price |
|---|---|---|
| Whole book | 543,348 | $0.163 |
| ch2 + ch3 | 120,353 | $0.036 |

**The money saved is about 13 cents per source per build.** Cost is not the argument, and this spec does not pretend otherwise. Two other things are:

- **Wall clock.** The cell loop is sequential, one chapter at a time ([`concept_map_builder.py:497`](../../src/thesisound/services/concept_map_builder.py:497)), and cross-chapter pairs are `2n − 3` for `n` chapters ([`iter_chapter_pairs_within_window`](../../src/thesisound/services/concept_map_builder.py:1008), window 2). Fifteen chapters is 15 cell calls + up to 15 consolidations + 15 intra-edge calls + 27 pair calls — **57 to 72 model calls before extraction begins.** Two chapters is 5 to 7.
- **Arguing with the model about an index.** §1.3. Seven of 15 chapters (72,949 tokens) go through the cell pass, with retries, to produce nothing. Most of that is recoverable *without* scope, by skipping the pass for a chapter whose sections are all exempt — a separate change of the same shape as spec [`06`](06-conditional-document-map.md), not a reason to scope.

## 2. Design

### D1 — Two decisions, two places

Doc `10c` §P3 Step 3 puts scope and compression on "the creation form". That cannot work as written: at creation time there is no source, so there are no chapters to choose from. The decision splits:

| Decision | Where | Why there |
|---|---|---|
| intent, compression, episode length | creation form | no source needed; they define what kind of lesson this is |
| **chapter scope** | **sources page** | needs a parsed source in hand |

This spec owns the second and the minimum of the first needed to reach it: the creation form gains a `source_coverage` switch that sets `lesson_intent` and `compression`. The full form redesign stays with `10c` §P5.

### D2 — The picker rides the Sources stop, and adds no new stop

Spec [`12-stop-budget.md`](12-stop-budget.md) caps a build at three human stops — Sources, Plan, Audio — and says a fourth cannot be added without removing one. A chapter picker must therefore not be a screen of its own.

It does not need to be. Parsing already happens at **upload** ([`ingest_uploaded_source`](../../src/thesisound/web/source_ingestion.py:41)), and both `BlockBuilder` and `detect_chapters` are pure. Measured on the two multi-chapter sources, the whole detection path costs:

| Source | Load parsed doc | Build blocks | Detect chapters | Total |
|---|---|---|---|---|
| `4c598a0d` (1.4 MB, 198 blocks) | 12 ms | 73 ms | <1 ms | **85 ms** |
| `98c6e53d` (0.7 MB, 111 blocks) | 8 ms | 37 ms | <1 ms | **45 ms** |

So the chapter list is computed on demand when the sources page renders, from the ingestion artifact the UI manifest already points at. No new artifact, no cache, no model call, no extra click. (If the sources page ever becomes live-polled like `processing`, memoize by `UiSourceManifest.content_key` — not before.)

The picker renders only when `lesson_intent == source_coverage`, exactly one source is selected, and that source has more than one detected chapter. Otherwise the sources page is unchanged.

### D3 — What the picker shows, and what it must not show

Per chapter: index (1-based), title, block count, **token count and share of the source**, and the `detection_agreement` flag when it is not `agreed`.

It must **not** show `SourceChapter.estimated_minutes`. Before Pass 2 that field is `Σ tokens / 300` — a reading-length proxy that `10c` §P1 Step 2 explicitly replaces with cell minutes later. On the real book it reads *168 minutes* for the endnotes chapter. Presented next to a form about lesson length it is not an approximation, it is a wrong number. Minutes appear on the concept-map page, after cells exist.

Below the list: the map+cells estimate for the current selection, from the already-shipped `estimate_tokens(chapter_token_total(blocks, selected_block_ids))` ([`concept_map_pipeline.py:60`](../../src/thesisound/services/concept_map_pipeline.py:60)), priced when `config/model-pricing.toml` has a row for `model_fast` and shown as tokens only when it does not. It is labelled as covering the map and cell passes only — extraction, planning, script and verification cannot be estimated before cells exist, and their estimate stays on the concept-map page where `cost_estimate.estimate` already lives.

**All chapters start checked.** Apparatus chapters may be *annotated* ("looks like front/back matter") from a conservative title match, but nothing is ever unchecked automatically. Silently dropping content is a correctness risk; an unchecked box the owner can see is not. The token-share column is what makes a 20%-of-the-book endnotes chapter obvious without guessing on behalf of the owner.

### D4 — `project.scope` is the single record of the decision

Confirming the sources page writes `Project.scope = ProjectScope(source_id, chapter_indexes)` (0-based, in book order, `None` when every chapter is selected) before the corpus run is queued. `chapter_indexes=None` and "all chapters listed" are deliberately the same state, so a source that later re-parses into a different chapter count does not silently narrow.

Validation: `lesson_intent == source_coverage` requires exactly one selected source, and `scope.source_id` must be that source. A multi-source `source_coverage` project is rejected at confirm time with that message, not silently scoped to the first source.

### D5 — Scope reaches the two calls that should have been bounded

Both edits are in `source_analysis_service`, and both mirror what the CLI pipeline already does:

1. `map_document` builds `partitions` from the in-scope chapters — the same six lines as [`concept_map_pipeline.py:183`](../../src/thesisound/services/concept_map_pipeline.py:183) — and passes them to `DocumentMapperService.map_document`. Extract that block into one function used by both callers; two copies of a partitioning rule is how the CLI and the web drift apart.
2. `_maybe_build_concept_map` passes `chapter_indexes=project.scope.chapter_indexes`.

Reading the shared document-map cache stays enabled: a cached **whole-document** map is a superset of a scoped one, and `_sections_for_chapter` selects from it for free. Only writing is restricted — see D6.

### D6 — A scoped map must never enter the shared cache

`DocumentMapCache` is keyed by `content_key = parsed_document_key(parsed)`, the identity of the whole parsed body. A map covering three of fifteen chapters written under that key would be served to every later project on the same book as if it were complete.

Use the mechanism already there for exactly this: [`is_shareable_document_map`](../../src/thesisound/services/document_map_cache.py:35) refuses maps carrying certain warning prefixes. Same shape as the rule in spec [`06`](06-conditional-document-map.md) §4.2 that a synthetic map is never cached.

**Shipped 2026-08-20** with the `--chapters` fix, ahead of the rest of this spec, because the CLI path could otherwise have written a subset map the moment it started working: `SCOPED_CHAPTERS_PREFIX` exists, `_warnings_are_shareable` rejects it, and the CLI pipeline stamps every scoped map with the chapter numbers it covers. D5 only has to keep stamping it.

### D7 — Per-chapter caching makes widening scope cheap; the resume checkpoint should not be lost

`_build_or_load_chapter` saves a cache entry per chapter keyed by `chapter_hash(chapter, blocks)` **whether or not the build is a subset** ([`concept_map_builder.py:656`](../../src/thesisound/services/concept_map_builder.py:656)). Widening scope from ch2+ch3 to ch2–ch5 therefore pays only for ch4 and ch5. This already works and is the reason scoping early does not become a trap.

One thing does regress today: `subset = chapter_indexes is not None` disables both the source-level cache **and** the partial checkpoint ([`:466`](../../src/thesisound/services/concept_map_builder.py:466), [`:486`](../../src/thesisound/services/concept_map_builder.py:486)). Disabling the source-level cache is correct — a partial map must never masquerade as the full one. Disabling resume is not: it was incidental to a CLI flag and becomes a real loss once scope is the normal path. Record the scope signature in `ConceptMapPartial` and match on it, so a scoped build resumes into the same scope and only into that scope.

### D8 — Closure cannot reach a chapter that was never built

This is the one thing the reordering genuinely costs, and it must be stated rather than discovered.

`select_cells` walks `prerequisite` edges backwards and may pull cells **from outside the chapter scope** ([`cell_selection.py:43`](../../src/thesisound/services/cell_selection.py:43)). That works today because every chapter has cells. Once out-of-scope chapters are never celled, their cells do not exist and no edge points at them: closure degrades from *"any prerequisite in the book"* to *"any prerequisite in the built scope"*.

Decision: **accept it, and make it visible.** Building a chapter lazily when closure asks for it would spend money after the owner approved an estimate, which is worse than a stated limit. Two obligations follow:

- When the selection skips a chapter that precedes a selected one, the picker warns before confirm: *"chapter 7 is selected without 1–6; prerequisites in the skipped chapters cannot be detected."*
- The lesson report names the chapters that were not analyzed, so "no prerequisite found" is never read as "no prerequisite exists".

Cross-chapter edges over a non-contiguous selection are kept as they are: with ch1 and ch3 selected they become adjacent for `iter_chapter_pairs_within_window`, and an edge between them is exactly what the packer and closure need for a lesson that jumps.

### D9 — Changing scope after a build

Nothing new is required for extraction. [`reusable_claim_ledger`](../../src/thesisound/services/corpus_reuse.py:25) replans with `resolve_extraction_seeds` over the effective map; a scope change changes the in-scope cells, which changes `selected_block_ids`, which misses as `selected_blocks_mismatch` and rebuilds. That is already the behaviour the seed fix restored.

What is required: narrowing or widening scope after a plan exists marks planning and everything after it stale — the `10c` release gate ("changing compression/target/scope after planning marks downstream stale"). Scope changes go through the existing `sources` rewind target ([`workflow_revision.py:16`](../../src/thesisound/services/workflow_revision.py:16)); scope is not editable while a run is active.

### D10 — CLI parity

`thesisound concept-map --chapters` keeps its behaviour and additionally writes `Project.scope`, so a CLI-built map and the web agree on what the project covers instead of the CLI leaving scope implicit in whichever chapters happen to be in the map.

## 3. Non-goals

- **Sub-chapter scope** (sections, page ranges, "the first half of chapter 4"). `ProjectScope` is chapter-granular by design; finer selection belongs to compression and tiering, which already exist.
- **Multi-source scope.** `ProjectScope` holds one `source_id` because `source_coverage` is a one-source lesson (`10b` §B1.1). Multi-source projects keep `scope = None`.
- **Scoping `focused_question`.** Its extraction is duration-ranked over the whole source and does not consult `select_cells` at all ([`analysis_profile.py:214`](../../src/thesisound/services/analysis_profile.py:214)). Adding chapter scope there changes the extraction contract of the shipped product for a benefit nobody has asked for.
- **Automatic exclusion of front/back matter.** D3. Annotate, never uncheck.
- **Scoping the parse.** Chapter detection reads the headings and TOC of the whole document; parsing a subset would break the detector that names the chapters.
- **Lazy chapter building on closure demand.** D8.

## 4. Acceptance criteria

1. A `source_coverage` project on `4c598a0d` with chapters 6 and 7 selected reads 57,311 in-scope tokens, not 258,737, and its map+cells estimate reads 120,353 input tokens on the sources page before confirm.
2. The same build issues at most 7 cell-pass model calls; unscoped it issues at least 57.
3. The document map produced by a scoped build is never written to `DocumentMapCache`, and a later unscoped project on the same file gets a cache miss, not a partial map.
4. A scoped build interrupted after its second chapter resumes into the same scope and rebuilds no completed chapter.
5. Widening a scope from two chapters to four issues cell-pass calls for the two new chapters only.
6. A selection that skips a preceding chapter shows the closure warning before confirm, and the resulting report names the unanalyzed chapters.
7. Confirming with `lesson_intent == source_coverage` and two selected sources is rejected with the one-source message.
8. Selecting every chapter stores `chapter_indexes = None` and produces byte-identical model calls to a project with no scope at all.
9. Changing scope after a plan exists marks the plan and everything after it stale.
10. A single-chapter source (six of the thirteen block-stage sources in `workspaces/`) renders no picker and behaves exactly as today.
11. `focused_question` projects are unaffected: same profile, same `selected_block_ids`, same ledger reuse.
12. The picker never displays `estimated_minutes`.

## 5. Test plan

| Test | Asserts |
|---|---|
| `test_sources_page_lists_detected_chapters` | picker renders from ingestion artifacts, no model call |
| `test_sources_page_hides_picker_for_single_chapter_source` | §4.10 |
| `test_confirm_writes_project_scope` | D4 — the missing write |
| `test_confirm_all_chapters_stores_none` | §4.8 |
| `test_source_coverage_rejects_multiple_sources` | §4.7 |
| `test_scoped_map_document_partitions_by_chapter` | D5.1 |
| `test_scoped_build_passes_chapter_indexes` | D5.2 |
| `test_scoped_map_is_not_shareable` | §4.3 — the poisoning guard |
| `test_scoped_build_resumes_within_scope` | §4.4 |
| `test_widening_scope_reuses_chapter_cache` | §4.5 |
| `test_gap_selection_warns_about_closure` | §4.6 |
| `test_scope_change_marks_plan_stale` | §4.9 |
| `test_focused_question_plan_unchanged_by_scope_code` | §4.11 — the regression guard |
| `test_picker_estimate_matches_estimate_tokens` | §4.1, D3 |
| `test_cli_chapters_writes_project_scope` | D10 |

§4.3 and §4.11 are the load-bearing ones. The first is the only way this change can corrupt work outside its own project; the second is the only way it can touch the shipped product.

## 6. Sequencing

1. D4 + D2 read-only: detect and render the chapter list on the sources page, write nothing. Ships behind the existing `source_coverage` gate and is safe on its own.
2. D3 estimate, D1 creation-form switch — the picker becomes reachable.
3. D5 — scope reaches the model calls in the service path. (D6, the cache guard, and the `--chapters` crash fix landed on 2026-08-20, before this step, so the guard can never trail the first scoped map.)
4. D7 resume, D8 warning and report line, D10 CLI parity.
5. Turn `concept_map_on_analysis_enabled` on (`10c` §P3 Step 18) with the whole path in place.

## 7. Related

- [`12-stop-budget.md`](12-stop-budget.md) — the three-stop rule D2 is written to respect.
- [`06-conditional-document-map.md`](06-conditional-document-map.md) — the "never cache an incomplete map" precedent D6 reuses.
- [`01-foundations/10b-personal-learning-companion-design.md`](../01-foundations/10b-personal-learning-companion-design.md) — §B1.1 `Project` fields, §B1.2 chapters, §B1.8 cost estimate.
- [`01-foundations/10c-personal-learning-companion-implementation.md`](../01-foundations/10c-personal-learning-companion-implementation.md) — P1 chapter detection, P3 scope/compression/closure, P5 UI. D1 corrects its "creation form" premise.
- [`03-web-ui/06-web-corpus-building.md`](../03-web-ui/06-web-corpus-building.md) — the corpus run and the reuse conditions D9 relies on.
