# Thesisound — Current Implementation Status

Last updated: 2026-08-08

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

## End-to-end readiness additions

- پروژه می‌تواند فقط با عنوان/موضوع شروع شود و در UI از Gemini Search منبع بگیرد.
- Search result و snippet candidate هستند؛ URL انتخاب‌شده قبل از evidence با URL Context capture و quality-gate می‌شود.
- اسناد بزرگ دیگر با hard cap رد نمی‌شوند؛ map در partitionهای کامل semantic انجام و سپس global reduce اجرا می‌شود.
- navigation بین مراحل روی همه صفحات پروژه نمایش داده می‌شود.
- rewind به Brief یا Sources خروجی downstream را archive و invalid می‌کند و raw inputs را نگه می‌دارد.
- پیام quality warning وضعیت، اثر و اقدام لازم را به زبان انسانی توضیح می‌دهد؛ parser/verdict در جزئیات فنی است.
- `uv run thesisound doctor` و `/system-check` پیش‌نیازهای live runtime را بررسی می‌کنند.

## Milestone status

- M0 Scaffold and contracts: implemented
- M1 Document ingestion: implemented; broader Persian benchmark remains empirical work
- M2 Structured model execution: implemented; live-provider behavior remains empirical work
- M3 Evidence pipeline: implemented
- M4 Episode preparation: implemented
- M5 Verified Persian script: implemented
- M6 TTS, ASR, and Audio QA vertical slice: implemented in code
- M6.5 Operator UI: implemented through final audio review with revision navigation
- M7 Gemini Source Discovery vertical slice: implemented; general crawler, deduplication quality, and authority ranking remain open
- M8 Full multi-source semantic reconciliation: not implemented
- M9 End-user product UI: not implemented
- M10 production persistence, jobs, deployment, and real OTP provider: not implemented

## What is not yet claimed

The local application is ready for live-path validation, but no claim is made yet about real Persian output quality, URL retrieval completeness, source authority ranking, latency, cost, or reliability. Those require recorded runs with actual providers and real source corpora.

Next empirical work:

1. run `thesisound doctor` and resolve all FAIL items;
2. execute one upload-based and one title-only/Search-based project;
3. include at least one Persian PDF near 900k extracted characters to validate hierarchical mapping cost and continuity;
4. record provider calls, latency, token usage, capture completeness, chunk count, regeneration count, and failure points;
5. inspect source trace, script quality, ASR diffs, final listening quality, and rewind/rebuild behavior;
6. change thresholds and defaults only from recorded evidence.
