# R7 — Parallel `document_map_part` with a probe breaker

**Implementation plan. Follow it as written.**

Audience: a junior/mid-level developer on this codebase.
Source of the requirement: [`docs/thesisound-pipeline-audit.md`](thesisound-pipeline-audit.md) §10, row **R7**.

> R7 🟧P1 — «document map سریالی است و ۶۰٪ توکن را دارد» → «همان الگوی fan-out با circuit-breaker که در `evidence_extractor` هست را روی partitions ببر»
> Quality ~0 · **Latency high** · Cost ~0 · Effort medium · Risk medium (Gemini quota) · Confidence High

This is a **latency-only** change. It must not alter a single field of the produced
`DocumentMap`. Every design decision below is already made; do not substitute your own.
If you believe a decision is wrong, stop and raise it before writing code — do not
silently pick a different approach.

---

## 1. What the change is

`DocumentMapperService.map_document` maps a long document by splitting it into
partitions and calling the model once per partition. Today that loop is sequential:

`src/thesisound/services/document_mapper.py:85`

```python
for part_number, partition in enumerate(partitions, start=1):
    cached_draft = self._load_cached_partition(project_id, partition)
    ...
    draft, last_part_record = self._map_partition(...)
    self._save_cached_partition(partition, draft)
```

Measured on the only real end-to-end run (audit §5): `document_map_part` is **60.3% of
all input tokens and 28.3% of all provider time**, at `avg_concurrency = 1.00`, p50 8.0 s
and max 118.8 s per call. Six partitions run back to back.

After this change the partitions that are **not** already in the partition cache run
concurrently through a bounded `ThreadPoolExecutor`, behind a one-call probe.

### Already done — do not redo

- **R3 (partition checkpointing)** is implemented: `DocumentMapPartCache`,
  `_load_cached_partition`, `_save_cached_partition`. R7 builds on it.
- **R1 (merge no-op)** and **R6 (verifier independence)** are unrelated to this task.

---

## 2. Scope

### In scope

| # | Change | File |
|---|---|---|
| 1 | `max_workers` on `DocumentMapperService`, fan-out + probe breaker | `src/thesisound/services/document_mapper.py` |
| 2 | Unique temp filename + non-fatal write in the partition cache | `src/thesisound/services/document_map_part_cache.py` |
| 3 | `document_map_workers` setting | `src/thesisound/config.py` |
| 4 | Wire the setting at both composition roots | `src/thesisound/web/corpus_runtime.py`, `src/thesisound/source_cli.py` |
| 5 | Document both worker knobs | `.env.example` |
| 6 | Tests | `tests/test_document_mapper_large_inputs.py` |

### Explicitly out of scope — do not touch

- `document_map_merge` (R1), `script_verifier` routing (R6), `audio_qa` (R2).
- `EvidenceExtractorService` — read it as the reference pattern, change nothing in it.
- TTS / ASR chunk loops in `audio_pipeline_service.py` — a separate item.
- The single-partition path (`len(partitions) == 1`) — it stays one serial call on
  stage `document_map`, no threads, no probe.
- The merge payload budget, the coverage validators, `_namespace_draft`,
  `_merge_part_drafts`, `_partition_blocks`.
- Prompt files and prompt versions. `PART_BUILDER_VERSION` **stays at 1** — the cached
  payload format does not change, so bumping it would throw away every cached partition
  for no reason.

---

## 3. Locked design decisions

Read all seven before writing code.

### D1 — Cache lookups stay serial, on the calling thread, before any fan-out

Do **not** move `_load_cached_partition` into the worker. Three reasons:

1. `tests/test_document_mapper_large_inputs.py::test_partition_cache_emits_hit_and_miss_events`
   asserts the exact ordered sequence `["miss", "miss", "miss", "miss", "hit", "hit", "hit", "hit"]`.
   Worker-side lookups make that order nondeterministic.
2. A fully cached document must not start a thread pool at all.
3. They are small local file reads; there is nothing to parallelise.

**Accepted trade-off, document it in a code comment:** today, two partitions with
byte-identical content inside one document share a content key, so the second one hits
the cache entry the first one just wrote. With lookups hoisted up front, both are mapped.
This costs one extra call in a rare case; the alternative (per-content-key dedup with
block-ID remapping) would duplicate `DocumentMapPartCache.load` for no measured benefit.
The observed corpus has six distinct partitions and zero duplicates.

