# Thesisound Pipeline Audit: Performance, Cost, Quality, and Reliability

**Audit date:** 2026-08-11  
**Repository baseline:** commit `4e13b66`  
**Audience:** Technical and product stakeholders  
**Scope:** Read-only audit of the repository, existing workspaces, model-run artifacts, and the observability ledger. No production code, migrations, instrumentation, configuration, or workflow behavior was changed.

## Evidence labels used in this report

- **Measured finding:** directly computed from stored runtime data or reproduced locally.
- **Code-supported inference:** follows from an implemented code path, but its production magnitude is not measured.
- **Unverified hypothesis:** plausible, but the available evidence cannot establish it.
- **Experiment recommendation:** a controlled comparison needed before making a design decision.
- **Instrumentation gap:** a requested conclusion cannot be computed from current telemetry.
- **Insufficient evidence:** the repository and artifacts do not support a defensible conclusion.

Latency totals in this report are measured model or parser work unless explicitly identified as wall-clock latency. They must not be interpreted as complete user-perceived latency. Token counts are provider-reported historical usage where present; they are not monetary cost estimates.

---

## 1. Executive Verdict

Thesisound has a serious, traceable architecture with unusually strong attention to provenance, artifact persistence, validation boundaries, and resumability. However, the implementation is ahead of the evidence that its complexity improves end-user quality. The available runtime corpus contains only one complete script, one archived audio manifest without retained media, no complete multi-source synthesis run, no actual 5/15/30/60-minute comparison set, and no frozen human-rated golden evaluation. The pipeline is therefore **architecturally promising but not yet empirically validated as a quality-efficient system**.

The clearest proven waste is in document parsing and historical repeat work. One unsuccessful Docling PDF attempt took 465 seconds, and the same text payload was processed four times for a combined 505.5 seconds. In model work, document-map partition calls and evidence extraction account for 28.3% and 28.0% respectively of measured historical model latency. Forty-five later successful calls share the same project, stage, prompt version, model, and input hash with an earlier success, representing 1,879,460 repeated input tokens and 1,966,114 repeated total tokens. That is a strong reuse opportunity, although not every repeated call is proven unnecessary because output randomness and explicit user reruns are not recorded.

The largest demonstrated quality risk is multi-source synthesis. Reconciliation is performed per source, then source ledgers are concatenated. The current disagreement graph contains no cross-source edges and the inspected artifacts use empty disagreement lists. This cannot reliably preserve contradiction, attribution, or uncertainty across sources. The second major risk is duration-aware reuse: changing duration replans the episode but does not scope previously extracted evidence to the new analysis profile. A short-to-long change under-analyzes deferred content; a long-to-short change can retain claims outside the new selection.

The most important observability limitation is that the ledger cannot reconstruct representative end-to-end user runs. Most rows were produced by tests, almost all model calls lack workflow identifiers, `pipeline_runs` counters remain zero, monetary costs are null, and deterministic work, queueing, user review time, and quality outcomes are not linked to runs. A successful branch has a 183.02-minute wall-clock envelope while recorded model-run time sums to only 14.83 minutes; 168 minutes are unclassified and cannot safely be attributed to parsing, queueing, human approval, process inactivity, or another cause.

### Direct answer

The parts that currently create demonstrable value are content-addressed ingestion, block-level provenance, document mapping for long documents, structured evidence extraction, deterministic script checks, artifact archiving, and chunk-level audio identity. The parts that remain unproven are the coverage audit, glossary, broad script verifier/reviser loop, second-speaker design, ASR quality gate, and the incremental quality gain of the document map itself. The parts that should change first are duration-scoped reuse, auxiliary evidence consumption, cross-source reconciliation, parser routing, cache versioning, retry policy, and separation of test telemetry from real workflow telemetry.

### Three priority actions

1. Correct the semantic reuse boundary for duration and profile changes, and ensure planning sees only evidence valid for the current selection.
2. Implement or explicitly defer true cross-source reconciliation; do not present the current empty disagreement graph as conflict handling.
3. Establish production-grade workflow/quality telemetry before optimizing stages whose quality gain is not measurable.

**Overall confidence:** High for code-path and stored-artifact findings; low for claims about user-perceived quality, monetary cost, and production reliability.

---

## 2. Scope and Evidence

### Repository sources inspected

The audit covered:

- `README.md`, `STATUS.md`, `PRODUCT.md`, and `DESIGN.md`;
- architecture, workflow, quality, observability, and evaluation documentation under `docs/`;
- active and legacy prompts under `prompts/`;
- model routing and runtime configuration under `config/` and `models.lock.json`;
- pipeline, services, adapters, web routes, and application wiring under `src/thesisound/`;
- tests, benchmarks, and GitHub Actions workflows;
- `workspaces/_observability/ledger.sqlite3` and its referenced artifacts;
- project workspaces, revision archives, parser reports, model-run JSON, scripts, evidence ledgers, and audio manifests.

The main orchestration and state transitions were traced from [`pipeline.py`](../src/thesisound/pipeline.py), corpus construction from [`corpus_building.py`](../src/thesisound/services/corpus_building.py), source analysis from [`source_analysis_service.py`](../src/thesisound/services/source_analysis_service.py), episode replanning from [`episode_planning_run.py`](../src/thesisound/services/episode_planning_run.py), audio processing from [`audio_pipeline_service.py`](../src/thesisound/services/audio_pipeline_service.py), and revision behavior from [`workflow_revision.py`](../src/thesisound/services/workflow_revision.py).

### Runtime populations inspected

- Observability ledger size: **18,046,976 bytes**, schema version 3.
- Ledger rows: 476 model calls, 477 model attempts, 723 pipeline runs, 12,727 spans, 15,160 events, and 13,203 `trace_nodes` view rows.
- Filesystem model-run records: 365 unique records with 481 attempts.
- Project-level runtime calls in the ledger: only 14, all for project `1296`.
- One end-to-end explanatory script workspace and one archived audio manifest were available for detailed output inspection.

### Verification performed

The full test suite collected 751 tests: **748 passed, 2 failed, and 1 skipped**. Both failures were audio tests caused by FFmpeg being absent in the local environment; the CI workflow installs FFmpeg. This result is evidence of regression coverage, not evidence of end-user content quality.

The repository's golden evaluation package reports **NOT READY TO FREEZE** and contains neither frozen answer hashes nor a complete human-scored benchmark. Therefore no stage's quality contribution can currently be claimed as experimentally established.

### Boundaries and exclusions

- No external provider calls were made, so the audit incurred no new model, search, TTS, ASR, or OCR charges.
- No production code, configuration, database schema, migration, or observability implementation was changed.
- Stored audio media were unavailable; only transcripts, QA records, and manifests could be inspected.
- No human raters were available, so unsupported-claim rate, Persian naturalness, verifier false-positive/false-negative rates, and manual correction time remain **Insufficient evidence**.
- No current complete multi-source trace or actual duration ladder was available.
- Historical artifacts span multiple code versions. Findings distinguish historical behavior from current unexercised fixes where possible.

### Documentation, code, tests, and runtime disagree in material ways

| Topic | Documentation or intended design | Current code | Runtime evidence | Audit conclusion |
| --- | --- | --- | --- | --- |
| Cross-source disagreement | Presented as a synthesis capability | Reconciliation is per source; graph construction has no effective cross-source edge population | Inspected graph has `edges=[]`; source disagreement lists are empty | Capability is not demonstrated and is structurally incomplete |
| Output-aware analysis | Duration controls depth, claims, and neighbor context | Selection changes by profile, but second-pass core analysis is declared and not consumed | Historical 10-minute run selected 40 blocks because it predates a seed-budget fix | Current selection logic improved, but incremental profile upgrades remain incorrect |
| Reviewer independence | Writer and reviewer are distinct roles | Reviewer falls back to the strong model if unset | Historical writer and verifier both resolved to Gemini 3.6 Flash | Independent failure modes are not established |
| Observability | End-to-end traces and cost-ready telemetry | Span APIs exist and current background tasks create roots | Stored population is overwhelmingly tests; workflow identifiers and prices are absent | Schema is ahead of usable production data |
| Audio verification | ASR/QA protects final quality | Manual-review results can be accepted by configuration | Archived manifest marked six chunks manual; current replay passes all transcripts | Historical false positives improved, but acoustic quality is unmeasured |
| Prompt versions | Active prompts are versioned | Several current versions are newer than recorded runs | `document_map_merge` 1.1, script 1.1, and verifier 1.1 have no representative real run | Current quality cannot be inferred from historical runs alone |

---

## 3. Reconstructed Pipeline

### Actual execution path

```text
User brief or uploaded source
  -> Web route / application service
  -> Research Brief generation and review
  -> Source discovery, capture, or upload
  -> Source inspection and parser routing
  -> Native parse / EPUB parse / Docling / conditional OCR
  -> Parse-quality audit and normalized document artifact
  -> Corpus selection and block construction
  -> Per-source document-map partitions and map merge
  -> Duration/mode-aware block selection
  -> Per-block evidence extraction
  -> Per-source claim reconciliation and coverage audit
  -> Deterministic claim priority, budget, and disagreement artifact
  -> Episode plan and evidence packs
  -> User plan approval
  -> Glossary generation
  -> Persian script segments
  -> Deterministic script checks
  -> Model verifier and conditional revision
  -> User script review
  -> TTS segmentation and generation
  -> ASR / transcript QA and optional regeneration
  -> Audio assembly and final validation
  -> Persisted artifacts, workflow state, and user-visible output
```

### User-flow reconstruction

