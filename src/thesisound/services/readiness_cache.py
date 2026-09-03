"""A memo in front of :func:`project_readiness`, keyed on the project's own files.

``project_readiness`` re-derives every gate from the artifacts on disk. That is the
point of it — the readiness page's whole claim is that its numbers are computed now,
not read back from something a run wrote earlier — but it costs roughly 60ms per
project warm and 250ms cold, dominated by re-running parse quality over every source
document. The project list needs that verdict for every row it renders, so a
seventeen-project workspace spent over a second before the first byte went out.

The key has two halves, because either one alone can be fooled:

* ``project.updated_at``, which ``save_project`` always advances and which lives in
  the file's *content*, so it is immune to filesystem timestamp granularity. Windows
  moves a file's modification time in ~15ms steps, so two saves inside one step share
  an mtime; their ``updated_at`` values still differ by microseconds.
* a fingerprint of the project directory — newest mtime, file count, total bytes —
  which catches artifact writes that never touch ``project.json`` at all.

Two trees are excluded from the fingerprint because readiness never opens them and
both grow without bound: ``model-runs`` (the append-only record of what each model
call sent and received) and ``archive`` (what a rewind moved aside). Excluding a tree
readiness *does* read would let a stale verdict outlive an edit — the exact class of
untruth this phase exists to remove — so the set stays narrow and stays commented.

The readiness page itself does not come through here. It is the authority every other
surface is checked against, and it runs the gates fresh on every request.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from uuid import UUID

from thesisound.services.readiness import GateResult, project_readiness

#: Trees readiness never reads. Both are append-only and dwarf everything else.
_UNREAD_TREES = frozenset({"model-runs", "archive"})

#: Bounded so a long-lived process cannot hold one entry per project ever rendered.
_MAX_ENTRIES = 256

_Key = tuple[str, str]
_Fingerprint = tuple[str | None, int, int, int]
_cache: dict[_Key, tuple[_Fingerprint, list[GateResult]]] = {}


def _directory_fingerprint(project_dir: Path) -> tuple[int, int, int]:
    """(newest mtime in ns, file count, total bytes) over every tree readiness reads."""
    newest = 0
    count = 0
    total = 0
    stack = [str(project_dir)]
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in _UNREAD_TREES:
                        stack.append(entry.path)
                    continue
                stat = entry.stat()
            except OSError:
                continue
            count += 1
            total += stat.st_size
            newest = max(newest, stat.st_mtime_ns)
    return newest, count, total


def cached_project_readiness(
    *,
    project_id: UUID,
    workspace_root: Path,
    updated_at: datetime | None = None,
) -> list[GateResult]:
    """The gate results :func:`project_readiness` returns, recomputed whenever they move.

    Pass ``updated_at`` from the already-loaded project; it is the stronger half of
    the key and costs nothing at the call site.
    """
    key = (str(workspace_root), str(project_id))
    current = (
        updated_at.isoformat() if updated_at is not None else None,
        *_directory_fingerprint(workspace_root / str(project_id)),
    )
    hit = _cache.get(key)
    if hit is not None and hit[0] == current:
        return hit[1]
    results = project_readiness(project_id=project_id, workspace_root=workspace_root)
    if len(_cache) >= _MAX_ENTRIES:
        _cache.clear()
    _cache[key] = (current, results)
    return results


def clear_cache() -> None:
    """Drop every memo."""
    _cache.clear()