Because of this trade-off, **D2 is mandatory, not optional.**

### D2 — Partition cache writes must be concurrency-safe

`DocumentMapPartCache.save` writes to a fixed `"<key>.json.tmp"` in a **shared**
directory (`<workspace>/_shared/document-map-parts`). Under fan-out two writers can now
target the same name — same-content partitions (D1), or two corpus builds running at
once. On Windows the second `Path.replace` can raise `PermissionError`, which would
propagate out of the worker and **abort a document map because a cache write failed**.

Fix: unique temp name per write, and treat a failed cache write as non-fatal.

### D3 — The breaker is a probe of exactly one partition

`EvidenceExtractorService` opens its breaker after `_BREAKER_CONSECUTIVE_FAILURES = 3`
consecutive failures, because there a per-block failure is *tolerated* (the block is
recorded `skipped` and the run continues).

Here a partition failure is **fatal**: coverage must be 100%, so the first failure aborts
`map_document`. That makes 3 the wrong number. Submit **one** partition, wait for it to
succeed, and only then release the full fan-out.

- Cost when the provider is healthy: one serial call (p50 8 s) before the wave.
- Saving when the provider is dead/revoked: you pay for 1 failed `document_map_part`
  instead of N. That is the most expensive call class in the pipeline (~35k input tokens
  per call on the observed run).

Constant: `_PROBE_PARTITIONS = 1`, with a comment stating exactly the above.

### D4 — Cache the partition **inside** the worker

`_save_cached_partition` must run in the worker, immediately after `_map_partition`
returns — not on the main thread after the join. When one partition fails, partitions
still in flight must still reach the cache; they were already paid for. This is what
keeps `test_successful_partitions_are_persisted_but_the_failed_partition_is_not`
deterministic under fan-out.

### D5 — Never submit more futures than the pool has threads; never cancel

Refill with `while len(futures) < workers`. Then every submitted future is running or
about to run, nothing sits queued, and leaving the `with ThreadPoolExecutor(...)` block
on an exception waits for the in-flight calls (`shutdown(wait=True)` is what `__exit__`
does) and lets them cache.

Do **not** call `pool.shutdown(cancel_futures=True)`. Cancelling a submitted-but-not-yet-
started future would discard a partition nondeterministically and make the cache-count
tests flaky.

The first observed failure is the one that propagates. Exceptions raised by other
in-flight partitions are discarded — their futures are never read. That is correct: one
report is enough, and the stage aborts either way.

### D6 — The first exception propagates unchanged

`future.result()` re-raises the original exception object. Do **not** wrap it, do not
convert it to a `ModelProviderError`, do not build a "circuit breaker opened" message the
way `evidence_extractor` does. `test_successful_partitions_are_not_remapped_after_a_later_partition_fails`
matches `DeterministicValidationError, match="forced partition failure"` and must keep
passing verbatim.

### D7 — Default `max_workers=1`

Match `EvidenceExtractorService.__init__`. The default keeps ~20 existing test
constructions on the sequential path. Concurrency is switched on only by the two
composition roots reading `Settings.document_map_workers` (whose own default is 4).

---

## 4. Invariants that must not change

Each row is enforced by a test that already exists. If you break one, you changed
behaviour, not just scheduling.

| # | Invariant | Guarded by |
|---|---|---|
| I1 | `part_drafts` are namespaced in partition order (`part-0001:` … `part-000N:`) | `test_large_document_is_mapped_without_omitting_or_duplicating_blocks` |
| I2 | Mapped block IDs equal the input block order exactly, no gaps, no duplicates | same, plus `test_map_draft_normalizes_unknown_and_overlapping_blocks` |
| I3 | The returned record, when the merge is skipped or fails, is the **highest-numbered partition that actually called the model** | `test_merge_failure_degrades_to_partition_union_with_a_warning`, `test_oversized_merge_payload_skips_the_merge_without_discarding_partitions` |
| I4 | All partitions cached + merge fails ⇒ returned record is `None` | `test_all_cached_partitions_and_a_merge_failure_return_no_record_and_mark_the_source` |
| I5 | A partition failure aborts with the original exception type and message | `test_successful_partitions_are_not_remapped_after_a_later_partition_fails` |
| I6 | Partitions that ran before the abort are cached; the failed one is not | `test_successful_partitions_are_persisted_but_the_failed_partition_is_not` |
| I7 | `cache.lookup` events, one per partition, in partition order | `test_partition_cache_emits_hit_and_miss_events` |
| I8 | `require_complete_coverage=True` on every multi-partition call | `test_large_document_rejects_any_omitted_content_block` |
| I9 | Merge variables and payload budget unchanged | `test_merge_variables_expose_the_trimmed_partition_payload`, `test_merge_payload_budget_is_independent_of_the_partition_text_budget` |
| I10 | Single-partition documents use stage `document_map`, no fan-out | `tests/test_source_analysis.py` (constructs `DocumentMapperService(runner)` with the default budget) |

