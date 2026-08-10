# 10 — Local Live End-to-End Runbook

Related: this is the manual acceptance procedure for the slices in [`05`](05-web-ui-auth-and-first-slice.md)–[`09`](09-audio-vertical-slice.md); the operating SOP for production gates is [`../06-operations/03-production-sop.md`](../06-operations/03-production-sop.md).

This runbook is the precondition for claiming that the implemented vertical slice works with real providers.

## 1. Install

```bash
uv sync --extra dev --extra web-ui --extra gemini --extra parsers
cp .env.example .env
```

Set:

```dotenv
GEMINI_API_KEY=...
```

Install FFmpeg and confirm it is on `PATH`:

```bash
ffmpeg -version
```

## 2. Preflight

```bash
uv run thesisound doctor
```

Do not start a paid run while any row is `FAIL`. `WARN` means the happy path may still work, but a parser fallback is unavailable.

## 3. Start UI

```bash
uv run thesisound-web
```

Open `http://127.0.0.1:8000`.

Development login:

```text
09120000000
999999
```

## 4. Recommended first source

Use one text-based Persian PDF with selectable text, a clear heading structure, and no encryption. Do not start the first live run with a scanned book or a multi-column PDF.

Record:

- filename and SHA-256;
- page count;
- parser selected and attempted parsers;
- quality verdict;
- block and character counts.

## 5. Execute the full path

1. Create project.
2. Confirm Research Brief.
3. Upload source.
4. Confirm parse-quality result.
5. Select and confirm corpus.
6. Wait for evidence pipeline.
7. Review coverage and supported duration.
8. Approve Episode Plan.
9. Review script checks, verifier output, and source trace.
10. Continue directly to audio.
11. Review `/system-check?scope=audio`.
12. Start audio generation.
13. Review each chunk, ASR transcript, QA verdict, and regeneration count.
14. Play and download final WAV.

## 6. Capture evidence

For each stage, preserve:

- start and finish timestamps;
- provider/model;
- token usage where available;
- retry count;
- final state;
- last error;
- artifact paths and checksums.

For audio, also preserve:

- chunk count;
- voice assignment;
- duration per chunk;
- similarity ratio;
- missing/repeated sentence flags;
- regenerated chunk IDs;
- final duration and checksum.

## 7. Failure handling

### Source is review or blocked

Install or repair the preferred parser, return to the source page, and use **تلاش دوباره برای استخراج**. If the file is unsuitable, remove it and upload a better copy.

### Corpus is insufficient

Do not bypass the gate. Reduce duration, add a source, or narrow the focus, then recompute.

### Model stage is blocked before start

Open `/system-check`. Correct `GEMINI_API_KEY`, install `google-genai`, or repair writable paths. The run has not been queued yet.

### Audio is blocked before start

Resolve all model checks and install FFmpeg. The guard runs before the audio run is queued.

### Service restarts during a run

Restart the app, open the project, and use the stage-specific retry. Existing healthy artifacts are reused when their upstream hash still matches.

## 8. Acceptance criterion for the first run

A first live run is technically complete only when:

- project reaches `COMPLETE`;
- final WAV is served and downloadable;
- final audio manifest is `verified`;
- script and audio artifacts match the current upstream hashes;
- no unsupported claim remains in the verified script;
- all audio chunks have an accepted QA result after at most one targeted regeneration.

Listening quality is a separate human acceptance decision and must be recorded explicitly.
