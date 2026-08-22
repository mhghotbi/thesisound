# Thesisound — Current Implementation Status

Last updated: 2026-08-19 (P0.5 grounding hotfix is in the implemented path)

The operating procedure is [`docs/06-operations/03-production-sop.md`](docs/06-operations/03-production-sop.md). The `thesisound readiness` command and matching web view re-run stored-input gate logic without model calls. The frozen machine-checkable evaluation is under [`benchmarks/eval/`](benchmarks/eval/); human scoring and the blind NotebookLM comparison remain separate work.

## Implemented local end-to-end path

```text
OTP login
→ project and Research Brief
→ source upload OR Gemini Google Search
→ URL Context capture for selected web sources
→ parse-quality gate
→ confirmed corpus
→ semantic blocks
→ hierarchical document map for large sources
→ evidence and claims
→ coverage audit and supported-duration gate
→ explicitly approved Episode Plan
→ grounded Persian script
→ deterministic checks and independent verification
→ named human review when verification leaves non-blocking issues
→ direct UI transition to audio
→ runtime preflight before provider work
→ TTS-safe chunks
→ TTS synthesis
→ WAV validation
→ ASR transcription
→ expected-vs-heard QA
→ targeted regeneration
→ FFmpeg normalization and assembly
→ verified final WAV
→ COMPLETE
```

All Gemini text, Google Search, URL Context, TTS, and ASR calls now pass through the unified model-call observability contract. Queryable metadata is written to `workspaces/_observability/ledger.sqlite3`, while redacted request, response, and parsed-output artifacts are stored under `workspaces/_observability/artifacts/`.

## End-to-end readiness additions

- پروژه می‌تواند فقط با عنوان/موضوع شروع شود و در UI از Gemini Search منبع بگیرد.
- Search result و snippet candidate هستند؛ URL انتخاب‌شده قبل از evidence با URL Context capture و quality-gate می‌شود.
- اسناد بزرگ دیگر با hard cap رد نمی‌شوند؛ map در partitionهای کامل semantic انجام و سپس global reduce اجرا می‌شود.
- navigation بین مراحل روی همه صفحات پروژه نمایش داده می‌شود.
- rewind به Brief یا Sources خروجی downstream را archive و invalid می‌کند و raw inputs را نگه می‌دارد.
- پیام quality warning وضعیت، اثر و اقدام لازم را به زبان انسانی توضیح می‌دهد؛ parser/verdict در جزئیات فنی است.
- `uv run thesisound doctor` و `/system-check` پیش‌نیازهای live runtime را بررسی می‌کنند.
- هر فراخوانی مدل دارای `call_id`، stage، model، timeout، token usage، provider attempt، retry/backoff، error و مسیر artifactهای redacted است.
- API key خام ثبت نمی‌شود؛ فقط slot و fingerprint غیرقابل‌بازگشت برای بررسی rotation و ADC fallback ذخیره می‌شود.
- مشاهده‌ی پروژه و یک call با `uv run thesisound observability <project-id>` و `uv run thesisound model-call <call-id>` ممکن است.

## Milestone status

- M0 Scaffold and contracts: implemented
- M1 Document ingestion: implemented; broader Persian benchmark remains empirical work
- M2 Structured model execution: implemented; live-provider behavior remains empirical work
- M2.5 Unified model-call observability: implemented for text, Search, URL Context, TTS, and ASR
- M3 Evidence pipeline: implemented
- M4 Episode preparation: implemented
- M5 Verified Persian script: implemented
- M6 TTS, ASR, and Audio QA vertical slice: implemented in code
- M6.5 Operator UI: implemented through final audio review with revision navigation
- M7 Gemini Source Discovery vertical slice: implemented; general crawler, deduplication quality, and authority ranking remain open
- M8 Full multi-source semantic reconciliation: **retired** — replaced by the doc 10 plan below
- M9 End-user product UI: **retired** — no end-user product; the owner is the user (doc 10 §1)
- M10 production persistence, jobs, deployment, and real OTP provider: **retired as a milestone** — revisit only if real use demands it (doc 10 §13)

## Personal learning companion plan (doc 10, revision 3.2 — 2026-08-19)

Direction approved in [`docs/01-foundations/10-personal-learning-companion-development-plan.md`](docs/01-foundations/10-personal-learning-companion-development-plan.md) (entry; parts 10a direction / 10b design + prompts / 10c implementation). Status per phase:

- P0 Product contract: **done** (this file, `PRODUCT.md`, foundation and pipeline docs aligned, prompt design notes moved under `docs/02-pipeline/prompt-design-notes/`)
- P0.5 Grounding hotfix (writer 1.3.0, `ClaimRecord` in packs, `unsupported_specifics` check, must-not-be-lost review page): **done**
- P1 Concept map (two-way chapter detection → tiered concept cells with promotion → edges → gate; cache + overlay; CLI + page): **done**
- P2 Evidence completeness (extraction 2.0 unified inventory for all intents, cell-unit batches ready, `must_not_be_lost` accounting, reconciliation 1.1.0, planner 1.3.0, glossary 1.1.0; golden re-baseline, no migration): **done**
- P3 `source_coverage` end to end (derived brief, compression + prerequisite closure, cost estimate, part packer, segment skeleton, per-part planning/script/audio, completion report): **done, checkpoint C-D passed real end to end 2026-08-22** — runbook steps 18–22 are built; see the P3 scope note below on how per-part script/audio was implemented
- P4 Text delivery (grounded prose lesson): **done** — runbook step 23; see the P4 scope note below
- P5 Owner UI consolidation: **done** — runbook step 24; see the P5 scope note below
- P6 Evaluation on one real source + cleanup: not started

Cross-project course memory is deferred: [`docs/01-foundations/11-course-memory-future-phase.md`](docs/01-foundations/11-course-memory-future-phase.md).

## Known gaps from the 2026-08-19 prompt audit (doc 10 §8)

Closed in P0.5 (2026-08-19):

- F1 — the active writer is `persian_script_segment/1.3.0`; grounding rules (no outside knowledge, `editorial_only`, qualifications/disagreement, `speaker_dynamic`) are back in the system prompt. `tests/test_script_speaker_balance.py::test_latest_script_prompt_is_1_3_0_and_renders_position` is green.
- F5 — evidence packs carry reconciled `ClaimRecord`s (`support_status`, qualifications); writer, verifier `1.2.0`, and reviser `1.1.0` receive them as `CLAIMS_JSON`.
- must-not-be-lost notes appear on the episode page, with unused count in the header.

Closed in P2 (2026-08-19, steps 13–17):

- definitions, distinctions, examples, objections and responses are claims with verbatim excerpts and IDs (`evidence_extraction/2.0.0`);
- surplus claims on dense blocks set `more_claims_available`, and the dense second pass now reads it together with `EvidenceExtractionPlan.dense_second_pass_block_ids` (populated on `source_coverage` concept-map plans only, so it stays dormant for `focused_question`);
- the glossary seed (`glossary/1.1.0`) is not Latin-token-only; Persian definition claims and concept-map cells seed terms;
- flagged must-not-be-lost claims cannot vanish from the plan without a stated omission (`episode_plan/1.3.0`).

Still open (P3):

- cell-unit extraction batches and the dense-block second pass are implemented but not switched on for `focused_question`;
- `excerpt_char_coverage` is now measured and stored on `EvidenceExtractionPlan` after each extraction (2026-08-20), but nothing reads it yet: the tier-1 `thin_extraction` gate still waits for `lesson_intent == source_coverage`. Measured on Arendt ch2–ch3 at the `deep` tier, mean coverage is 0.30 and 28 of 38 blocks fall under the 0.35 threshold, so the threshold needs calibrating against depth tier before it gates anything;
- `source_coverage` part packing (step 20) and per-part planning (step 21: `segment_skeleton`, the per-part loop in `EpisodePreparationService.plan_episode`, re-pack on `target * 1.25` overflow, and the five intent-conditional points) are built. `EpisodePlanner.plan()`'s own whole-scope-budget precondition was also found to block every part call and was scoped to the non-skeleton (`focused_question`) path only — not one of the five named points, but required for the loop to run at all.
- Step 22 scope decision (2026-08-20): the runbook envisions each part as a fully independent script/audio build (its own check/verify/revise cycle, its own retry). The existing pipeline is built around one `Script` and one `ProjectState` machine per project, so full per-part independence would mean a second parallel state machine. Instead, `write_script`/`run_checks`/`verify_script`/`revise_script` still run once over the whole multi-part draft (all parts checked and verified together, which also catches cross-part repetition), and a deterministic, non-model-calling step slices the verified result into `script/parts/<n>/script.json` and `audio/parts/<n>/final.{wav,mp3}` for delivery, the parts list on the script/audio pages, and the report. A retry re-runs every part, not just a failed one. `services/lesson_report.py` (`episode/report.json` + `/projects/{id}/report`) and the creation-form fields (`lesson_intent`, `delivery`, `compression`, `episode_target_minutes`, `known_concepts`) are built; `scope.chapter_indexes` selection and a pre-run cost-estimate display still need a home on a later screen (a concept map, which `cost_estimate.estimate` requires, does not exist yet at project-creation time).