**One accepted behaviour change, and only one:** on the abort path, every partition now
emits a `cache.lookup` event, because all lookups happen before any call. Previously the
partitions after the failing one emitted none. No test asserts the old count. Note it in
the PR description.

---

## 5. Implementation

### Step 1 — `src/thesisound/services/document_mapper.py`

**1a. Imports.** Add to the existing import block:

```python
from collections.abc import Callable, Iterable          # Callable is new
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
```

**1b. Module constant**, next to the class:

```python
# Evidence extraction tolerates a failed block, so its breaker waits for three
# consecutive failures. A failed partition is fatal here -- the document map must
# cover every content block -- so the first failure already aborts the stage. The
# breaker is therefore a single probe: prove the provider answers once before
# paying for the fan-out. document_map_part is the largest call class in the
# pipeline (60% of all input tokens on the 2026-08-09 run).
_PROBE_PARTITIONS = 1
```

**1c. Constructor.** Add a keyword-only `max_workers: int = 1`, validated like
`EvidenceExtractorService`:

```python
        part_cache: DocumentMapPartCache | None = None,
        max_workers: int = 1,
    ) -> None:
        if maximum_input_characters < 1:
            raise ValueError("maximum_input_characters must be positive.")
        if maximum_merge_payload_characters < 1:
            raise ValueError("maximum_merge_payload_characters must be positive.")
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1.")
```

and `self.max_workers = max_workers` after `self.part_cache = part_cache`.

**1d. Replace the sequential loop** (current lines 83–100) with:

```python
        drafts, records = self._map_partitions(
            project_id=project_id,
            source_id=source_id,
            partitions=partitions,
            model=model,
            prompt_version=prompt_version,
        )
        part_drafts = [_namespace_draft(draft, index + 1) for index, draft in enumerate(drafts)]
        last_part_record = next(
            (record for record in reversed(records) if record is not None),
            None,
        )
```

Everything from `sections = [...]` down is unchanged.

Note the simplification: `_namespace_draft` is now applied uniformly on the main thread
to cached and freshly-mapped drafts alike. The cache still stores **un-namespaced**
drafts — do not change that.

**1e. New method `_map_partitions`**, placed directly after `map_document`:

```python
    def _map_partitions(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        partitions: list[list[SourceDocumentBlock]],
        model: str,
        prompt_version: str | None,
    ) -> tuple[list[DocumentMapDraft], list[ModelRunRecord | None]]:
        """One draft per partition, in partition order, reusing the cache.

        Lookups stay on this thread and in order: they are local reads, a fully
        cached document must not start a pool, and `cache.lookup` has to arrive in
        a stable order. The cost is that two partitions with identical text are
        both mapped instead of the second reading what the first just wrote --
        rare, and cheaper than remapping block IDs for a second-chance lookup.
        """

        drafts: list[DocumentMapDraft | None] = [None] * len(partitions)
        records: list[ModelRunRecord | None] = [None] * len(partitions)
        pending: list[int] = []
        for index, partition in enumerate(partitions):
            cached = self._load_cached_partition(project_id, partition)
            if cached is None:
                pending.append(index)
            else:
                drafts[index] = cached

        def work(index: int) -> tuple[int, DocumentMapDraft, ModelRunRecord]:
            partition = partitions[index]
            with tracing.span(
                "corpus.map_partition",
                component="corpus",
                project_id=project_id,
                subject_type="partition",
                subject_id=f"part-{index + 1:04d}",
            ):
                draft, record = self._map_partition(
                    project_id=project_id,
                    source_id=source_id,
                    blocks=partition,
                    model=model,
                    prompt_version=prompt_version,
                    part_number=index + 1,
                    require_complete_coverage=True,
                )
            # Inside the worker on purpose: when one partition fails, the ones
            # still in flight were already paid for and must reach the cache.
            self._save_cached_partition(partition, draft)
            return index, draft, record

        workers = min(self.max_workers, len(pending))
        if workers <= 1:
            for index in pending:
                _, draft, record = work(index)
                drafts[index] = draft
                records[index] = record
        else:
            self._fan_out_partitions(work, pending, workers, drafts, records)

        complete = [draft for draft in drafts if draft is not None]
        if len(complete) != len(partitions):
            raise AssertionError("A document-map partition finished without a draft.")
        return complete, records
```

