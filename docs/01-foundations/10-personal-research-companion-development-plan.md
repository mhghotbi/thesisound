# 10. Personal Research Companion — Development Plan

Status: approved direction, implementation plan

## 1. Product decision

Thesisound is no longer being optimized as a general-purpose public podcast product. The primary product is a **personal, cumulative audio research companion for one owner**.

The job is not merely:

> turn a topic and some sources into a standalone podcast.

The new job is:

> help one person pursue a long-running research question across many sources and episodes, while preserving evidence quality, remembering what has already been covered, exposing unresolved questions and disagreements, and producing Persian audio that advances the research instead of restarting from zero.

This is a change in product context, not a rewrite of the research pipeline.

The existing evidence path remains the core asset:

```text
Research Brief
→ source discovery / upload
→ source triage and quality gates
→ document mapping
→ evidence extraction
→ claim reconciliation
→ coverage audit
→ Episode Plan
→ grounded Persian script
→ independent verification
→ audio generation and QA
```

The implementation must add a **persistent research layer above `Project`** and inject bounded context into selected stages. It must not weaken claim/evidence grounding.

---

## 2. Non-negotiable anti-drift rules

An implementation agent MUST treat these rules as product constraints, not suggestions.

### 2.1 Do not rewrite the evidence pipeline

Do not replace or bypass source confirmation, evidence extraction, claim reconciliation, coverage gating, script verification, or audio QA.

Personalization is allowed to influence:

- scope;
- pedagogical depth;
- terminology;
- search strategy;
- episode structure;
- what does not need to be re-explained;
- which unresolved questions deserve attention.

Personalization is **not** allowed to turn unsourced memory into evidence.

### 2.2 `Project` remains the execution unit

The current `Project` is episode-centric and has a linear state machine. Keep it that way.

Do not turn `Project` into a god object containing the owner's full profile, an entire research series, all prior episodes, and all historical sources.

Add a higher-level context model:

```text
PersonalProfile
       +
ResearchSeries → ResearchAxis
       +
SeriesKnowledgeState
       +
ResearchLens
       ↓
ResearchContextSnapshot
       ↓
Project → existing research/audio pipeline
```

A `Project` may reference a series/axis/context snapshot, but its existing lifecycle must remain independently executable.

### 2.3 Personal context is not a truth store

The system must distinguish:

- `covered`: the system has already explained a concept in an accepted episode;
- `user_marked_understood`: the owner explicitly says the concept is understood;
- `unresolved`: the research has not settled or adequately covered a question;
- `contested`: verified sources materially disagree.

Never infer that the owner has mastered a concept simply because an episode was generated.

Never store ideological assumptions, preferences, or prior model summaries as verified facts.

### 2.4 Research lenses must remain falsifiable

A lens such as:

- coloniality;
- dependency;
- infrastructural concentration;
- technological sovereignty;
- sociotechnical alternatives;

is a way to formulate questions and search for literature. It is not a conclusion.

The system must continue to seek serious counter-positions, competing explanations, qualifications, and terminology disputes.

Bad implementation:

> Prove that AI infrastructure is a new form of American colonialism.

Required implementation:

> Investigate whether and under what definitions AI infrastructure concentration is adequately explained by coloniality, dependency, monopoly, or geopolitical coercion; preserve competing accounts.

### 2.5 Do not hard-code the current decolonial-AI topic into the product

The current research series is a first real use case, not the global ontology of Thesisound.

Core schemas, prompts, and UI must also work later for Arendt, platform capitalism, sociology of technology, philosophy, literature, or another research line.

Topic-specific terms belong in `ResearchSeries` / `ResearchLens` data, not global system prompts.

### 2.6 Freeze public-product expansion

Until this plan is complete, do not spend product effort on:

- public onboarding optimization;
- generic novice personas;
- multi-user collaboration;
- social/sharing features;
- subscriptions or billing;
- public discovery feeds;
- marketing pages;
- generalized role/permission systems;
- polishing Simple Mode for hypothetical users.

Do not remove working auth or weaken deployment security merely because the product is personal. Existing development-only bypasses must remain development-only.

### 2.7 Preserve reproducibility

Once a Research Brief is confirmed, the personal/series context used to create it must be frozen in a `ResearchContextSnapshot`.

Later edits to profile, series, lens, or knowledge state must not silently rewrite the meaning of an already-confirmed project.

---

