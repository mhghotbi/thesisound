# 05 — Unified model-call observability

Thesisound records every Gemini interaction through one observed-call contract. The contract covers structured text generation, Google Search grounding, URL Context, TTS, and ASR. Okian calls reuse this same contract — see [`06-okian-provider-and-model-routing.md`](06-okian-provider-and-model-routing.md).

## Storage

Metadata is queryable in:

```text
workspaces/_observability/ledger.sqlite3
```

Redacted payload artifacts are stored in:

```text
workspaces/_observability/artifacts/<project-id-or-_global>/<call-id>/
  request.json
  raw-response.json
  parsed-output.json
```

The pre-existing per-project `model-runs/` artifacts remain for backward compatibility and prompt-contract auditing. The SQLite ledger is the cross-stage operational source for model usage and failures.

## Recorded call fields

Each call has a `call_id` and may also have a `trace_id`, `parent_call_id`, `project_id`, and `workflow_run_id`. The ledger records:

- pipeline stage and operation;
- provider, requested model, resolved model, prompt ID, and prompt version;
- source, partition, search query, script segment, or audio chunk identity;
- start/end timestamps, latency, and explicit timeout;
- provider request ID and HTTP status when exposed by the SDK;
- input, output, thinking, cached, and total token counts;
- finish reason, grounding mode, status, error type/code/message;
- whether another retry was scheduled, why, and the backoff duration;
- paths and SHA-256 hashes for request, raw-response, and parsed-output artifacts.

## Provider attempts and key rotation

Every actual credential attempt is a row in `model_attempts`. This includes quota rotation across API keys and ADC fallback. The raw credential is never stored. The ledger keeps only:

- one-based key slot;
- a 12-character SHA-256 fingerprint;
- credential type (`api_key`, `adc`, or injected test client);
- latency, HTTP status, error, retryability, and failure scope.

A logical prompt retry and a provider/key retry are different:

- `logical_attempt` identifies the prompt-contract attempt, such as schema repair;
- `provider_attempt` identifies actual provider requests, including key rotation.

## Payload policy

`THESISOUND_OBSERVABILITY_STORE_PAYLOADS=true` stores redacted request and response artifacts. The redactor removes API keys, authorization headers, cookies, sessions, OTPs, passwords, and common access-token fields. Gemini API-key patterns are also replaced inside arbitrary strings.

Binary audio is not duplicated into JSON. TTS responses are represented by byte length and SHA-256; ASR requests contain WAV length and SHA-256. Audio files remain in the normal project audio artifacts.

For environments that must not retain prompts or outputs:

```dotenv
THESISOUND_OBSERVABILITY_STORE_PAYLOADS=false
```

The SQLite metadata ledger remains active even when payload retention is disabled.

## Timeout and retry ownership

The Google Gen AI SDK receives a per-request timeout and SDK-level automatic retries are limited to one attempt so Thesisound can observe each retry itself.

Default timeouts:

```dotenv
THESISOUND_MODEL_TIMEOUT_SECONDS=180
THESISOUND_SEARCH_TIMEOUT_SECONDS=120
THESISOUND_TTS_TIMEOUT_SECONDS=240
THESISOUND_ASR_TIMEOUT_SECONDS=180
```

Provider retries for Search, TTS, and ASR use:

```dotenv
THESISOUND_PROVIDER_MAX_ATTEMPTS=2
THESISOUND_PROVIDER_RETRY_BASE_SECONDS=1
```

Versioned structured prompts retain their existing contract-level retry logic. Each logical retry receives a new `call_id` and shares the same `trace_id`.

## Inspection commands

Project summary and recent calls:

```bash
uv run thesisound observability <project-id>
```

Filters:

```bash
uv run thesisound observability <project-id> --stage document_map --status failed
uv run thesisound observability <project-id> --include-synthetic
```

Include synthetic telemetry only when deliberately inspecting test pollution:

```bash
uv run thesisound runs <project-id> --include-synthetic
uv run thesisound cost <project-id> --include-synthetic
uv run thesisound pipeline-summary <project-id> --include-synthetic
```

One call with all credential attempts:

```bash
uv run thesisound model-call <call-id>
```

Show redacted artifacts:

```bash
uv run thesisound model-call <call-id> \
  --show-request \
  --show-response \
  --show-output
```

## Status semantics

- `running`: provider call has started;
- `provider_succeeded`: provider returned, but parsing or deterministic validation is not finished;
- `succeeded`: parsed output was accepted;
- `rejected`: provider output arrived but a deterministic application validator rejected it;
- `failed`: provider, timeout, safety, schema, or other execution failure.

This distinction prevents a valid HTTP response with unusable output from being reported as a successful model operation.

## Environment isolation and synthetic telemetry

Every pipeline row (`model_calls`, `pipeline_spans`, `pipeline_events`, `pipeline_runs`) is stamped with:

- `environment` — from `Settings.environment` (`development`, `test`, or `production`);
- `is_synthetic` — true when `Settings.allow_test_otp` is set or `environment == "test"` (same rule as product metrics).

Operator CLI and UI aggregates **exclude synthetic rows by default**. Pass `--include-synthetic` (CLI) or `?include_synthetic=true` (web) to include them. Unit tests that construct `ObservabilityLedger` directly default to `is_synthetic=false` and write into a temp path, so they do not pollute the shared workspace ledger.

## Required workflow linkage

Production writes fail closed when a model call or root `kind="stage"` span lacks `project_id` and `workflow_run_id` (calls also require `pipeline_trace_id`). Development soft-reports missing fields via a `linkage.incomplete` event and still writes. Synthetic/test writes are exempt.

Use `ObservabilityLedger.check_workflow_linkage(workflow_run_id)` before treating a run’s aggregates as decision-ready. Every span/call in that run must resolve to project, workflow, trace, and stage.

## Cost rollups

Call-level `cost_micros` / `pricing_version` are filled when `config/model-pricing.toml` has matching rows (left empty by default so unknown never looks like $0). On run finish, `pipeline_runs` stores:

- `total_cost_micros` — sum of priced calls only;
- `priced_call_count` / `unpriced_call_count` — when `unpriced_call_count > 0` and no priced calls, treat cost as **unknown**, not free.

Fill pricing rows for your account, then run `thesisound observability-reprice` if historical calls need recomputation.

## Cache, review, and quality lineage events

Append-only `pipeline_events` carry decision-ready lineage:

| Event | Purpose |
| --- | --- |
| `cache.lookup` | `cache`, `result` (`hit`/`miss`), plus optional `lookup_key`, `artifact_id`/`artifact_hash`, `invalidation_reason`, `forced_refresh`, `avoided_calls`, `avoided_tokens_est`. Optional explicit `project_id` when ambient span context is absent. |
| `review.decision` | Human or gate disposition for `plan` / `script` / `parse` / `audio_chunk` with optional reviewer and reason |
| `quality.label` | Machine auxiliary scores/verdicts (parse QA, script verifier, audio QA) — never human ground truth |

These inherit ambient `workflow_run_id` / `project_id` from the active root stage span.