`workers <= 1` also covers `pending == []` (`min(n, 0) == 0`), which is the
fully-cached case: the loop body never runs and no pool is created.

**1f. New method `_fan_out_partitions`**, directly after it:

```python
    def _fan_out_partitions(
        self,
        work: Callable[[int], tuple[int, DocumentMapDraft, ModelRunRecord]],
        pending: list[int],
        workers: int,
        drafts: list[DocumentMapDraft | None],
        records: list[ModelRunRecord | None],
    ) -> None:
        """Probe one partition, then run the rest concurrently.

        Never more futures in flight than the pool has threads, so nothing sits
        queued and nothing is cancelled: leaving the `with` block on an exception
        waits for the calls already running and keeps what they cached. The first
        failure observed is the one that propagates, unwrapped -- a failed
        partition aborts the whole map, so there is nothing to degrade to.
        """

        bound_work = tracing.bind_context(work)
        position = 0
        futures: set[Future[tuple[int, DocumentMapDraft, ModelRunRecord]]] = set()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for _ in range(min(_PROBE_PARTITIONS, len(pending))):
                futures.add(pool.submit(bound_work, pending[position]))
                position += 1
            while futures:
                future = next(as_completed(futures))
                futures.discard(future)
                index, draft, record = future.result()
                drafts[index] = draft
                records[index] = record
                # Reached only after a success, which is what releases the probe.
                while len(futures) < workers and position < len(pending):
                    futures.add(pool.submit(bound_work, pending[position]))
                    position += 1
```

`tracing.bind_context` is **required**. `ThreadPoolExecutor` does not copy contextvars,
so without it every partition span is orphaned at the trace root — see
`tests/test_tracing_propagation.py::test_threadpoolexecutor_orphans_children_without_bind_context`,
which exists specifically to document this trap. Wrap on the submitting thread, as
written.

### Step 2 — `src/thesisound/services/document_map_part_cache.py`

Add `from uuid import uuid4` to the imports. Replace the tail of `save`:

```python
        path = self.path(content_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(cached.model_dump(mode="json"), ensure_ascii=False, indent=2)
        # Partitions are mapped concurrently and two partitions with identical text
        # share a content key, so a fixed ".tmp" name would let two writers interleave
        # into the same file. Caching is an optimisation: a write that loses the race
        # must return None, never fail the document map that already paid for the call.
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(payload + "\n", encoding="utf-8")
            temporary.replace(path)
        except OSError:
            temporary.unlink(missing_ok=True)
            return None
        return path
```

The docstring on `load` already says it never raises; leave it. Do not add a lock —
content-addressed writes of identical bytes do not need one.

### Step 3 — `src/thesisound/config.py`

Directly **after** `evidence_extraction_workers` (line 73):

```python
    # document_map_part is the largest call class in the pipeline (60% of input tokens,
    # 28% of provider time on the 2026-08-09 run) and partitions are independent, so
    # this is where fan-out buys the most wall clock. One partition is probed first: a
    # partition failure aborts the whole map, so a dead provider must not be paid for
    # once per partition. Set to 1 to restore the fully sequential behaviour.
    document_map_workers: int = Field(default=4, ge=1, le=16)
```

Same default, bounds and style as `evidence_extraction_workers`. Do not invent a
different range.

### Step 4 — Composition roots

`src/thesisound/web/corpus_runtime.py:50`:

```python
            document_mapper=DocumentMapperService(
                runner,
                part_cache=DocumentMapPartCache(workspace.root),
                max_workers=settings.document_map_workers,
            ),
```