## 3. Target domain model

The exact persistence mechanism should follow the repository's existing storage abstractions. Do not invent an unrelated database stack.

### 3.1 `PersonalProfile`

One owner profile. Do not build multi-user profile infrastructure.

Minimum fields:

```text
profile_id
version
preferred_output_language
source_languages[]
disciplinary_background[]
technical_background[]
default_depth
default_duration_minutes
pedagogy_preferences[]
terminology_preferences[]
baseline_familiar_concepts[]
created_at
updated_at
```

Semantics:

- `disciplinary_background` and `technical_background` help decide assumed prerequisites.
- `baseline_familiar_concepts` means “normally do not explain from first principles,” not “this is true.”
- `pedagogy_preferences` may express preferences such as conceptual distinctions, argument reconstruction, or avoiding textbook-level introductions.
- Per-project values must be able to override profile defaults.

Do not add personality profiling, ideology labels, or inferred political preferences.

### 3.2 `ResearchSeries`

Represents a durable research programme spanning multiple projects.

Minimum fields:

```text
series_id
title
purpose
central_problem
scope_inclusions[]
scope_exclusions[]
status: active | paused | archived
created_at
updated_at
```

A series is not a source and cannot support a claim.

### 3.3 `ResearchAxis`

A bounded line of inquiry within a series.

Minimum fields:

```text
axis_id
series_id
title
central_question
scope_notes[]
order
status: planned | active | sufficiently_covered | parked
created_at
updated_at
```

Keep this flat for the first implementation. Do not add arbitrary tree nesting unless actual use demonstrates the need.

### 3.4 `SeriesKnowledgeState`

Persistent continuity for a series.

Use structured records, not one giant free-text summary.

Minimum components:

#### `ConceptCoverage`

```text
concept_key
preferred_label
status: introduced | covered | user_marked_understood | needs_deeper_treatment
first_project_id
latest_project_id
supporting_project_ids[]
notes
```

#### `UnresolvedQuestion`

```text
question_id
question
axis_id | null
status: open | partially_answered | parked | resolved_for_now
opened_by_project_id | null
updated_by_project_id | null
notes
```

#### `SourceHistoryRecord`

```text
source_fingerprint_or_id
canonical_title
project_ids[]
roles_seen[]
last_used_at
```

This is for deduplication and continuity. It does not make the source automatically valid evidence in a new project.

#### `ClaimHistoryReference`

```text
project_id
claim_id
claim_type
support_status
```

Store references to prior verified claims, not a flattened cross-series “truth database.” A new episode may use these references to avoid repetition or locate prior work, but a substantive new script claim must still satisfy the current pipeline's grounding contract.

#### `ResearchOpenLoop`

Use for explicit follow-up created by an accepted episode:

```text
loop_id
text
type: unresolved_question | source_gap | conceptual_gap | disagreement | follow_up_topic
axis_id | null
origin_project_id
status
```

### 3.5 `ResearchLens`

Initially keep this as series-level structured data rather than a standalone configurable plugin system.

Minimum fields:

```text
framing_questions[]
hypotheses_under_test[]
required_distinctions[]
counterposition_requirements[]
disallowed_presuppositions[]
```

Example for the current series:

```text
framing_questions:
- How does AI concentration create dependency across chips, compute, models, data, labor and platforms?

hypotheses_under_test:
- Coloniality may explain some forms of dependency better than ordinary monopoly analysis.

required_distinctions:
- colonialism vs coloniality
- monopoly vs dependency
- dependence vs coercive leverage
- state sovereignty vs community/data sovereignty

counterposition_requirements:
- include serious accounts that explain the same phenomena primarily through capitalism, monopoly, industrial organization, security competition, or state capacity.
```

### 3.6 `ResearchContextSnapshot`

Create an immutable snapshot when a project becomes context-bound.

Minimum fields:

```text
snapshot_id
project_id
profile_version
series_id | null
series_version | null
axis_id | null
knowledge_state_version | null
lens_version | null
serialized_context
created_at
```

The snapshot must contain only the bounded context needed by the project, not every historical artifact in the series.

---

## 4. Phase 0 — Reframe the product contract

### Goal

Make the new product direction explicit before code starts changing.

### Required changes