| Scenario | Reconstructed behavior | Critical limitation |
| --- | --- | --- |
| Digital-born PDF | Inspect -> native/Docling candidates -> quality gate -> normalized blocks | Router can pay for slow Docling before selecting native output |
| Scanned PDF | Inspect -> OCR-required route -> OCR/Docling candidate -> quality gate | No real scanned Persian run exists; OCR quality is unmeasured |
| EPUB | EPUB parser -> normalization -> blocks | Two ingestions exist, but only limited end-to-end evidence |
| URL/web source | Discovery or URL capture -> stored source -> normal ingestion | Search and URL-context costs are not linked to episode cost |
| Multiple sources | Each source is built and analyzed, then ledgers are concatenated | No true cross-source reconciliation or disagreement edges |
| Research Brief | Model output -> validation -> user review/state transition | Value is plausible; no ablation or human-time data |
| Corpus build | Sources are processed in a service loop, maps and blocks persisted | Source-level loop is serial in the inspected implementation |
| Document mapping | Partition map calls -> merge -> reusable map artifact | Major measured token/latency share; incremental quality gain unmeasured |
| Evidence extraction | Profile selects blocks -> one extraction record per block | Default batch size is one; auxiliary outputs are largely unused |
| Episode planning | Reconciled claims -> deterministic priorities/budget -> plan model | Plan cache omits prompt/model/validator and evidence content identity |
| Script generation/review | Glossary -> serial segments -> checks -> verifier -> revision | One real script; no calibrated human quality labels |
| Audio generation | Chunk -> TTS -> ASR/QA -> regeneration -> assembly | No retained audio media for listening-based verification |
| Brief revision | Archive current revision -> invalidate affected downstream stages | Revision preserves sources but historical behavior moved model runs |
| Duration change | Update brief duration -> requeue episode planning | Corpus/evidence scope is not recomputed correctly |
| Provider retry | Provider/key attempts inside a logical model operation | Key rotation is visible in attempt traces; missing usage hides full economics |
| Resume after failure | Persisted artifacts permit stage-level retries in several paths | No durable job queue; process restart can require manual retry |

### Stage inventory

| Stage | Input | Output | Type | Model tier | Blocking dependency | Reuse | Retry | User-visible |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Research Brief | User intent | Structured brief | Model | Fast | User request | Persisted brief | Up to 2 | Yes, reviewed |
| Source discovery | Brief/query | Candidate sources | Conditional model/tool | Fast/search | Brief | 24-hour query cache | Provider policy | Yes |
| Source capture | URL/upload | Source artifact | Deterministic/tool | N/A | Selected source | Source hash | Tool-specific | Yes |
| Document inspection | Bytes/extension | Route signals | Deterministic | N/A | Source | Recomputed | No | No |
| Parsing/OCR | Source | Parser candidates | Deterministic/external | Parser/OCR | Inspection | Parsed-document cache | Candidate fallback | Indirectly |
| Parse audit | Candidate artifacts | Selected normalized document | Deterministic heuristic | N/A | Parser candidates | Stored report | Candidate fallback | Warning state |
| Block building | Normalized document | Located blocks | Deterministic | N/A | Accepted parse | Source artifacts | No | No |
| Document map | Blocks | Part maps and merged map | Model | Fast | Blocks | Content/version key | Up to 3/2 | Indirectly |
| Profile selection | Brief, map, blocks | Selected/deferred block IDs | Deterministic | N/A | Map | Persisted corpus manifest | No | Indirectly |
| Evidence extraction | Selected blocks | Claims plus auxiliary evidence | Model | Fast | Selection | Block skip/carry-forward | Up to 3 | No |
| Claim reconciliation | Source evidence | Per-source claim ledger | Model | Strong | Evidence | Persisted ledger | Up to 2 | No |
| Coverage audit | Ledger, brief, map | Gaps/audit | Model | Strong | Reconciliation | Persisted | Up to 2 | Indirectly |
| Priority/budget | Claims, profile | Ranked scoped claims | Deterministic | N/A | Ledger | Recomputed | No | No |
| Disagreement graph | Ledgers | Graph | Deterministic | N/A | Reconciliation | Persisted | No | Indirectly |
| Episode plan | Scoped claims, brief | Structured plan | Model | Strong | Evidence package | Episode key | Up to 2 | Yes, approval |
| Glossary | Plan/evidence | Term mapping | Model | Strong | Approved plan | Persisted | Up to 2 | No |
| Script segments | Plan, evidence, glossary | Persian dialogue segments | Model | Strong | Glossary/plan | Revision artifacts | Up to 2 | Yes |
| Script checks | Script/contracts | Deterministic defects | Deterministic | N/A | Script | Recomputed | No | Indirectly |
| Script verifier | Script/evidence | Verdict/issues | Model | Reviewer/strong | Checks/script | Persisted | Up to 2 | Indirectly |
| Script reviser | Failed script/issues | Revised script | Model | Strong | Verifier failure | Persisted revision | Up to 2 | Yes |
| TTS segmentation | Approved script | Voice chunks | Deterministic | N/A | Script approval | Chunk hashes | No | Indirectly |
| TTS generation | Chunks | Audio segments | Provider | TTS | Chunk list | Robust chunk identity | Per chunk | Progress/result |
| ASR/audio QA | Audio segment + expected text | QA result | Provider/deterministic | ASR | TTS segment | WAV/chunk key | Per chunk | Review state |
| Audio assembly | Verified segments | Final audio | Deterministic/FFmpeg | N/A | Segment acceptance | Final artifact | Stage retry | Yes |
| Persistence/revision | Stage artifacts/state | Versioned workspace | Deterministic | N/A | Every stage | Archive/reuse rules | Manual/stage | Yes |

### Mandatory, conditional, and audit-only work

- **Mandatory for the current product contract:** ingestion, provenance-preserving blocks, evidence extraction, plan construction, script creation, deterministic checks, TTS segmentation, assembly, and artifact persistence.
- **Input-conditional:** discovery, URL capture, OCR, parser fallback, ASR regeneration, and cross-source synthesis.
- **Potentially conditional pending evidence:** coverage audit, glossary generation, full model verification, script revision, and ASR on every low-risk chunk.
- **Primarily auditability/future-use artifacts today:** parts of the auxiliary evidence schema, the empty disagreement graph, and some persisted model metadata that has no downstream consumer.
- **Candidate for merge:** deterministic claim prioritization, budgeting, and plan-package construction can remain separate functions but need not create independent user waits.

### Critical path observations

- Different sources are processed in a serial service loop, even though most ingestion and mapping work is source-local.
- Map partitions and evidence extraction support bounded worker counts (`4` each), so block-level concurrency already exists.
- Script segments were generated serially in the inspected historical run.
- TTS/ASR is chunk-granular, but production concurrency and rate-limit behavior are not measurable from the ledger.
- The web layer uses FastAPI background tasks, not a durable job queue. A server/process interruption can therefore leave a workflow requiring recovery rather than automatic continuation.

---

## 4. Observability and Data Adequacy Audit

### The schema is broad, but the stored population is not decision-ready

**Type:** Measured finding / Instrumentation gap

**Observation:** The ledger contains model calls, provider attempts, pipeline runs, spans, events, and a trace view. However, 462 of 476 calls lack a project ID, all 476 lack a workflow-run ID, 462 lack a trace ID, all lack a pipeline-trace ID and parent-span ID, 462 lack a subject, 462 lack a prompt version, 78 lack a resolved model, and one call lacks an end time/latency. Token fields are absent for 370 calls; all cost and pricing fields are null.

**Evidence:** `workspaces/_observability/ledger.sqlite3`; schema and null-count queries in Appendix A. All 723 `pipeline_runs` rows report `call_count=0` and `total_tokens=0`.

**Interpretation:** The current database schema could support detailed tracing, but the available rows cannot reliably tie calls to workflows, users, episodes, or quality outcomes. Test-generated calls dominate the population.

**Counterfactual:** With environment-labeled, root-linked traces and finalized workflow aggregates, end-to-end stage attribution, retry overhead, and episode cost could be computed directly.

**Impact:** Optimization based on global ledger averages would likely optimize test fixtures rather than real user behavior. Production success rate and total workflow latency are not defensible metrics today.

**Confidence:** High.

**Validation:** Run a fixed set of representative workflows in an isolated runtime ledger and require every span/call to resolve to one project, workflow, trace, stage, and subject before accepting aggregate metrics.

### Coverage and integrity results

| Check | Result | Interpretation |
| --- | ---: | --- |
| Model calls | 476 | Mostly tests; only 14 project-linked calls |
| Model attempts | 477 | Provider-level detail exists for very few representative calls |
| Pipeline runs | 723 | Counters are not populated, so run aggregates are unusable |
| Pipeline spans | 12,727 | Broad deterministic span vocabulary exists |
| Pipeline events | 15,160 | Event volume is high, but runtime/test separation is absent |
| Artifact references | 1,177 | 1,072 resolve; 105 are missing |
| Files under observability artifacts | 2,736 | 1,664 have no direct artifact-reference row |
| Call artifact directories | 1,045 | 611 do not map to ledger calls |
| Ledger calls without call directory | 42 | Artifact coverage is incomplete |
| Calls stuck `running` | 1 | At least one incomplete logical record remains |

Missing artifacts are concentrated in test, source-discovery, and evidence paths. Orphan files are not automatically proof of corruption because some are nested payloads rather than top-level references, but the current store cannot provide a clean referential-integrity guarantee.

### Metric computability matrix

| Metric or question | Computable now? | Data source | Limitation | Confidence |
| --- | ---: | --- | --- | --- |
| Provider/model-call latency | Partially | `model_calls`, model-run JSON | Population mostly tests; provider vs validation not consistently separated | Medium |
| Logical attempt latency | Partially | Filesystem run attempts | Failed-attempt usage often absent | Medium |
| Deterministic stage time | Schema only | `pipeline_spans` | No representative end-to-end production trace | Low |
| Queue wait | No | None | Background scheduling and queue timestamps not linked | High |
| User-perceived wall time | No | Workspace timestamps | Human pauses and process inactivity cannot be separated | High |
| Parse/OCR time | Partially | Parser reports/benchmarks | Small, non-representative sample; OCR absent | Medium |
| DB query and file-I/O time | No | None usable | Operations exist but are not measured in representative runs | High |
| Cache hit rate and saved work | No | Cache files/code | No hit/miss lineage or avoided-work fields | High |
| Tokens by historical stage/prompt/model | Yes, for filesystem subset | Model-run JSON | Failed attempts often lack usage; versions mixed | Medium |
| Tokens per accepted output | Partially | Status + usage | Content acceptance semantics differ by stage | Medium |
| Retry recovery by stage | Partially | Attempt records | Provider/logical categories incomplete in older runs | Medium |
| Monetary cost per call/stage/episode | No | Cost columns/config | Pricing version unset; `cost_micros` null | High |
| TTS/ASR/search/OCR cost | No | No linked pricing/usage ledger | Provider and infrastructure cost missing | High |
| Unsupported-claim rate | No | No human labels | Verifier verdict is not ground truth | High |
| Persian naturalness | No | One script, no calibrated ratings | No rubric-scored human panel | High |
| Audio accuracy | No | Transcripts/QA only | Audio files absent; no listening labels | High |
| Manual review time | No | None | Approval timestamps do not distinguish active review | High |
| Output stability/tail risk | No | No repeated controlled runs | Inputs, models, versions, and seeds not fixed | High |