Checkpoint C-D (real run on `FA-2-Citizenship-as-Alternative-to-World-Alienation.pdf`, a real Persian Arendt article, with a real Gemini key pool and real TTS): **complete (2026-08-22)**, after a multi-day resumption documented below.

Verified for real, end to end, the whole pipeline: concept-map build (11 cells, sensible tiers/edges/labels, spot-checked against the source), cell-seeded extraction (50 real claims, coverage climbing 33%→53%→64%→75%→passing across resumed retries — the 85% evidence-retention gate and the extraction resume-on-retry behavior both work as designed), the step 21 per-part planning loop (3 real parts, 13 segments, all `graph_backed=True`, sensible titles and minute counts, `short_last_part` correctly flagged on the last part), script writing and verification (all 13 segments, 76 turns, verified), and real audio synthesis (all 3 parts, `final.wav`/`final.mp3` at project and part scope). The final report shows all 11 concept-map cells at `coverage_level: "spoken"` (zero omitted, zero not-covered) and all 3 must-not-be-lost claims used in the plan. This real run found and fixed six genuine defects, none caught by any existing test (all now covered):
- a shared concept-map cache hit under a different project/source reused block ids that pointed at another source's blocks (`ConceptMapBuilder.build` now remaps them);
- `claim_prioritizer._BASE_TYPE_SCORE` was missing the three extraction-2.0 claim types, crashing on any `definition`/`distinction`/`example` claim;
- `SegmentEvidencePack` rejected the skeleton's claimless recap segment;
- `invalidate_from_stage("writing_segments")` deleted every cached per-segment script draft on *every* retry, including already-succeeded segments — a transient failure partway through a 13-segment script forced a full re-write from segment 1 on each attempt (`script_artifact_store.py`);
- `GeminiKeyPool.call()` aborted the whole call on the first connection-level error (reset/timeout) instead of trying the pool's other keys, since only quota and auth errors advanced past the current key — one flaky key could starve out six working ones (`gemini_key_pool.py`);
- the skeleton's trailing recap segment (`claim_ids=[]` by design) could never pass the writer's F1 editorial-word-ratio floor, since a claimless segment is necessarily ~100% editorial — permanently blocking that segment regardless of retries (`persian_script_writer.py`).

Step 23 scope decisions (2026-08-20, P4 text delivery): a written paragraph is stored as the same `ScriptTurn` used for spoken dialogue (`speaker` fixed to `"A"`, a new `heading_level` field added) so the existing checks/verify/revise/remediation machinery runs over prose completely unchanged, per the design doc's "turn ↔ paragraph reinterpretation" — the only writer-facing difference is which prompt runs (`persian_lesson_prose/1.0.0` vs `persian_script_segment/1.3.0`) and that the deterministic consecutive-same-speaker check is skipped for `delivery == text`. `delivery == both` writes a second, grounded prose pass from the same evidence packs after the dialogue script is verified, but does not run its own check/verify/revise cycle for it — duplicating the whole script state machine for a bonus artifact was judged out of proportion to the value, mirroring the step 22 per-part scope call. The `/projects/{id}/lesson/{part}` page reuses the same claim/evidence drawer component already built for the script page (`evidence_views.claim_groups_for_ids`) rather than inventing new citation UI; the Markdown export renders true numbered footnotes. This has not yet been run against a real model — verification is limited to the fake-runner test suite (`tests/test_script_pipeline.py`, `tests/test_script_checks.py`, `tests/test_script_speaker_balance.py`, `tests/test_web_lesson.py`). The provider/proxy instability that blocked a real run through 2026-08-22 is resolved (see checkpoint C-D below); a real `delivery == text` run is still a separate, not-yet-scheduled task.

