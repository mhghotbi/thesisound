from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/thesisound/services/evidence_extractor.py"

text = TARGET.read_text(encoding="utf-8")
start = text.index("        workers = min(self.max_workers, len(pending))")
end = text.index("\n        ordered = [results[block.block_id] for block in pending]", start)
replacement = '''        workers = min(self.max_workers, len(pending))
        if workers == 1:
            for block in pending:
                block_id, outcome = work(block)
                breaker_reason = hand_over(block_id, outcome)
                if breaker_reason is not None:
                    raise ModelProviderError(
                        "Evidence extraction circuit breaker opened after "
                        f"{_BREAKER_CONSECUTIVE_FAILURES} consecutive provider failures "
                        f"before any block succeeded: {breaker_reason}"
                    )
        else:
            # Preserve the configured fan-out for small batches. For larger batches,
            # probe at most the breaker limit first: an immediate global provider
            # failure is then bounded at three calls, while the first usable answer
            # releases the normal worker pool. This also preserves the established
            # max_workers concurrency contract for batches that fit in one wave.
            bound_work = tracing.bind_context(work)
            next_index = 0
            futures = {}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                initial = (
                    len(pending)
                    if len(pending) <= workers
                    else min(len(pending), _BREAKER_CONSECUTIVE_FAILURES)
                )
                for _ in range(initial):
                    block = pending[next_index]
                    next_index += 1
                    futures[pool.submit(bound_work, block)] = block.block_id
                try:
                    while futures:
                        future = next(as_completed(futures))
                        futures.pop(future)
                        block_id, outcome = future.result()
                        breaker_reason = hand_over(block_id, outcome)
                        if breaker_reason is not None:
                            for remaining in futures:
                                remaining.cancel()
                            pool.shutdown(wait=True, cancel_futures=True)
                            raise ModelProviderError(
                                "Evidence extraction circuit breaker opened after "
                                f"{_BREAKER_CONSECUTIVE_FAILURES} consecutive provider "
                                f"failures before any block succeeded: {breaker_reason}"
                            )
                        if succeeded > 0:
                            while len(futures) < workers and next_index < len(pending):
                                block = pending[next_index]
                                next_index += 1
                                futures[pool.submit(bound_work, block)] = block.block_id
                except BaseException:
                    # Drop work that has not started but let in-flight blocks land: each
                    # finished block is already saved and is retried by the next attempt
                    # unless it was extracted successfully.
                    pool.shutdown(wait=True, cancel_futures=True)
                    raise
'''
TARGET.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