### Cost is not currently calculable

The repository records resolved models for many calls and has token fields, but no active, versioned pricing table is linked to calls. `pricing_version` and `cost_micros` are null for all 476 ledger calls. Search, URL context, OCR compute, TTS, ASR, storage, bandwidth, and manual review are not captured in a common cost model. Any currency amount would therefore be fabricated; this report does not provide one.

---

## 5. Performance and Cost Findings

### Document mapping and evidence extraction dominate measured model work

**Type:** Measured finding

Across 365 filesystem model-run records, recorded usage totals 4,428,302 input tokens, 267,143 output tokens, 87,965 thinking tokens, 889,433 cached tokens, and 4,783,410 total tokens. Document-map partition calls contribute 784.2 seconds of measured run time (28.3% of the measured total), while evidence extraction contributes 773.8 seconds (28.0%). This is total work, not necessarily wall-clock critical-path time because parts may execute concurrently.

| Stage | Runs (timed) | P50 | P75 | P90 | P95 | P99 | Mean | Max | Total measured work |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Document-map part | 55 | 8.429s | 15.761s | 25.445s | 46.838s | 93.676s | 14.259s | 127.082s | 784.231s |
| Evidence extraction | 242 | 2.299s | 3.680s | 6.169s | 7.481s | 13.736s | 3.197s | 28.720s | 773.787s |
| Claim reconciliation | 11 | 17.833s | 58.536s | 101.328s | 101.332s | 101.335s | 37.728s | 101.335s | 415.010s |
| Script segments | 8 | 23.742s | 28.634s | 37.890s | 45.413s | 51.431s | 27.358s | 52.936s | 218.863s |
| Episode planning | 7 | 24.040s | 25.864s | 61.854s | 87.581s | 108.163s | 27.454s | 113.309s | 192.177s |
| Script verifier | 3 | 29.817s | 42.747s | 50.506s | 53.092s | 55.161s | 33.587s | 55.678s | 100.762s |
| Coverage audit | 8 | 10.661s | 12.435s | 13.709s | 14.508s | 15.147s | 11.104s | 15.307s | 88.832s |
| Document map, small | 10 | 8.823s | 10.557s | 11.449s | 11.853s | 12.176s | 8.546s | 12.257s | 85.461s |
| Glossary | 9 | 5.536s | 5.738s | 15.635s | 17.661s | 19.282s | 6.667s | 19.687s | 60.004s |
| Document-map merge | 6 | 0.902s | 1.410s | 21.919s | 32.089s | 40.225s | 7.893s | 42.259s | 47.360s |

**Interpretation:** Map partitions and extraction deserve the first optimization/ablation attention because they dominate measured model work. Claim reconciliation and episode planning have much smaller samples but high tails.

**Counterfactual:** If block selection reduced low-value map/extraction calls without lowering must-cover recall, total work would fall approximately in proportion to avoided calls. If map/extraction calls are already concurrent, the wall-clock reduction would be smaller than the work reduction.

**Impact:** High potential token and provider-work savings; wall-clock impact is medium and unproven until concurrency is traced.

**Confidence:** High for measured work share; low for user-perceived latency contribution.

**Validation:** A controlled workflow trace must record task start/end, worker concurrency, rate-limit delay, and join time for every partition/block.

### Parser routing is the largest single measured latency outlier

**Type:** Measured finding / Code-supported inference

**Observation:** Thirteen ingestion reports cover nine unique content hashes: seven PDFs, two EPUBs, and four TXT ingestions. Docling was attempted nine times and selected four times; native parsing was selected seven times. Ten of thirteen reports ended with warnings. No OCR run was present. One unsuccessful Docling PDF attempt consumed 465 seconds. The same TXT content hash was processed four times for 505.54 seconds total.

**Evidence:** Project parser reports and the parser benchmark artifacts. In the `Attention Is All You Need` benchmark, Docling took 305.86 seconds and produced 500 blocks with no formulas, while MinerU took 139.99 seconds and produced 137 blocks with five formulas; both received an automatic score of 100.

**Interpretation:** The quality gate is unable to distinguish materially different structural fidelity, and routing can spend minutes on a candidate that is rejected or no better than a faster alternative. Repeated content processing also indicates that parse reuse is either unavailable for those historical runs or bypassed by version/workspace boundaries.

**Counterfactual:** A document-type-aware route that starts with the lowest-cost parser capable of satisfying stronger structural gates would avoid expensive candidates on easy digital-born inputs, while retaining OCR/Docling for scans or structurally complex PDFs.

**Impact:** High latency and compute risk; high downstream quality risk for formulas, reading order, and headings.

**Confidence:** High for observed runs; medium for expected generalization.

**Validation:** Benchmark at least 20 documents per input class with page-level completeness, reading order, heading, locator, formula/table, and semantic OCR metrics. Compare router strategies on quality, elapsed time, and fallback rate.

### Historical retry economics vary sharply by stage

**Type:** Measured finding

| Stage | Retried records | Recovered | Recovery rate | Extra measured latency | Known extra tokens | Attempts with missing usage | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Evidence extraction | 55 | 52 | 94.5% | 183.1s | 184,838 | 26 | Retry appears valuable, but expensive |
| Document-map part | 21 | 10 | 47.6% | 151.1s | 636,957 | 11 | Conditional value; inspect error type |
| Small document map | 5 | 4 | 80.0% | 23.4s | 96,566 | 1 | Likely valuable |
| Claim reconciliation | 4 | 1 | 25.0% | 160.9s | 34,047 | 3 | Weak historical economics |
| Episode planning | 4 | 0 | 0% | 73.1s | 0 known | 4 | No demonstrated value |
| Glossary | 7 | 0 | 0% | 7.7s incl. backoff | 0 known | 7 | No demonstrated value |
| Script verifier | 1 | 0 | 0% | 50.0s | 0 known | 1 | No demonstrated value |

There were 153 failed attempts: 102 deterministic-validation failures, 37 provider errors, 12 rate limits, and two schema failures. In a representative provider trace, key 1 returned 429 after 0.756 seconds, key 2 returned 401 after 2.192 seconds, and key 3 succeeded after 6.275 seconds; total provider-attempt time was 9.298 seconds. This confirms that provider retries and key rotation can occur inside one logical operation and must be reported separately.

**Interpretation:** A uniform retry count is not economically justified. Extraction failures often recover; historical episode, glossary, and verifier retries did not. Missing failed-attempt usage means token waste is understated.

**Counterfactual:** Stage- and error-specific policies would retry transient/rate-limit failures and high-recovery deterministic repairs, but stop early on repeated contract failures with unchanged inputs.

**Impact:** Medium-to-high latency/token savings and lower retry-storm risk.

**Confidence:** Medium because samples are small and versions are mixed.

**Validation:** Recompute by current prompt version, resolved model, error class, and repair message over at least 100 production operations per high-cost stage.

### Prompt efficiency and contract behavior

| Prompt / version | Records | Success | Failed/rejected/running | Retried | Input tokens | Output tokens | Thinking tokens | Total tokens | Main risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Document map 1.0 | 70 | 52 | 13 / 0 / 5 | 26 | 3,248,524 | 129,278 | n/a | 3,377,802 | Very high context and repair volume |
| Map merge 1.0 | 6 | 6 | 0 | 0 | 1,538 | 383 | n/a | 1,921 | Historical version lacked current global layer |
| Evidence 1.1 | 27 | 23 | 3 / 0 / 1 | 6 | 63,206 | 11,975 | n/a | 75,181 | Old version |
| Evidence 1.2 | 68 | 68 | 0 | 24 | 172,772 | 36,077 | n/a | 208,849 | High retry count despite final success |
| Evidence 1.3 | 148 | 148 | 0 | 25 | 550,004 | 61,568 | n/a | 611,572 | Input-heavy, output relatively small |
| Claim reconciliation 1.0 | 11 | 8 | 3 | 4 | 46,605 | 10,750 | 23,578 | 80,933 | High thinking share and poor retry recovery |
| Coverage 1.0 | 8 | 8 | 0 | 0 | 69,475 | 3,561 | 12,577 | 85,613 | Large input for compact output; value unproven |
| Episode plan | 7 | 3 | 4 | 4 | 47,276 | 5,028 | 11,390 | 63,694 | Historical retries never recovered |
| Glossary 1.0 | 9 | 2 | 7 | 7 | 69,818 | 1,787 | 3,989 | 75,594 | High failure and low output; value unproven |
| Script 1.0 | 8 | 8 | 0 | 2 | 79,480 | 6,694 | 26,385 | 112,559 | Serial segment overhead |
| Verifier 1.0 | 3 | 2 | 1 | 1 | 79,604 | 42 | 10,046 | 89,692 | Extremely input-heavy and no human calibration |

Active prompt files are versioned, but several current versions have no representative real execution: map merge 1.1, episode 1.1, script 1.1, and verifier 1.1. The active evidence prompt is 1.3. Legacy top-level prompts for query planning, source triage, and parse auditing are not equivalent to active service paths and should not be counted as current runtime stages without call evidence.

The verifier is the clearest input/output imbalance: 79,604 input tokens produced 42 output tokens across three historical calls. This alone does not prove waste because a small verdict may prevent a costly defect, but there is no human label set demonstrating that benefit.

### Historical repeat work is material, but not all duplicates are proven waste

**Type:** Measured finding with qualification

Forty-five later successful calls share an earlier successful call's project, stage, prompt version, resolved model, and input hash. Those later successes account for 1,879,460 input tokens and 1,966,114 total tokens. The current records do not identify whether a duplicate was an intentional regeneration, a user-requested alternative, stochastic quality recovery, or accidental recomputation.

**Interpretation:** The upper bound on avoidable historical repeat work is large. The defensible conclusion is that the pipeline lacks enough reuse lineage to distinguish intentional reruns from unnecessary duplicates.