1. Update `PRODUCT.md`:
   - primary audience = owner / personal researcher;
   - product = personal cumulative audio research companion;
   - preserve evidence-grounded core promise;
   - mark public Simple Mode expansion as frozen/deprioritized;
   - explain that Operator capabilities are now first-class owner capabilities rather than a secondary admin product.
2. Update the relevant foundation docs, especially product scope, only where the existing wording conflicts with this direction.
3. Add this plan to the docs index.
4. Do not change runtime behavior in this phase.

### Acceptance criteria

- No active product document claims that the primary target is a broad student audience.
- The evidence/verification rules remain unchanged.
- Public/multi-user work is explicitly a non-goal for the current roadmap.

### Tests

No new behavior tests required. Existing test suite must remain unchanged and green.

---

## 5. Phase 1 — Add the persistent research-context domain

### Goal

Introduce the higher-level models without changing the current Project pipeline.

### Required changes

1. Inspect `src/thesisound/domain.py` and related domain modules.
2. Add the new persistent research-context schemas in a focused module such as:

```text
src/thesisound/research_context.py
```

Prefer a separate module over making `domain.py` substantially larger.

3. Implement:
   - `PersonalProfile`;
   - `ResearchSeries`;
   - `ResearchAxis`;
   - `SeriesKnowledgeState` and its structured child records;
   - `ResearchLens`;
   - `ResearchContextSnapshot`.
4. Use existing project storage patterns for persistence.
5. Add version fields needed to construct reproducible snapshots.
6. Add only optional references to existing `Project` if required:

```text
series_id: UUID | None
axis_id: UUID | None
context_snapshot_id: UUID | None
```

Do not make old projects invalid.

### Compatibility requirement

A legacy project with no profile/series/context reference must still run exactly as before.

### Acceptance criteria

- Create/read/update one owner profile.
- Create/read/update/archive a research series.
- Add/reorder/status-update axes.
- Read/write a structured knowledge state.
- Existing project serialization/deserialization still works.
- No research prompt has changed yet.

### Tests

Add tests for:

- Pydantic validation;
- persistence round-trip;
- version increment semantics;
- legacy project compatibility;
- rejecting an axis that references a nonexistent series if the persistence layer can enforce it;
- snapshot immutability.

### Do not do

- no generic user/profile table redesign;
- no embeddings/vector memory;
- no automatic concept extraction yet;
- no UI redesign yet.

---

## 6. Phase 2 — Create a personal profile and series workflow

### Goal

Make the higher-level context usable before touching generation quality.

### Required behavior

Provide owner-facing operations, initially through the simplest existing interface (CLI or current web app), for:

1. viewing/editing `PersonalProfile`;
2. creating a `ResearchSeries`;
3. creating and ordering `ResearchAxis` records;
4. creating a new `Project` linked to a series and optionally to an axis;
5. creating a standalone legacy-style project with no series.

### Initial owner profile

Seed no ideological or content-specific assumptions in code. The owner may enter their actual background and preferences through data/configuration.

### Initial real series

The current decolonial-AI work may be entered as the first series, but it must be normal application data. Suggested title:

```text
AI, Coloniality, Dependency & Technological Sovereignty
```

The existing `research/decolonial-ai/` files remain research artifacts, not automatic verified context.

### Acceptance criteria

- A project can visibly show its parent series/axis.
- A standalone project still behaves normally.
- Deleting/archive operations cannot orphan completed project provenance; prefer archive over destructive delete.
- No generated claim can cite profile or series records as evidence.

### Tests

- create series → axis → project linkage;
- standalone project path;
- archive series with historical projects;
- invalid ID references;
- serialized API/UI payload compatibility.

---

## 7. Phase 3 — Context-aware Research Brief

### Goal

Use personal and cumulative context first at the safest stage: scoping.

### Why start here

`01_research_brief.md` already accepts audience and prior knowledge. This is the natural place to improve personalization without contaminating evidence.

### Required implementation

Build a deterministic `ResearchContextCompiler` that receives:

```text
PersonalProfile
ResearchSeries | null
ResearchAxis | null
SeriesKnowledgeState | null
ResearchLens | null
raw project input
```

and produces a bounded `ResearchContextSnapshot` payload containing only fields relevant to brief creation.

Extend the Research Brief prompt input with sections such as:

```text
<LEARNER_CONTEXT>
...</LEARNER_CONTEXT>

<SERIES_CONTEXT>
...</SERIES_CONTEXT>

<CONTINUITY_CONTEXT>
...</CONTINUITY_CONTEXT>
```