Step 24 scope decisions (2026-08-20, P5 UI consolidation): the concept-map page (`concepts/concept_map.html`) gained a 2D graph view — Cytoscape.js 3.34.1 + dagre 0.8.5 + the cytoscape-dagre 2.5.0 adapter, downloaded once from unpkg and vendored under `src/thesisound/web/static/vendor/` (no CDN reference at runtime) — colored by coverage state (covered / omitted by compression / not covered, from `LessonReportBuilder`, dashed border for prerequisite-closure cells) when a completion report exists, or by tier otherwise; clicking a node scrolls to and highlights its row in the existing cell table. Verified live against a seeded project in an isolated scratch workspace (not the real `workspaces/`): all three vendored libraries loaded and initialized correctly, node/edge counts matched the seed data, and the tier legend rendered as expected. The project overview page (`/projects/{id}`) gained an always-visible "دربارهٔ این گفتار" section for `source_coverage` projects — intent, compression, target minutes per part, chapter scope, part count, and a cost summary line (when `LessonReportBuilder` has cost data) — linking to the existing `/report` page rather than duplicating its full cost table, per the "owner can go from upload to report without leaving the project pages" acceptance line.

"One UI mode" was intentionally scoped down after mapping its real size: the Simple/Operator toggle touches 68 `simple-only`/`operator-only` class occurrences across 20 templates, most of which fully hide content (not just relabel it) via `html[data-mode="operator"]` CSS rules, and about a dozen are genuine wording-alternative pairs (e.g. "پرسش اصلی" vs "پرسش مرکزی") rather than simple show/hide. Collapsing this correctly — without either silently deleting operator-only content or rendering duplicate/conflicting prose sitewide — requires a per-template review, not a mechanical toggle removal; doc 10c's own P6 line ("simplify Simple/Operator duplication where evidence shows it unused") assigns exactly this work to P6, not P5. Step 24 therefore did not touch the toggle mechanism (`base.html`, `app.js`, `/ui/preferences`, the `app.css` mode rules) or the existing 20 templates; both new step-24 surfaces (the graph legend, the overview section) were built as a single, non-toggled view from the start, satisfying the acceptance line for new content without touching old content under time pressure. This is a real gap against the runbook's literal "یک حالت UI" wording, left for a dedicated P6 pass.

Checkpoint C-E (2026-08-20): the runbook asks the owner to walk the full path in a browser; done here as a solo agent pass instead (owner asleep, standing approval to use best judgment on checkpoints) — a real dev server against an isolated scratch workspace (not `workspaces/`), logged in via test OTP, verifying the concept-map graph and project overview pages built in step 24 (see the step 24 note above for what was checked). Friction and vocabulary gaps found, for the owner's later review rather than blocking on:
- the "one UI mode" gap itself (68 occurrences, 20 templates, deferred to P6 as above) is the largest one;
- `docs/05-ui-redesign/02-ui-redesign-spec.md`'s own P0/P1/P2 redesign (unified `StepRail`, `AttentionPanel`, `ErrorRecoveryPanel`, etc.) is a separate, much larger initiative that overlaps in spirit with P5 but was never in the runbook's literal step 24/25 scope; it remains entirely unimplemented and un-scheduled — worth a deliberate decision on whether/when to pick it up, since right now two UI-vocabulary documents exist (`03-product-language.md`, applied; `02-ui-redesign-spec.md`, not applied) without a tracked relationship between them.