**Validation:** Record `cache_lookup_key`, hit/miss, reused artifact ID, invalidation reason, user-forced regeneration, and estimated avoided provider work.

### Model routing is internally consistent but not empirically optimized

| Stage family | Current model/tier | Required capability | Fit assessment | Cost risk | Quality risk | Candidate experiment |
| --- | --- | --- | --- | --- | --- | --- |
| Brief/map/evidence/web capture | Gemini 3.5 Flash Lite / fast | Structured extraction, long context, Persian/English | Plausible; not benchmarked | Map context dominates | Missed nuance/contract repair | Fast vs current/strong on frozen extraction set |
| Reconciliation/coverage/plan/glossary/script | Gemini 3.6 Flash / strong | Synthesis, contradiction, Persian generation | Plausible | Thinking/retry overhead | Shared failure modes | Strong vs stronger and stage-specific cheap variants |
| Script verifier | Reviewer config falls back to strong | Independent evidence checking | Poor experimental separation | Duplicate large context | Correlated writer/reviewer errors | Distinct reviewer vs same model vs deterministic-only |
| TTS | Gemini 3.1 Flash TTS Preview | Persian prosody/pronunciation | Insufficient evidence | Unknown currency cost | Voice drift/pronunciation | Human listening benchmark |
| ASR | Gemini 3.6 Flash | Persian transcript alignment | Transcript replay looks strong | Unknown currency cost | False negatives without acoustic labels | Calibrated audio-error corpus |

Resolved model logging is present for many real filesystem records, and no silent model-family fallback was found; the runtime rotates keys rather than models. However, reviewer configuration currently resolves to the same model as strong generation unless separately configured, and preflight treats that equivalence as a blocker in the current code. A stale `model-routing copy.toml` also exists and creates maintenance ambiguity, though there is no evidence it is loaded.

### Cache and invalidation correctness

| Cache/artifact | Key material | Reuse scope | Invalidation weakness | Risk | Measured benefit |
| --- | --- | --- | --- | --- | --- |
| Web search | Query + fast model, 24h TTL | Cross-workflow | No prompt/tool/search-policy version | Stale/incompatible results | Not measured |
| Parsed document | Byte hash, extension, encryption/complexity, parser identity | Cross-workflow | Appears robust; no representative hit data | Low correctness risk | Not measured |
| Full document map | Block content + manual builder version | Cross-workflow | Manual version bump; model/prompt indirectly incomplete | Stale map after logic change | One shared artifact; savings unmeasured |
| Map partition | Content + builder version | Cross-workflow | No measured hit lineage | Duplicate partitions | Not measured |
| Block evidence | Block ID/skip behavior | Within source/workflow | Omits prompt, model, profile, validator | Stale evidence after semantic changes | Partial retry reuse observed |
| Claim carry-forward | Source hash + profile + selected IDs | Revision/profile | Omits prompt/model/validator | Incorrect reuse | Not measured |
| Episode plan | Source IDs, claim IDs, plans, brief | Revision | Omits prompt/model/validator and evidence content | Stale plan | Not measured |
| Script binding | Plan hash | Revision | Prompt/model/checker changes do not invalidate | Stale script contract | Not measured |
| TTS chunk | Script/turn/speaker/voice/model/style/text | Cross-retry | Strong identity | Low | Seven chunks reached generation 2 historically |
| ASR result | Chunk + WAV | Cross-retry | ASR model/version omitted | Stale transcript evaluation | Not measured |
| QA result | Chunk + WAV | Cross-retry | Threshold/validator version omitted | Stale accept/reject verdict | Historical replay changed verdicts |

The strongest cache is TTS chunk identity. The highest-risk reuse boundaries are evidence, planning, script, ASR, and QA because semantic or validator versions are omitted. The audit does **not** recommend adding generic caching; it recommends correcting identity and measuring actual hit value before expansion.

### Parallelism opportunities

| Opportunity | Dependency evidence | Expected latency gain | Risk | Rate-limit impact | Validation |
| --- | --- | ---: | --- | --- | --- |
| Per-source ingest/map/extract | Source-local until synthesis | Potentially high for multi-source runs | Disk/SQLite contention, provider bursts | High | Replay 2/4/8 sources with bounded workers |
| Script segments | Segment evidence packs are precomputed; historical calls were serial | Historical call-time upper bound: 133s sum to 53s max, about 61% | Terminology/transition drift | Medium-high | Compare serial vs 2 workers with boundary rubric |
| TTS chunks | Chunk hashes and QA are independent before assembly | Potentially high | Voice drift, quota bursts, out-of-order persistence | High | 1/2/4 worker audio test with quality labels |
| ASR checks | Chunk-local | Potentially high | Provider quota and duplicated retry | High | Same as TTS; separate limiter |
| Search queries | Query-local before triage | Moderate | Duplicate sources and search quota | Medium-high | Deduplicate after bounded parallel search |

No parallelism recommendation is production-ready because representative queue, rate-limit, key-pool, and SQLite contention measurements are absent. SQLite uses WAL and a 30-second busy timeout, and workspace JSON writes are atomic; no current evidence identifies SQLite as a bottleneck.

### Total work is not user-perceived latency

One successful branch spans a 183.02-minute timestamp envelope, while recorded model runs sum to 14.83 minutes. The 168-minute difference cannot be assigned. It may include parsing, inactive process time, user approvals, queue delay, file operations, or missing instrumentation. Reporting it as pipeline compute or user wait would violate the evidence.

### Non-token cost breakdown

| Cost category | Measurable now? | Current estimate | Missing data | Required collection |
| --- | ---: | ---: | --- | --- |
| LLM input/output/thinking | Partially | Token counts only | Pricing version; failed-attempt usage | Versioned pricing + complete attempt usage |
| Cached-token savings | No | None | Provider price treatment and cache causality | Cached token billing + avoided-call lineage |
| Search/grounding/URL context | No | None | Requests, units, provider price | Operation usage and price snapshot |
| OCR/parser compute | Partially | Seconds for small sample | CPU/GPU/RAM and fleet cost | Process resource sampling per parser |
| TTS | No | None | Characters/audio seconds/billing | Per-chunk usage and price |
| ASR | No | None | Audio seconds/billing | Per-chunk usage and price |
| Storage | Partially | One archive is 28.84 MiB of a 39.42 MiB workspace (73.2%) | Growth by artifact type and retention | Artifact bytes, lineage, retention events |
| Bandwidth | No | None | Upload/download bytes | Provider and user transfer counters |
| Manual review | No | None | Active review duration and corrections | Review start/submit + change magnitude |
| Rerun/failed workflow | Partially | Model retry work only | Parse/audio/manual duplicate work | Root workflow and idempotency lineage |
| Operational maintenance | No | None | Engineering/incident effort | Work-log or issue classification |

---

## 6. Quality Findings

### Output-aware analysis changes selection, but not all downstream semantics

**Type:** Measured finding / Code-supported inference

Replaying current selection logic on the inspected long-document workspace (258,194 source tokens) produced:

| Duration | Selected blocks | Deferred blocks | Selected input tokens | Source-token coverage | Max claims/block | Neighbor context | Target output words | Main risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 5 min | 9 | 189 | 12,747 | 4.94% | 2 | 0 | 650 | Core nuance may be missed |
| 10 min | 13 | 185 | 18,307 | 7.09% | 2 | 0 | Historical artifacts are not comparable to current logic |
| 15 min | 20 | 178 | 27,652 | 10.71% | 3 | 0 | Must-cover recall unmeasured |
| 30 min | 40 | 158 | 54,949 | 21.28% | 5 | 1 | Neighbor leakage unmeasured |
| 60 min | 80 | 118 | 109,008 | 42.22% | 7 | 2 | Still excludes most source tokens; padding vs depth untested |

The historical 10-minute artifact selected 40 blocks and 55,913 tokens because it predates a seed-budget correction. Its manifest retained 19.93% of the source and produced 70 claims. This means historical quality/cost cannot be used as a clean estimate of current 10-minute behavior.

`second_pass_for_core_sections` is declared in the analysis profile/data model but is not consumed by the execution path. Moreover, duration requeue updates the brief and episode plan without recomputing the corpus/evidence scope. Existing extraction records are loaded into reconciliation, so profile changes do not implement a correct incremental upgrade/downgrade.

**Impact:** High correctness risk for duration changes and uncertain coverage for long outputs.

**Confidence:** High for the code path and replay; low for actual quality effects.

**Validation:** Produce a frozen 5/15/30/60-minute ladder from identical sources and score must-cover recall, nuance, padding, unsupported claims, and human review time.

### Most auxiliary evidence is produced but not consumed

**Type:** Measured finding / Code-supported inference

The inspected extraction set contains 70 claims, 35 definitions, 30 distinctions, 11 references, 62 `must_not_be_lost` items, and 138 auxiliary evidence items overall; examples, objections, and responses are zero. Downstream reconciliation consumes `extraction.claims`, and the source evidence store persists claim items. The auxiliary objects are not integrated into the episode claim ledger. Only six of 70 ledger claims appear in the inspected plan/script, leaving 91.4% unused in that single run.

**Interpretation:** The pipeline pays to request structured evidence categories that currently have little or no direct downstream effect. Some may indirectly influence claims within the same model response, so their total value is not proven zero.

**Counterfactual:** Either downstream planning should explicitly consume high-value definitions/distinctions/objections, or extraction contracts should omit categories that are not used for the active mode/duration.

**Impact:** High potential token waste and missed synthesis quality.

**Confidence:** High for data flow; medium for net value.

**Validation:** Run extraction variants with and without auxiliary categories, then measure must-cover recall, conceptual distinctions, objections, plan quality, and total pipeline cost.

### Cross-source contradiction handling is not implemented end to end

**Type:** Code-supported inference with runtime confirmation

Per-source claim ledgers are reconciled independently. Episode construction concatenates those ledgers. The disagreement graph inspected from runtime has no edges, and claim disagreement lists are empty. `STATUS.md` also leaves the relevant multi-source milestone incomplete.

**Interpretation:** The pipeline cannot currently demonstrate duplicate collapsing, contradiction preservation, or false-consensus prevention across sources. Attribution remains source-local, but synthesis-level relationships are missing.

