from __future__ import annotations

import hashlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from uuid import UUID

from thesisound import tracing
from thesisound.audio import (
    AudioChunk,
    AudioPipelineManifest,
    AudioSegmentRecord,
    pcm_to_wav,
    script_hash,
)
from thesisound.audio_ports import SpeechToTextPort, TextToSpeechPort, TtsRequest
from thesisound.domain import EpisodePlan, ProjectState
from thesisound.pipeline import WorkspaceStore, transition
from thesisound.services.audio_artifact_store import AudioArtifactStore
from thesisound.services.audio_assembler import AudioAssembler
from thesisound.services.audio_qa import AudioQaService
from thesisound.services.audio_validator import AudioValidator
from thesisound.services.lineage_events import emit_review_decision
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.semantic_identity import audio_qa_identity
from thesisound.services.tts_segmenter import TtsSegmenter


class AudioPipelineService:
    def __init__(
        self,
        *,
        workspace_store: WorkspaceStore,
        script_store: ScriptArtifactStore,
        audio_store: AudioArtifactStore,
        tts: TextToSpeechPort,
        asr: SpeechToTextPort,
        segmenter: TtsSegmenter,
        validator: AudioValidator,
        qa: AudioQaService,
        assembler: AudioAssembler,
        tts_model: str,
        asr_model: str,
        voices: dict[str, str],
        style_prompts: dict[str, str],
        max_regeneration_attempts: int = 1,
        accept_manual_review: bool = False,
        asr_enabled: bool = True,
        tts_workers: int = 4,
    ) -> None:
        if tts_workers < 1:
            raise ValueError("tts_workers must be at least 1.")
        self.workspace_store = workspace_store
        self.script_store = script_store
        self.audio_store = audio_store
        self.tts = tts
        self.asr = asr
        self.segmenter = segmenter
        self.validator = validator
        self.qa = qa
        self.assembler = assembler
        self.tts_model = tts_model
        self.asr_model = asr_model
        self.voices = voices
        self.style_prompts = style_prompts
        self.max_regeneration_attempts = max_regeneration_attempts
        self.accept_manual_review = accept_manual_review
        self.asr_enabled = asr_enabled
        self.tts_workers = tts_workers

    def run(
        self,
        project_id: UUID,
        *,
        on_stage: Callable[[str], None] | None = None,
    ) -> AudioPipelineManifest:
        stage = on_stage or (lambda _: None)
        project = self.workspace_store.load_project(project_id)
        if project.state not in {
            ProjectState.SCRIPT_VERIFIED,
            ProjectState.AUDIO_GENERATING,
            ProjectState.AUDIO_READY,
            ProjectState.AUDIO_VERIFYING,
            ProjectState.FAILED_RETRYABLE,
        }:
            raise ValueError(f"Cannot generate audio from project state {project.state.value}.")
        script = self.script_store.load_latest_script(project_id)
        if not self.script_store.has_verified_artifacts(project_id):
            raise ValueError("Verified script artifacts are required before audio generation.")
        current_script_hash = script_hash(script)
        self.audio_store.prepare_for_script(project_id, current_script_hash)

        if project.state in {ProjectState.SCRIPT_VERIFIED, ProjectState.FAILED_RETRYABLE}:
            transition(project, ProjectState.AUDIO_GENERATING)
            self.workspace_store.save_project(project)

        stage("segmenting")
        with tracing.span("audio.segmenting", component="audio") as span:
            desired_chunks = self.segmenter.segment(
                script,
                script_hash=current_script_hash,
                model=self.tts_model,
                voices=self.voices,
                style_prompts=self.style_prompts,
            )
            chunks = self.audio_store.load_chunks_optional(project_id)
            if chunks is None or [item.content_hash for item in chunks] != [
                item.content_hash for item in desired_chunks
            ]:
                chunks = desired_chunks
                self.audio_store.save_chunks(project_id, chunks)
            span.measure(chunk_count=len(chunks))
        manifest = AudioPipelineManifest(
            project_id=project_id,
            script_hash=current_script_hash,
            status="segmented",
            chunk_count=len(chunks),
        )
        self.audio_store.save_manifest(manifest)

        stage("synthesizing")
        with tracing.span("audio.synthesizing", component="audio") as span:
            pending = [
                chunk
                for chunk in chunks
                if self.audio_store.load_segment_optional(
                    project_id,
                    chunk.chunk_id,
                    chunk.content_hash,
                )
                is None
            ]
            self._synthesize_pending(project_id, pending)
            span.measure(chunk_count=len(chunks), synthesized_count=len(pending))
        manifest.status = "segments_ready"
        manifest.updated_at = datetime.now(UTC)
        self.audio_store.save_manifest(manifest)

        project = self.workspace_store.load_project(project_id)
        if project.state == ProjectState.AUDIO_GENERATING:
            transition(project, ProjectState.AUDIO_READY)
            self.workspace_store.save_project(project)
        if project.state == ProjectState.AUDIO_READY:
            transition(project, ProjectState.AUDIO_VERIFYING)
            self.workspace_store.save_project(project)

        if self.asr_enabled:
            stage("transcribing")
            with tracing.span("audio.transcribing", component="audio") as span:
                qa_reports = []
                regenerated: list[str] = []
                for chunk in chunks:
                    report = self._transcribe_and_check(project_id, chunk)
                    needs_regen = (
                        self._needs_regeneration(report.verdict)
                        and self.max_regeneration_attempts > 0
                    )
                    if needs_regen:
                        stage("regenerating")
                        instruction = report.regeneration_instruction or (
                            "متن را دقیق و کامل بازتولید کن"
                        )
                        with tracing.span(
                            "audio.regenerating", component="audio",
                            subject_type="chunk", subject_id=chunk.chunk_id, detail="verbose",
                        ):
                            self._synthesize(
                                project_id,
                                chunk,
                                attempts=2,
                                additional_instruction=instruction,
                            )
                            report = self._transcribe_and_check(
                                project_id, chunk, force=True
                            )
                        regenerated.append(chunk.chunk_id)
                    qa_reports.append(report)
                span.measure(chunk_count=len(chunks), regenerated_count=len(regenerated))

            manifest.status = "qa_ready"
            manifest.regenerated_chunk_ids = regenerated
            manifest.passed_chunk_count = sum(
                report.verdict == "pass" for report in qa_reports
            )
            manifest.updated_at = datetime.now(UTC)
            self.audio_store.save_manifest(manifest)
            failed = [
                report for report in qa_reports if not self._qa_acceptable(report.verdict)
            ]
            if failed:
                detail = ", ".join(f"{item.chunk_id}:{item.verdict}" for item in failed)
                raise ValueError(f"Audio QA did not pass for all chunks: {detail}")
            for report in qa_reports:
                if report.verdict == "manual_review" and self.accept_manual_review:
                    emit_review_decision(
                        disposition="accepted_manual_review",
                        subject_type="audio_chunk",
                        subject_id=report.chunk_id,
                        reason_code="accept_manual_review_config",
                        component="audio",
                    )
        else:
            # MVP: skip ASR cost; treat synthesized+validated segments as accepted.
            manifest.status = "qa_ready"
            manifest.passed_chunk_count = len(chunks)
            manifest.regenerated_chunk_ids = []
            manifest.updated_at = datetime.now(UTC)
            self.audio_store.save_manifest(manifest)

        stage("assembling")
        with tracing.span("audio.assembling", component="audio") as span:
            wav_segments = [
                self.audio_store.load_segment(project_id, chunk.chunk_id)[1]
                for chunk in chunks
            ]
            final_wav, normalization = self.assembler.assemble(wav_segments)
            final_validation = self.validator.validate(final_wav)
            if final_validation.verdict != "pass":
                raise ValueError(
                    "Final audio validation failed: " + "; ".join(final_validation.issues)
                )
            final_ref, final_sha = self.audio_store.save_final_audio(project_id, final_wav)
            span.measure(duration_seconds=final_validation.duration_seconds or 0)
            if project.episode_plan is not None and project.episode_plan.parts:
                self._assemble_part_audio(project_id, project.episode_plan, chunks, wav_segments)
        manifest.status = "verified"
        manifest.final_audio_ref = final_ref
        manifest.final_audio_sha256 = final_sha
        manifest.final_duration_seconds = final_validation.duration_seconds
        manifest.normalization = normalization
        manifest.updated_at = datetime.now(UTC)
        self.audio_store.save_manifest(manifest)

        project = self.workspace_store.load_project(project_id)
        if project.state == ProjectState.AUDIO_VERIFYING:
            transition(project, ProjectState.COMPLETE)
            self.workspace_store.save_project(project)
        return manifest

    def _assemble_part_audio(
        self,
        project_id: UUID,
        episode_plan: EpisodePlan,
        chunks: list[AudioChunk],
        wav_segments: list[bytes],
    ) -> None:
        """One assembled, validated WAV/MP3 per part (`10c` P3 Step 9).

        Chunks are already ordered and verified (this runs after QA); this
        step re-groups the same validated segments by part and re-runs only
        the deterministic assembly + validation, not synthesis or QA, once
        per part.
        """

        part_by_segment = {
            segment.segment_id: segment.part_index for segment in episode_plan.segments
        }
        wav_by_part: dict[int, list[bytes]] = {}
        for chunk, wav_bytes in zip(chunks, wav_segments, strict=True):
            part_index = part_by_segment.get(chunk.segment_id)
            if part_index is None:
                continue
            wav_by_part.setdefault(part_index, []).append(wav_bytes)
        for part_index, part_wav_segments in wav_by_part.items():
            part_wav, _normalization = self.assembler.assemble(part_wav_segments)
            part_validation = self.validator.validate(part_wav)
            if part_validation.verdict != "pass":
                raise ValueError(
                    f"Part {part_index} audio validation failed: "
                    + "; ".join(part_validation.issues)
                )
            self.audio_store.save_part_final_audio(project_id, part_index, part_wav)

    def _qa_acceptable(self, verdict: str) -> bool:
        if verdict == "pass":
            return True
        return self.accept_manual_review and verdict == "manual_review"

    def _needs_regeneration(self, verdict: str) -> bool:
        if verdict == "regenerate":
            return True
        # When manual_review is accepted for assembly, skip costly regen loops on it.
        if verdict == "manual_review" and self.accept_manual_review:
            return False
        return verdict != "pass"

    def _synthesize_pending(
        self,
        project_id: UUID,
        pending: list[AudioChunk],
    ) -> None:
        """Synthesize missing chunks; fan out when more than one worker is allowed.

        Chunks write distinct segment files, so they are independent. Leaving the
        executor ``with`` block on an exception waits for in-flight calls so any
        completed synthesis is still cached for resume.
        """

        if not pending:
            return
        workers = min(self.tts_workers, len(pending))
        if workers == 1:
            for chunk in pending:
                self._synthesize(project_id, chunk, attempts=1)
            return

        def work(chunk: AudioChunk) -> None:
            self._synthesize(project_id, chunk, attempts=1)

        bound_work = tracing.bind_context(work)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(bound_work, chunk) for chunk in pending]
            for future in as_completed(futures):
                future.result()

    def _synthesize(
        self,
        project_id: UUID,
        chunk,
        *,
        attempts: int,
        additional_instruction: str | None = None,
    ) -> None:
        style = self.style_prompts[chunk.speaker]
        if additional_instruction:
            style = f"{style}\nاصلاح لازم: {additional_instruction}"
        response = self.tts.synthesize(
            TtsRequest(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                speaker=chunk.speaker,
                voice_name=chunk.voice_name,
                model=self.tts_model,
                style_prompt=style,
            )
        )
        wav_bytes = pcm_to_wav(
            response.pcm_bytes,
            sample_rate_hz=response.sample_rate_hz,
            channels=response.channels,
            sample_width_bytes=response.sample_width_bytes,
        )
        validation = self.validator.validate(
            wav_bytes,
            expected_duration_seconds=chunk.expected_duration_seconds,
        )
        if validation.verdict != "pass":
            raise ValueError(
                f"WAV validation failed for {chunk.chunk_id}: "
                + "; ".join(validation.issues)
            )
        self.audio_store.save_segment(
            project_id,
            AudioSegmentRecord(
                chunk=chunk,
                wav_ref=f"audio/segments/{chunk.chunk_id}.wav",
                wav_sha256=hashlib.sha256(wav_bytes).hexdigest(),
                provider=response.provider,
                model=response.model,
                validation=validation,
                generation_attempts=attempts,
            ),
            wav_bytes,
        )

    def _transcribe_and_check(self, project_id: UUID, chunk, *, force: bool = False):
        record, wav_bytes = self.audio_store.load_segment(project_id, chunk.chunk_id)
        transcript = None
        if not force:
            transcript = self.audio_store.load_transcript_optional(
                project_id,
                chunk.chunk_id,
                chunk.content_hash,
                record.wav_sha256,
                expected_model=self.asr_model,
            )
        if transcript is None:
            transcript = self.asr.transcribe(
                chunk_id=chunk.chunk_id,
                chunk_hash=chunk.content_hash,
                wav_sha256=record.wav_sha256,
                wav_bytes=wav_bytes,
                model=self.asr_model,
                expected_speaker=chunk.speaker,
                language="fa",
            )
            self.audio_store.save_transcript(project_id, transcript)
        report = self.qa.compare(chunk, transcript)
        self.audio_store.save_qa(project_id, report)
        return report

    def qa_identity(self) -> dict[str, float | int]:
        return audio_qa_identity(
            pass_threshold=self.qa.pass_threshold,
            review_threshold=self.qa.review_threshold,
            missing_sentence_threshold=self.qa.missing_sentence_threshold,
        )
