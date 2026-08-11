# R11 — Product metrics: a closed vocabulary, one choke point, and a store that outlives tracing

**Status:** plan, not yet implemented
**Audience:** the developer wiring this up, assumed junior on this codebase
**Prerequisite reading:** [PRODUCT.md](../PRODUCT.md), [docs/04-integrations/05-model-observability.md](04-integrations/05-model-observability.md)

The one-line summary: we already record the product funnel by accident, we
record it without a user attached, and we record it on a channel an operator
can switch off. This plan keeps the accident, fixes the user gap, and moves
product metrics off the switchable channel.

---

## 1. What this is, and five findings that reframe it

Read this section before touching code. Four of these five findings mean the
obvious implementation is the wrong one.

### 1.1 There are genuinely no product metrics today

Verified, not assumed:

- No analytics SDK is wired in. A repo-wide search for `posthog`, `mixpanel`,
  `segment`, `amplitude`, `google_analytics`, `plausible` returns nothing in
  source. (The 128-file hit for `retention|DAU|signup|churn` is noise — every
  match is inside logged JSON payloads under `workspaces/` and `artifacts/`,
  not code.)
- [PRODUCT.md](../PRODUCT.md) has no metrics section. It defines the product,
  the audience, the job, and eight non-negotiable rules — no success measures.
- What exists in the ledger is *technical* telemetry: model calls, tokens,
  latency, cost, retries. That answers "is the pipeline healthy," never
  "is the product working for anyone."

### 1.2 But the core funnel is already recorded — as a side effect

