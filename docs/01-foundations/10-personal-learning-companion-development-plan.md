# 10. Personal Learning Companion — Development Plan (entry)

Status: approved direction — **revision 3.2 (2026-08-19)**. The plan is split into three executable parts; this file is the entry point and the section map for references of the form "doc 10 §N" written before the split.

| Part | File | Answers | Read when |
| --- | --- | --- | --- |
| **A** | [`10a-personal-learning-companion-direction.md`](10a-personal-learning-companion-direction.md) | **Why** — owner decisions, the job, current state vs target, lessons from KMS/AQT, non-negotiable rules | before any phase; when a design question arises |
| **B** | [`10b-personal-learning-companion-design.md`](10b-personal-learning-companion-design.md) | **What** — domain model, pipeline, duration model, text delivery, prompt audit, **full text of every new/replaced prompt (Appendix A)** | while implementing a phase |
| **C** | [`10c-personal-learning-companion-implementation.md`](10c-personal-learning-companion-implementation.md) | **How** — phases P0 … P6 at developer detail, order, protocol, file guidance, risk status, definition of done | to pick up the next task |

Deferred material (cross-project course memory): [`11-course-memory-future-phase.md`](11-course-memory-future-phase.md).

## Section map (revision 3.1 numbering → 3.2 location)

| 3.1 section | Now |
| --- | --- |
| §0 owner decisions | 10a A0 |
| §1 product decision | 10a A1 |
| §2 current state vs target | 10a A2 |
| §3 lessons from KMS / AQT Maker | 10a A3 (detail: `docs/06-operations/01` items 15–24) |
| §4 non-negotiable rules | 10a A4 |
| §5 domain model | 10b B1 (B1.4 closure, B1.6 skeleton, B1.8 cost estimate are new) |
| §6 pipeline for `source_coverage` | 10b B2 |
| §7 text delivery | 10b B4 |
| §8 prompt audit | 10b B5 |
| §9 phases | 10c P0 … P6 (P0.5 is new) |
| §10 implementation order | 10c C-O |
| §11 agent protocol | 10c C-P |
| §12 file-level guidance | 10c C-F |
| §13 risks and open decisions | 10c C-R (status table) |
| §14 definition of done | 10c C-D |
| Appendix A prompt texts | 10b Appendix A (A.4 updated for the segment skeleton) |

## What changed in 3.2 (owner decisions of 2026-08-19)

- Risk 1: the document map **stays** in the `source_coverage` path (quality over cost); pre-run cost estimate and cell-unit batch extraction added.
- Risk 2: **deterministic segment skeleton** — the planner fills narrative only.
- Risk 3: **two chapter detectors with a disagreement flag**, no owner gate.
- Risk 4: **prerequisite closure** in compression and **deterministic tier promotion**.
- Risk 5: edges, including cross-chapter, are **always built**.
- Risk 6: extraction 2.0 **switches for all intents in P2; no migration** of old artifacts.
- New **P0.5 grounding hotfix** (writer 1.3.0, claims in packs, `unsupported_specifics` check, must-not-be-lost review page) ships before P1.