Rules for the prompt:

- do not treat prior coverage as evidence;
- avoid reintroducing baseline concepts unless needed for this episode;
- preserve the project's actual user input over defaults;
- use the axis to narrow scope;
- use unresolved questions as possible subquestions only when relevant;
- a lens may shape questions but may not pre-answer them.

### Snapshot timing

Recommended rule:

- draft project may refresh against latest profile/series state;
- when the Research Brief is explicitly confirmed, freeze the `ResearchContextSnapshot` for that project;
- changing profile/series later does not mutate the confirmed brief;
- explicit rewind to Brief may opt into a fresh snapshot and must invalidate downstream artifacts using existing rewind semantics.

### Acceptance criteria

Given the same raw input:

- an advanced profile receives less introductory scoping than an introductory profile;
- a project within an axis inherits relevant scope without copying the whole series;
- unresolved questions can influence subquestions;
- the brief does not assert the series hypothesis as fact;
- a standalone project remains unchanged except for optional owner defaults.

### Tests

Create fixture cases for:

1. advanced vs introductory profile;
2. series-linked vs standalone project;
3. lens containing a strong hypothesis;
4. prior concept marked covered;
5. context change after brief confirmation;
6. rewind-to-brief and snapshot refresh.

Prompt regression test: topic-specific decolonial terms must appear only when supplied through series/lens input, never from global prompt text.

---

## 8. Phase 4 — Build cumulative knowledge state safely

### Goal

Stop every episode from behaving as if it is episode one.

### Critical semantic rule

The system may automatically mark something as `covered`; it may not automatically mark it `user_marked_understood`.

### Update trigger

Do **not** update persistent knowledge state when a draft script is merely generated.

Update only from an accepted/finalized project. Prefer the existing `COMPLETE` state plus an explicit owner acceptance event if the product already distinguishes completion from acceptance. If no such event exists, add a minimal explicit “accept episode into series history” action.

### Knowledge update compiler

Create a deterministic or tightly constrained stage that proposes updates from verified project artifacts:

Inputs:

- confirmed Research Brief;
- verified claim ledger references;
- accepted Episode Plan;
- verified Script;
- follow-up topics;
- disagreement graph / coverage gaps when available.

Outputs:

- concepts newly introduced/covered;
- unresolved questions opened/updated;
- source-history references;
- claim-history references;
- follow-up open loops.

Human-editable updates are acceptable. Provenance must be retained.

### Important prohibition

Do not copy prose from an episode summary into `SeriesKnowledgeState` and later feed it to the script writer as factual evidence.

### Acceptance criteria

After accepting episode 1:

- episode 2 knows which concepts have been covered;
- source discovery can know a source was previously used;
- unresolved questions remain visible;
- prior claims retain references back to their original project/evidence;
- deleting or editing a knowledge-state note does not alter historical project artifacts.

### Tests

- failed/unverified project does not update knowledge state;
- COMPLETE but not accepted does not update if explicit acceptance is implemented;
- accepted episode produces expected coverage/open loops;
- duplicate concept normalization is conservative;
- prior claim references never satisfy current `EvidenceItem` requirements by themselves.

---

## 9. Phase 5 — Propagate continuity through search, planning, and script

### Goal

Use the knowledge state where it creates real value, without passing an enormous memory blob through every model call.

### 9.1 Query Planner

Extend `02_query_planner.md` inputs with bounded history:

- previously used sources relevant to the same axis;
- unresolved source gaps;
- concepts/positions already well covered;
- lens counter-position requirements.

Behavior:

- avoid redundant rediscovery unless a source needs reconsideration;
- search targeted gaps;
- still allow canonical sources to recur when necessary;
- do not exclude a source merely because it appeared before;
- distinguish “already encountered” from “already adequate for this project's evidence.”

### 9.2 Source triage

Show prior-use metadata as context only.

A source previously accepted in another project still goes through the current project's access/quality/evidence requirements.

### 9.3 Episode Plan

Extend planning context with:

- concepts already covered;
- user-marked understood concepts;
- current axis position;
- unresolved questions;
- previous episode outcomes relevant to continuity.

Planning behavior:

- do not spend substantial duration re-explaining understood prerequisites;
- allow concise reminders when required for argument continuity;
- explicitly advance at least one current research question when the corpus supports it;
- preserve disagreements even if an earlier episode favored one position.

