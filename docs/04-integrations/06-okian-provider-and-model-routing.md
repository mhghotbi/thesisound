# 06 — Okian provider and stage-based model routing

Thesisound supports two text-model providers:

- `gemini`: Google Gen AI SDK, including Google Search and URL Context.
- `okian`: an OpenAI-compatible `/chat/completions` endpoint configured with a base URL and API key.

Okian is installed as an available provider but is not assigned to any stage by default.

## Environment

```dotenv
OKIAN_BASE_URL=
OKIAN_API_KEY=
THESISOUND_OKIAN_TIMEOUT_SECONDS=180

THESISOUND_MODEL_ROUTING_FILE=./config/model-routing.toml
THESISOUND_MODEL_ROUTE_OVERRIDES={}
```

With Okian credentials set, ungrounded Gemini structured-text calls automatically fall back to Okian when the Gemini key pool is exhausted (quota / rate-limit across all keys). The same model ID is reused. Explicit stage routing to an Okian profile still works independently of this failover.

Fallback does **not** apply to:

- grounded stages (`grounding_mode` other than `none`);
- TTS / ASR;
- non-rate-limit Gemini failures (schema, safety, timeouts, single-key non-quota errors).

Without `OKIAN_BASE_URL` and `OKIAN_API_KEY`, exhausted Gemini keys fail as before.

## Routing file

The default `config/model-routing.toml` keeps every structured-text stage on Gemini. Profiles separate provider/model configuration from stage assignment:

```toml
[profiles.okian_qwen]
provider = "okian"
model = "your-qwen-model-id"

[profiles.okian_gemma]
provider = "okian"
model = "your-gemma-model-id"

[routes]
document_map = "okian_qwen"
persian_script_segment = "okian_gemma"
```

For a temporary deployment override without editing the routing file:

```dotenv
THESISOUND_MODEL_ROUTE_OVERRIDES={"document_map":"okian_qwen"}
```

The referenced profile must still exist in the TOML file.

## Resolution order

For versioned structured prompts, routing resolves in this order:

1. an explicit CLI `--model` override remains a direct Gemini model override;
2. `THESISOUND_MODEL_ROUTE_OVERRIDES` for the prompt contract id;
3. the prompt-contract route in `config/model-routing.toml` (e.g. `persian_script_segment`, not observability stages like `script_segment:{id}`);
4. the existing `THESISOUND_MODEL_FAST` or `THESISOUND_MODEL_STRONG` Gemini fallback.

Prompt contracts continue to declare only the logical tier (`fast` or `strong`). Provider deployment decisions remain outside the prompts.

## Grounded stages

See [`01-gemini-grounding.md`](01-gemini-grounding.md) for the full per-stage grounding policy. Okian is text-only in this integration. It does not provide Gemini Google Search or URL Context. Routing a grounded stage to Okian fails before an HTTP request is sent.

Keep these operations on Gemini:

- Google Search source discovery;
- URL Context source capture;
- research brief and any future prompt whose grounding mode is not `none`.

Glossary is ungrounded and may be routed to Okian with the rest of script drafting.

TTS and ASR also remain on their dedicated Gemini settings and are not controlled by the text routing file.

## OpenAI-compatible request contract

The Okian adapter calls:

```text
<OKIAN_BASE_URL>/chat/completions
```

If the configured base URL already ends in `/chat/completions`, it is used unchanged. Requests include:

- bearer authentication;
- system and user messages;
- `temperature = 0`;
- strict JSON Schema response format;
- the selected model ID;
- explicit timeout.

The response must use the common OpenAI-compatible `choices[0].message.content` and `usage` fields.

## Observability

Okian calls use the same unified ledger as Gemini — same fields, same per-attempt key-rotation rows, same redaction. See [`05-model-observability.md`](05-model-observability.md). The only difference is `provider` recorded as `okian`; the API key itself is never written to the ledger or payload artifacts.

On key-pool fallback, the failed Gemini call stays in the ledger, and the Okian retry is a new call with `parent_call_id` pointing at that Gemini row and `okian_fallback_from=gemini` in call metadata.
