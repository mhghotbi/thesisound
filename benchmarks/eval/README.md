# Frozen golden evaluation

This directory implements the machine-checkable release-gate subset of [`docs/01-foundations/05-quality-evaluation.md`](../../docs/01-foundations/05-quality-evaluation.md). It runs committed markdown sources through the real ingestion, source-analysis, episode-planning, approval, and script pipeline, then stops before TTS, ASR, or audio assembly.

It does **not** automate the human evaluation protocol or the blind NotebookLM comparison described in doc 05. The `expectations.toml` files preserve must-cover points and distinctions for that human review, but the runner deliberately does not pretend to score them automatically.

Run validation with no model construction or provider calls:

```bash
uv run thesisound eval --dry-run
```

Run the paid evaluation explicitly:

```bash
uv run thesisound eval
```

Each case gets an isolated workspace under `benchmarks/eval/runtime/<case-id>/`, including its own observability ledger. Reports are written as JSON and Markdown under `benchmarks/eval/reports/`. Unknown cost is represented as unknown; a configured cost gate is reported as `skipped`, never silently passed.