**Counterfactual:** A cross-source layer would compare normalized claims while preserving source-specific attribution, qualification, and uncertainty. For a single source it should be bypassed.

**Impact:** P0 content-quality risk for comparative, critical, debate, and conflicting-source modes.

**Confidence:** High.

**Validation:** Use a labeled corpus of complementary and contradictory sources; score contradiction recall, false merges, false consensus, attribution errors, and review time.

### Parse fidelity is guarded, but the gate misses important semantics

Current parse audits cover broad automatic quality and safe-to-proceed status. The inspected reports do not establish page completeness, reading order, heading preservation, semantic OCR error rate, locator correctness, footnote/endnote handling, repeated margins, or formula/table fidelity. The parser benchmark's identical automatic score for materially different outputs demonstrates that the current gate is under-discriminating.

**Failure propagation:** A heading or reading-order error can alter block boundaries; the document map can then omit or mis-rank a concept; extraction may create a decontextualized claim; reconciliation and planning will treat it as valid provenance; a fluent Persian script can hide the upstream defect. The current pipeline does not reliably catch that chain.

### Evidence fidelity cannot be quantified from current artifacts

Artifacts preserve source IDs, block IDs, excerpts, and locators, which is a strong auditability foundation. However, there is no labeled sample for excerpt match, unsupported claims, attribution correctness, inference labeling, or qualification preservation. The model verifier's historical `pass` is not ground truth.

**Insufficient evidence:** unsupported-claim ratio, excerpt validity rate, attribution accuracy, and qualification preservation.

### Coverage and synthesis remain unvalidated

Coverage auditing exists, but there is no human-labeled gap set against which to estimate recall or false alarms. The single inspected run cannot establish that the map, reconciliation, coverage audit, or glossary improves the final learning path. The absence of examples, objections, and responses in the inspected evidence set is a warning for theoretical and critical content, but one run is not enough to estimate prevalence.

### The inspected Persian script is usable as a prototype, not a quality benchmark

The one available explanatory script contains 1,221 stored words and an estimated 9.39 minutes, with 22 alternating turns. Rechecking the current text gives approximately 835 words for speaker A and 386 for speaker B; the editorial/secondary-speaker share is 31.37%. Speaker B asks ten questions, but only one turn was classified as clearly substantive by the inspected deterministic heuristic, and four low-value restatement flags were found.

This supports a narrow observation: the second speaker frequently asks questions but may add limited independent conceptual value in this example. It does not establish general filler rate, Persian naturalness, listening rhythm, or suitability for humanities students.

The glossary contains eight entries; seven preferred forms appear in the script, and six source forms are represented. That demonstrates actual use in this one script, not incremental value relative to a no-glossary variant.

### Audio QA improved on transcript replay, but acoustic quality is unknown

The archived audio revision contains a verified manifest for 24 chunks, with 18 historical passes and six manual-review results. Seven chunks reached generation 2, yet `regenerated_chunk_ids` is empty, creating an audit inconsistency. Final duration is 700.94 seconds versus a 10-minute target (+16.8%) and 564 seconds of expected chunk durations (+24.3%). The final validator does not enforce the episode target duration, and segment duration tolerance is wide.

Replaying current transcript-based QA on the stored expected/ASR text produces 24/24 passes, a minimum similarity of 0.9944, and no missing, truncated, or repeated-text flags. This proves that historical text-level false positives were fixed for this artifact. It does **not** prove pronunciation, prosody, voice consistency, loudness, name/number/date accuracy, instruction leakage, or false-negative performance because the audio files and human listening labels are absent.

Four of five inspected historical audio runs failed, including an invalid-argument run after roughly 12 minutes, QA-related failures, and a missing-verified-artifact failure. The one successful run took approximately 6 minutes 26 seconds. These are too few and too version-mixed for a reliability rate.

### Quality by input and scenario

| Input/scenario | Reliability evidence | Quality evidence | Latency/cost evidence | Common risk | Readiness |
| --- | --- | --- | --- | --- | --- |
| English digital-born article | Several parser runs | Structural benchmark only | Docling/native times available | Slow over-routing, formula loss | Pilot |
| Persian digital-born article | Limited warning-bearing parses | No labeled evidence/script set | Partial parser data | Reading order, terminology | Early pilot |
| Scanned Persian PDF | None | None | None | OCR semantic error, names, order | Not assessed |
| Theoretical book chapter | One long-document workspace | One explanatory script | Historical model runs | Nuance, objections, padding | Prototype |
| Long book/document | One 258k-token case | Selection replay only | Strong map/extraction evidence | Undercoverage at long duration | Prototype |
| EPUB | Two ingestions | Limited downstream sample | Sparse | Notes/structure | Early pilot |
| Single source | Most available evidence | One full script | Partial | Over-processing and verifier value | Prototype |
| Complementary multi-source | No complete trace | None | None | Duplicate/imbalanced synthesis | Not assessed |
| Conflicting multi-source | No complete trace | Structural deficiency found | None | False consensus | Not ready |
| 5-minute output | Code replay only | No output | Estimated selection only | Over-analysis or omission | Not assessed |
| 15-minute output | Code replay only | No output | Estimated selection only | Coverage calibration | Not assessed |
| 30-minute output | Code replay only | No output | Estimated selection only | Neighbor leakage | Not assessed |
| 60-minute output | Code replay only | No output | Estimated selection only | Under-analysis/padding | Not assessed |
| Explanatory mode | One prototype | One script | Partial | Second-speaker filler | Prototype |
| Critical/debate/comparative | No successful representative output | None | Failed/incomplete artifacts only | Missing cross-source disagreement | Not ready |

### Technical quality, content quality, and user value are different

- **Technical quality:** artifact identity, schemas, provenance, and stage checks are comparatively strong.
- **Content quality:** factual support, qualification, cross-source disagreement, and conceptual depth are not sufficiently measured.
- **User-perceived value:** learning gain, willingness to wait, preference over reading a summary, and manual correction burden are entirely unmeasured.

---

## 7. Stage Value Assessment

| Stage | Problem addressed | Downstream use/value evidence | Cost/risk evidence | Classification | Confidence |
| --- | --- | --- | --- | --- | --- |
| Research Brief | Turns intent into constraints | Drives selection and planning | No ablation; user approval adds wait | Keep but optimize | Medium |
| Query Planning | Expands source search | Legacy prompt exists; active independent stage not demonstrated | Dead/ambiguous maintenance surface | Candidate for removal | Medium |
| Source Discovery | Finds external sources | Needed only when user lacks sources | Search cost/quality unmeasured | Make conditional | High |
| Source Triage | Filters candidates | Prevents irrelevant ingestion | Active implementation differs from legacy prompt | Keep as-is | Medium |
| Source Capture | Materializes URL/upload | Required for web sources | External cost unmeasured | Make conditional | High |
| Document Ingestion | Creates stable source identity | Provenance and reuse foundation | Parser routing is expensive | Keep but optimize | High |
| Parse Quality Audit | Chooses acceptable parse | Detects broad failure | Misses structural/semantic differences | Redesign | High |
| Document Map | Provides long-document substrate | Consumed by selection/planning | 28.3% measured model work; quality gain unproven | Keep but optimize | Medium |
| Evidence Extraction | Grounds downstream claims | Core provenance path | 28.0% measured work; auxiliary fields unused | Keep but optimize | High |
| Claim Prioritization | Fits evidence to output budget | Deterministic and consumed | No standalone quality benchmark | Keep as-is | Medium |
| Claim Reconciliation | Deduplicates/normalizes claims | Per-source ledger consumed | High tail; no cross-source synthesis | Redesign | High |
| Disagreement Graph | Preserves conflict | Intended for planning | Runtime graph empty | Redesign / make conditional | High |
| Coverage Audit | Detects missing core material | Produces audit artifact | Human recall/false alarms unknown | Make conditional | Low |
| Glossary | Stabilizes Persian terminology | Terms appear in one script | Historical failures; no ablation | Make conditional | Medium |
| Episode Plan | Creates learning sequence | Direct script contract | Historical high tail/retry failures | Keep but optimize | High |
| Persian Script Generation | Creates user-facing content | Essential | One prototype only | Keep but optimize | High |
| Script Checks | Finds contract/structure errors | Deterministic gate consumed | Cheap relative to model checks | Keep as-is | High |
| Script Verifier | Checks evidence support | Verdict drives revision | Very high input/output ratio; no calibrated accuracy | Make conditional | Medium |
| Script Reviser | Repairs verifier failures | Conditional path | No reliable real sample of localized vs broad rewrite | Insufficient evidence | Low |
| TTS Segmentation | Enables bounded audio work | Chunk IDs support retry/reuse | Segment duration calibration weak | Keep as-is | High |
| TTS Generation | Produces audio | Essential | Cost and Persian quality unknown | Keep but optimize | Medium |
| Audio Assembly | Creates final deliverable | Essential | FFmpeg/environment dependency | Keep as-is | High |
| Audio QA | Detects transcript/audio defects | Drives review/regeneration | Manual acceptance and duration gaps | Redesign | Medium |
| ASR Validation | Compares expected and spoken text | Transcript replay catches text mismatch classes | Acoustic false negatives unknown; cost unknown | Make conditional / calibrate | Low |
| Artifact Persistence | Enables audit/resume | Strong provenance and archives | Duplication/retention growth | Keep but optimize | High |
| Workflow Revision | Preserves history and restarts stages | Archives and partial reuse observed | Duration scope and historical model-run movement issues | Keep but optimize | High |
| Cache/Reuse | Avoids repeat work | Parse/TTS identities show good foundations | Several semantic versions omitted | Redesign | High |

No stage is classified `Keep as-is` solely because it exists, and no model stage is recommended for removal solely because it is expensive. Coverage, glossary, verifier, reviser, and ASR require controlled value tests before stronger decisions.

---

## 8. Failure Propagation and Recovery Analysis

### Failure propagation matrix