### 9.4 Persian script

Current grounding rules must remain unchanged.

Continuity context may tell the writer:

- a concept can be referenced without full redefinition;
- preferred established terminology;
- immediately previous accepted episode tail/outcome where relevant.

Continuity context may **not** supply new factual claims.

### Acceptance criteria

- episode 2 is measurably less repetitive than episode 1 in a controlled fixture;
- no unsupported historical statement enters the script from knowledge state;
- source search targets real gaps rather than repeating the orientation round;
- standalone behavior remains available.

### Tests

Add integration fixtures for a two-episode series and assert:

- search query differences;
- plan prerequisite behavior;
- no invalid claim IDs;
- no knowledge-state text appears as evidence IDs;
- verification still rejects unsupported content.

---

## 10. Phase 6 — Add Research Lens with explicit anti-confirmation-bias controls

### Goal

Allow the owner to pursue a serious theoretical perspective without turning Thesisound into an ideological summarizer.

### Required implementation

Expose `ResearchLens` at series level and optionally allow axis-level additions.

Before query planning, derive:

```text
framing questions
hypotheses to test
required conceptual distinctions
required counter-position searches
```

### Query requirement

When a lens includes a substantive hypothesis, Query Planner must allocate at least one appropriate search family to:

- counter-position;
- alternative causal explanation;
- terminology/concept criticism;

unless the Research Brief explicitly does not require adjudicating that hypothesis. The model must state why if it omits the counter-position role.

### Claim requirement

Do not create a special “lens claim.” All substantive claims still enter through ordinary evidence extraction and reconciliation.

### UI requirement

Show the lens as:

> questions/assumptions being tested

not:

> truths the system believes.

### Acceptance criteria

For a fixture lens asserting a possible colonial interpretation:

- search includes serious adjacent explanations such as monopoly, political economy, security/geopolitics, or dependency where relevant;
- the Research Brief uses conditional language;
- Episode Plan can conclude that evidence supports, qualifies, rejects, or leaves the framing unresolved;
- no hard-coded current-topic vocabulary exists in generic prompts.

### Tests

Prompt/eval fixtures must explicitly test confirmation-bias failure modes.

---

## 11. Phase 7 — Replace generic podcast modes with research intents

### Goal

Turn the output from “generic educational podcast” into an audio research companion.

### Domain addition

Add an `EpisodeIntent` enum. Initial values:

```text
concept_explanation
literature_map
argument_reconstruction
debate
source_comparison
technical_social_deep_dive
axis_synthesis
```

Do not create a different pipeline per intent.

`EpisodeIntent` changes planning priorities and speaker dynamics only. Evidence rules remain common.

### Intent semantics

#### `concept_explanation`

Goal: build a precise concept and its boundaries/prerequisites.

#### `literature_map`

Goal: identify schools, concepts, anchor works, overlaps, disagreements, and gaps. Avoid fake comprehensiveness.

#### `argument_reconstruction`

Goal: reconstruct one author's/work's argument, premises, distinctions, objections, and implications.

#### `debate`

Goal: preserve two or more substantive positions rather than forcing synthesis.

#### `source_comparison`

Goal: compare selected sources on explicitly shared questions.

#### `technical_social_deep_dive`

Goal: connect technical mechanisms to social/political consequences without allowing either side to become hand-waving.

#### `axis_synthesis`

Goal: synthesize accumulated verified work in one research axis, identify what is established for the series, what remains contested, and what should come next. Historical claims still require traceable references to original verified project evidence or refreshed evidence.

### Prompt changes

Update `06_episode_plan.md` to accept `EpisodeIntent` and define plan constraints per intent.

Update `07_persian_script.md` only enough to respect the selected plan dynamic. Do not fork seven large writer prompts unless evaluation proves necessary.

### Acceptance criteria

The same claim ledger produces meaningfully different plans for `literature_map` vs `debate`, while both remain fully claim-bound.

### Tests

- one golden planning fixture per intent;
- claim-set validation unchanged;
- duration budget unchanged;
- disagreement preservation especially for `debate`;
- no prose generation inside the planner.

---

## 12. Phase 8 — Owner-first interface

### Goal

Make the persistent research model visible and useful to the owner.

Do this after the domain and pipeline semantics are stable. Do not lead with UI.

### Primary information architecture

Recommended owner flow:

