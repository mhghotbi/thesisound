# 11. Course Memory Across Projects — Future Phase

Status: **deferred**. Not part of the current roadmap. Kept so the ideas are not lost and so the preconditions for starting are explicit.
Parent plan: [`10-personal-learning-companion-development-plan.md`](10-personal-learning-companion-development-plan.md) (revision 3). This document holds everything that revisions 1–2 of that plan put *above* `Project` and that the owner decided to leave out for now.

---

## 1. Why it was deferred

- The owner keeps the course (axes, sources, field map) outside the system and comes to Thesisound one project at a time. `research/decolonial-ai/` is not, and must not become, an automatic input.
- The hardest part — **concept identity across sources** — has no cheap solution (AQT Maker has none either; it merges books by hand). Without it, "course coverage" is a meaningless number.
- Under the binding rule "memory is never evidence", cross-project memory can only shape *scope and wording*. Most of that value is available for free inside a project through `known_concepts` (owner-typed list per project) and through the source itself being fully uploaded (earlier chapters' evidence is available to later parts).
- The layer (course, axis, source registry, coverage ledger, persistent glossary, snapshot, acceptance action, continuity injection) was larger than the lesson pipeline it sat on, and would have been built before a single real source had been completed.

## 2. Preconditions to reopen

Reopen this document only when **all** of these are true:

1. At least three real sources have been completed end to end with the current plan (P5 done), with cost and quality recorded.
2. There is a measured, repeated problem that a per-project `known_concepts` list does not solve — e.g. the owner is retyping the same skip list, or later projects re-explain concepts noticeably.
3. A concrete, conservative approach to concept identity across sources has been chosen (owner-maintained alias list first; model-suggested aliases with owner confirmation second; embeddings only as a suggestion aid, never for evidence).
4. The evidence pipeline and the concept map (doc 10, P1–P2) are stable — no prompt or schema churn for a full evaluation cycle.

## 3. What was designed (condensed, for later reuse)

Domain (revision 2, §5): `Course` (settings: default episode minutes, default delivery, known concepts), `Axis` (flat, ordered, status), `SourceRecord` (fingerprint, axes, projects, concept-map hash, status), `ConceptCoverage` (`planned | covered | known | carried_forward`, provenance = project and claim references, never text), course-level glossary merged on acceptance, `CourseContextSnapshot` frozen at brief confirmation (versions of course/axis/map/overlay/coverage/glossary; serialized context = labels and keys only).

Behaviour: an explicit **accept lesson** action (distinct from `COMPLETE`) runs a deterministic knowledge-update compiler over the accepted project's plan, verified script/prose, ledger and cell keys; continuity is injected into planning and script as bounded label lists ("brief reminder allowed, no re-definition"; preferred terminology; previous accepted part's title/outcome line); it may never supply claims. `coverage_ratio` rolls up source → axis → course weighted by cell tier/importance, shown with `known` cells labelled "skipped by owner", never "covered".

Rules that would still bind: `covered ≠ known ≠ true`; never store prose or model output as fact; store references with provenance; editing course data never rewrites a confirmed project; a failed or unaccepted project never updates memory; hard release gates from revision 1 §13.3.

Owner UI sketch: course → axes → sources → parts; concept map with coverage overlay; "continue where I left off". Optional later: an `axis_synthesis` lesson over accepted lessons of one axis, with every historical claim re-traced to its original evidence.

## 4. What is explicitly *not* planned even then

Learner analytics, mastery scores, spaced repetition, quizzes; a generalized cross-source truth graph; RAG over prior lesson summaries; automatic inference of the owner's beliefs; multi-user.
