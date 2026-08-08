from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Literal


class AudioAssembler:
    def __init__(
        self,
        *,
        ffmpeg_command: str = "ffmpeg",
        silence_milliseconds: int = 220,
    ) -> None:
        self.ffmpeg_command = ffmpeg_command
        self.silence_milliseconds = silence_milliseconds

    def assemble(self, wav_segments: list[bytes]) -> tuple[bytes, Literal["ffmpeg_loudnorm"]]:
        raw = concatenate_wav(
            wav_segments,
            silence_milliseconds=self.silence_milliseconds,
        )
        command = shutil.which(self.ffmpeg_command)
        if command is None:
            raise RuntimeError("FFmpeg is required for final loudness normalization.")
        with tempfile.TemporaryDirectory(prefix="thesisound-audio-") as directory:
            source = Path(directory) / "raw.wav"
            output = Path(directory) / "normalized.wav"
            source.write_bytes(raw)
            completed = subprocess.run(
                [
                    command,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-af",
                    "loudnorm=I=-16:TP=-1.5:LRA=11",
                    "-ar",
                    "24000",
                    "-ac",
                    "1",
                    str(output),
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if completed.returncode != 0 or not output.exists():
                detail = completed.stderr.strip() or "FFmpeg did not create normalized audio."
                raise RuntimeError(detail)
            return output.read_bytes(), "ffmpeg_loudnorm"


def concatenate_wav(
    wav_segments: list[bytes],
    *,
    silence_milliseconds: int = 220,
) -> bytes:
    if not wav_segments:
        raise ValueError("At least one WAV segment is required.")
    output = io.BytesIO()
    params: tuple[int, int, int] | None = None
    frames: list[bytes] = []
    for payload in wav_segments:
        with wave.open(io.BytesIO(payload), "rb") as source:
            current = (
                source.getnchannels(),
                source.getsampwidth(),
                source.getframerate(),
            )
            if params is None:
                params = current
            elif current != params:
                raise ValueError("All WAV segments must use identical PCM parameters.")
            frames.append(source.readframes(source.getnframes()))
    assert params is not None
    channels, width, rate = params
    silence_frames = round(rate * silence_milliseconds / 1000)
    silence = b"\x00" * silence_frames * channels * width
    with wave.open(output, "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(width)
        target.setframerate(rate)
        for index, frame_payload in enumerate(frames):
            if index:
                target.writeframes(silence)
            target.writeframes(frame_payload)
    return output.getvalue()
