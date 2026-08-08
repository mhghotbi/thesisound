from __future__ import annotations

import io
import sys
import wave
from array import array

from thesisound.audio import WavValidationReport


class AudioValidator:
    def __init__(
        self,
        *,
        expected_sample_rate_hz: int = 24_000,
        duration_tolerance_ratio: float = 0.65,
    ) -> None:
        self.expected_sample_rate_hz = expected_sample_rate_hz
        self.duration_tolerance_ratio = duration_tolerance_ratio

    def validate(
        self,
        wav_bytes: bytes,
        *,
        expected_duration_seconds: float | None = None,
    ) -> WavValidationReport:
        issues: list[str] = []
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as source:
                channels = source.getnchannels()
                sample_width = source.getsampwidth()
                sample_rate = source.getframerate()
                frames = source.getnframes()
                payload = source.readframes(frames)
        except (EOFError, wave.Error) as exc:
            return WavValidationReport(
                verdict="reject",
                duration_seconds=0,
                sample_rate_hz=1,
                channels=1,
                sample_width_bytes=1,
                frame_count=0,
                peak_ratio=0,
                issues=[f"Invalid WAV container: {exc}"],
            )

        duration = frames / sample_rate if sample_rate else 0
        if channels != 1:
            issues.append("Audio must be mono.")
        if sample_width != 2:
            issues.append("Audio must use 16-bit PCM samples.")
        if sample_rate != self.expected_sample_rate_hz:
            issues.append(
                f"Expected {self.expected_sample_rate_hz} Hz, received {sample_rate} Hz."
            )
        if frames <= 0 or duration <= 0:
            issues.append("Audio contains no frames.")
        if expected_duration_seconds is not None:
            low = expected_duration_seconds * (1 - self.duration_tolerance_ratio)
            high = expected_duration_seconds * (1 + self.duration_tolerance_ratio)
            if duration < max(0.5, low):
                issues.append("Audio is materially shorter than the expected speech duration.")
            if duration > max(2.0, high):
                issues.append("Audio is materially longer than the expected speech duration.")

        peak_ratio = _peak_ratio(payload, sample_width)
        if peak_ratio >= 0.999:
            issues.append("Audio appears clipped at full scale.")
        return WavValidationReport(
            verdict="reject" if issues else "pass",
            duration_seconds=duration,
            sample_rate_hz=sample_rate,
            channels=channels,
            sample_width_bytes=sample_width,
            frame_count=frames,
            peak_ratio=peak_ratio,
            issues=issues,
        )


def _peak_ratio(payload: bytes, sample_width: int) -> float:
    if sample_width != 2 or not payload:
        return 0
    samples = array("h")
    samples.frombytes(payload)
    if sys.byteorder != "little":
        samples.byteswap()
    peak = max((abs(value) for value in samples), default=0)
    return min(1.0, peak / 32767)
