from __future__ import annotations

from uuid import UUID

from thesisound.adapters.models.gemini import GeminiStructuredModel
from thesisound.config import Settings
from thesisound.pipeline import WorkspaceStore
from thesisound.prompt_loader import PromptLoader
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.glossary_builder import GlossaryBuilderService
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner
from thesisound.services.persian_script_writer import PersianScriptWriterService
from thesisound.services.plan_approval import EpisodePlanApprovalStore
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_checks import ScriptChecker
from thesisound.services.script_pipeline_service import ScriptPipelineService
from thesisound.services.script_reviser import TargetedScriptReviserService
from thesisound.services.script_run import ScriptBuildRunService, ScriptBuildRunStore
from thesisound.services.script_verifier import ScriptVerifierService
from thesisound.services.source_artifact_store import SourceArtifactStore


def create_script_builder(
    settings: Settings,
    workspace: WorkspaceStore,
) -> ScriptBuildRunService:
    source_store = SourceArtifactStore(workspace.root)
    episode_store = EpisodeArtifactStore(workspace.root)
    script_store = ScriptArtifactStore(workspace.root)
    approval_store = EpisodePlanApprovalStore(workspace.root)

    def pipeline_factory(project_id: UUID) -> ScriptPipelineService:
        del project_id
        model_port = GeminiStructuredModel(api_key=settings.gemini_api_key)
        runner = ModelRunner(
            model_port,
            PromptLoader(),
            WorkspaceModelRunStore(
                workspace.root,
                keep_prompts=settings.keep_rendered_prompts,
            ),
            base_retry_delay_seconds=settings.model_retry_base_seconds,
        )
        return ScriptPipelineService(
            workspace_store=workspace,
            source_store=source_store,
            episode_store=episode_store,
            script_store=script_store,
            approval_store=approval_store,
            glossary_builder=GlossaryBuilderService(runner),
            script_writer=PersianScriptWriterService(runner),
            script_checker=ScriptChecker(),
            verifier=ScriptVerifierService(runner),
            reviser=TargetedScriptReviserService(runner),
        )

    builder = ScriptBuildRunService(
        workspace_store=workspace,
        run_store=ScriptBuildRunStore(workspace.root),
        approval_store=approval_store,
        script_store=script_store,
        pipeline_factory=pipeline_factory,
        glossary_model=settings.model_strong,
        writer_model=settings.model_strong,
        verifier_model=settings.model_strong,
        reviser_model=settings.model_strong,
    )
    builder.recover_interrupted_runs()
    return builder
