from __future__ import annotations

from uuid import UUID

from thesisound.adapters.audio.gemini import GeminiAsrAdapter, GeminiTtsAdapter
from thesisound.config import Settings
from thesisound.gemini_key_pool import shared_gemini_key_pool
from thesisound.pipeline import WorkspaceStore
from thesisound.services.audio_artifact_store import AudioArtifactStore
from thesisound.services.audio_assembler import AudioAssembler
from thesisound.services.audio_direction import AudioDirectionSettings
from thesisound.services.audio_pipeline_service import AudioPipelineService
from thesisound.services.audio_qa import AudioQaService
from thesisound.services.audio_run import AudioBuildRunService, AudioBuildRunStore
from thesisound.services.audio_validator import AudioValidator
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.semantic_identity import audio_qa_identity
from thesisound.services.tts_segmenter import TtsSegmenter


def create_audio_builder(
    settings: Settings,
    workspace: WorkspaceStore,
) -> AudioBuildRunService:
    script_store = ScriptArtifactStore(workspace.root)
    audio_store = AudioArtifactStore(workspace.root)
    default_direction = AudioDirectionSettings(
        voice_a=settings.tts_voice_a,
        voice_b=settings.tts_voice_b,
    )
    qa_identity = audio_qa_identity(
        pass_threshold=settings.audio_qa_pass_threshold,
        review_threshold=settings.audio_qa_review_threshold,
        missing_sentence_threshold=settings.audio_qa_missing_sentence_threshold,
    )

    def pipeline_factory(
        project_id: UUID,
        direction: AudioDirectionSettings,
        workflow_run_id: UUID,
    ) -> AudioPipelineService:
        gemini_pool = shared_gemini_key_pool(settings.gemini_api_keys)
        style_prompts = {
            speaker: f"{settings.tts_style_prompt}\n{direction.style_prompt_for(speaker)}"
            for speaker in ("A", "B")
        }
        return AudioPipelineService(
            workspace_store=workspace,
            script_store=script_store,
            audio_store=audio_store,
            tts=GeminiTtsAdapter(
                pool=gemini_pool,
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                settings=settings,
            ),
            asr=GeminiAsrAdapter(
                pool=gemini_pool,
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                settings=settings,
            ),
            segmenter=TtsSegmenter(
                max_characters=settings.tts_chunk_max_characters,
                words_per_minute=settings.tts_words_per_minute,
            ),
            validator=AudioValidator(expected_sample_rate_hz=settings.audio_sample_rate_hz),
            qa=AudioQaService(
                pass_threshold=settings.audio_qa_pass_threshold,
                review_threshold=settings.audio_qa_review_threshold,
                missing_sentence_threshold=settings.audio_qa_missing_sentence_threshold,
            ),
            assembler=AudioAssembler(
                ffmpeg_command=settings.ffmpeg_command,
                silence_milliseconds=settings.audio_silence_milliseconds,
            ),
            tts_model=settings.model_tts,
            asr_model=settings.model_asr,
            voices=direction.voices_map,
            style_prompts=style_prompts,
            max_regeneration_attempts=settings.audio_max_regeneration_attempts,
            accept_manual_review=settings.audio_qa_accept_manual_review,
        )

    builder = AudioBuildRunService(
        workspace_store=workspace,
        run_store=AudioBuildRunStore(workspace.root),
        script_store=script_store,
        audio_store=audio_store,
        pipeline_factory=pipeline_factory,
        default_direction=default_direction,
        accept_manual_review=settings.audio_qa_accept_manual_review,
        asr_model=settings.model_asr,
        qa_identity=qa_identity,
    )
    builder.recover_interrupted_runs()
    return builder