Step 25 (P6 evaluation + cleanup), revised (2026-08-20): re-read doc 10c's own P6 line and only the *last* cleanup item ("simplify Simple/Operator duplication where evidence shows it unused") is actually evidence-gated by its wording — "remove dead `subquestions` usage", "collapse the five duration bounds", and the doc-update items are not, so those were done without waiting for the blocked real run:
- **Duration bounds, done and committed.** Five independent `target_duration_minutes: Field(ge=5, le=120)` declarations (`ResearchBrief`, `ClaimPriorityReport`, `EpisodeBudgetReport`, `AnalysisProfile`, `EpisodePlanningRun`) plus two literal `5`/`120` call sites now share `domain.BRIEF_DURATION_MINUTES_MIN`/`MAX`. Behavior-preserving (identical bounds), confirmed by the full suite. The separate `max_supported_minutes`-family bounds (`ge=0, le=120`, a different concept — corpus-supported duration, not requested duration) were deliberately left alone.
- **`subquestions`, investigated and NOT removed.** `domain.CoverageItem`/`CoverageReport` (an orphaned early coverage-audit design, confirmed dead by repo-wide grep, superseded by `episode.CoverageReport`) were removed. `ResearchBrief.subquestions`, despite never being validated, edited by the owner, or shown in the UI, turned out to have one real, narrow consumer: `analysis_profile._block_score()` folds it into a capped (≤30-point) term-overlap score used to rank which document-map sections get included for evidence extraction on the `focused_question` path, and three `benchmarks/eval/cases/*/case.toml` fixtures set it. Removing it would be a real behavior change requiring a deliberate decision (drop the scoring signal, or keep the field and its narrow effect), not a mechanical no-op — left alone rather than guessed at.
- **Real evaluation run: unblocked as of 2026-08-22** — checkpoint C-D's own real project reached COMPLETE (see above). Step 25's own two-compression run is still to be scheduled, but the provider/infrastructure blocker that stopped it is resolved.
- **Simple/Operator simplification: still correctly not attempted** — it is the one item the doc's own wording actually gates on evidence from a real run, and P6's evaluation run itself is still pending.

**Local environment fixes, found across several days resuming checkpoint C-D (2026-08-20 through 2026-08-22):**
- The real root cause behind the recurring "proxy" failures was not `.env` drift alone — `src/thesisound/http_proxy.py`'s `DEFAULT_HTTP_PROXY = "http://127.0.0.1:10809"` is a hardcoded Python-level fallback used whenever `THESISOUND_HTTP_PROXY` is absent, so commenting the `.env` line out still fell through to the same dead port. The Gemini API-key path also deliberately refuses to run unproxied by default (`ModelConfigurationError` on no proxy) — proxying is required by design, not optional, though it's now configurable (`THESISOUND_GEMINI_PROXY_REQUIRED`, see `config.py`/`http_proxy.py`) for the rare case where the proxy itself is down and direct access is confirmed to work. The local Xray proxy's port drifts across restarts of that process (was 10808 both times checked); find it live with `netstat -ano | grep "127.0.0.1:108"` rather than assuming a fixed value.
- One resumed attempt (before a driver-script gating bug was fixed — see `okian-proxy-tunnel-outage-2026-08-20` in agent memory for the full blow-by-blow) re-ran `analyze_source` on an already-claims-ready source and left its `manifest.json` reporting `status: "failed"` with zeroed counts, even though the underlying `claim-ledger.json`/`evidence-items.jsonl`/`document-blocks.jsonl` were completely intact on disk. Recovered by restoring the manifest's `status`/counts from the real files via `SourceArtifactStore.save_manifest`, not by re-running extraction.

Full narrative, including three more days of intermittent Gemini quota exhaustion and Okian backend instability that were genuinely external and self-resolved (not fixed by any code change), is in agent memory (`okian-proxy-tunnel-outage-2026-08-20`, `local-live-run-blockers`).

## What is not yet claimed

The local application is ready for live-path validation, but no claim is made yet about real Persian output quality, URL retrieval completeness, source authority ranking, latency, cost, or reliability. Those require recorded runs with actual providers and real source corpora. Pricing-versioned cost calculation is not implemented yet; the ledger records provider token usage needed to add it later.

Every document map built before prompt version `document_map_merge/1.1.0` is missing its
cross-partition layer: the merge template's `partitions` placeholder was never substituted, so
the model received no partition maps and returned an empty merge. Affected maps show zero
cross-partition dependencies and a global thesis copied from the first partition. Maps in the
shared cache are invalidated automatically; project artifacts written before the fix are not
rewritten.

Next empirical work:

1. run `thesisound doctor` and resolve all FAIL items;
2. execute one upload-based and one title-only/Search-based project;
3. include at least one Persian PDF near 900k extracted characters to validate hierarchical mapping cost and continuity;
4. inspect the observability ledger for model selection, latency, timeout, token usage, key rotation, retry/backoff, capture completeness, chunk count, regeneration count, and failure points;
5. inspect source trace, script quality, ASR diffs, final listening quality, and rewind/rebuild behavior;
6. change thresholds and defaults only from recorded evidence.
