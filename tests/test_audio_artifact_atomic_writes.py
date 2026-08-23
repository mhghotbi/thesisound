from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from thesisound.services import audio_artifact_store
from thesisound.services.audio_artifact_store import (
    _STALE_TEMPORARY_AGE_SECONDS,
    _atomic_write_bytes,
    _atomic_write_text,
)


def _temporaries(destination: Path) -> list[Path]:
    return sorted(
        child
        for child in destination.parent.iterdir()
        if child.name.startswith(f"{destination.name}.") and child.name.endswith(".tmp")
    )


def test_concurrent_writes_to_one_path_never_tear(tmp_path: Path) -> None:
    """Writers to a shared destination must not land in one another's file.

    A temporary named only after the destination is shared by every concurrent
    writer, so they interleave into one file and then race to rename it away.
    That surfaced two ways: a FileNotFoundError for the losers, and — worse —
    a destination silently holding a mixture of two writers' bytes.
    """

    writers = 4
    rounds = 15
    # Self-identifying payloads: distinct byte value, distinct length.
    payloads = [bytes([65 + index]) * ((index + 1) * 4096) for index in range(writers)]

    errors: list[BaseException] = []

    def worker(target: Path, index: int, barrier: threading.Barrier) -> None:
        barrier.wait()
        try:
            _atomic_write_bytes(target, payloads[index])
        except BaseException as exc:  # noqa: BLE001 — collected for assertion below
            errors.append(exc)

    for round_index in range(rounds):
        target = tmp_path / f"final{round_index}.wav"
        barrier = threading.Barrier(writers)
        threads = [
            threading.Thread(target=worker, args=(target, index, barrier))
            for index in range(writers)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors, errors
        # Whichever writer won, the file must be exactly one payload — never a
        # blend, and never truncated.
        assert target.read_bytes() in payloads
        assert _temporaries(target) == []


def test_a_failed_write_leaves_no_temporary_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unique temporaries cannot be reused, so a failed write must clean up."""

    def explode(source: Path, destination: Path) -> None:
        raise OSError("disk went away")

    monkeypatch.setattr(audio_artifact_store, "_replace_atomically", explode)

    target = tmp_path / "chunks.json"
    with pytest.raises(OSError, match="disk went away"):
        _atomic_write_text(target, "{}\n")

    assert _temporaries(target) == []
    assert not target.exists()


def test_stale_temporaries_are_swept_but_live_ones_are_spared(tmp_path: Path) -> None:
    """The sweep reclaims crash orphans without touching a writer in flight."""

    target = tmp_path / "final.wav"
    target.write_bytes(b"original")

    orphan = tmp_path / f"final.wav.{uuid4().hex}.tmp"
    orphan.write_bytes(b"abandoned by a crashed run")
    stale = time.time() - _STALE_TEMPORARY_AGE_SECONDS - 60
    os.utime(orphan, (stale, stale))

    in_flight = tmp_path / f"final.wav.{uuid4().hex}.tmp"
    in_flight.write_bytes(b"another writer is still filling this")

    unrelated = tmp_path / f"final.mp3.{uuid4().hex}.tmp"
    unrelated.write_bytes(b"a different destination's temporary")
    os.utime(unrelated, (stale, stale))

    _atomic_write_bytes(target, b"replacement")

    assert target.read_bytes() == b"replacement"
    assert not orphan.exists()
    assert in_flight.exists(), "swept a temporary a live writer could still be using"
    assert unrelated.exists(), "swept another destination's temporary"
