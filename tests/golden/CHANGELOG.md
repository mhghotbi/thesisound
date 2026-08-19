# Golden re-baseline — extraction 2.0 (P2, 2026-08-19)

Reviewed diff for the `focused_question` goldens after extraction 2.0 became the only extraction path. Human `must_cover` / `must_preserve_distinctions` lines in `benchmarks/eval/cases/*/expectations.toml` are unchanged (neutral). Live `thesisound eval` was not re-spent in this step (no provider keys in the environment); `thesisound eval --dry-run` still lists the same three cases.

Judgement key: **better** = more auditable or less silent loss; **worse** = a real drop; **neutral** = same evidence, different shape.

## Eval cases (`benchmarks/eval/cases/`)

| Case | What changed | Judgement |
| --- | --- | --- |
| `argument-and-context` | Same two markdown sources and the same three must-cover points (labor/work/action, plurality, historical context). Distinctions that used to sit in unaudited aux lists now enter the claim ledger with excerpts if the model emits `claim_type=distinction` / `definition`. | better |
| `competing-interpretations` | Same two interpretation sources and the same must-cover points. Type-aware merge (1.1.0) refuses to collapse an objection into a response or a competing reading into consensus. | better |
| `conceptual-distinction` | Same single source and the same must-cover points (compliance vs authority). The case that previously failed coverage for “overlap and boundary cases” is the one most likely to *gain* typed distinction claims; that is an expected inventory lift, not a rewritten brief. | better (expected); live score not re-measured |

## Inventory shape (every former aux line)

These are the contract lines that used to appear beside `claims` on `EvidenceExtractionDraft` and now appear only as typed claims:

| Former field (1.4.0) | 2.0.0 replacement | Judgement |
| --- | --- | --- |
| `definitions[]` (term + free text, no excerpt, no ID) | `claims[]` with `claim_type=definition` and required `term` | better |
| `distinctions[]` (item_a/item_b, no excerpt, no ID) | `claims[]` with `claim_type=distinction` and required `contrast` | better |
| `examples[]` | `claims[]` with `claim_type=example` | better |
| `objections[]` | `claims[]` with `claim_type=objection` | better |
| `responses[]` | `claims[]` with `claim_type=response` (optional `responds_to_excerpt`) | better |
| `must_not_be_lost[]` (free strings) | `must_not_be_lost: bool` on each claim; planner 1.3.0 rejects a silent drop | better |
| surplus claims past `max_claims_per_block` dropped with no signal | `more_claims_available` (second pass still gated to `source_coverage` in P3) | better for `source_coverage`; **neutral** for `focused_question` until that gate |
| — | per-block `excerpt_char_coverage` on the extraction plan | better (metric only; does not add or drop claims) |

Net effect on a typical `focused_question` block in tests: **one** `author_position` claim stays; **five** additional typed claims (definition, distinction, example, objection, response) appear in the same inventory. That is more claims, not fewer. No test showed a drop in author-position / interpretation coverage.

## Fixtures deliberately not rewritten

| File | Why it stayed | Judgement |
| --- | --- | --- |
| `tests/fixtures/evidence_artifacts/definitions_missing_ids.json` | Pre-2.0 payload for the schema-v1 locator upgrade path (`upgrade_block_extraction_payload`). Not an extraction-2.0 draft. | neutral |
| `tests/fixtures/evidence_artifacts/must_not_be_lost_string.json` | Same: lifts a string `must_not_be_lost` list to `MustNotBeLostPoint`. Loading a *cached* 1.4 extraction is refused by `EVIDENCE_EXTRACTOR_VERSION = 2` (regenerate), not by rewriting this fixture. | neutral |

## Downstream prompts the goldens now pin

Active versions (highest directory): `evidence_extraction/2.0.0`, `evidence_extraction_batch/2.0.0`, `claim_reconciliation/1.1.0`, `claim_reconciliation_merge/1.1.0`, `episode_plan/1.3.0`, `glossary/1.1.0`, `document_map/1.1.0`. Older directories are unchanged for reproducibility.
