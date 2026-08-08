from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from thesisound.domain import ClaimRecord, ProjectState, Script
from thesisound.modeling import ModelError
from thesisound.pipeline import WorkspaceStore, mark_failed, transition
from thesisound.script import (
    Glossary,
    ScriptCheckReport,
    ScriptPipelineManifest,
    ScriptPipelineResult,
    VerificationDraft,
)
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.glossary_builder import GlossaryBuilderService
from thesisound.services.persian_script_writer import PersianScriptWriterService
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_checks import ScriptChecker
from thesisound.services.script_reviser import TargetedScriptReviserService
from thesisound.services.script_verifier import ScriptVerifierService
from thesisound.services.source_artifact_store import SourceArtifactStore


class ScriptPipelineService:
    def __init__(
        self,
        *,
        workspace_store: WorkspaceStore,
        source_store: SourceArtifactStore,
        episode_store: EpisodeArtifactStore,
        script_store: ScriptArtifactStore,
        glossary_builder: GlossaryBuilderService,
        script_writer: PersianScriptWriterService,
        script_checker: ScriptChecker,
        verifier: ScriptVerifierService,
        reviser: TargetedScriptReviserService,
    ) -> None:
        self.workspace_store = workspace_store
        self.source_store = source_store
        self.episode_store = episode_store
        self.script_store = script_store
        self.glossary_builder = glossary_builder
        self.script_writer = script_writer
        self.script_checker = script_checker
        self.verifier = verifier
        self.reviser = reviser

    def build_glossary(
        self,
        project_id: UUID,
        *,
        model: str,
        prompt_version: str | None = None,
    ) -> Glossary:
        project = self.workspace_store.load_project(project_id)
        self._enter_script_drafting(project)
        if project.brief is None or project.episode_plan is None:
            raise ValueError("ResearchBrief and EpisodePlan are required for glossary generation.")
        packs = self.episode_store.load_evidence_packs(project_id)
        graph = self.episode_store.load_disagreement_graph(project_id)
        glossary, run = self.glossary_builder.build(
            project_id=project_id,
            brief=project.brief,
            episode_plan=project.episode_plan,
            evidence_packs=packs,
            disagreement_graph=graph,
            model=model,
            prompt_version=prompt_version,
        )
        self.script_store.save_glossary(glossary)
        self.script_store.save_manifest(
            ScriptPipelineManifest(
                project_id=project_id,
                status="glossary_ready",
                segment_count=len(project.episode_plan.segments),
                model_run_ids=[run.run_id],
            )
        )
        self.workspace_store.save_project(project)
        return glossary

    def write_script(
        self,
        project_id: UUID,
        *,
        model: str,
        prompt_version: str | None = None,
    ) -> Script:
        project = self.workspace_store.load_project(project_id)
        self._require_state(project.state, ProjectState.SCRIPT_DRAFTING)
        if project.brief is None or project.episode_plan is None:
            raise ValueError("ResearchBrief and EpisodePlan are required for script writing.")
        glossary = self.script_store.load_glossary(project_id)
        graph = self.episode_store.load_disagreement_graph(project_id)
        pack_by_segment = {
            pack.segment_id: pack
            for pack in self.episode_store.load_evidence_packs(project_id)
        }
        turns = []
        run_ids = []
        for segment in project.episode_plan.segments:
            pack = pack_by_segment.get(segment.segment_id)
            if pack is None:
                raise ValueError(f"Missing evidence pack for segment {segment.segment_id}.")
            segment_turns, draft, run = self.script_writer.write_segment(
                project_id=project_id,
                brief=project.brief,
                segment=segment,
                evidence_pack=pack,
                glossary=glossary,
                disagreement_graph=graph,
                model=model,
                prompt_version=prompt_version,
            )
            self.script_store.save_segment_draft(project_id, segment.segment_id, draft)
            turns.extend(segment_turns)
            run_ids.append(run.run_id)
        script = Script(
            title=project.episode_plan.title,
            turns=turns,
            glossary_terms_used=[term.preferred_persian for term in glossary.terms],
        )
        self.script_store.save_script(project_id, script)
        project.script = script
        transition(project, ProjectState.SCRIPT_READY)
        self.workspace_store.save_project(project)
        manifest = self.script_store.load_manifest(project_id)
        manifest.status = "draft_ready"
        manifest.turn_count = len(turns)
        manifest.model_run_ids.extend(run_ids)
        manifest.updated_at = datetime.now(UTC)
        self.script_store.save_manifest(manifest)
        return script

    def run_checks(self, project_id: UUID, *, revised: bool = False) -> ScriptCheckReport:
        project = self.workspace_store.load_project(project_id)
        self._require_state(project.state, ProjectState.SCRIPT_READY)
        if project.episode_plan is None:
            raise ValueError("EpisodePlan is required for script checks.")
        script = self.script_store.load_script(project_id, revised=revised)
        report = self.script_checker.check(
            project_id=project_id,
            script=script,
            episode_plan=project.episode_plan,
            evidence_packs=self.episode_store.load_evidence_packs(project_id),
            claims=self._load_claims(project_id),
            glossary=self.script_store.load_glossary(project_id),
        )
        self.script_store.save_checks(report, revised=revised)
        manifest = self.script_store.load_manifest(project_id)
        manifest.status = "checks_ready"
        manifest.updated_at = datetime.now(UTC)
        self.script_store.save_manifest(manifest)
        return report

    def verify_script(
        self,
        project_id: UUID,
        *,
        model: str,
        revised: bool = False,
        prompt_version: str | None = None,
    ) -> VerificationDraft:
        project = self.workspace_store.load_project(project_id)
        self._require_state(project.state, ProjectState.SCRIPT_READY)
        if project.episode_plan is None:
            raise ValueError("EpisodePlan is required for verification.")
        transition(project, ProjectState.SCRIPT_VERIFYING)
        self.workspace_store.save_project(project)
        script = self.script_store.load_script(project_id, revised=revised)
        checks = self.script_store.load_checks(project_id, revised=revised)
        report, run = self.verifier.verify(
            project_id=project_id,
            script=script,
            checks=checks,
            episode_plan=project.episode_plan,
            evidence_packs=self.episode_store.load_evidence_packs(project_id),
            glossary=self.script_store.load_glossary(project_id),
            disagreement_graph=self.episode_store.load_disagreement_graph(project_id),
            model=model,
            prompt_version=prompt_version,
        )
        self.script_store.save_verification(project_id, report, revised=revised)
        manifest = self.script_store.load_manifest(project_id)
        manifest.status = "verification_ready"
        manifest.model_run_ids.append(run.run_id)
        manifest.updated_at = datetime.now(UTC)
        self.script_store.save_manifest(manifest)
        return report

    def revise_script(
        self,
        project_id: UUID,
        *,
        model: str,
        prompt_version: str | None = None,
    ) -> Script:
        project = self.workspace_store.load_project(project_id)
        self._require_state(project.state, ProjectState.SCRIPT_VERIFYING)
        original = self.script_store.load_script(project_id)
        checks = self.script_store.load_checks(project_id)
        verification = self.script_store.load_verification(project_id)
        revised, draft, run = self.reviser.revise(
            project_id=project_id,
            script=original,
            checks=checks,
            verification=verification,
            evidence_packs=self.episode_store.load_evidence_packs(project_id),
            glossary=self.script_store.load_glossary(project_id),
            model=model,
            prompt_version=prompt_version,
        )
        transition(project, ProjectState.SCRIPT_DRAFTING)
        self.script_store.save_script(project_id, revised, revised=True)
        project.script = revised
        transition(project, ProjectState.SCRIPT_READY)
        self.workspace_store.save_project(project)
        manifest = self.script_store.load_manifest(project_id)
        manifest.status = "revision_ready"
        manifest.revision_count += len(draft.revised_turns)
        manifest.model_run_ids.append(run.run_id)
        manifest.updated_at = datetime.now(UTC)
        self.script_store.save_manifest(manifest)
        return revised

    def run(
        self,
        project_id: UUID,
        *,
        glossary_model: str,
        writer_model: str,
        verifier_model: str,
        reviser_model: str,
        prompt_version: str | None = None,
    ) -> ScriptPipelineResult:
        try:
            glossary = self.build_glossary(
                project_id,
                model=glossary_model,
                prompt_version=prompt_version,
            )
            script = self.write_script(
                project_id,
                model=writer_model,
                prompt_version=prompt_version,
            )
            checks = self.run_checks(project_id)
            if checks.verdict == "reject":
                self._enter_script_verifying(project_id)
                verification = VerificationDraft(
                    verdict="revise",
                    issues=[],
                    unsupported_claim_ratio=0,
                )
                self.script_store.save_verification(project_id, verification)
            else:
                verification = self.verify_script(
                    project_id,
                    model=verifier_model,
                    prompt_version=prompt_version,
                )
            if checks.verdict != "pass" or verification.verdict != "pass":
                script = self.revise_script(
                    project_id,
                    model=reviser_model,
                    prompt_version=prompt_version,
                )
                checks = self.run_checks(project_id, revised=True)
                if checks.verdict != "pass":
                    raise ValueError("Revised script failed deterministic checks.")
                verification = self.verify_script(
                    project_id,
                    model=verifier_model,
                    revised=True,
                    prompt_version=prompt_version,
                )
            if verification.verdict != "pass" or verification.unsupported_claim_ratio != 0:
                raise ValueError("Script failed verification after one targeted revision.")
            project = self.workspace_store.load_project(project_id)
            transition(project, ProjectState.SCRIPT_VERIFIED)
            project.script = script
            self.workspace_store.save_project(project)
            manifest = self.script_store.load_manifest(project_id)
            manifest.status = "verified"
            manifest.updated_at = datetime.now(UTC)
            self.script_store.save_manifest(manifest)
            return ScriptPipelineResult(
                glossary=glossary,
                script=script,
                checks=checks,
                verification=verification,
            )
        except (FileNotFoundError, ModelError, ValueError) as exc:
            self._mark_failed(project_id, str(exc))
            raise

    def _load_claims(self, project_id: UUID) -> list[ClaimRecord]:
        claims = []
        for source_id in self.source_store.list_claim_ready_source_ids(project_id):
            claims.extend(self.source_store.load_claim_ledger(project_id, source_id).claims)
        return claims

    def _enter_script_verifying(self, project_id: UUID) -> None:
        project = self.workspace_store.load_project(project_id)
        self._require_state(project.state, ProjectState.SCRIPT_READY)
        transition(project, ProjectState.SCRIPT_VERIFYING)
        self.workspace_store.save_project(project)

    @staticmethod
    def _require_state(actual: ProjectState, expected: ProjectState) -> None:
        if actual != expected:
            raise ValueError(f"Expected {expected.value} state, found {actual.value}.")

    @staticmethod
    def _enter_script_drafting(project) -> None:
        if project.state in {
            ProjectState.EPISODE_PLANNED,
            ProjectState.FAILED_RETRYABLE,
        }:
            transition(project, ProjectState.SCRIPT_DRAFTING)
        elif project.state != ProjectState.SCRIPT_DRAFTING:
            raise ValueError(f"Cannot draft script from project state {project.state.value}.")

    def _mark_failed(self, project_id: UUID, message: str) -> None:
        project = self.workspace_store.load_project(project_id)
        if project.state != ProjectState.FAILED_RETRYABLE:
            mark_failed(project, message)
        else:
            project.last_error = message
            project.updated_at = datetime.now(UTC)
        self.workspace_store.save_project(project)
        try:
            manifest = self.script_store.load_manifest(project_id)
        except FileNotFoundError:
            return
        manifest.status = "failed"
        manifest.last_error = message
        manifest.updated_at = datetime.now(UTC)
        self.script_store.save_manifest(manifest)
