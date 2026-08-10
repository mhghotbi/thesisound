# Phase 2.5 audit trail

The benchmark history is intentionally cumulative. Later files do not rewrite earlier proposals as if the final v1 design had always existed.

| Layer | Artifact | Meaning |
|---|---|---|
| Original proposal | `README.md`, `REQUIREMENTS.md`, `CASE-MATRIX.md`, `SOURCE-CANDIDATES.md`, `SOURCE-RECOMMENDATIONS.md`, `sources.json` | Phase-1 discovery and recommendations, including the original C05 and C12 designs and H13/H14/H15 holdout labels |
| Independent review | `OPUS-INDEPENDENT-REVIEW.md` | Opus review findings, including implementation mismatches and source-usability concerns |
| Reconciliation | `opus-decisions.json` | Authoritative Phase-2 decisions for settlement |
| Phase-2.5 disposition | `pre-freeze/` before the final audit | Source settlement, acquisition evidence, validation results, pinned inputs, readiness, and blockers; not frozen and containing no gold |
| Final pre-freeze audit | `pre-freeze/OPUS-FINAL-PRE-FREEZE-AUDIT.md`, `pre-freeze/opus-final-audit.json` | Authoritative Phase-2.6 blocker list and corrected freeze-gate semantics |
| Phase-2.6 closure disposition | current `pre-freeze/` manifests, reports, and tools | Smallest-blocker fixes and honest remaining human/acquisition/legal blockers; still not frozen and containing no gold |

Final v1 disposition differs from the proposal in the following traceable ways:

- The visible release-gating core is C01, C02, C03, C04, C05R, C06, C07, C08, C09, C10, C11, and V15.
- H13/H14/H15 are burned as holdouts. V13 and V14 are visible non-gating challenges; repaired H15 becomes visible-core V15.
- Original C05 remains preserved and deferred until M8. C05R fills its v1 slot; the final bounded search selects Lin rather than the reconciled Mill baseline.
- C12 remains preserved and deferred to v1.1. It is not force-filled.
- C09 is Chapters I-IV, VI, and XIV from the 1859 first edition, not the complete book.
- C10/C11 are an exact 20/40-minute control pair.
- Three future hidden holdouts are represented only by opaque public records and a private-bundle interface. No hidden semantics were authored here.

`SOURCE-RECOMMENDATIONS.md` is part of the tracked audit trail. Rejected and deferred designs remain visible in the Phase-1 and Opus artifacts.

Phase 2.6 does not rewrite the earlier state. It records that C02's isolated private-use marks were reclassified and canonicalized while human Gate E remains open; C04/C09 scope declarations were corrected by rebuilding and machine validation; C08's decoy package was completed; C05R and C10/C11 pinning were hardened; and C06/V15 remain blocked for the exact reasons in the current blocker register.

The subsequent C06-only pre-freeze blocker pass preserves that history and the failed 2011 OECD R13 report. It replaces only C06's corrupted second source with the bounded OECD *How's Life? 2020* Chapter 1 fixture after acquisition, rights review, corpus-size comparison, section verification, and R13; it does not revise another case, author gold, or freeze the set.