| Upstream error | Current detection point | Downstream impact | Current recovery | Residual risk |
| --- | --- | --- | --- | --- |
| OCR error in name/term | Broad parse audit or later ASR/reader review | Wrong entity propagates into claims, Persian script, and pronunciation | Parser fallback/manual warning | High; no semantic OCR benchmark |
| Wrong reading order | Parse audit may miss it | Block boundaries and conceptual dependencies corrupt | Candidate parser selection | High |
| Dropped heading | Parse structure checks, if severe | Map/selection loses topic hierarchy | Alternate parser | Medium-high |
| Footnote merged into body | Usually silent | Attribution/qualification becomes main claim | None specific | High |
| Bad block boundary | Evidence validator may reject excerpt | Decontextualized or duplicated claim | Retry extraction | Medium |
| Incomplete document map | Coverage audit may flag gap | Important blocks never selected | Coverage-triggered review/reanalysis | High; audit accuracy unmeasured |
| Claim loses qualification | Model verifier may flag | Overconfident script | Revision | High; no human ground truth |
| Inference labeled as direct claim | Evidence/schema checks may miss semantics | Unsupported authority in script | Verifier/revision | High |
| Invalid excerpt/locator | Deterministic evidence validation | Claim rejected/retried | Local extraction retry | Medium-low for syntactic mismatch; semantic validity unknown |
| Cross-source contradiction | Current graph does not detect reliably | False consensus or duplicated claims | None end to end | Critical for multi-source modes |
| Plan ignores conceptual dependency | Script checks focus on contract, not pedagogy | List-of-facts episode | User plan review / model verifier | Medium-high |
| Unsupported script transition | Model verifier or human review | Fluent but ungrounded synthesis | Revision | High; verifier accuracy unknown |
| TTS truncation/repetition | ASR similarity/QA | Missing or duplicated audio | Chunk regeneration/manual review | Medium; false negatives unmeasured |
| Pronunciation or voice drift | Human listening only in practice | Reduced trust/comprehension | Manual review/regeneration | High; audio unavailable |

### Recovery matrix

| Failure | Detection | Retry scope | Duplicate-work risk | Data-consistency risk | Current recovery |
| --- | --- | --- | --- | --- | --- |
| Provider timeout/rate limit | Provider attempt record | Key/attempt then logical stage | Medium | Low if no artifact committed | Retry/key rotation |
| API key failure | Provider response | Key rotation | Low-medium | Low | Next key; representative trace recovered |
| Schema failure | Output parser/validator | Logical call | Medium-high | Low | Repair/retry |
| Deterministic rejection | Stage validator | Logical call | High if prompt unchanged | Low | Repair prompt/retry |
| Parser crash | Parser candidate status | Parser/source | Medium | Partial artifacts possible | Alternate parser/manual retry |
| OCR crash | OCR adapter | Source | Medium | Partial artifact risk | Fallback/manual retry |
| Artifact write failure after provider success | Persistence boundary | Often whole logical operation | High duplicate-charge risk | High DB/filesystem divergence risk | No provider idempotency proof |
| DB write failure | Ledger/store layer | Operation/stage | Medium | High | Transaction error/manual retry |
| Process restart | Startup/recovery state | Background task or stage | Medium-high | Stale `running` state | Mark failure/manual resume; no durable queue |
| TTS chunk failure | Per-chunk result | Chunk | Low-medium | Low with chunk identity | Regenerate chunk |
| ASR failure | Per-chunk QA | Chunk | Medium | Low | Retry/manual review |
| Partial audio assembly | Final validation | Assembly | Low if segments retained | Medium final-manifest risk | Reassemble from verified chunks |
| User revision during execution | Workflow state/revision | Depends on transition | High if old task continues | High stale-write risk | No representative concurrency test |

Workspace JSON writes use atomic replacement and SQLite uses transactions/WAL, which are useful safeguards. The unresolved risk is cross-system atomicity: provider success, filesystem artifact writes, and database state are not one transaction. A failure after a paid provider success can therefore cause a second paid call on manual retry.

---

## 9. Ablation and Experiment Results

### Experiments actually performed in this audit

| Comparison | Variant/result | Quality | Latency | Tokens | Retry | Manual work | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Current duration profile replay | 5/10/15/30/60-minute selectors on the same 258k-token source | No human output score | Deterministic selection only | 12.7k to 109.0k selected source tokens | N/A | Not measured | Confirms scaling logic, not quality |
| Historical vs current transcript QA | Archived six-manual result vs replayed current QA | 24/24 current text checks pass; min similarity 0.9944 | Local deterministic replay | No provider tokens | N/A | Not measured | Confirms prior text-level false positives were fixed |
| Parser benchmark | Docling vs MinerU on one technical PDF | Outputs structurally differ despite both score 100 | 305.86s vs 139.99s | N/A | N/A | Not measured | Current gate cannot choose based on important structure |
| Retry outcome analysis | Stage-specific historical retries | No human quality score | Recovery and extra time measured | Partial extra-token counts | Stage-specific | Not measured | Uniform retry policy is not supported |
| Current script heuristic replay | Existing script under current deterministic checks | Secondary speaker mostly asks rather than develops concepts | Local only | N/A | N/A | Not measured | One-example signal only |

No new paid model/provider ablation was run. The repository lacks a frozen, human-rated corpus, so running expensive variants now would produce outputs without a trustworthy decision rule.

### Required ablation designs

| Ablation | Variants | Primary quality metrics | Performance metrics | Decision guardrail |
| --- | --- | --- | --- | --- |
| Document map | With map vs direct selection/extraction | Must-cover recall, locator fidelity, plan coherence, review time | Tokens, latency, calls | Keep only if quality/review benefit exceeds overhead |
| Claim reconciliation | Per-source only vs cross-source reconciliation | Contradiction recall, false consensus, duplicate claims, attribution | Tokens, latency, retries | False merges <=5% and material contradiction improvement |
| Coverage audit | On vs off | Gap-detection recall, false alarms, final omissions | Revision calls, tokens, time | Recall >=80%, false-positive rate <=15% |
| Glossary | On vs deterministic seed vs off | Term consistency, semantic translation, naturalness | Context tokens, latency | >=30% fewer terminology errors with <=5% total-token overhead |
| Script verifier/reviser | Writer only; writer+verifier; writer+reviser; all | Unsupported claims, semantic drift, verifier FP/FN, unnecessary rewrite, Persian naturalness | Total final cost, time, retries | >=25% fewer critical errors; FP <=15%; unnecessary rewrite <=10% |
| Neighbor context | 0 vs 1 vs 2 neighbors | Interpretation fidelity, leakage, excerpt validity | Input tokens, latency | >=5 percentage-point fidelity gain with <=1% leakage |
| Model tier | Cheap vs current vs stronger | Final accepted quality and manual correction | Full pipeline cost, retries, repairs | Non-inferior within 2 points or >=5-point quality gain at accepted cost |

**Insufficient evidence:** No current table can honestly fill the requested `Quality`, `Manual work`, or monetary `Overall verdict` fields for these ablations. Those values require controlled runs and human labels.

---

## 10. Prioritized Recommendations

| ID | Priority | Finding type | Finding and evidence | Proposed change | Quality impact | Latency impact | Cost impact | Effort | Risk | Confidence |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| R1 | P0 | Code-supported inference | Duration requeue changes planning but not current-scope corpus/evidence; old records remain eligible | Make profile changes produce an explicit delta extraction and a current-scope evidence view | High | Medium | Medium | Medium | Medium | High |
| R2 | P0 | Measured + code-supported | 138 auxiliary evidence items are produced but not consumed; second-pass core analysis is unused | Either integrate definitions/distinctions/objections into planning or remove them from profile-specific contracts; implement or remove the dead second-pass flag | High | Medium | High | Medium | Medium | High |
| R3 | P0 | Code-supported inference | Reconciliation is per source and disagreement graph is empty | Add a conditional cross-source reconciliation layer, or explicitly label multi-source conflict handling unsupported | Critical | Medium negative unless conditional | Medium negative | High | High | High |
| R4 | P0 | Instrumentation gap | Ledger is test-polluted, workflow links/cost/quality labels are absent | Isolate test/runtime telemetry and require root-linked workflow, stage, cost, cache, manual-review, and quality lineage | Enables decisions | Neutral | Enables decisions | Medium | Low | High |
| R5 | P1 | Measured finding | One failed Docling attempt took 465s; parser gate scored materially different outputs equally | Use input-type-aware candidate ordering and stronger structural/semantic parse gates | High | High | Medium-high | Medium | Medium | High |
| R6 | P1 | Code-supported inference | Evidence, plan, script, ASR, and QA reuse omit semantic/model/validator versions | Version cache keys by all behavior-changing inputs and store invalidation reasons | High | Medium | Medium | Medium | Low-medium | High |
| R7 | P1/P2 | Measured finding | Retry recovery ranges from 0% to 94.5% by stage; failed-attempt usage is incomplete | Calibrate retry by stage and error class; stop unchanged deterministic repairs with poor recovery | Neutral-to-high | High | High | Medium | Medium | Medium |
| R8 | P1/P2 | Measured + experiment recommendation | Historical writer/verifier share a model; verifier consumed 89.7k tokens across three calls with no human calibration | Configure an independent reviewer, then ablate verifier, glossary, and second-speaker policies; make them risk-conditional | Potentially high | High | High | Medium | Medium | Medium |
| R9 | P2 | Code-supported inference | Sources and historical script segments are serialized despite local independence | Test bounded source-, segment-, TTS-, and ASR-level concurrency with separate rate limiters | Neutral if controlled | High | Neutral/slightly negative | Medium-high | High | Medium |
| R10 | P0/P2 | Measured + instrumentation gap | Historical manual audio results can be accepted; final duration exceeded target 16.8%; acoustic quality absent | Make manual review an explicit gate, enforce calibrated episode-duration bounds, and validate ASR/QA against human-labeled audio | High | Potentially negative | Potentially negative | High | Medium | High for gap, low for calibrated design |

These ten recommendations are intentionally bounded. Generic cache expansion, blanket parallelism, more retries, or automatic model downgrades are not supported by the evidence.

---

## 11. Proposed Target Pipeline

The target is an experiment-backed simplification, not an implementation plan for this audit.