`src/thesisound/source_cli.py:195`:

```python
        document_mapper=DocumentMapperService(
            runner,
            part_cache=DocumentMapPartCache(root),
            max_workers=settings.document_map_workers,
        ),
```

These are the only two production constructions — confirm with:

```bash
grep -rn "DocumentMapperService(" src/
```

### Step 5 — `.env.example`

In the **“Provider execution and retry policy”** block, after
`THESISOUND_MODEL_RETRY_BASE_SECONDS=1`, add:

```
# Per-stage fan-out. Both stages are one independent model call per unit of work.
# 1 restores fully sequential execution; raise only if the Gemini key pool has the
# quota headroom, because every worker is a concurrent request against it.
THESISOUND_EVIDENCE_EXTRACTION_WORKERS=4
THESISOUND_DOCUMENT_MAP_WORKERS=4
```

`THESISOUND_EVIDENCE_EXTRACTION_WORKERS` is currently undocumented; adding the new knob
without its sibling would be actively confusing. That one line is in scope. Nothing else
in `.env.example` changes.

No other doc needs editing — `grep -rn "evidence_extraction_workers" docs/` returns only
the audit, which is a dated snapshot and must not be rewritten.

---

## 6. Tests

**Put every new test in `tests/test_document_mapper_large_inputs.py`.** Do not create a
new module: `HierarchicalRunner`, `_blocks`, `_map` and `_document_map_signature` already
live there, `tests/` is not an importable package, and duplicating a 70-line test double
is worse than a longer file. Add them under a section comment:

```python
# --------------------------------------------------------------------------
# R7: partition fan-out
# --------------------------------------------------------------------------
```

### 6.0 Preparation

**Make `HierarchicalRunner` thread-safe.** `self.stages.append` is called from worker
threads now. `list.append` happens to be atomic on CPython today, but do not rely on it:

```python
class HierarchicalRunner:
    def __init__(self) -> None:
        self.stages: list[str] = []
        self._stages_lock = Lock()

    def _record_stage(self, stage: str) -> None:
        with self._stages_lock:
            self.stages.append(stage)
```

Replace both `self.stages.append(...)` sites (`HierarchicalRunner.run` and
`FailingLastPartitionRunner.run`) with `self._record_stage(...)`. Import `Lock` from
`threading`.

**Extend the `_map` helper** so parametrised tests can pass workers:

```python
def _map(mapper: DocumentMapperService, blocks: list[SourceDocumentBlock]):
```

stays as is — instead pass `max_workers=` at each `DocumentMapperService(...)` call site
in the new tests. Do not change `_map`'s signature.

**Partition arithmetic you will rely on** (`_blocks()` is 8 blocks of ~312 chars, paired
under 4 headings):

- `maximum_input_characters=900` → **4 partitions of 2 blocks**
- `maximum_input_characters=500` → **8 partitions of 1 block**

### 6.1 Parametrise two existing tests over `[1, 4]`

These are the abort-path invariants (I5, I6). They must hold on both paths.

```python
@pytest.mark.parametrize("max_workers", [1, 4])
def test_successful_partitions_are_not_remapped_after_a_later_partition_fails(
    tmp_path: Path, max_workers: int
) -> None:
```

Pass `max_workers=max_workers` to **both** `DocumentMapperService(...)` constructions in
the body. The assertion `second_runner.stages == ["document_map_part", "document_map_merge"]`
stays unchanged and must stay deterministic: probe part 1 → succeed → submit parts 2, 3, 4
→ part 4 raises → the pool waits for 2 and 3, both cache → 3 hits on the rerun.

Same treatment for:

```python
@pytest.mark.parametrize("max_workers", [1, 4])
def test_successful_partitions_are_persisted_but_the_failed_partition_is_not(
    tmp_path: Path, max_workers: int
) -> None:
```

and in that test **change line 519** from `glob("*.json.tmp")` to `glob("*.tmp")` — the
temp filename now carries a uuid, so the old pattern would match nothing and the
assertion would pass vacuously.

### 6.2 New tests — required list

Write all eleven. Each one exists to catch a specific way this change can go wrong.

**T1 — fan-out produces a byte-identical map.** The single most important test.

