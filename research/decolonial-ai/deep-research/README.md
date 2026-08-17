# Decolonial AI Deep Research Workspace

This directory stores external research-agent outputs before they are promoted into the canonical field map.

## Structure

- `inputs/` — structured ingests of each incoming research batch.
- `../field-map.md` — canonical working map; update only after verification and synthesis.

## Status model

Each incoming batch is treated as one of:

- `unverified agent synthesis` — useful leads, claims, concepts, and citations that have not been independently checked.
- `verified evidence` — claims and bibliographic details checked against primary/authoritative sources.
- `synthesis candidate` — verified material ready to be compared with other batches and integrated into the field map.

## Ingestion rules

1. Preserve provenance and batch date.
2. Extract concepts, relationships, anchor works, empirical claims, and proposed alternatives.
3. Keep agent-created labels distinct from established scholarly terminology.
4. Add explicit verification flags for suspicious, overly broad, or normative claims.
5. Do not silently merge incoming material into `field-map.md`.
6. At final synthesis, distinguish established vs emerging literature, diagnosis vs alternatives, technical vs institutional mechanisms, and global vs Iran/Global-South-specific claims.
7. Preserve disagreements and trade-offs rather than forcing one coherent ideological frame.

## Current batches

- `inputs/2026-08-17-batch-01.md` — first field map plus expansions on extractivism/labor/language, digital sovereignty, sociotechnical alternatives, and provisional grassroots/constraint-oriented strategies.