```text
CURRENT
Brief
 -> serial source processing
 -> broad parser candidates
 -> map all selected source structures
 -> duration selection
 -> extraction with partially unused schema
 -> per-source reconciliation
 -> coverage + empty disagreement graph
 -> plan approval
 -> glossary
 -> serial script segments
 -> full verifier/reviser policy
 -> script approval
 -> chunk TTS + ASR/QA
 -> assembly

RECOMMENDED TARGET
Brief + corpus gate
 -> bounded-parallel per-source ingest
 -> type-aware cheapest-capable parser + conditional OCR/fallback
 -> versioned reusable blocks/maps
 -> profile selection + delta extraction + explicit current-scope evidence view
 -> conditional cross-source synthesis for multi-source/conflict modes
 -> deterministic priority/budget + risk-triggered coverage audit
 -> plan with explicit omissions
 -> one plan approval
 -> deterministic terminology seed + conditional model glossary
 -> bounded-parallel script segments with boundary contracts
 -> deterministic checks + risk-targeted independent verifier
 -> localized revision only
 -> early text/audio preview
 -> bounded TTS/ASR with explicit manual-review gate
 -> calibrated duration/checksum validation + assembly
```

### Stage disposition in the target

- **Retain:** provenance-preserving ingestion, block construction, mapping for long/complex documents, evidence extraction, planning, deterministic checks, TTS segmentation, assembly, and versioned persistence.
- **Make conditional:** discovery, OCR, cross-source synthesis, coverage audit, model glossary, model verifier, reviser, and exhaustive ASR.
- **Merge at the workflow level:** deterministic priority, budget, evidence packaging, and plan preparation should not create separate waits.
- **Replace with deterministic logic where validated:** terminology seeding, low-risk structural checks, duplicate detection, duration bounds, and local script contract validation.
- **Parallelize only after rate-limit tests:** sources, independent script segments, TTS chunks, and ASR chunks.
- **Approval points:** retain plan approval and final script/audio acceptance; avoid intermediate approvals unless a quality-risk gate fires.
- **Reuse levels:** content-addressed source/parse/block/map; profile-aware evidence deltas; semantic-versioned plan/script; robust chunk-level audio; every reuse event linked to its source artifact and invalidation reason.

---

## 12. Experiment Backlog

### E1 — Document-map value

- **Hypothesis:** A map improves must-cover recall and review efficiency on long/structured documents enough to justify its model work.
- **Dataset:** At least 30 English/Persian articles, theoretical chapters, and long books with human must-cover annotations.
- **Variants:** Current map; no map with deterministic headings/TF-IDF retrieval; lighter map.
- **Metrics:** Must-cover recall, evidence relevance, locator fidelity, plan coherence, human review minutes, tokens, wall time.
- **Acceptance threshold:** At least +5 percentage points recall or -15% review time, with no material attribution loss and <=20% token overhead.
- **Estimated cost:** Unknown until pricing telemetry exists.
- **Decision rule:** Keep full map only for input classes meeting the threshold; otherwise use the light/deterministic route.

### E2 — Cross-source reconciliation

- **Hypothesis:** Cross-source reconciliation reduces false consensus and duplicate claims without incorrectly merging distinct theoretical positions.
- **Dataset:** At least 20 complementary and 20 contradictory source sets, bilingual where possible.
- **Variants:** Current concatenation; cross-source model reconciliation; deterministic candidate pairing plus model adjudication.
- **Metrics:** Contradiction recall, false merge rate, attribution errors, duplicate rate, review time, tokens, latency.
- **Acceptance threshold:** >=30% reduction in contradiction/consensus errors and <=5% false merges.
- **Estimated cost:** Unknown.
- **Decision rule:** Enable only for multi-source sets and risk modes if the threshold is met.

### E3 — Coverage audit

- **Hypothesis:** Coverage audit identifies true must-cover gaps that would survive into the final episode.
- **Dataset:** Human-labeled omissions across at least 50 source/brief pairs.
- **Variants:** Off; current audit; deterministic coverage checks plus model escalation.
- **Metrics:** Gap recall, false-positive rate, revision calls, final omissions, review time.
- **Acceptance threshold:** Recall >=80%, false-positive rate <=15%, and measurable final-omission reduction.
- **Estimated cost:** Unknown.
- **Decision rule:** Make conditional if benefit concentrates in long/critical modes.

### E4 — Glossary

- **Hypothesis:** A glossary materially improves terminology consistency and semantic translation in Persian.
- **Dataset:** 30 scripts rich in theoretical terms, reviewed by bilingual humanities readers.
- **Variants:** No glossary; deterministic term seed; current model glossary.
- **Metrics:** Term inconsistency, mistranslation, unnatural phrasing, context tokens, latency.
- **Acceptance threshold:** >=30% fewer terminology errors with <=5% total-token overhead.
- **Estimated cost:** Unknown.
- **Decision rule:** Prefer deterministic seed unless model glossary clears the threshold.

### E5 — Writer, verifier, and reviser

- **Hypothesis:** Verification and targeted revision reduce critical unsupported claims more than they introduce false alarms and semantic drift.
- **Dataset:** At least 100 evidence-script sections with independent human labels.
- **Variants:** Writer only; writer+verifier; writer+reviser; writer+verifier+reviser.
- **Metrics:** Unsupported claims, verifier precision/recall, unnecessary rewrite rate, semantic drift, Persian naturalness, final total cost and review time.
- **Acceptance threshold:** >=25% fewer critical errors, verifier false positives <=15%, unnecessary rewrites <=10%.
- **Estimated cost:** Unknown.
- **Decision rule:** Apply verifier/reviser only to risk-scored sections if full coverage fails cost-benefit criteria.

### E6 — Neighbor context

- **Hypothesis:** One neighbor improves interpretation; a second gives diminishing returns and increases leakage.
- **Dataset:** Ambiguous and boundary-sensitive blocks from at least 40 documents.
- **Variants:** Zero, one, and two neighbors.
- **Metrics:** Interpretation fidelity, excerpt validity, cross-block leakage, tokens, latency.
- **Acceptance threshold:** >=5 percentage-point fidelity gain and <=1% leakage.
- **Estimated cost:** Unknown.
- **Decision rule:** Choose the smallest context that meets the threshold by source type.

### E7 — Model tier and final-system cost

- **Hypothesis:** Some cheap models are cheaper only per call, while a stronger model may reduce repair/retry/manual work enough to lower final cost.
- **Dataset:** Frozen inputs from E1-E6.
- **Variants:** Fast/cheap, current, stronger, with fixed prompts and validators.
- **Metrics:** Accepted quality, retries, repairs, verifier/reviser use, failed-workflow cost, human correction, wall time, currency cost.
- **Acceptance threshold:** Non-inferior quality within two points at lower final cost, or >=5-point quality gain at an explicitly accepted premium.
- **Estimated cost:** Cannot estimate without a pricing snapshot.
- **Decision rule:** Route by stage/risk/input class, not one global model.

### E8 — Stability and tail risk

- **Hypothesis:** Current average-looking outputs hide substantial run-to-run variance.
- **Dataset:** Representative single/multi-source and duration/mode matrix.
- **Variants:** At least five repeated runs for each fixed configuration.
- **Metrics:** Quality variance, latency/tokens variance, catastrophic failure rate, worst-decile manual work.
- **Acceptance threshold:** Catastrophic quality failure <1%; stage-specific variance budgets defined before test.
- **Estimated cost:** High and currently unknown.
- **Decision rule:** Do not claim production readiness until tail risk is bounded.

### E9 — Audio QA calibration

- **Hypothesis:** Current ASR/QA thresholds detect meaningful Persian audio errors with acceptable manual-review burden.
- **Dataset:** At least 300 labeled Persian chunks with seeded omissions, repetitions, truncations, names, dates, numbers, pronunciation, and voice drift.
- **Variants:** Deterministic transcript metrics; current ASR/QA; risk-conditional ASR; human review.
- **Metrics:** Error recall/precision by class, manual-review precision, cost, latency.
- **Acceptance threshold:** False-negative rate <=1% for missing/repeated/truncated speech; manual-review precision >=80%.
- **Estimated cost:** Unknown.
- **Decision rule:** Use exhaustive ASR only if it clears the threshold; otherwise target high-risk chunks.

### E10 — Bounded concurrency

- **Hypothesis:** Source/segment/chunk concurrency reduces wall time without raising retries or lowering consistency.
- **Dataset:** Fixed 1/2/4/8-source workflows and 24/48-chunk audio workloads.
- **Variants:** Worker counts 1, 2, and 4 with separate provider limiters.
- **Metrics:** Wall time, total work, rate limits, retries, SQLite busy time, artifact conflicts, quality.
- **Acceptance threshold:** >=30% wall-time reduction, no quality regression, retry increase <=5 percentage points, no consistency failure.
- **Estimated cost:** Similar provider work if retry behavior stays stable; currency amount unknown.
- **Decision rule:** Select the lowest concurrency that captures most of the gain.

---

## 13. Instrumentation Requirements for the Separate Observability Mission

These are requirements only; none were implemented during this audit.

### Identity and lifecycle

- One immutable root `workflow_run_id` and `trace_id` per user-triggered run.
- Required `project_id`, revision, subject/source/episode ID, stage, operation, environment, code commit, prompt version, requested model, and resolved model.
- Explicit queued, started, provider-started, validation-started, artifact-committed, user-visible, and ended timestamps.
- Terminal reconciliation for stale `running` rows after process restart.

### Timing

- Separate queue wait, deterministic compute, provider time, retry backoff, validation/repair, DB time, file-I/O time, and user/human wait.
- Parent-child spans for source, block, segment, and chunk workers.
- Time to first useful artifact, plan, script preview, audio preview, and final output.
- Worker concurrency and join/critical-path attribution.

### Usage and cost

- Complete input, output, thinking, cached, and failed-attempt usage.
- Versioned pricing snapshot and computed cost per provider attempt and logical operation.
- Search calls, URL-context units, OCR CPU/GPU time, TTS characters/audio seconds, ASR audio seconds, storage bytes, and bandwidth.
- Explicit distinction between provider retry, key rotation, logical repair, deterministic rejection, timeout, and user-forced regeneration.

### Cache and reuse

- Cache lookup key, hit/miss, reused artifact ID/hash, originating workflow, invalidation reason, forced refresh, and estimated avoided calls/tokens/time.
- Artifact lineage and semantic versions for parser, prompt, model, validator, thresholds, profile, mode, duration, and language.
- Duplicate artifact and orphan reconciliation metrics.

### Quality and human work

