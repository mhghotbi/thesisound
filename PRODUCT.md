# Thesisound Product Context

Revised 2026-08-19 per [`docs/01-foundations/10-personal-learning-companion-development-plan.md`](docs/01-foundations/10-personal-learning-companion-development-plan.md) (revision 3.1). Sections marked *planned* describe behaviour that plan introduces; everything else is current.

## Product

Thesisound is a **personal learning companion for one owner**. It turns a source the owner has chosen into evidence-grounded Persian lessons — audio or text — so the owner can learn the source without reading all of it, or get a focused question about the source answered.

The product is not a generic AI audio generator and not an educational platform. Its core promise is that every statement in a lesson is traceable to the source, that the system never pads or invents when the source is thin, and that nothing important in the source is silently lost.

## Primary user

The owner: one Persian-speaking reader with an academic background who works through a personal course of humanities and social-science sources one project at a time. The owner is also the operator: technical detail is available on demand, not hidden behind a second product. There is no separate end-user product, no student audience and no multi-user offering in scope.

## Primary job

> Take one source I chose and turn it — completely, at the compression I want, in episodes of the length I want — into Persian lessons I can trust, in audio or text; or answer one focused question I have about it.

## Two lesson intents (one pipeline)

- **`focused_question`** — a Research Brief with a central question and 2–5 learning objectives, one episode. This is today's behaviour and stays unchanged.
- **`source_coverage`** *(planned, doc 10 P1–P3)* — the whole source or chosen chapters; the owner sets compression (`concise | standard | full`), episode length (a packing reference such as 20 minutes, not a cap on the project), delivery (`audio | text | both`) and optional known concepts to skip. The system builds a chapter-first concept map, extracts evidence over the in-scope concepts, packs them into parts no longer than the episode length and close to it, and produces one verified lesson per part with a completion report.

## Product modes

The web UI has one mode. Operator details (run attempts, warnings, artifacts, parsers, model usage, logs, recovery) live behind an "inspect technical details" affordance; the state machine is single and server-driven. The former "Simple Mode" surfaces remain in the code but are frozen: no further work targets hypothetical non-technical users.

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

Quizzes, self-check questions, transcripts as a product, mastery scoring, spaced repetition, learner analytics; multi-user or public product, billing, sharing; a generalized cross-source knowledge graph; vector memory; a chatbot; a separate pipeline per intent.

## Current implementation slice

Implemented today: OTP authentication; project list and creation; Research Brief confirmation; source upload, URL capture and Gemini search; corpus confirmation; document map; evidence extraction and claim ledger; coverage audit and duration gate; Episode Plan approval; grounded Persian dialogue script with deterministic checks and independent verification; TTS, ASR QA and assembly; observability ledger. All of this is the `focused_question` path.

Planned per doc 10: P0 this contract → P1 concept map → P2 evidence completeness (prompt audit) → P3 `source_coverage` end to end → P4 text delivery → P5 owner UI consolidation → P6 evaluation on one real source.

The development account is:

- phone: `09120000000`
- OTP: `999999`

This credential exists only when `THESISOUND_ALLOW_TEST_OTP=true` outside production.