```python
def test_fan_out_produces_the_same_document_map_as_the_serial_path() -> None:
    blocks = _blocks()
    serial, _ = _map(
        DocumentMapperService(HierarchicalRunner(), maximum_input_characters=500, max_workers=1),
        blocks,
    )
    parallel, _ = _map(
        DocumentMapperService(HierarchicalRunner(), maximum_input_characters=500, max_workers=8),
        blocks,
    )
    assert _document_map_signature(parallel) == _document_map_signature(serial)
```

**T2 — section IDs keep partition order regardless of completion order.** With
`max_workers=8` over 8 partitions, assert the mapped section IDs are exactly
`["part-0001:section", ..., "part-0008:section"]` and that mapped block IDs equal
`[block.block_id for block in blocks]`. (I1, I2.)

**T3 — real concurrency.** Prove R7 actually did something. Add a runner that blocks the
post-probe partitions on a `threading.Barrier`; if execution is still serial the barrier
times out and the test fails loudly instead of hanging.

```python
class BarrierPartitionRunner(HierarchicalRunner):
    """Deadlocks unless the post-probe partitions really overlap."""

    def __init__(self, parties: int, timeout: float = 5.0) -> None:
        super().__init__()
        self.barrier = Barrier(parties, timeout=timeout)
        self._intervals_lock = Lock()
        self.intervals: list[tuple[int, float, float]] = []

    def run(self, **kwargs):
        part_number = None
        if kwargs["stage"] == "document_map_part":
            part_number = int(kwargs["variables"]["part_number"])
        started = perf_counter()
        if part_number is not None and part_number > _PROBE_PARTITIONS:
            self.barrier.wait()
        execution = super().run(**kwargs)
        if part_number is not None:
            with self._intervals_lock:
                self.intervals.append((part_number, started, perf_counter()))
        return execution
```

```python
def test_partitions_after_the_probe_run_concurrently() -> None:
    blocks = _blocks()
    runner = BarrierPartitionRunner(parties=3)  # partitions 2, 3, 4
    mapper = DocumentMapperService(runner, maximum_input_characters=900, max_workers=4)

    _map(mapper, blocks)  # BrokenBarrierError here means execution is still serial

    assert len(runner.intervals) == 4
```

**T4 — the probe runs alone.** Reuse `BarrierPartitionRunner` from T3:

```python
def test_the_probe_partition_finishes_before_any_other_partition_starts() -> None:
    ... same setup, then:
    probe = next(item for item in runner.intervals if item[0] == 1)
    others = [item for item in runner.intervals if item[0] != 1]
    assert len(others) == 3
    assert all(other[1] >= probe[2] for other in others)
```

**T5 — the breaker: a dead provider costs exactly one call.** Mirror of
`test_breaker_aborts_after_three_consecutive_provider_failures` in `test_evidence_fanout.py`.

```python
class DeadProviderRunner(HierarchicalRunner):
    def run(self, **kwargs):
        if kwargs["stage"] == "document_map_part":
            self._record_stage("document_map_part")
            raise ModelProviderError("provider is unreachable")
        return super().run(**kwargs)


def test_a_dead_provider_is_paid_for_once_not_once_per_partition() -> None:
    blocks = _blocks()
    mapper = DocumentMapperService(
        DeadProviderRunner(), maximum_input_characters=500, max_workers=8
    )  # 8 partitions

    runner = mapper.model_runner
    with pytest.raises(ModelProviderError, match="provider is unreachable"):
        _map(mapper, blocks)

    assert runner.stages.count("document_map_part") == 1
```

Import `ModelProviderError` from `thesisound.modeling`.

**T6 — the original exception type survives the pool.** (I5, D6.) With
`FailingLastPartitionRunner(failing_part_number=4)`, `maximum_input_characters=900`,
`max_workers=4`, assert `pytest.raises(DeterministicValidationError, match="forced partition failure")`
— and assert the raised exception is **not** a `ModelProviderError` and its message
contains no "circuit breaker" text.

**T7 — the returned record is the last partition in partition order.** (I3.)

