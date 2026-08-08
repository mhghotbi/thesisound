# Thesisound — Current Implementation Status

Last updated: 2026-08-08

## Implemented end-to-end path

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
→ explicitly started audio generation
→ TTS-safe chunks
→ TTS synthesis
→ WAV validation
→ ASR transcription
→ expected-vs-heard QA
→ targeted regeneration of defective chunks
→ FFmpeg normalization and assembly
→ verified final WAV
→ COMPLETE
```

## Milestone status

- M0 Scaffold and contracts: implemented
- M1 Document ingestion: implemented; broader Persian parser benchmark remains empirical work
- M2 Structured model execution: implemented; live provider smoke tests remain empirical work
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

The code path is implemented and covered by deterministic/fake-provider tests. It is not yet empirically calibrated on a real Persian golden corpus.

The next validation work is:

1. run live Gemini TTS and ASR on real verified scripts;
2. compare chunk sizes and voices;
3. run blind listening and transcript-fidelity evaluation;
4. benchmark Persian parsing/OCR across the fixed corpus;
5. update thresholds and defaults only from recorded evidence.

`docs/25-audio-vertical-slice.md` is the authoritative contract for the audio milestone. Older roadmap language that still calls M6 “the next step” should be read as historical until the roadmap document is consolidated.