[`transition()`](../src/thesisound/pipeline.py#L99) already emits an event on
every state change:

```python
tracing.event(
    "project.state_changed",
    component="pipeline",
    project_id=project.project_id,
    previous=previous.value,
    current=target.value,
)
```

In the current ledger that is **7,165 events across 2,453 distinct projects**,
and `project_id` is set on **100%** of them. The full transition matrix is
already sitting there and has never been queried as a funnel. A sample:

| transition | count |
| --- | --- |
| `corpus_building → corpus_ready` | 359 |
| `corpus_building → failed_retryable` | 315 |
| `script_verifying → script_drafting` (rework) | 194 |
| `script_verifying → script_verified` | 170 |
| `episode_planned → episode_planning` (replan) | 176 |
| `audio_verifying → complete` | 145 |

**Consequence for the implementation:** do not build a new collector for the
project funnel. The 19-state machine in
[`ALLOWED_TRANSITIONS`](../src/thesisound/pipeline.py#L11) already forces every
funnel movement through one function. Instrument that function, not the twenty
route handlers that call into it. This is the single largest anti-drift lever
in the plan — see **D4**.

### 1.3 The events carry no user, and the user lives in a different database file

`pipeline_events` has `project_id`, `workflow_run_id`, `subject_type`,
`subject_id` — and no user column. The project→user link is
[`project_members(project_id, user_id)`](../src/thesisound/accounts.py#L447),
which lives in `accounts.sqlite3`, a **separate database file** from
`ledger.sqlite3`.

So today, *not one per-user metric is computable*. Not activation, not
retention, not projects-per-user. This is the blocking gap, and it is why the
plan cannot be "just write some SQL against the existing events."

### 1.4 Tracing is the wrong channel to hang product metrics on

Three properties of the tracing channel make it unfit:

- [`tracing_enabled: bool = True`](../src/thesisound/config.py#L102) — one
  setting silently zeroes every product metric.
- [`tracing_detail`](../src/thesisound/config.py#L103) gates span volume, and
  [observability.py](../src/thesisound/observability.py#L1338) states outright
  that detail is "the primary lever for keeping volume down."
- The ledger is expected to be pruned; it is debug data with a retention story.

A metric that disappears because an operator lowered trace detail to save disk
is not a metric. Product events therefore get **their own table and their own
writer, always on, never detail-gated** (**D1**). We still *derive* from the
same choke points — we just do not ride the same switch.

### 1.5 Today's data is ~all synthetic, and would poison every metric forever

2,453 projects created in a 2-day window; the `users` table has **0 rows**; the
`model_calls` rows show `requested_model = "gemini-test"`. This is a test
corpus, not product usage.

If events are not stamped with environment and a synthetic flag **at write
time**, you can never separate fixture data from real data retroactively —
there is no field to filter on and no way to reconstruct one. This must be in
the schema from the first commit (**D6**), not added later.

---

## 2. Scope

### In scope

- One new table, `product_events`, in the existing ledger database.
- One derived table, `product_metric_daily`, recomputable from raw events.
- A closed event vocabulary + typed payloads.
- Instrumentation at three choke points: `transition()`, the auth routes, and
  the human-gate / consumption routes.
- A metric catalogue expressed as data, not scattered SQL.
- A rollup service, a CLI command, and one operator-mode page.
- Guard tests that make drift fail CI rather than fail silently.

### Explicitly out of scope — do not touch

- **The SQLite → Postgres question.** Unrelated to this work. Use the same
  `sqlite3` + `_MIGRATIONS` pattern the ledger already uses; if the database
  moves later, this table moves with it like every other.
- **Any change to `ALLOWED_TRANSITIONS` or the state machine.** Metrics observe
  the state machine; they never alter it.
- **Any change to the existing `pipeline_events` / tracing behaviour.** Do not
  remove the `project.state_changed` event, do not "migrate" it. It stays
  exactly as-is and keeps serving debugging.
- **Retro-backfilling metrics from the existing 7,165 events.** They are
  synthetic (§1.5) and have no user attached (§1.3). Backfilling them produces
  confident, wrong history. Start the series at first deploy.
- **A third-party analytics SDK.** Out of scope by decision, not oversight —
  see D12 on PII, and note the audience is Persian students under an
  ownership model where source data stays on our infrastructure.
- **Dashboards beyond one operator page.** Datasette already browses the raw
  table (see §9).

---

## 3. Locked design decisions

These are decisions, not options. If you think one is wrong, raise it before
implementing — do not quietly do the other thing. That is what drift is.

### D1 — Product events live in a new table in the ledger DB, with their own writer

Not a new database file (that would add a third store and a second cross-file
join problem). Not inside `pipeline_events` (that inherits the tracing
switch, §1.4). A new `product_events` table inside `ledger.sqlite3`, written by
a dedicated `ProductEventStore` that never consults `tracing_enabled`.

### D2 — The vocabulary is a closed `StrEnum`; an unlisted name cannot be emitted

```python
class ProductEvent(StrEnum):
    AUTH_CODE_REQUESTED = "auth.code_requested"
    ...
```

`emit()` accepts `ProductEvent`, never `str`. This makes `project_created` vs
`project.created` a type error instead of two metrics that each look half-right.
This is the difference between a schema and a habit.

### D3 — Every event has a typed payload model

One pydantic model per event, in the same module as the enum. No
`**kwargs: Any` at the emit site. The codebase is pydantic-first everywhere
else ([domain.py](../src/thesisound/domain.py#L432)); match it. A payload field
that appears on 60% of an event's rows is a metric you cannot trust, and typed
payloads are what prevent it.

### D4 — Instrument choke points, not routes

Three choke points cover the whole surface:

1. [`transition()`](../src/thesisound/pipeline.py#L99) — the entire project
   funnel, because the state machine already forces every movement through it.
2. The auth routes in [app.py](../src/thesisound/web/app.py#L532) — identity,
   which no choke point covers.
3. Gate/consumption routes — explicit human decisions that are *not* state
   transitions (see the list in Step 6).

Adding instrumentation to individual route handlers as a general habit is the
main way this rots. If you find yourself adding a fourth category, stop and ask.

### D5 — `user_id` is resolved once, at write time, and denormalized onto the event

Resolve via `project_members` and store the integer on the row. Do **not** plan
to join `accounts.sqlite3` to `ledger.sqlite3` at query time — that is the
cross-file join from §1.3 and it does not work in one SQL statement.

Denormalization is correct here: an event is an immutable historical fact, so
"who owned this project at the time" is exactly what we want frozen.

### D6 — Every event carries `environment` and `is_synthetic`, stamped at write time

`environment` from settings (`production` / `staging` / `development`).
`is_synthetic` true when the run is a test fixture, an eval harness run, or
`THESISOUND_ALLOW_TEST_OTP=true` is in effect. Every catalogue query filters
`is_synthetic = 0 AND environment = 'production'` by default.

Non-negotiable, per §1.5: this cannot be reconstructed later.

### D7 — Metrics are definitions-as-data in one module

One `MetricDefinition` dataclass per metric, all in
`product_metrics/catalogue.py`, each carrying: `key`, `question` (the
plain-language question it answers), `sql`, `grain`, `owner`, `caveat`.

Rationale: the failure mode for metrics is not bad SQL, it is *the same metric
computed two slightly different ways in two places*, so two dashboards disagree
and nobody can say which is right. One definition, one place, every consumer
reads from it.

### D8 — Raw events are append-only; rollups are disposable and recomputable

`product_events` is never updated or deleted. `product_metric_daily` can be
dropped and rebuilt from raw at any time, and the rebuild must be
deterministic. If a metric definition changes, you delete its rows and
recompute — you never edit a rollup in place.

### D9 — The 19 states collapse to 7 funnel stages, defined exactly once

19 states are right for the pipeline and useless as a funnel. The collapse
lives in **one** mapping in `catalogue.py`:

| # | Funnel stage | States included |
| --- | --- | --- |
| 1 | Created | `draft` |
| 2 | Brief confirmed | `brief_ready` |
| 3 | Sources gathered | `sources_collecting`, `source_selection_required` |
| 4 | Corpus confirmed | `corpus_building`, `corpus_ready` |
| 5 | Episode planned | `episode_planning`, `episode_planned` |
| 6 | Script verified | `script_drafting`, `script_ready`, `script_verifying`, `script_review_required`, `script_verified` |
| 7 | Audio complete | `audio_generating`, `audio_ready`, `audio_verifying`, `complete` |

`failed_retryable` / `failed_permanent` are **not** stages — they are a
condition recorded against the stage the project was in when it failed.

Every consumer imports this mapping. Nobody re-lists states inline. When a
20th state is added, one edit updates every funnel metric.

### D10 — Metrics never gate, slow, or break the request path

`emit()` catches every exception, increments an internal
`product_metrics.emit_failed` counter, and returns. A metrics bug must never
turn into a user-facing 500 or a failed episode.

Corollary: because failures are swallowed, the failure counter must be visible
on the operator page, or silent total loss looks identical to zero usage.

### D11 — Same migration pattern as the ledger, append-only

Add `_SCHEMA_V4_PRODUCT_EVENTS` to the existing
[`_MIGRATIONS`](../src/thesisound/observability.py#L2186) tuple in
`observability.py`. Obey the rule already documented there: migrations must be
idempotent, and **never edit a migration that has shipped**.

### D12 — No PII in payloads, ever

No phone numbers, no OTP codes, no raw topic text, no source filenames, no
script content. `user_id` (an opaque integer) is the only identity on a row.
This is a hard rule, and there is a guard test for it (Step 10).

Note the `users` table stores `phone` ([accounts.py:429](../src/thesisound/accounts.py#L429)).
Never copy it onto an event.

---

## 4. Invariants that must not change

1. `ALLOWED_TRANSITIONS` and the state machine are untouched.
2. The existing `project.state_changed` tracing event keeps firing, unchanged.
3. `product_events` is append-only.
4. No metrics code path can raise into a request handler.
5. Every emitted event name exists in the `ProductEvent` enum.
6. Every enum member has a payload model, a catalogue entry or an explicit
   `# raw-only` marker, and a test.
7. Every row has `environment` and `is_synthetic` set.
8. No payload field contains PII.

Invariants 5–8 are enforced by tests, not by review (Step 10).

---

## 5. The event vocabulary

Twenty-two events, closed set. Grouped by choke point.

### Choke point 1 — `transition()` (project funnel)

| Event | Fires when | Key payload |
| --- | --- | --- |
| `project.created` | project first persisted | `topic_type`, `entry_mode` |
| `project.stage_entered` | any transition into a new funnel stage (D9) | `stage`, `from_stage`, `state`, `from_state` |
| `project.stage_failed` | transition into `failed_retryable`/`failed_permanent` | `stage`, `state`, `permanent`, `error_class` |
| `project.recovered` | transition *out of* `failed_retryable` | `stage`, `failed_for_seconds` |
| `project.transition_rejected` | invalid transition attempted | `from_state`, `attempted_state` |

`error_class` is a bounded category (e.g. `parser`, `model`, `coverage`,
`timeout`) — **not** the raw `last_error` string (D12, and unbounded strings
make a useless dimension).

### Choke point 2 — auth routes (identity)

| Event | Route |
| --- | --- |
| `auth.code_requested` | `POST /login/request-code` |
| `auth.code_verified` | `POST /login/verify` (success) |
| `auth.code_failed` | `POST /login/verify` (failure) |
| `auth.password_succeeded` | `POST /login/password` (success) |
| `auth.password_failed` | `POST /login/password` (failure) |
| `auth.locked_out` | lockout triggered (`locked_until` set) |
| `auth.logged_out` | `POST /logout` |
| `user.registered` | first successful auth for a new `user_id` |

### Choke point 3 — human gates and consumption

These are explicit human decisions and are the product's actual differentiator
(PRODUCT.md's non-negotiable rules are all gates), so they get first-class
events rather than being inferred from state changes.

| Event | Source |
| --- | --- |
| `gate.brief_confirmed` | `POST /projects/{id}/brief` |
| `gate.brief_edited` | brief modified before confirmation |
| `gate.corpus_confirmed` | `POST /projects/{id}/corpus/confirm` |
| `gate.source_toggled` | `POST /projects/{id}/sources/{sid}/toggle` |
| `gate.source_deleted` | `POST /projects/{id}/sources/{sid}/delete` |
| `gate.script_approved` | `POST /projects/{id}/script/approve` |
| `gate.script_review_requested` | `POST /projects/{id}/script/review` |
| `gate.blocked` | a blocking gate stops progress; `gate_name`, `reason` |
| `gate.resolved` | a previously blocking gate clears; `gate_name`, `blocked_seconds` |
| `workflow.rewound` | `POST /projects/{id}/workflow/rewind` |
| `episode.audio_downloaded` | `GET .../audio/final.wav` or `.mp3`; `format` |
| `episode.source_trace_opened` | user opens the claim→source trace |

Two notes for the implementer:

- `workflow.rewound` is a **friction signal, not a failure**. The route exists
  at [source_routes.py:540](../src/thesisound/web/source_routes.py#L540). A user
  going backwards means the previous screen produced something they did not
  want; it is one of the highest-value signals in this list.
- `episode.source_trace_opened` measures a stated product promise — PRODUCT.md
  says "source trace available on demand." If nobody opens it, that promise is
  not being delivered, however good the traceability engine is.

---

## 6. The metric catalogue

Every metric below is computable from the vocabulary in §5 plus the existing
ledger. Each carries the question it answers and its gotcha. All default to
`is_synthetic = 0 AND environment = 'production'` (D6).

### A. North star

**A1 — Trusted episodes delivered (weekly).**
Count of distinct projects reaching funnel stage 7 (`complete`) *and* having at
least one `episode.audio_downloaded`, per week.
*Why both:* completion alone measures the pipeline, not the product. An episode
nobody listened to did not deliver the job in PRODUCT.md. This is deliberately
harder to move than "completed episodes" and that is the point.

### B. Acquisition and identity

| Key | Question | Formula |
| --- | --- | --- |
| B1 `auth_request_to_verify_rate` | Do people who ask for a code get in? | `auth.code_verified / auth.code_requested`, by day |
| B2 `auth_verify_failure_rate` | Is OTP entry painful? | `auth.code_failed / (verified + failed)` |
| B3 `auth_median_seconds_to_verify` | How long does the code round-trip take? | median seconds `code_requested → code_verified`, same user |
| B4 `auth_lockout_rate` | Are we locking real users out? | distinct users with `auth.locked_out` / distinct users attempting |
| B5 `new_users_weekly` | Are we growing? | distinct `user.registered` per week |

*Gotcha for B1/B3:* SMS delivery is a third party
([Kavenegar](../src/thesisound/adapters/sms/)). A drop here is as likely to be
a delivery outage as a UX problem — always read B1 next to B3.

### C. Activation

The activation question for this product is not "did they sign up" but "did
they get one trustworthy episode out."

| Key | Question | Formula |
| --- | --- | --- |
| C1 `activation_rate_7d` | Do new users reach a completed episode within 7 days? | users with stage 7 within 7d of `user.registered` / all registered that week |
| C2 `time_to_first_episode_p50` / `_p90` | How long does the first success take? | `user.registered → first stage 7` |
| C3 `first_project_rate` | Do they even start? | users with ≥1 `project.created` / registered |
| C4 `first_session_depth` | How far does the first project get? | max funnel stage reached in first session, distribution 1–7 |

*Gotcha:* C1's denominator is a **cohort**, so it is only final 7 days after the
cohort closes. Never render a partial cohort next to complete ones without
marking it — this is the single most common way an activation chart lies.

### D. Core funnel

| Key | Question | Formula |
| --- | --- | --- |
| D1 `stage_conversion` | Where do projects die? | for each stage *n*: projects reaching *n+1* / reaching *n* |
| D2 `stage_dropoff_absolute` | How many projects are stuck, and where? | projects whose max stage = *n*, no activity in 14d |
| D3 `stage_median_duration` | Which stage is slowest *for the user*? | median `stage_entered(n) → stage_entered(n+1)` |
| D4 `end_to_end_completion_rate` | What fraction of started projects finish? | stage 7 / stage 1 |
| D5 `end_to_end_duration_p50/p90` | How long is the whole job? | `project.created → stage 7` |

*Gotcha for D3:* this is wall-clock and includes the user being asleep. It is a
*user-experienced* latency, deliberately — for machine latency use the existing
`pipeline_runs.duration_ms`. Do not conflate them; they answer different
questions and will differ by orders of magnitude.

### E. Human gates — the product's actual differentiator

| Key | Question | Formula |
| --- | --- | --- |
| E1 `brief_confirm_rate` | Do we get the brief right first time? | `gate.brief_confirmed` with no preceding `gate.brief_edited` / all confirmed |
| E2 `corpus_edit_depth` | How much do users fight source selection? | count of `gate.source_toggled` + `gate.source_deleted` per project before confirm |
| E3 `script_approval_rate` | Is the first script good enough? | `gate.script_approved` / (`approved` + `review_requested`) |
| E4 `script_rework_loops` | How many script rounds per episode? | count of transitions `script_verifying → script_drafting` per project |
| E5 `gate_block_rate` | How often does a blocking rule fire? | projects with ≥1 `gate.blocked` / active projects, by `gate_name` |
| E6 `gate_resolution_rate` | Do users recover from a block? | `gate.resolved` / `gate.blocked`, by `gate_name` |
| E7 `gate_median_blocked_seconds` | How long are people stuck? | median `blocked_seconds` |
| E8 `rewind_rate` | How often do users go backwards? | projects with ≥1 `workflow.rewound` / active projects, by `from_stage` |

E5–E7 are the most important block in this catalogue. PRODUCT.md's rules
("insufficient coverage blocks script generation", "a blocking source-quality
failure cannot be silently accepted") are *deliberate friction*. That friction
is the product promise, so the question is never "how do we reduce blocks" — it
is **"when we block someone, do they successfully recover?"** E6 is that number.

For calibration, the current synthetic data shows `gate.blocked` 105 vs
`gate.resolved` 70 in the episode component. If that ratio held with real
users, roughly a third of blocked users never get unstuck — that is a product
emergency, and today nothing would surface it.

### F. Trust and quality

| Key | Question | Source |
| --- | --- | --- |
| F1 `source_trace_open_rate` | Is the traceability promise used? | `episode.source_trace_opened` / completed episodes |
| F2 `coverage_block_rate` | How often is the corpus genuinely insufficient? | `gate.blocked` where `gate_name = 'coverage'` |
| F3 `claim_retention_rate` | What share of claims survive verification? | existing `corpus.evidence_yield` / `kept_claim_count` vs `dropped_claim_count` in the ledger |
| F4 `episodes_per_source_count` | Does corpus size predict success? | completion rate bucketed by confirmed source count |

F3 needs no new instrumentation — `kept_claim_count` and `dropped_claim_count`
are already recorded in span attributes
([observability_rollup.py:188](../src/thesisound/services/observability_rollup.py#L188)).

### G. Reliability, as the user feels it

| Key | Question | Formula |
| --- | --- | --- |
| G1 `stage_failure_rate` | Which stage breaks most? | `project.stage_failed` / `stage_entered`, by stage |
| G2 `recovery_rate` | Do failures self-heal? | `project.recovered` / `stage_failed` |
| G3 `permanent_failure_rate` | How often do we lose a project entirely? | `stage_failed(permanent=true)` / projects created |
| G4 `user_visible_failure_rate` | What fraction of users hit any failure? | distinct users with ≥1 `stage_failed` / active users |

*Calibration from current synthetic data:* `corpus_building → failed_retryable`
fires 315 times against 359 successes — a ~47% failure rate at corpus build,
and `script_verifying → script_drafting` (194) exceeds
`script_verifying → script_verified` (170). If anything close to this survives
into production, G1 will be the most actionable metric on this list. **Treat
these numbers as a hypothesis to test, not a finding** — they come from fixture
data (§1.5).

### H. Retention and economics

| Key | Question | Formula |
| --- | --- | --- |
| H1 `wau` / `mau` | Are people coming back at all? | distinct `user_id` with any event, 7d / 30d |
| H2 `w1_w4_retention` | Do they come back in later weeks? | cohort by `user.registered` week, active in week *n* |
| H3 `projects_per_user_p50` | Is this a one-off or a habit? | distinct projects per user, trailing 30d |
| H4 `resumption_rate` | Is "continue later" real? | projects with a ≥24h gap between consecutive events that later reach stage 7 |
| H5 `cost_per_completed_episode` | What does one delivered episode cost? | `SUM(model_calls.cost_micros)` per project / completed episodes |
| H6 `cost_per_abandoned_project` | What do we spend on projects that die? | same, over projects whose max stage < 7 and idle 14d |

H4 measures a promise made verbatim in PRODUCT.md's primary job statement
("review, and continue later"). H5/H6 need no new events — `cost_micros` is
already on `model_calls`
([observability.py:2156](../src/thesisound/observability.py#L2156)) and joins on
`project_id`.

H6 is the one that funds prioritisation arguments: it converts "the corpus
stage fails a lot" into a currency figure.

---

## 7. Implementation

Ten steps, in order. Each is independently reviewable; do not batch them into
one commit.

### Step 1 — `src/thesisound/product_metrics/events.py`

The `ProductEvent` StrEnum (all 22 names from §5) plus one pydantic payload
model per event, and a `PAYLOAD_MODELS: dict[ProductEvent, type[BaseModel]]`
registry mapping each member to its model.

No I/O in this file. It is the vocabulary and nothing else.

### Step 2 — `src/thesisound/product_metrics/store.py`

`ProductEventStore`, modelled directly on `ObservabilityLedger`:

```sql
CREATE TABLE IF NOT EXISTS product_events(
    event_id        TEXT PRIMARY KEY,
    occurred_at     TEXT NOT NULL,
    name            TEXT NOT NULL,
    user_id         INTEGER,
    anon_id         TEXT,
    project_id      TEXT,
    session_id      TEXT,
    environment     TEXT NOT NULL,
    is_synthetic    INTEGER NOT NULL DEFAULT 0,
    event_version   INTEGER NOT NULL DEFAULT 1,
    properties_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_product_events_name_time
    ON product_events(name, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_product_events_user_time
    ON product_events(user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_product_events_project
    ON product_events(project_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_product_events_real
    ON product_events(occurred_at DESC) WHERE is_synthetic = 0;

CREATE TABLE IF NOT EXISTS product_metric_daily(
    metric_key      TEXT NOT NULL,
    day             TEXT NOT NULL,
    dimension_json  TEXT NOT NULL DEFAULT '{}',
    value           REAL NOT NULL,
    numerator       REAL,
    denominator     REAL,
    computed_at     TEXT NOT NULL,
    PRIMARY KEY (metric_key, day, dimension_json)
);
```

Register as `_SCHEMA_V4_PRODUCT_EVENTS` in the existing `_MIGRATIONS` tuple
(D11). `anon_id` exists so pre-login events (`auth.code_requested`) are still
attributable; stitch it to `user_id` on successful auth.

`product_metric_daily` is intentionally narrow (key/day/dimension/value) so
**adding a metric never requires a schema migration** — a new metric is a new
row in the catalogue, nothing more. This is a deliberate anti-drift choice.

### Step 3 — `src/thesisound/product_metrics/emit.py`

```python
def emit(
    event: ProductEvent,
    payload: BaseModel,
    *,
    user_id: int | None = None,
    project_id: UUID | None = None,
    session_id: str | None = None,
) -> None:
```

Validates the payload against `PAYLOAD_MODELS[event]`, stamps `environment` and
`is_synthetic` from settings, resolves `user_id` from `project_members` when not
passed (D5), writes one row. Wraps everything in `try/except Exception`,
counting failures (D10). This function is the only write path.

### Step 4 — Wire choke point 1: `transition()`

In [pipeline.py](../src/thesisound/pipeline.py#L99), *alongside* (never
replacing) the existing `tracing.event` call. Map old/new state to funnel stage
via the D9 mapping and emit `project.stage_entered` only when the **stage**
changes, plus `stage_failed` / `recovered` / `transition_rejected`.

`transition()` currently takes only `(project, target)` — no user context. Add
an optional `actor_user_id: int | None = None` keyword; web callers pass it, CLI
callers do not. Do **not** thread a request object into the domain layer.

### Step 5 — Wire choke point 2: auth

The eight `auth.*` / `user.registered` events in
[app.py](../src/thesisound/web/app.py#L532)`:475–592`. Emit `user.registered`
when `last_login_at IS NULL` before this login — that is the existing signal
for "first time," so no new column is needed.

Set `is_synthetic = true` whenever the test-OTP path
(`THESISOUND_ALLOW_TEST_OTP`, [PRODUCT.md](../PRODUCT.md#L64)) is used. The dev
account `09120000000` must never appear in production metrics.

### Step 6 — Wire choke point 3: gates and consumption

The twelve gate/consumption events, at the routes named in §5. Concretely:
`source_routes.py` (`corpus/confirm`, `sources/*/toggle`, `sources/*/delete`,
`workflow/rewind`), `script_routes.py` (`approve`, `review`), `audio_routes.py`
(`final.wav`, `final.mp3`), and `app.py` (`brief`).

### Step 7 — `src/thesisound/product_metrics/catalogue.py`

`MetricDefinition` dataclass + one instance per metric in §6 + the D9 stage
mapping as the single source of truth. Nothing else in the codebase re-lists
states or re-writes a metric's SQL.

### Step 8 — `src/thesisound/services/product_metrics_rollup.py`

Modelled on the existing
[`observability_rollup.py`](../src/thesisound/services/observability_rollup.py).
Iterates the catalogue, computes each metric for a date range, upserts into
`product_metric_daily`. Must be idempotent — rerunning for a day replaces that
day's rows exactly (D8).

Open the connection with `PRAGMA query_only=ON` for the read phase, as the
existing rollup does.

### Step 9 — CLI + one operator page

`thesisound metrics rollup --since YYYY-MM-DD` and `thesisound metrics show`.
One operator-mode page rendering the north star, the D1 funnel, and the E5–E7
gate block. Surface the `emit_failed` counter here (D10 corollary).

### Step 10 — Tests

Ordinary per-event tests, plus four **guard tests** that turn the invariants in
§4 into CI failures:

1. `test_every_event_has_payload_model` — enum members == `PAYLOAD_MODELS` keys.
2. `test_every_event_is_emitted_or_marked` — grep the source for each enum
   member; any member neither emitted nor marked `# raw-only` fails.
3. `test_no_pii_fields_in_payloads` — assert no payload model declares a field
   whose name matches `phone|password|otp|code|token|email|raw_input|content`.
4. `test_catalogue_sql_executes` — run every catalogue query against an empty
   schema; each must execute and return the declared shape. Catches a stale
   metric the day a column is renamed, not six months later.

Guard test 2 is the one that actually prevents drift over time: it makes
"someone added an event name and never wired it" a red build.

---

## 8. Verification

Ship criteria:

1. All guard tests green.
2. A scripted end-to-end run (register → project → brief → corpus → script →
   audio → download) produces exactly the expected event sequence, with
   `is_synthetic = 1` throughout.
3. Rollup run twice over the same range produces byte-identical
   `product_metric_daily` rows (idempotence, D8).
4. `tracing_enabled=false` — every product event still lands (this is the whole
   point of §1.4; test it explicitly).
5. Killing the metrics store mid-request (simulate by pointing it at a
   read-only path) leaves the user flow working and increments `emit_failed`.

---

## 9. What will read zero, and why that is expected

The `users` table has **0 rows** today. On the day this ships, B1–B5, C1–C4,
H1–H4 will all read zero or undefined, and that is correct behaviour, not a
bug. Do not "fix" it by backfilling from synthetic data (§1.5, and out of scope
per §2).

What *will* have signal immediately: D1–D5, E1–E8, G1–G4 for any real project
run, plus F3/H5/H6 which draw on ledger data that already exists.

Reviewing raw events during rollout does not need the operator page. Any SQLite
browser pointed at `ledger.sqlite3` will pick `product_events` up automatically
as an eighth table — e.g.:

```bash
uv run --with datasette datasette serve workspaces/_observability/ledger.sqlite3 --host 127.0.0.1 --port 8011
```

---

## 10. Sequencing against other work

- Independent of the SQLite→Postgres question. If that migration happens,
  `product_events` ports with the rest; the `WHERE is_synthetic = 0` partial
  index is Postgres-compatible as written.
- Independent of R10 (speaker B). No shared files.
- Steps 1–3 are a self-contained foundation and can merge before any
  instrumentation exists. Steps 4, 5, 6 are independent of each other and can
  land in any order or in parallel.