```python
class StampedPartitionRunner(HierarchicalRunner):
    def run(self, **kwargs):
        execution = super().run(**kwargs)
        if kwargs["stage"] == "document_map_part":
            execution.record.input_hash = f"part-{int(kwargs['variables']['part_number']):04d}"
        return execution


def test_the_returned_record_is_the_last_partition_in_partition_order() -> None:
    mapper = DocumentMapperService(
        StampedPartitionRunner(),
        maximum_input_characters=900,
        maximum_merge_payload_characters=1,  # forces the merge to be skipped
        max_workers=4,
    )

    _, run = _map(mapper, _blocks())

    assert run is not None
    assert run.input_hash == "part-0004"
```

If `ModelRunRecord` turns out to be frozen, use
`execution.model_copy(update={"record": execution.record.model_copy(update={...})})`
instead of assigning — check before assuming.

**T8 — a fully cached document starts no pool and calls nothing.** Run once to warm the
cache, then run again with `max_workers=8` and assert
`second_runner.stages == ["document_map_merge"]`.

**T9 — a mixed hit/miss run keeps the cache-event order.** Warm the cache with
`maximum_input_characters=900` (4 partitions), delete exactly one cache file, rerun with
`max_workers=4` and a `recording_tracer`, then assert the `cache.lookup` results list has
length 4 with exactly one `"miss"`, and that the miss is at the index of the deleted
partition. (I7.)

**T10 — partition spans are children of the caller's span, one per model call.**

```python
def test_partition_spans_attach_to_the_calling_span(recording_tracer: tracing.Tracer) -> None:
    blocks = _blocks()
    mapper = DocumentMapperService(
        HierarchicalRunner(), maximum_input_characters=900, max_workers=4
    )

    with tracing.span("corpus.map_document", component="corpus") as parent:
        _map(mapper, blocks)

    spans = recording_tracer.sink.find("corpus.map_partition")
    assert len(spans) == 4
    assert all(span.parent_span_id == parent.context.span_id for span in spans)
    assert {span.subject_id for span in spans} == {
        "part-0001", "part-0002", "part-0003", "part-0004",
    }
```

Then a second run against the warm cache must produce **zero** `corpus.map_partition`
spans.

**T11 — concurrent cache writes of one content key are safe.** (D2.) Directly against
`DocumentMapPartCache`, no mapper involved:

```python
def test_concurrent_saves_of_one_content_key_leave_a_valid_file(tmp_path: Path) -> None:
    cache = DocumentMapPartCache(tmp_path)
    blocks = _blocks()[:2]
    content_key = partition_block_key(blocks)
    draft = DocumentMapDraft(
        working_thesis="thesis",
        sections=[
            DocumentMapDraftSection(
                section_id="section",
                source_block_ids=[block.block_id for block in blocks],
                title="Mapped partition",
                function="argument",
            )
        ],
    )

    with ThreadPoolExecutor(max_workers=8) as pool:
        for future in [pool.submit(cache.save, content_key, blocks, draft) for _ in range(8)]:
            future.result()

    assert len(list(cache.root.glob("*.json"))) == 1
    assert list(cache.root.glob("*.tmp")) == []
    assert cache.load(content_key, blocks) is not None
```

### 6.3 Composition-root tests

Add at the end of the same file, under a second section comment. These catch the classic
"implemented but never wired" failure.

```python
def test_corpus_runtime_wires_the_document_map_worker_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(corpus_runtime, "GeminiStructuredModel", lambda **_: object())
    settings = Settings(
        environment="test",
        workspace_root=tmp_path / "workspaces",
        ingestion_artifact_root=tmp_path / "artifacts",
        web_session_secret="test-secret-that-is-long-enough",
        document_map_workers=3,
    )
    builder = corpus_runtime.create_corpus_builder(settings, WorkspaceStore(settings.workspace_root))

    service = builder.analysis_service_factory()

    assert service.document_mapper.max_workers == 3
```

Copy the `Settings(...)` shape from `tests/test_runtime_reconciliation.py::_settings`
(including `ui_demo_mode=False` if that field exists there) rather than inventing one.

Write the equivalent for the CLI root against `source_cli._model_service(settings, root)`,
monkeypatching `source_cli.GeminiStructuredModel`.

Plus two settings-contract assertions:

```python
def test_document_map_workers_defaults_to_four_and_is_bounded() -> None:
    assert Settings(environment="test").document_map_workers == 4
    with pytest.raises(ValidationError):
        Settings(environment="test", document_map_workers=0)
    with pytest.raises(ValidationError):
        Settings(environment="test", document_map_workers=17)
```

