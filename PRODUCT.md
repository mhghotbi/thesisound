# Product

<!-- impeccable:product-schema 1 -->

The user-facing product is **«مقال»**; `Thesisound` is the repository and codebase name.

Revised 2026-08-22. Four facts were confirmed with the owner on that date and are marked *(confirmed 2026-08-22)* where they appear: the interface is one mode, «مقال» is a binding brand, the product is going to the hosted web with real accounts for other people, and the full workflow must be completable on a phone. Everything else is carried forward from the 2026-08-19 revision per [`docs/01-foundations/10-personal-learning-companion-development-plan.md`](docs/01-foundations/10-personal-learning-companion-development-plan.md) (revision 3.1). Sections marked *planned* describe behaviour that plan introduces; everything else is current.

## Platform

web

## Users

**The owner.** One Persian-speaking reader with an academic background who works through a personal course of humanities and social-science sources, one project at a time. The owner is also the operator: technical detail is available on demand, not hidden behind a second product.

**Other account holders** *(confirmed 2026-08-22)*. The product is going to the hosted web and other people will hold accounts. The account store, the `operator` / `member` role split and project membership in [`src/thesisound/accounts.py`](src/thesisound/accounts.py) are product truth, not scaffolding, and project isolation is a real requirement rather than a defensive default.

What the non-owner experience actually is — whether other holders run their own projects, are invited into someone else's, or see a reduced surface — **is not decided**. Do not design for a shape nobody has chosen; ask before building it.

## Product Purpose

«مقال» turns a source the user has chosen into evidence-grounded Persian lessons — audio or text — so they can learn the source without reading all of it, or get a focused question about the source answered.

It is not a generic AI audio generator and not an educational platform. Its core promise is that every statement in a lesson is traceable to the source, that the system never pads or invents when the source is thin, and that nothing important in the source is silently lost.

The primary job, in the user's words:

> Take one source I chose and turn it — completely, at the compression I want, in episodes of the length I want — into Persian lessons I can trust, in audio or text; or answer one focused question I have about it.

## Positioning

Refusal is built into the pipeline, and that is the part a neighbouring product could not truthfully copy.

A claim ledger ties every substantive statement to evidence and a source location. A coverage audit and a supported-duration gate block script generation when the corpus cannot carry the requested episode, instead of padding it. The finished script is verified independently of the model that wrote it. Generated audio is transcribed back and compared expected-against-heard before assembly, and failing spans are regenerated rather than shipped.

Products in the same category generate first and disclaim afterwards. This one declines to generate.

## Operating Context

The interface is Persian and right-to-left by default — not an English layout with a translation layer over it.

Today it runs locally: Python 3.12+, `uv`, FFmpeg on `PATH`, and Gemini keys for the model, Search, URL Context, TTS and ASR. It is destined for the hosted web *(confirmed 2026-08-22)*, which makes authentication, project isolation and remote-network behaviour real product concerns rather than local conveniences.

Desktop and mobile are both product surfaces, and the **entire** workflow must be completable on a phone *(confirmed 2026-08-22)*: creating a project, confirming the Research Brief, uploading or discovering sources, confirming the corpus, approving the Episode Plan and reviewing the script. Mobile is not a monitoring view for work done elsewhere.

The work itself is long-running and stateful. A project moves through many stages over minutes to hours, the user leaves and returns, and the server owns the state machine.

## Capabilities and Constraints

The two lesson intents below are the functional core; the non-negotiable rules further down constrain every stage of the pipeline.

- **One UI mode** *(confirmed 2026-08-22)*. Operator detail — run attempts, warnings, artifacts, parsers, model usage, logs, recovery — lives behind an "inspect technical details" affordance inside that single mode. The `simple` / `operator` switch still shipping in the session state, the `data-mode` attribute and the `.simple-only` / `.operator-only` classes are technical debt to consolidate, not a product capability. No further work targets hypothetical non-technical users.
- **Stack**: FastAPI with server-rendered Jinja templates, one hand-written stylesheet and vanilla JavaScript. No frontend framework and no build step.
- **Themes**: four named colour themes ship (cobalt, wood, olive, slate), user-selectable and persisted client-side. Light is the only colour scheme; there is no dark mode. DESIGN.md owns the values.
- **Authentication stays.** The test OTP is development-only and must be impossible to enable in production.

## Brand Commitments

- The brand is **«مقال»** *(confirmed 2026-08-22 as binding)*. `Thesisound` names the repository, not the product. Design work may not replace or dilute the brand.
- Assets: the logo mark and full lockup live in [`src/thesisound/web/static/`](src/thesisound/web/static/), including reverse variants per theme. The client-side theme preference key is `maqaal-theme`.
- Voice: Persian-first, calm and precise. The product does not advertise "AI" as decoration.

## Evidence on Hand

