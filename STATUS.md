# Thesisound — Current Implementation Status

Last updated: 2026-08-08

## Implemented local end-to-end path

```text
OTP login
→ project and Research Brief
→ source upload and real ingestion
→ parse-quality gate
→ confirmed corpus
→ semantic blocks, evidence, and claims
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

- `uv run thesisound doctor` checks live runtime prerequisites.
- `/system-check` exposes the same checks in the UI.
- model and audio POST actions are blocked before queueing when required dependencies are missing.
- the verified-script screen links directly to audio generation.
- blocked or review-needed sources can be retried or removed before corpus confirmation.
- README and the local live-run runbook describe the current PDF-to-WAV path.

## Milestone status

- M0 Scaffold and contracts: implemented
- M1 Document ingestion: implemented; broader Persian benchmark remains empirical work
- M2 Structured model execution: implemented; live-provider behavior remains empirical work
- M3 Evidence pipeline: implemented
- M4 Episode preparation: implemented
- M5 Verified Persian script: implemented
- M6 TTS, ASR, and Audio QA vertical slice: implemented in code
- M6.5 Operator UI: implemented through final audio review for the current source-bound workflow
- M7 Source discovery: not implemented
- M8 Full multi-source semantic reconciliation: not implemented
- M9 End-user product UI: not implemented
- M10 production persistence, jobs, deployment, and real OTP provider: not implemented

## What is not yet claimed

The local application is ready for a live happy-path run, but no claim is made yet about real Persian output quality, latency, cost, or reliability. Those require a recorded run with actual providers and a real source corpus.

The next work is empirical rather than another architecture milestone:

1. run `thesisound doctor` and resolve all FAIL items;
2. execute one real project from login to final WAV;
3. record provider calls, latency, token usage, TTS chunk count, regeneration count, and failure points;
4. inspect source trace, script quality, ASR diffs, and final listening quality;
5. change thresholds and defaults only from recorded evidence.