- Human review start, submit, disposition, active time, edited fields, edit distance, regenerated stages, and reason codes.
- Links from source/block/evidence/claim/plan/script/chunk to quality labels.
- Parse fidelity, evidence support, attribution, qualification, coverage, synthesis, Persian naturalness, terminology, dialogue value, and audio-error rubrics.
- Blind double-rating and adjudication metadata; LLM-judge scores may be auxiliary but never ground truth.
- Repeated-run configuration identity for variance/tail-risk measurement.

### Operational safeguards

- Environment isolation so unit/integration tests never enter the production ledger.
- Provider-success/artifact-commit idempotency keys to detect duplicate-charge risk.
- SQLite busy/lock duration, transaction retry, and artifact-write failure events.
- Durable job IDs and restart/resume checkpoints if background tasks remain asynchronous.

---

## 14. Appendix

### Appendix A — Core SQLite queries

```sql
SELECT name, type
FROM sqlite_master
WHERE type IN ('table', 'index', 'view')
ORDER BY type, name;
```

For every relevant table:

```sql
PRAGMA table_info(model_calls);
PRAGMA index_list(model_calls);
PRAGMA table_info(model_attempts);
PRAGMA index_list(model_attempts);
PRAGMA table_info(pipeline_runs);
PRAGMA index_list(pipeline_runs);
PRAGMA table_info(pipeline_spans);
PRAGMA index_list(pipeline_spans);
PRAGMA table_info(pipeline_events);
PRAGMA index_list(pipeline_events);
```

Status and metadata coverage:

```sql
SELECT status, COUNT(*) AS calls
FROM model_calls
GROUP BY status
ORDER BY calls DESC;

SELECT
  SUM(project_id IS NULL) AS missing_project,
  SUM(workflow_run_id IS NULL) AS missing_workflow,
  SUM(trace_id IS NULL) AS missing_trace,
  SUM(pipeline_trace_id IS NULL) AS missing_pipeline_trace,
  SUM(parent_span_id IS NULL) AS missing_parent_span,
  SUM(subject IS NULL) AS missing_subject,
  SUM(resolved_model IS NULL) AS missing_resolved_model,
  SUM(prompt_version IS NULL) AS missing_prompt_version,
  SUM(ended_at IS NULL OR latency_ms IS NULL) AS missing_end_or_latency,
  SUM(input_tokens IS NULL OR output_tokens IS NULL) AS missing_usage,
  SUM(cost_micros IS NULL OR pricing_version IS NULL) AS missing_cost
FROM model_calls;
```

Stage/operation summary:

```sql
SELECT
  stage,
  operation,
  status,
  COUNT(*) AS calls,
  AVG(latency_ms) AS mean_latency_ms,
  MAX(latency_ms) AS max_latency_ms,
  SUM(COALESCE(input_tokens, 0)) AS input_tokens,
  SUM(COALESCE(output_tokens, 0)) AS output_tokens,
  SUM(COALESCE(thinking_tokens, 0)) AS thinking_tokens,
  SUM(COALESCE(cached_tokens, 0)) AS cached_tokens
FROM model_calls
GROUP BY stage, operation, status
ORDER BY stage, operation, status;
```

Provider attempts for a logical call:

```sql
SELECT
  call_id,
  attempt_number,
  provider_key_id,
  status,
  error_type,
  started_at,
  ended_at,
  latency_ms
FROM model_attempts
WHERE call_id = :call_id
ORDER BY attempt_number;
```

Trace reconstruction:

```sql
SELECT
  started_at,
  ended_at,
  stage,
  operation,
  resolved_model,
  attempt_number,
  latency_ms,
  input_tokens,
  output_tokens,
  thinking_tokens,
  cached_tokens,
  status
FROM trace_nodes
WHERE trace_id = :trace_id
ORDER BY started_at;
```

Potential repeated successful calls:

```sql
SELECT
  project_id,
  stage,
  prompt_version,
  resolved_model,
  input_hash,
  COUNT(*) AS successful_calls,
  SUM(COALESCE(input_tokens, 0)) AS input_tokens,
  SUM(COALESCE(output_tokens, 0) + COALESCE(thinking_tokens, 0)) AS generated_tokens
FROM model_calls
WHERE status = 'succeeded'
GROUP BY project_id, stage, prompt_version, resolved_model, input_hash
HAVING COUNT(*) > 1
ORDER BY successful_calls DESC;
```

### Appendix B — Selected traces

#### Rejected evidence call followed by recovery

Trace/call identifier prefix: `5fcbd1e2...`

| Sequence | Stage | Attempt/result | Latency | Tokens | Status |
| ---: | --- | --- | ---: | ---: | --- |
| 1 | Evidence extraction | Logical output rejected | 2.605s | 3,299 | Rejected |
| 2 | Evidence extraction | Later accepted result | 1.973s | 3,140 | Succeeded |

This shows content rejection is distinguishable from provider HTTP success in at least one stored path.

#### Failed document-map call

Trace/call identifier prefix: `ce427fe4...`

| Sequence | Stage | Attempt/result | Latency | Status |
| ---: | --- | --- | ---: | --- |
| 1 | Document-map part | Failed | 62.257s | Failed |
| 2 | Backoff | Delay | 1.000s | Waiting |
| 3 | Document-map part | Failed | 1.918s | HTTP 503 |

The trace demonstrates that provider/error and backoff time can materially differ from a simple final call latency.

#### Provider key rotation

| Attempt | Result | Latency |
| ---: | --- | ---: |
| 1 | HTTP 429 on key 1 | 0.756s |
| 2 | HTTP 401 on key 2 | 2.192s |
| 3 | Success on key 3 | 6.275s |
| **Total** | Logical provider sequence | **9.298s** |

#### Inspected successful script/audio branch

The archived `f781...` branch includes a 10-minute explanatory plan/script and a 24-chunk audio manifest. Historical script-stage calls included glossary at 19.687s; segment calls at 52.936s, 23.185s, 31.442s, and 27.698s; a failed verifier at 55.678s; and a later verifier at 29.817s. The serial segment sum is approximately 133 seconds, while the largest call is approximately 53 seconds. This is a theoretical concurrency bound, not an observed wall-time gain.

No complete multi-source, duration-change, or current prompt-version trace was available.

### Appendix C — Key code locations

- Pipeline declaration: [`src/thesisound/pipeline.py`](../src/thesisound/pipeline.py)
- Serial source build path: [`src/thesisound/services/corpus_building.py`](../src/thesisound/services/corpus_building.py)
- Duration requeue: [`src/thesisound/services/episode_planning_run.py`](../src/thesisound/services/episode_planning_run.py)
- Evidence reuse: [`src/thesisound/services/source_analysis_service.py`](../src/thesisound/services/source_analysis_service.py)
- Episode reuse identity: [`src/thesisound/services/episode_reuse.py`](../src/thesisound/services/episode_reuse.py)
- Claim reconciliation: [`src/thesisound/services/claim_reconciler.py`](../src/thesisound/services/claim_reconciler.py)
- Disagreement graph: [`src/thesisound/services/disagreement_graph.py`](../src/thesisound/services/disagreement_graph.py)
- Output-aware profile: [`src/thesisound/services/analysis_profile.py`](../src/thesisound/services/analysis_profile.py)
- Document inspection/routing: [`src/thesisound/services/document_inspector.py`](../src/thesisound/services/document_inspector.py), [`src/thesisound/services/parser_router.py`](../src/thesisound/services/parser_router.py)
- Document mapping: [`src/thesisound/services/document_mapper.py`](../src/thesisound/services/document_mapper.py)
- Evidence extraction: [`src/thesisound/services/evidence_extractor.py`](../src/thesisound/services/evidence_extractor.py)
- Audio workflow: [`src/thesisound/services/audio_pipeline_service.py`](../src/thesisound/services/audio_pipeline_service.py)
- Workflow revision: [`src/thesisound/services/workflow_revision.py`](../src/thesisound/services/workflow_revision.py)
- Manual audio-review acceptance configuration: [`src/thesisound/config.py`](../src/thesisound/config.py)

### Appendix D — Assumptions and unresolved questions

1. Archived model-run records are treated as historical evidence, not as behavior of the current prompt versions.
2. Repeated input hashes are treated as potential reuse opportunities, not automatically as waste.
3. Timestamp gaps are not treated as compute or user wait without explicit activity spans.
4. Cached tokens are not translated into currency savings without provider-specific pricing.
5. ASR transcript agreement is not treated as proof of acoustic quality.
6. Current reviewer configuration is evaluated from repository/environment defaults; production secrets may differ, but no contrary runtime evidence was available.
7. Test success is evidence of implementation consistency, not content quality.
8. The single script and audio manifest are not assumed representative.

Unresolved questions requiring new data:

- What is the human-rated unsupported-claim and attribution-error rate by input class?
- Does the document map improve final quality enough to justify its dominant model work?
- What is the actual end-to-end latency distribution, including queueing and approvals?
- What is the currency cost per accepted episode, including failed workflows and manual correction?
- How often do duration/mode/brief revisions occur in real use?
- What is the production cache hit rate, and which hits are semantically safe?
- Does a distinct verifier model reduce correlated errors?
- What is the Persian audio false-negative rate for pronunciation, truncation, repetition, and voice drift?
- Does a 60-minute output become more nuanced, or merely longer?

---

## Final Answer

If Thesisound's goal is to produce accurate, trustworthy, listenable Persian episodes with the least time, cost, and manual intervention, its strongest current value comes from **provenance-preserving ingestion, reusable document structure, evidence-grounded planning, deterministic contract checks, versioned artifacts, and chunk-level audio recovery**. These components create a credible foundation for auditability and localized recovery.

The value of **coverage audit, glossary, full-script verifier/reviser, second-speaker dialogue, exhaustive ASR, and the map's incremental quality gain** remains unproven because no frozen human-rated comparison exists. They should not be removed on intuition, but they should become conditional or remain experimental until ablation data justifies their cost.

The components that need direct change are **duration/profile-scoped reuse, unused evidence contracts, cross-source reconciliation, parser routing and quality gates, semantic cache invalidation, stage-specific retry policies, reviewer independence, and explicit audio/manual-review acceptance**. Before broad architectural optimization, Thesisound also needs isolated, root-linked production telemetry that connects cost and latency to accepted quality and human effort. Without that link, the pipeline can be made faster, but not demonstrably better.
