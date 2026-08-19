# Thesisound — Current Implementation Status

Last updated: 2026-08-19 (direction and milestone list; implemented path unchanged since 2026-08-10)

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
- P0.5 Grounding hotfix (writer 1.3.0, `ClaimRecord` in packs, `unsupported_specifics` check, must-not-be-lost review page): not started — **next**
- P1 Concept map (two-way chapter detection → tiered concept cells with promotion → edges → gate; cache + overlay; CLI + page): not started
- P2 Evidence completeness (extraction 2.0 unified inventory for all intents, cell-unit batches, `must_not_be_lost` accounting, reconciliation 1.1.0, planner 1.3.0, glossary seeds; golden re-baseline, no migration): not started
- P3 `source_coverage` end to end (derived brief, compression + prerequisite closure, cost estimate, part packer, segment skeleton, per-part planning/script/audio, completion report): not started
- P4 Text delivery (grounded prose lesson): not started
- P5 Owner UI consolidation: not started
- P6 Evaluation on one real source + cleanup: not started

Cross-project course memory is deferred: [`docs/01-foundations/11-course-memory-future-phase.md`](docs/01-foundations/11-course-memory-future-phase.md).

## Known gaps from the 2026-08-19 prompt audit (doc 10 §8)

These describe the **current** code and are fixed by P2:

- the active writer prompt `persian_script_segment/1.2.0` carries tone guidance only; the grounding rules of 1.1.0 (no outside knowledge, `editorial_only` semantics, preserve qualifications/disagreement, `speaker_dynamic` contract) are absent from its system prompt — `tests/test_script_speaker_balance.py::test_latest_script_prompt_is_1_2_0_and_renders_position` already fails on this (it asserts "Never add outside knowledge" is present); the fix is `persian_script_segment/1.3.0` (doc 10, Appendix A.1), after which the test's version pin moves to 1.3.0;
- `must_not_be_lost` points are extracted and cross-referenced but never supplied to the planner and shown on no page;
- definitions, distinctions, examples, objections and responses carry no verbatim excerpt and no ID, so they are neither audited nor accounted for in the plan;
- `max_claims_per_block` silently drops surplus claims on dense blocks (no `truncated` signal, no second pass);
- evidence packs omit the reconciled `ClaimRecord` (`support_status`, qualifications), so the writer sees `uncertain` only through the disagreement graph;
- the glossary model pass triggers only on Latin tokens; Persian sources with transliterated terms get an empty glossary and a silent pass.

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
