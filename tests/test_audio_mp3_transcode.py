from __future__ import annotations

import io
import shutil
import threading
import time
import wave
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from thesisound.services import audio_artifact_store
from thesisound.services.audio_artifact_store import AudioArtifactStore


def _wav(seconds: float = 0.25, *, sample_rate: int = 24_000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(b"\x00\x00" * round(sample_rate * seconds))
    return output.getvalue()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_write_final_mp3_from_wav_succeeds(tmp_path: Path) -> None:
    store = AudioArtifactStore(tmp_path / "workspaces")
    project_id = uuid4()
    store.save_final_audio(project_id, _wav())

    mp3 = store.final_mp3_path(project_id)
    assert mp3.exists()
    assert mp3.stat().st_size > 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_concurrent_mp3_encodes_do_not_raise_empty_streamable_error(
    tmp_path: Path,
) -> None:
    """Overlapping encodes must not collide on final.mp3.

    Each encode already writes its own partial file; what still collided was
    the rename onto the shared destination, which Windows refuses while
    another rename holds it. One round of this races by luck, so run many and
    release the threads from a barrier to make the renames actually overlap.
    """

    store = AudioArtifactStore(tmp_path / "workspaces")
    rounds = 25
    writers = 4

    errors: list[BaseException] = []
    ok = 0
    lock = threading.Lock()

    def worker(project_id: UUID, barrier: threading.Barrier) -> None:
        nonlocal ok
        barrier.wait()
        try:
            path = store.write_final_mp3_from_wav(project_id)
            assert path.exists() and path.stat().st_size > 0
            with lock:
                ok += 1
        except BaseException as exc:  # noqa: BLE001 — collected for assertion below
            with lock:
                errors.append(exc)

    for _ in range(rounds):
        project_id = uuid4()
        (store.audio_dir(project_id) / "final.wav").write_bytes(_wav(seconds=0.4))
        barrier = threading.Barrier(writers)
        threads = [
            threading.Thread(target=worker, args=(project_id, barrier))
            for _ in range(writers)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert store.final_mp3_path(project_id).stat().st_size > 0

    assert not errors, errors
    assert ok == rounds * writers


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_mp3_encode_waits_out_a_reader_holding_the_previous_file(
    tmp_path: Path,
) -> None:
    """A download in flight must not fail the next encode.

    `FileResponse` streams final.mp3 with an open handle, and on Windows that
    blocks the rename onto it — a holder no in-process lock can serialise, so
    the replace has to retry until the reader lets go.
    """

    store = AudioArtifactStore(tmp_path / "workspaces")
    project_id = uuid4()
    (store.audio_dir(project_id) / "final.wav").write_bytes(_wav(seconds=0.4))
    store.write_final_mp3_from_wav(project_id)

    released = threading.Event()

    def reader() -> None:
        with store.final_mp3_path(project_id).open("rb") as handle:
            handle.read(1)
            released.wait(timeout=5.0)

    failure: list[BaseException] = []

    def encoder() -> None:
        try:
            store.write_final_mp3_from_wav(project_id)
        except BaseException as exc:  # noqa: BLE001 — a thread's error is otherwise lost
            failure.append(exc)

    holder = threading.Thread(target=reader)
    holder.start()
    try:
        encode = threading.Thread(target=encoder)
        encode.start()
        # Outlive at least the first few retry waits, then let the reader go.
        time.sleep(0.3)
        released.set()
        encode.join(timeout=30.0)
        assert not encode.is_alive()
    finally:
        released.set()
        holder.join(timeout=5.0)

    assert not failure, failure

    assert store.final_mp3_path(project_id).stat().st_size > 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_a_failed_replace_leaves_no_partial_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each encode's partial is uniquely named, so a lost race must clean up."""

    store = AudioArtifactStore(tmp_path / "workspaces")
    project_id = uuid4()
    (store.audio_dir(project_id) / "final.wav").write_bytes(_wav(seconds=0.4))

    def explode(source: Path, destination: Path) -> None:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(audio_artifact_store, "_replace_atomically", explode)

    with pytest.raises(PermissionError):
        store.write_final_mp3_from_wav(project_id)

    leftovers = [
        child
        for child in store.audio_dir(project_id).iterdir()
        if child.name.endswith(".partial")
    ]
    assert leftovers == []
