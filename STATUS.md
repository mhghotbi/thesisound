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
- P3 `source_coverage` end to end (derived brief, compression + prerequisite closure, cost estimate, part packer, segment skeleton, per-part planning/script/audio, completion report): **done, pending checkpoint C-D** — runbook steps 18–22 are built; see the P3 scope note below on how per-part script/audio was implemented
- P4 Text delivery (grounded prose lesson): not started
- P5 Owner UI consolidation: not started
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

Checkpoint C-D (2026-08-20, real run on `FA-2-Citizenship-as-Alternative-to-World-Alienation.pdf`, a real Persian Arendt article, with a real Gemini key pool): **partially completed**.

Verified for real, end to end: concept-map build (11 cells, sensible tiers/edges/labels, spot-checked against the source), cell-seeded extraction (50 real claims, coverage climbing 33%→53%→64%→75%→passing across resumed retries — the 85% evidence-retention gate and the extraction resume-on-retry behavior both work as designed), and the step 21 per-part planning loop (3 real parts, 13 segments, all `graph_backed=True`, sensible titles and minute counts, `short_last_part` correctly flagged on the last part). This real run found and fixed three genuine crashes, none caught by any existing test (all now covered): a shared concept-map cache hit under a different project/source reused block ids that pointed at another source's blocks (`ConceptMapBuilder.build` now remaps them); `claim_prioritizer._BASE_TYPE_SCORE` was missing the three extraction-2.0 claim types, crashing on any `definition`/`distinction`/`example` claim; `SegmentEvidencePack` rejected the skeleton's claimless recap segment.

Not verified: script writing, verification, and audio. Blocked, not by a code defect: Gemini's key pool was quota-exhausted mid-run, and its automatic Okian failover was itself down server-side (`okian-proxy-tunnel-outage-2026-08-20` in agent memory) — 40 consecutive retries all failed identically once both providers were unavailable. The project (`3dfd0711-eccc-4526-a635-6aaf9da7470c`, `failed_retryable` at the script stage) is left in the local workspace, fully resumable, for whenever either provider recovers.

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
