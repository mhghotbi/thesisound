# Source Discovery, large-document mapping, and workflow revision

## 1. Starting with only a topic

A user may create a project without uploading a source. The Sources screen exposes two first-class paths:

1. upload a local file;
2. run Gemini Google Search from the confirmed Research Brief.

Search output is candidate metadata only. A candidate becomes eligible for the corpus only after:

1. explicit or automatic selection;
2. Gemini URL Context capture;
3. honest access classification (`full_text`, `partial_text`, `metadata_only`, `unavailable`);
4. local persistence as an inspectable Markdown artifact;
5. the normal parser and parse-quality gate;
6. explicit corpus confirmation.

A snippet, overview, abstract, inaccessible page, or incomplete capture is never silently promoted to evidence.

## 2. Large documents

`DocumentMapperService` uses `maximum_input_characters` as a per-call budget, not a document-size limit.

For an oversized source:

1. semantic blocks stay unchanged;
2. contiguous top-level heading groups are preferred;
3. an oversized chapter is recursively split on deeper headings;
4. only if necessary, splitting falls back to semantic-block boundaries;
5. every partition is mapped independently and deterministically namespaced;
6. a separate merge prompt adds cross-partition dependencies, global threads, and a working thesis;
7. a final deterministic validation confirms order, uniqueness, known IDs, and at least 90% non-front-matter coverage.

No source block is truncated, sampled, duplicated, or dropped. If a single semantic block itself exceeds the model budget, the run stops with an instruction to fix BlockBuilder; silently slicing that block would damage locator and evidence integrity.

## 3. Human-readable parse warnings

The source card separates three concepts:

- **usable status**: whether the source can enter evidence;
- **human explanation**: what the warning means and whether action is required;
- **technical details**: parser, internal verdict, attempted parser route, block count, and character count.

Individual issues are translated to a readable label, severity, affected pages, and the parser's recorded evidence. A `warning` with `safe_for_claim_extraction=true` is explicitly described as non-blocking.

## 4. Navigation and revision

Completed and prior stages remain readable through the project workflow navigation.

Editing an upstream stage is a destructive semantic change, so it is implemented as an explicit rewind rather than an unrestricted state assignment.

Rewind to Sources or Brief:

- rejects genuinely active queued/running work;
- archives downstream episode, script, audio, run, and model-run artifacts;
- clears `Project.sources`, `episode_plan`, `script`, and `last_error`;
- preserves uploaded files and ingestion artifacts;
- resets source selection when returning to Brief;
- writes `archive/revisions/<timestamp>/revision.json` with actor, reason, previous/new state, and archived paths.

Rewind to Sources additionally keeps `sources/`, the per-source analysis of each source. This is what lets an edited selection be re-confirmed without paying again for the sources the user kept. Reuse is never assumed: the corpus builder re-validates each one against the file hash and the current brief before carrying it forward — see [22](22-web-corpus-building.md). Rewind to Brief archives `sources/` as well, because the brief is the input the analysis was planned against.

This guarantees that a revised Brief or corpus cannot reuse a stale Episode Plan, script, or audio artifact.

## 5. Known limits

The implemented source-discovery path is a local Gemini vertical slice. It does not yet provide:

- general-purpose crawling;
- paywall or authenticated-source access;
- independent byte-for-byte verification of URL Context capture;
- strong authority ranking across scholarly and general-web sources;
- cross-provider search redundancy;
- production job queues and cancellation.