and one for the constructor guard:

```python
def test_document_mapper_rejects_a_worker_count_below_one() -> None:
    with pytest.raises(ValueError, match="max_workers"):
        DocumentMapperService(HierarchicalRunner(), max_workers=0)
```

### 6.4 Test hygiene

- No `sleep()` anywhere. T3/T4 use a `Barrier` with a timeout — that is the whole point:
  a serial implementation fails in 5 s rather than hanging CI.
- Every new test must pass with `-p no:randomly` and repeated: run
  `uv run pytest tests/test_document_mapper_large_inputs.py --count=20` if
  `pytest-repeat` is available, otherwise loop the command 20 times. A fan-out test that
  passes once proves nothing.
- Do not assert on wall-clock durations. Overlap is proven by the barrier, not by timing.

---

## 7. Verification

Run in order. All must be green before you open the PR.

```bash
uv run ruff check .
```

```bash
uv run pytest tests/test_document_mapper_large_inputs.py tests/test_document_map_part_cache.py tests/test_evidence_fanout.py tests/test_tracing_propagation.py -v
```

```bash
uv run pytest
```

Repeat-run the fan-out file to shake out ordering flakes:

```bash
for i in 1 2 3 4 5 6 7 8 9 10; do uv run pytest tests/test_document_mapper_large_inputs.py -q || break; done
```

Then walk this checklist by hand:

- [ ] `grep -rn "DocumentMapperService(" src/` — both production sites pass `max_workers`.
- [ ] `grep -rn "for part_number, partition in enumerate" src/` — no hits left.
- [ ] `grep -rn "bind_context" src/thesisound/services/document_mapper.py` — exactly one hit.
- [ ] `_save_cached_partition` is called from inside `work`, not from `map_document`.
- [ ] `PART_BUILDER_VERSION` is still `1`.
- [ ] `_PROBE_PARTITIONS` is `1` and carries the comment from Step 1b.
- [ ] `document_map_workers` sits directly after `evidence_extraction_workers` in `config.py`.
- [ ] `.env.example` has both worker lines.
- [ ] `map_document`'s signature and return type are unchanged.
- [ ] No change to `evidence_extractor.py`, `audio_qa.py`, `audio_pipeline_service.py`,
      any prompt file, or any file under `prompts/`.

**No live provider run.** The audit was produced without provider spend and this task
does not authorise any. If a live validation is wanted, it needs explicit approval and a
cost estimate first — the natural one is a rerun of the Arendt EPUB (~760k input tokens),
comparing wall clock and asserting the `DocumentMap` is unchanged.

---

## 8. Rollout and rollback

- **Kill switch:** `THESISOUND_DOCUMENT_MAP_WORKERS=1` restores the exact sequential
  behaviour with no code change. Say this in the PR description.
- **Quota is the live risk** (the audit rates R7's risk “medium — Gemini quota”). With
  `document_map_workers=4` and `evidence_extraction_workers=4` the pool can see 4
  concurrent requests per stage — the stages do not overlap, so the peak stays 4, not 8.
  `GeminiKeyPool` is `RLock`-guarded and rotates keys on 429, so this is safe by
  construction; if 429s rise on the first real run, drop the setting to 2.
- **First real run, check these three things** in `workspaces/<project>/model-runs/`:
  1. `document_map_part` records overlap in time (start ≈ `started_at − latency_ms`;
     remember `started_at` is really the *end* time — audit §4, R4).
  2. The number of `document_map_part` records equals the number of partitions — no
     duplicate `input_hash` values, which would mean partitions were paid for twice.
  3. `_shared/document-map-parts/` holds one `.json` per partition and zero `.tmp`.

---

## 9. Definition of done

1. Steps 1–5 implemented exactly as specified.
2. Sections 6.1–6.3 written, all passing, ten consecutive clean runs of the mapper test file.
3. Full `uv run pytest` and `uv run ruff check .` green.
4. Section 7 checklist walked.
5. PR description states: the kill switch, the one accepted behaviour change from §4
   (cache-lookup events on the abort path), the D1 trade-off (identical partitions mapped
   twice), and that no live provider run was performed.

**Do not** bundle R1, R2, R4 or R8 into this PR, and do not "improve" the merge, the
verifier or the audio QA while you are in the file. One recommendation, one PR.
