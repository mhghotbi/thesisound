from __future__ import annotations

import io
import shutil
import threading
import wave
from pathlib import Path
from uuid import uuid4

import pytest

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
    """Overlapping encodes used to share final.mp3.partial and lose the file."""
    store = AudioArtifactStore(tmp_path / "workspaces")
    project_id = uuid4()
    wav_path = store.audio_dir(project_id) / "final.wav"
    wav_path.write_bytes(_wav(seconds=1.0))

    errors: list[BaseException] = []
    ok = 0
    lock = threading.Lock()

    def worker() -> None:
        nonlocal ok
        try:
            path = store.write_final_mp3_from_wav(project_id)
            assert path.exists() and path.stat().st_size > 0
            with lock:
                ok += 1
        except BaseException as exc:  # noqa: BLE001 — collected for assertion below
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    assert ok == 4
    assert store.final_mp3_path(project_id).stat().st_size > 0