```text
Research Series
  → Series overview
      → Axes
      → Open questions
      → Covered concepts
      → Sources used
      → Previous episodes
  → Start next episode
      → choose axis
      → choose EpisodeIntent
      → add current question/focus
      → Research Brief
      → existing source/evidence/plan/script/audio workflow
```

### Required screens/surfaces

#### A. Series list

Show:

- title;
- central problem;
- active axis;
- number of accepted episodes;
- open-loop count;
- last activity.

#### B. Series overview

Show:

- central problem and scope;
- research lens clearly labeled as questions under test;
- axes and status;
- unresolved questions;
- covered/user-understood concepts;
- source history;
- accepted episodes.

#### C. Personal profile/settings

Edit only fields that genuinely affect research/audio behavior.

#### D. New episode from series

Require minimal inputs:

- axis or no axis;
- episode intent;
- raw focus/question;
- optional duration override.

Everything else should default from profile/series.

#### E. Knowledge-state review

Allow owner to:

- mark a concept understood;
- mark it as needing deeper treatment;
- reopen an unresolved question;
- park an open loop;
- inspect provenance back to projects.

### Operator behavior

Do not throw away existing technical/operator surfaces. The owner is also the operator.

Prefer an “inspect technical details” affordance over maintaining two increasingly divergent products.

### Auth/security

Do not remove authentication unless the deployment architecture makes the application genuinely private and another access-control boundary replaces it.

Do not permit `THESISOUND_ALLOW_TEST_OTP` in production.

### Design constraints

Preserve existing design direction:

- research/reading-tool character;
- RTL-first Persian;
- no SaaS dashboard decoration;
- no fake progress;
- dense technical details only where they aid owner decisions.

### Acceptance criteria

The owner can start from a series and create the next episode without re-entering background, scope, known concepts, or prior research manually.

---

## 13. Phase 9 — Evaluation, migration, and cleanup

### Goal

Prove that cumulative personalization improves research utility without degrading epistemic quality.

### 13.1 Backward compatibility

Existing projects must remain readable and rerunnable.

Options:

- leave old projects standalone; preferred first choice;
- optionally provide a manual “attach to series” operation.

Do not auto-assign historical projects to a series based on model inference.

### 13.2 Add series-level evaluation fixtures

Existing golden/eval infrastructure should gain multi-episode cases.

Minimum evaluation scenario:

```text
Series: one topic
Episode 1: orientation / concept map
Episode 2: targeted deep dive
Episode 3: competing positions or synthesis
```

Measure at least:

- repeated explanatory content across episodes;
- unsupported claims introduced from memory/context;
- coverage of open loops;
- source rediscovery redundancy;
- preservation of disagreement;
- correct use of prior terminology;
- continuity quality by human review.

### 13.3 Hard release gates

The feature is not complete if any of these occur:

1. prior knowledge state can satisfy a new claim without evidence;
2. changing a profile silently changes a confirmed project's meaning;
3. research lens causes counter-position search to disappear;
4. accepted-episode continuity creates fabricated “what we established” statements;
5. old standalone projects stop working;
6. multi-episode output becomes less verifiable than standalone output.

### 13.4 Cleanup only after real use

After multiple real series runs:

- remove/deprecate unused public-product UI only with evidence that it is not needed;
- simplify duplicate Simple/Operator surfaces;
- delete dead code only after callers/tests confirm it is dead;
- update `README.md`, `STATUS.md`, product docs, and operational SOP to match actual behavior.

Do not perform speculative cleanup in earlier phases.

---

## 14. Implementation order and dependencies

Execute in this order:

```text
P0 Product contract
 ↓
P1 Research-context domain
 ↓
P2 Profile + Series workflow
 ↓
P3 Context-aware Research Brief
 ↓
P4 Safe cumulative Knowledge State
 ↓
P5 Context propagation to Search / Plan / Script
 ↓
P6 Research Lens + anti-bias controls
 ↓
P7 EpisodeIntent modes
 ↓
P8 Owner-first UI
 ↓
P9 Multi-episode evaluation + cleanup
```

Do not merge P8 ahead of the domain semantics. A polished UI on an unstable memory model will create rework and hide conceptual mistakes.

---

## 15. Agent execution protocol

Every implementation agent working from this plan must follow this protocol.

### Before each phase

