# Phase 2.5 audit trail

The benchmark history is intentionally cumulative. Later files do not rewrite earlier proposals as if the final v1 design had always existed.

| Layer | Artifact | Meaning |
|---|---|---|
| Original proposal | `README.md`, `REQUIREMENTS.md`, `CASE-MATRIX.md`, `SOURCE-CANDIDATES.md`, `SOURCE-RECOMMENDATIONS.md`, `sources.json` | Phase-1 discovery and recommendations, including the original C05 and C12 designs and H13/H14/H15 holdout labels |
| Independent review | `OPUS-INDEPENDENT-REVIEW.md` | Opus review findings, including implementation mismatches and source-usability concerns |
| Reconciliation | `opus-decisions.json` | Authoritative Phase-2 decisions for settlement |
| Final v1 disposition | `pre-freeze/` | Phase-2.5 acquisition evidence, validation results, pinned inputs, readiness, and blockers; still not frozen and containing no gold |

Final v1 disposition differs from the proposal in the following traceable ways:

- The visible release-gating core is C01, C02, C03, C04, C05R, C06, C07, C08, C09, C10, C11, and V15.
- H13/H14/H15 are burned as holdouts. V13 and V14 are visible non-gating challenges; repaired H15 becomes visible-core V15.
- Original C05 remains preserved and deferred until M8. C05R fills its v1 slot; the final bounded search selects Lin rather than the reconciled Mill baseline.
- C12 remains preserved and deferred to v1.1. It is not force-filled.
- C09 is Chapters I-IV, VI, and XIV from the 1859 first edition, not the complete book.
- C10/C11 are an exact 20/40-minute control pair.
- Three future hidden holdouts are represented only by opaque public records and a private-bundle interface. No hidden semantics were authored here.

`SOURCE-RECOMMENDATIONS.md` is part of the tracked audit trail. Rejected and deferred designs remain visible in the Phase-1 and Opus artifacts.
