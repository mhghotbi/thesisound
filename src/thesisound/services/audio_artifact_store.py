from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from thesisound import tracing
from thesisound.audio import (
    AsrTranscript,
    AudioChunk,
    AudioPipelineManifest,
    AudioSegmentQa,
    AudioSegmentRecord,
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
    ) -> AsrTranscript | None:
        path = self.audio_dir(project_id, create=False) / "asr" / f"{chunk_id}.json"
        try:
            transcript = AsrTranscript.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if transcript.chunk_hash != chunk_hash or transcript.wav_sha256 != wav_sha256:
            return None
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
    ) -> AudioSegmentQa | None:
        path = self.audio_dir(project_id, create=False) / "qa" / f"{chunk_id}.json"
        try:
            report = AudioSegmentQa.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if report.chunk_hash != chunk_hash or report.wav_sha256 != wav_sha256:
            return None
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
        command = shutil.which(ffmpeg_command)
        if command is None:
            raise RuntimeError("FFmpeg is required to build the streamable MP3.")
        temporary = mp3_path.with_name(mp3_path.name + ".partial")
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
            if completed.returncode != 0 or not temporary.exists():
                temporary.unlink(missing_ok=True)
                detail = completed.stderr.strip() or "FFmpeg did not create streamable MP3."
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
            record, _ = segment
            transcript = self.load_transcript_optional(
                project_id,
                chunk.chunk_id,
                chunk.content_hash,
                record.wav_sha256,
            )
            qa = self.load_qa_optional(
                project_id,
                chunk.chunk_id,
                chunk.content_hash,
                record.wav_sha256,
            )
            if transcript is None or qa is None or qa.verdict not in acceptable:
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