1. Read:
   - `PRODUCT.md`;
   - `DESIGN.md` if UI is touched;
   - `STATUS.md`;
   - this plan;
   - the relevant foundation/pipeline docs;
   - current domain model and affected prompts/tests.
2. Inspect actual call sites before modifying schemas.
3. State the phase's acceptance criteria in its working notes.

### During implementation

- Implement one phase at a time.
- Prefer additive, backwards-compatible changes.
- Reuse existing model execution, persistence, invalidation, observability and UI patterns.
- Do not introduce a new framework or datastore without a demonstrated blocker.
- Do not refactor unrelated code “while here.”
- Do not change model routing/cost settings unless the phase specifically requires it.
- Do not broaden schemas for hypothetical future users.
- Topic-specific context must remain data, never generic prompt text.
- Every new model-generated artifact needs an explicit grounding/provenance story.

### Before completing a phase

1. Run focused tests for the changed area.
2. Run the full existing test suite if practical in the environment.
3. Run formatting/type/static checks used by the repository.
4. Confirm legacy standalone project behavior.
5. Update relevant docs/status only to describe behavior actually implemented.
6. Report:
   - changed files;
   - acceptance criteria passed/failed;
   - tests run;
   - migrations/data implications;
   - any intentional deferrals.

### Stop conditions

Stop and surface the issue rather than improvising if implementation would require:

- weakening evidence traceability;
- treating memory as source evidence;
- changing the core Project state machine solely to accommodate series context;
- silently invalidating historical projects;
- production auth weakening;
- embedding a particular political/theoretical conclusion in generic prompts.

---

## 16. File-level guidance

Known likely touchpoints; verify current call sites before editing.

### Product/docs

```text
PRODUCT.md
docs/README.md
docs/01-foundations/01-product-scope.md
docs/01-foundations/02-architecture.md
docs/01-foundations/03-agent-workflow.md
docs/01-foundations/10-personal-research-companion-development-plan.md
STATUS.md
```

### Domain/runtime

```text
src/thesisound/domain.py
src/thesisound/research_context.py        # recommended new focused module
```

Locate and reuse the current persistence/store abstraction rather than assuming a new file name.

### Prompts

```text
prompts/01_research_brief.md
prompts/02_query_planner.md
prompts/03_source_triage.md               # only if prior-source metadata is surfaced
prompts/06_episode_plan.md
prompts/07_persian_script.md
prompts/08_script_verifier.md             # only if continuity-specific checks are required
```

Do not modify evidence extraction or claim reconciliation prompts unless a concrete test demonstrates a need. The research context should not affect what a source actually says.

### Tests

Use current test organization. Add focused tests for research context plus multi-episode fixtures; do not create a parallel test framework.

---

## 17. Explicit non-goals for this roadmap

Do not build these as part of the personalization work:

- social podcast publishing;
- RSS hosting;
- public user acquisition flows;
- recommendation feeds;
- multi-user teams;
- collaboration permissions;
- generalized knowledge graph;
- autonomous infinite research loops;
- automatic belief/profile inference from listening behavior;
- vector memory merely because “memory” is needed;
- a chatbot bolted onto the project without a research job;
- a separate pipeline for every episode mode;
- fine-tuning models on the owner's ideology or writing style;
- replacing source evidence with RAG over prior episode summaries.

---

## 18. Definition of done

This roadmap is complete when the following workflow is real, tested, and usable:

```text
1. Owner has one persistent learning/research profile.
2. Owner creates a durable Research Series and several Research Axes.
3. Owner starts an episode inside an axis with a specific EpisodeIntent.
4. Thesisound creates a bounded Research Brief using profile + series + prior coverage.
5. Search targets new evidence and open gaps while preserving counter-positions.
6. Normal source/evidence/claim/coverage gates run unchanged.
7. Episode Plan assumes prior concepts appropriately and advances the research line.
8. Script remains fully evidence-bound while avoiding unnecessary repetition.
9. Verified audio is accepted into the series.
10. SeriesKnowledgeState updates with provenance: covered concepts, source history, claim refs, disagreements and open questions.
11. The next episode continues from that state rather than starting over.
12. At no point can personal memory, a theoretical lens, or an old summary masquerade as current evidence.
```

The success criterion is not “more personalized audio.”

The success criterion is:

> **Thesisound can sustain a long-running, evidence-grounded personal research programme in audio form, with cumulative understanding and explicit open questions, without sacrificing the source traceability that made the original pipeline valuable.**
