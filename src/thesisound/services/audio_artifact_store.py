from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel

from thesisound import tracing
from thesisound.audio import (
    AsrTranscript,
    AudioChunk,
    AudioPipelineManifest,
    AudioSegmentQa,
    AudioSegmentRecord,
)
from thesisound.services.lineage_events import emit_cache_lookup
from thesisound.services.semantic_identity import first_mismatch

_QA_IDENTITY_FIELDS = (
    "qa_version",
    "pass_threshold",
    "review_threshold",
    "missing_sentence_threshold",
)


class AudioArtifactStore:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def audio_dir(self, project_id: UUID, *, create: bool = True) -> Path:
        path = self.workspace_root / str(project_id) / "audio"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def binding_path(self, project_id: UUID) -> Path:
        return self.audio_dir(project_id, create=False) / "verified-script-hash.txt"

    def prepare_for_script(self, project_id: UUID, script_hash: str) -> None:
        directory = self.audio_dir(project_id, create=False)
        if directory.exists() and not self.artifacts_match_script(project_id, script_hash):
            shutil.rmtree(directory)
        _atomic_write_text(
            self.audio_dir(project_id) / "verified-script-hash.txt",
            script_hash + "\n",
        )

    def artifacts_match_script(self, project_id: UUID, script_hash: str) -> bool:
        path = self.binding_path(project_id)
        return path.exists() and path.read_text(encoding="utf-8").strip() == script_hash

    def save_chunks(self, project_id: UUID, chunks: list[AudioChunk]) -> None:
        payload = [item.model_dump(mode="json") for item in chunks]
        self._write_json(self.audio_dir(project_id) / "chunks.json", payload)

    def load_chunks(self, project_id: UUID) -> list[AudioChunk]:
        path = self.audio_dir(project_id, create=False) / "chunks.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [AudioChunk.model_validate(item) for item in payload]

    def load_chunks_optional(self, project_id: UUID) -> list[AudioChunk] | None:
        try:
            return self.load_chunks(project_id)
        except FileNotFoundError:
            return None

    def segment_wav_path(self, project_id: UUID, chunk_id: str) -> Path:
        return self.audio_dir(project_id, create=False) / "segments" / f"{chunk_id}.wav"

    def save_segment(
        self,
        project_id: UUID,
        record: AudioSegmentRecord,
        wav_bytes: bytes,
    ) -> None:
        wav_path = self.audio_dir(project_id) / "segments" / f"{record.chunk.chunk_id}.wav"
        _atomic_write_bytes(wav_path, wav_bytes)
        self._write_json(
            self.audio_dir(project_id) / "segments" / f"{record.chunk.chunk_id}.json",
            record,
        )

    def load_segment(
        self,
        project_id: UUID,
        chunk_id: str,
    ) -> tuple[AudioSegmentRecord, bytes]:
        directory = self.audio_dir(project_id, create=False) / "segments"
        record = AudioSegmentRecord.model_validate_json(
            (directory / f"{chunk_id}.json").read_text(encoding="utf-8")
        )
        payload = (directory / f"{chunk_id}.wav").read_bytes()
        if hashlib.sha256(payload).hexdigest() != record.wav_sha256:
            raise ValueError(f"Audio segment checksum mismatch: {chunk_id}")
        return record, payload

    def load_segment_optional(
        self,
        project_id: UUID,
        chunk_id: str,
        chunk_hash: str,
    ) -> tuple[AudioSegmentRecord, bytes] | None:
        try:
            record, payload = self.load_segment(project_id, chunk_id)
        except (FileNotFoundError, ValueError):
            return None
        return (record, payload) if record.chunk.content_hash == chunk_hash else None

    def save_transcript(self, project_id: UUID, transcript: AsrTranscript) -> None:
        self._write_json(
            self.audio_dir(project_id) / "asr" / f"{transcript.chunk_id}.json",
            transcript,
        )

    def load_transcript_optional(
        self,
        project_id: UUID,
        chunk_id: str,
        chunk_hash: str,
        wav_sha256: str,
        *,
        expected_model: str | None = None,
    ) -> AsrTranscript | None:
        path = self.audio_dir(project_id, create=False) / "asr" / f"{chunk_id}.json"
        try:
            transcript = AsrTranscript.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if transcript.chunk_hash != chunk_hash or transcript.wav_sha256 != wav_sha256:
            emit_cache_lookup(
                cache="asr_transcript",
                result="miss",
                project_id=project_id,
                subject_type="chunk",
                subject_id=chunk_id,
                invalidation_reason="wav_or_chunk_mismatch",
            )
            return None
        if expected_model is not None and transcript.model != expected_model:
            emit_cache_lookup(
                cache="asr_transcript",
                result="miss",
                project_id=project_id,
                subject_type="chunk",
                subject_id=chunk_id,
                invalidation_reason="model_mismatch",
            )
            return None
        if expected_model is not None:
            emit_cache_lookup(
                cache="asr_transcript",
                result="hit",
                project_id=project_id,
                subject_type="chunk",
                subject_id=chunk_id,
                avoided_calls=1,
            )
        return transcript

    def save_qa(self, project_id: UUID, report: AudioSegmentQa) -> None:
        self._write_json(
            self.audio_dir(project_id) / "qa" / f"{report.chunk_id}.json",
            report,
        )

    def load_qa_optional(
        self,
        project_id: UUID,
        chunk_id: str,
        chunk_hash: str,
        wav_sha256: str,
        *,
        expected_identity: dict[str, Any] | None = None,
    ) -> AudioSegmentQa | None:
        path = self.audio_dir(project_id, create=False) / "qa" / f"{chunk_id}.json"
        try:
            report = AudioSegmentQa.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if report.chunk_hash != chunk_hash or report.wav_sha256 != wav_sha256:
            emit_cache_lookup(
                cache="audio_qa",
                result="miss",
                project_id=project_id,
                subject_type="chunk",
                subject_id=chunk_id,
                invalidation_reason="wav_or_chunk_mismatch",
            )
            return None
        if expected_identity is not None:
            stored = {
                "qa_version": report.qa_version,
                "pass_threshold": report.pass_threshold,
                "review_threshold": report.review_threshold,
                "missing_sentence_threshold": report.missing_sentence_threshold,
            }
            reason = first_mismatch(stored, expected_identity, _QA_IDENTITY_FIELDS)
            if reason is not None:
                emit_cache_lookup(
                    cache="audio_qa",
                    result="miss",
                    project_id=project_id,
                    subject_type="chunk",
                    subject_id=chunk_id,
                    invalidation_reason=reason,
                )
                return None
            emit_cache_lookup(
                cache="audio_qa",
                result="hit",
                project_id=project_id,
                subject_type="chunk",
                subject_id=chunk_id,
                avoided_calls=1,
            )
        return report

    def save_manifest(self, manifest: AudioPipelineManifest) -> None:
        self._write_json(self.audio_dir(manifest.project_id) / "manifest.json", manifest)

    def load_manifest(self, project_id: UUID) -> AudioPipelineManifest:
        return AudioPipelineManifest.model_validate_json(
            (self.audio_dir(project_id, create=False) / "manifest.json").read_text(
                encoding="utf-8"
            )
        )

    def load_manifest_optional(self, project_id: UUID) -> AudioPipelineManifest | None:
        try:
            return self.load_manifest(project_id)
        except FileNotFoundError:
            return None

    def save_final_audio(self, project_id: UUID, wav_bytes: bytes) -> tuple[str, str]:
        path = self.audio_dir(project_id) / "final.wav"
        _atomic_write_bytes(path, wav_bytes)
        # Browser players are unreliable with long PCM WAV; keep a streamable MP3 too.
        self.write_final_mp3_from_wav(project_id)
        return "audio/final.wav", hashlib.sha256(wav_bytes).hexdigest()

    def final_audio_path(self, project_id: UUID) -> Path:
        return self.audio_dir(project_id, create=False) / "final.wav"

    def final_mp3_path(self, project_id: UUID) -> Path:
        return self.audio_dir(project_id, create=False) / "final.mp3"

    def part_audio_dir(self, project_id: UUID, part_index: int, *, create: bool = True) -> Path:
        path = self.audio_dir(project_id, create=create) / "parts" / str(part_index)
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def save_part_final_audio(
        self, project_id: UUID, part_index: int, wav_bytes: bytes
    ) -> tuple[str, str]:
        """One part's assembled, verified audio (`10c` P3 Step 9)."""

        path = self.part_audio_dir(project_id, part_index) / "final.wav"
        _atomic_write_bytes(path, wav_bytes)
        self._write_mp3_from_wav(
            path,
            self.part_final_mp3_path(project_id, part_index),
            project_id=project_id,
        )
        return f"audio/parts/{part_index}/final.wav", hashlib.sha256(wav_bytes).hexdigest()

    def part_final_audio_path(self, project_id: UUID, part_index: int) -> Path:
        return self.part_audio_dir(project_id, part_index, create=False) / "final.wav"

    def part_final_mp3_path(self, project_id: UUID, part_index: int) -> Path:
        return self.part_audio_dir(project_id, part_index, create=False) / "final.mp3"

    def list_part_audio(self, project_id: UUID) -> list[int]:
        parts_dir = self.audio_dir(project_id, create=False) / "parts"
        if not parts_dir.exists():
            return []
        return sorted(
            int(child.name)
            for child in parts_dir.iterdir()
            if child.is_dir() and child.name.isdigit() and (child / "final.wav").exists()
        )

    def write_final_mp3_from_wav(
        self,
        project_id: UUID,
        *,
        ffmpeg_command: str = "ffmpeg",
    ) -> Path:
        wav_path = self.final_audio_path(project_id)
        if not wav_path.exists():
            raise FileNotFoundError(f"Final WAV missing for {project_id}")
        mp3_path = self.audio_dir(project_id) / "final.mp3"
        return self._write_mp3_from_wav(
            wav_path, mp3_path, project_id=project_id, ffmpeg_command=ffmpeg_command
        )

    def _write_mp3_from_wav(
        self,
        wav_path: Path,
        mp3_path: Path,
        *,
        project_id: UUID,
        ffmpeg_command: str = "ffmpeg",
    ) -> Path:
        command = shutil.which(ffmpeg_command)
        if command is None:
            raise RuntimeError("FFmpeg is required to build the streamable MP3.")
        # Unique name so concurrent encodes (overlapping runs/retries) cannot
        # steal or delete each other's partial output — that used to surface as
        # the empty-stderr "FFmpeg did not create streamable MP3" failure.
        temporary = mp3_path.with_name(f"{mp3_path.name}.{uuid4().hex}.partial")
        with tracing.span(
            "audio.transcode_mp3.ffmpeg", component="audio", kind="subprocess",
            project_id=project_id,
        ) as span:
            completed = subprocess.run(
                [
                    command,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(wav_path),
                    "-codec:a",
                    "libmp3lame",
                    "-qscale:a",
                    "4",
                    "-ar",
                    "24000",
                    "-ac",
                    "1",
                    "-f",
                    "mp3",
                    str(temporary),
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            span.set(exit_code=completed.returncode)
            output_ok = (
                temporary.exists()
                and temporary.stat().st_size > 0
                and completed.returncode == 0
            )
            if not output_ok:
                temporary.unlink(missing_ok=True)
                detail = completed.stderr.strip() or (
                    f"FFmpeg did not create streamable MP3 "
                    f"(exit {completed.returncode})."
                )
                span.set(stderr_tail=detail[:700])
                raise RuntimeError(detail)
            temporary.replace(mp3_path)
            span.measure(output_bytes=mp3_path.stat().st_size)
            return mp3_path

    def has_verified_artifacts(
        self,
        project_id: UUID,
        *,
        script_hash: str,
        accept_manual_review: bool = False,
        expected_asr_model: str | None = None,
        expected_qa_identity: dict[str, Any] | None = None,
        asr_enabled: bool = True,
    ) -> bool:
        if not self.artifacts_match_script(project_id, script_hash):
            return False
        try:
            manifest = self.load_manifest(project_id)
            final = self.final_audio_path(project_id)
            payload = final.read_bytes()
        except FileNotFoundError:
            return False
        if not (
            manifest.status == "verified"
            and manifest.final_audio_sha256 == hashlib.sha256(payload).hexdigest()
            and manifest.final_duration_seconds is not None
        ):
            return False
        acceptable = {"pass", "manual_review"} if accept_manual_review else {"pass"}
        try:
            chunks = self.load_chunks(project_id)
        except (FileNotFoundError, ValueError):
            return False
        if len(chunks) != manifest.chunk_count:
            return False
        accepted = 0
        for chunk in chunks:
            segment = self.load_segment_optional(
                project_id,
                chunk.chunk_id,
                chunk.content_hash,
            )
            if segment is None:
                return False
            if not asr_enabled:
                # MVP without ASR: validated segments + final mix are enough.
                accepted += 1
                continue
            record, _ = segment
            transcript = self.load_transcript_optional(
                project_id,
                chunk.chunk_id,
                chunk.content_hash,
                record.wav_sha256,
                expected_model=expected_asr_model,
            )
            qa = self.load_qa_optional(
                project_id,
                chunk.chunk_id,
                chunk.content_hash,
                record.wav_sha256,
                expected_identity=expected_qa_identity,
            )
            if transcript is None or qa is None or qa.verdict not in acceptable:
                return False
            # When callers omit expected identity, still refuse pre-versioning QA.
            if expected_qa_identity is None and (
                qa.qa_version is None
                or qa.pass_threshold is None
                or qa.review_threshold is None
                or qa.missing_sentence_threshold is None
            ):
                return False
            if expected_asr_model is None and not transcript.model:
                return False
            accepted += 1
        return accepted == manifest.chunk_count

    @staticmethod
    def _write_json(path: Path, value: BaseModel | dict[str, Any] | list[Any]) -> None:
        payload: Any = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        _atomic_write_text(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