- **Real project runs**: [`workspaces/`](workspaces/) holds twenty project workspaces keyed by project UUID, each with `project.json`, `sources/`, `model-runs/`, `runs/`, `script/` and `episode/`. This filesystem store is the trustworthy record of what the system has actually produced; prefer it over the SQLite observability ledger when citing a real run.
- **Audits**: MVP readiness audits (2026-08-12, 2026-08-13) and the pipeline audit (2026-08-11) in [`docs/`](docs/).
- **A real end-to-end pass**: checkpoint C-D reached a genuine `COMPLETE` on 2026-08-22.
- **Absences future work must not fabricate**: there is no user research, no testimonial, no benchmark against another tool, no production deployment and no usage data beyond the owner's own runs.

## Product Principles

1. **Refusal beats padding.** When the source cannot support the requested output, the system stops and says why. Every blocking gate is a feature, and no interface may dress a block up as a failure or hide it.
2. **Traceability is the product.** A statement that cannot be tied to evidence and a source location has no right to appear.
3. **Computed, never authored.** Progress, coverage, duration and completeness are measured from real stages and units. The interface never invents a percentage or a reassuring state.
4. **One server-driven state machine.** The server owns truth; the interface reflects it rather than maintaining a parallel client-side story.
5. **Depth on demand, not a second product.** The same person is learner and operator, so technical detail is one affordance away — never a separate mode, audience or app.

## Accessibility & Inclusion

- Persian RTL is the document's default direction, not a localisation layer.
- WCAG AA contrast is the target, and colour is never the only carrier of state.
- Interactive targets are at least 44px in their smallest dimension. This is binding now that the full workflow must be completable on a phone.
- OTP entry is keyboard-operable; labels are never placeholders; form errors sit beside their field; nothing depends on hover.
- Identifiers, filenames, timestamps, costs, model names, phone numbers, OTP values, hashes and URLs use bidi isolation and `dir="ltr"` where appropriate.

## Two lesson intents (one pipeline)

- **`focused_question`** — a Research Brief with a central question and 2–5 learning objectives, one episode. This is today's behaviour and stays unchanged.
- **`source_coverage`** *(planned, doc 10 P1–P3)* — the whole source or chosen chapters; the owner sets compression (`concise | standard | full`), episode length (a packing reference such as 20 minutes, not a cap on the project), delivery (`audio | text | both`) and optional known concepts to skip. The system builds a chapter-first concept map, extracts evidence over the in-scope concepts, packs them into parts no longer than the episode length and close to it, and produces one verified lesson per part with a completion report.

## Non-negotiable product rules

- The Research Brief (or, for `source_coverage`, the derived brief and scope) is explicitly confirmed.
- The corpus is explicitly confirmed.
- A blocking source-quality failure cannot be silently accepted.
- For `focused_question`, insufficient coverage blocks script generation. For `source_coverage` *(planned)*, coverage is measured per concept cell and reported; a cell with no evidence is carried into the report, never hidden.
- Progress is based on real stages or known units, not invented percentages; `graph_backed`, "not covered", "omitted by compression" and part minutes vs target are computed, never authored.
- Editing upstream inputs (including scope, compression or episode length after planning) marks affected downstream outputs stale.
- Every substantive statement remains traceable to evidence and source location; definitions, distinctions, objections, responses and examples are audited claims like any other *(planned, extraction 2.0)*.
- Nothing but current-project evidence supports a claim: known concepts, concept maps and course notes are scoping hints, never evidence.
- No memory is carried between projects; caches are content-addressed and describe sources, not the learner (cross-project memory is a deferred future phase, doc 11).
- The owner's current course vocabulary is data, never part of a global prompt.
- Test OTP is development-only and must be impossible to enable in production. Authentication stays.

## Explicit non-goals

Quizzes, self-check questions, transcripts as a product, mastery scoring, spaced repetition, learner analytics; billing and sharing; a generalized cross-source knowledge graph; vector memory; a chatbot; a separate pipeline per intent.

Multi-user was a non-goal until 2026-08-22 and no longer is. That change covers accounts and project isolation only: billing and sharing were not part of it and stay out of scope until stated otherwise.

## Current implementation slice

Implemented today: OTP authentication; project list and creation; Research Brief confirmation; source upload, URL capture and Gemini search; corpus confirmation; document map; evidence extraction and claim ledger; coverage audit and duration gate; Episode Plan approval; grounded Persian dialogue script with deterministic checks and independent verification; TTS, ASR QA and assembly; observability ledger. All of this is the `focused_question` path.

Planned per doc 10: P0 this contract → P1 concept map → P2 evidence completeness (prompt audit) → P3 `source_coverage` end to end → P4 text delivery → P5 owner UI consolidation → P6 evaluation on one real source.

The development account is:

- phone: `09120000000`
- OTP: `999999`

This credential exists only when `THESISOUND_ALLOW_TEST_OTP=true` outside production.
