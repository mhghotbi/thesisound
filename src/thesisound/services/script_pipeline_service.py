from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from thesisound import tracing
from thesisound.concepts import ConceptCell
from thesisound.domain import (
    ClaimRecord,
    DeliveryMode,
    EpisodePlan,
    ExtractedDefinition,
    Project,
    ProjectState,
    Script,
    ScriptTurn,
)
from thesisound.modeling import ModelError
from thesisound.pipeline import WorkspaceStore, mark_failed, transition
from thesisound.script import (
    Glossary,
    ProseLessonDraft,
    QualityNote,
    RevisionDecision,
    ScriptCheckReport,
    ScriptPipelineManifest,
    ScriptPipelineResult,
    SegmentScriptDraft,
    VerificationDraft,
)
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.glossary_builder import GlossaryBuilderService
from thesisound.services.lineage_events import emit_cache_lookup, emit_quality_label
from thesisound.services.persian_lesson_prose_writer import PersianLessonProseWriterService
from thesisound.services.persian_script_writer import PersianScriptWriterService
from thesisound.services.plan_approval import EpisodePlanApprovalStore
from thesisound.services.quality_notes import make_quality_note
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_checks import ScriptChecker
from thesisound.services.script_grounding_remediation import remediate_script_grounding
from thesisound.services.script_outcome import script_outcome
from thesisound.services.script_quality import is_better
from thesisound.services.script_reviser import TargetedScriptReviserService
from thesisound.services.script_verifier import ScriptVerifierService
from thesisound.services.semantic_identity import script_pipeline_identity
from thesisound.services.source_artifact_store import SourceArtifactStore

ScriptStageCallback = Callable[[str], None]


def revision_is_required(checks: ScriptCheckReport, verification: VerificationDraft) -> bool:
    """Whether the targeted reviser should run.

    The model verifier is unconditional (audit revision 2). This helper only
    gates the reviser: skip when deterministic checks and verification both pass.
    """

    return checks.verdict != "pass" or verification.verdict != "pass"


class ScriptPipelineService:
    def __init__(
        self,
        *,
        workspace_store: WorkspaceStore,
        source_store: SourceArtifactStore,
        episode_store: EpisodeArtifactStore,
        script_store: ScriptArtifactStore,
        approval_store: EpisodePlanApprovalStore,
        glossary_builder: GlossaryBuilderService,
        script_writer: PersianScriptWriterService,
        script_checker: ScriptChecker,
        verifier: ScriptVerifierService,
        reviser: TargetedScriptReviserService,
        prose_writer: PersianLessonProseWriterService | None = None,
        quality_gate_enabled: bool = False,
        min_quality_overall: float = 0.70,
    ) -> None:
        self.workspace_store = workspace_store
        self.source_store = source_store
        self.episode_store = episode_store
        self.script_store = script_store
        self.approval_store = approval_store
        self.glossary_builder = glossary_builder
        self.script_writer = script_writer
        self.prose_writer = prose_writer
        self.script_checker = script_checker
        self.verifier = verifier
        self.reviser = reviser
        self.quality_gate_enabled = quality_gate_enabled
        self.min_quality_overall = min_quality_overall

    def build_glossary(
        self,
        project_id: UUID,
        *,
        model: str,
        prompt_version: str | None = None,
    ) -> Glossary:
        project = self.workspace_store.load_project(project_id)
        self.approval_store.require_current(project)
        self._enter_script_drafting(project)
        self.workspace_store.save_project(project)
        if project.brief is None or project.episode_plan is None:
            raise ValueError("ResearchBrief and EpisodePlan are required for glossary generation.")
        packs = self.episode_store.load_evidence_packs(project_id)
        graph = self.episode_store.load_disagreement_graph(project_id)
        definitions, claims, concept_cells = self._load_glossary_inputs(project_id)
        glossary, run = self.glossary_builder.build(
            project_id=project_id,
            brief=project.brief,
            episode_plan=project.episode_plan,
            evidence_packs=packs,
            disagreement_graph=graph,
            definitions=definitions,
            claims=claims,
            concept_cells=concept_cells,
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
        self.approval_store.require_current(project)
        if project.brief is None or project.episode_plan is None:
            raise ValueError("ResearchBrief and EpisodePlan are required for script writing.")
        glossary = self.script_store.load_glossary(project_id)
        graph = self.episode_store.load_disagreement_graph(project_id)
        pack_by_segment = {
            pack.segment_id: pack for pack in self.episode_store.load_evidence_packs(project_id)
        }
        turns: list[ScriptTurn] = []
        speaker_balance_violations = self.script_store.load_speaker_balance_violations_optional(
            project_id
        )
        run_ids = []
        segment_count = len(project.episode_plan.segments)
        is_prose = project.delivery == DeliveryMode.TEXT
        if is_prose and self.prose_writer is None:
            raise ValueError("delivery == text requires a configured prose_writer.")
        for index, segment in enumerate(project.episode_plan.segments, start=1):
            pack = pack_by_segment.get(segment.segment_id)
            if pack is None:
                raise ValueError(f"Missing evidence pack for segment {segment.segment_id}.")
            if is_prose:
                prose_draft = self.script_store.load_prose_segment_draft_optional(
                    project_id,
                    segment.segment_id,
                )
                if prose_draft is None:
                    assert self.prose_writer is not None
                    prose_result = self.prose_writer.write_segment(
                        project_id=project_id,
                        brief=project.brief,
                        segment=segment,
                        evidence_pack=pack,
                        glossary=glossary,
                        disagreement_graph=graph,
                        model=model,
                        prompt_version=prompt_version,
                        segment_index=index,
                        segment_count=segment_count,
                    )
                    segment_turns = prose_result.turns
                    self.script_store.save_prose_segment_draft(
                        project_id,
                        segment.segment_id,
                        prose_result.draft,
                    )
                    run_ids.append(prose_result.record.run_id)
                else:
                    segment_turns = self._materialize_prose_segment_turns(
                        segment.segment_id, prose_draft
                    )
                turns.extend(segment_turns)
                continue
            draft = self.script_store.load_segment_draft_optional(
                project_id,
                segment.segment_id,
            )
            if draft is None:
                result = self.script_writer.write_segment(
                    project_id=project_id,
                    brief=project.brief,
                    segment=segment,
                    evidence_pack=pack,
                    glossary=glossary,
                    disagreement_graph=graph,
                    model=model,
                    prompt_version=prompt_version,
                    segment_index=index,
                    segment_count=segment_count,
                )
                segment_turns = result.turns
                draft = result.draft
                run = result.record
                if result.violations:
                    speaker_balance_violations[segment.segment_id] = result.violations
                else:
                    speaker_balance_violations.pop(segment.segment_id, None)
                self.script_store.save_segment_draft(
                    project_id,
                    segment.segment_id,
                    draft,
                )
                # Segment drafts survive a later build failure, so their final-attempt
                # balance results must survive with them for a resumed build.
                self.script_store.save_speaker_balance_violations(
                    project_id,
                    speaker_balance_violations,
                )
                run_ids.append(run.run_id)
            else:
                segment_turns = self._materialize_segment_turns(segment.segment_id, draft)
            turns.extend(segment_turns)
        self.script_store.save_speaker_balance_violations(
            project_id,
            speaker_balance_violations,
        )
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
        self.approval_store.require_current(project)
        if project.episode_plan is None:
            raise ValueError("EpisodePlan is required for script checks.")
        script = self.script_store.load_script(project_id, revised=revised)
        claims = self._load_claims(project_id)
        remediation = remediate_script_grounding(
            script,
            claims,
            episode_plan=project.episode_plan,
            words_per_minute=self.script_checker.words_per_minute,
        )
        script = remediation.script
        if remediation.notes or remediation.faults:
            self.script_store.save_script(project_id, script, revised=revised)
            if not revised:
                project.script = script
                self.workspace_store.save_project(project)
            if remediation.notes:
                self.script_store.append_quality_notes(project_id, remediation.notes)
        # Draft remediation owns the per-run fault ledger; revision appends.
        if revised:
            self.script_store.append_absorbed_faults(
                project_id,
                remediation.faults,
                substantive_turn_count=remediation.substantive_turn_count,
            )
        else:
            self.script_store.replace_absorbed_faults(
                project_id,
                remediation.faults,
                substantive_turn_count=remediation.substantive_turn_count,
            )
        try:
            must_not_be_lost_review = self.episode_store.load_must_not_be_lost_review(
                project_id
            )
        except FileNotFoundError:
            must_not_be_lost_review = None
        report = self.script_checker.check(
            project_id=project_id,
            script=script,
            episode_plan=project.episode_plan,
            evidence_packs=self.episode_store.load_evidence_packs(project_id),
            claims=claims,
            glossary=self.script_store.load_glossary(project_id),
            speaker_balance_violations=(
                {}
                if revised
                else self.script_store.load_speaker_balance_violations_optional(project_id)
            ),
            must_not_be_lost_review=must_not_be_lost_review,
            single_speaker=project.delivery == DeliveryMode.TEXT,
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
        self.approval_store.require_current(project)
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
        self.approval_store.require_current(project)
        original = self.script_store.load_script(project_id)
        checks = self.script_store.load_checks(project_id)
        verification = self.script_store.load_verification(project_id)
        revised, draft, run, notes = self.reviser.revise(
            project_id=project_id,
            script=original,
            checks=checks,
            verification=verification,
            evidence_packs=self.episode_store.load_evidence_packs(project_id),
            glossary=self.script_store.load_glossary(project_id),
            model=model,
            prompt_version=prompt_version,
        )
        self.script_store.append_quality_notes(project_id, notes)
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
        on_stage: ScriptStageCallback | None = None,
    ) -> ScriptPipelineResult:
        stage = on_stage or (lambda _: None)
        try:
            project = self.workspace_store.load_project(project_id)
            approval = self.approval_store.require_current(project)
            identity = script_pipeline_identity(
                glossary_model=glossary_model,
                glossary_prompt_version=prompt_version,
                writer_model=writer_model,
                writer_prompt_version=prompt_version,
                verifier_model=verifier_model,
                verifier_prompt_version=prompt_version,
                reviser_model=reviser_model,
                reviser_prompt_version=prompt_version,
            )
            pipeline_matched = self.script_store.prepare_for_pipeline(
                project_id,
                approval.plan_hash,
                identity,
            )
            self._seed_quality_notes_from_episode(project_id)
            if project.state == ProjectState.SCRIPT_VERIFIED and pipeline_matched:
                return ScriptPipelineResult(
                    glossary=self.script_store.load_glossary(project_id),
                    script=self.script_store.load_latest_script(project_id),
                    checks=self.script_store.load_latest_checks(project_id),
                    verification=self.script_store.load_latest_verification(project_id),
                )
            if project.state == ProjectState.SCRIPT_VERIFIED and not pipeline_matched:
                # Semantic identity changed; verified artifacts were wiped.
                mark_failed(project, "Script pipeline identity changed; regenerating.")
                transition(project, ProjectState.SCRIPT_DRAFTING)
                self.workspace_store.save_project(project)
            else:
                self._enter_script_drafting(project)
                self.workspace_store.save_project(project)

            glossary = self.script_store.load_glossary_optional(project_id)
            if glossary is None:
                stage("building_glossary")
                with tracing.span("script.building_glossary", component="script"):
                    glossary = self.build_glossary(
                        project_id,
                        model=glossary_model,
                        prompt_version=prompt_version,
                    )
            else:
                emit_cache_lookup(
                    cache="script_glossary",
                    result="hit",
                    project_id=project_id,
                    avoided_calls=1,
                )

            script = self.script_store.load_script_optional(project_id)
            if script is None:
                stage("writing_segments")
                self._ensure_script_drafting(project_id)
                with tracing.span("script.writing_segments", component="script") as span:
                    script = self.write_script(
                        project_id,
                        model=writer_model,
                        prompt_version=prompt_version,
                    )
                    span.measure(turn_count=len(script.turns))
            else:
                self._ensure_script_ready(project_id, script)
                emit_cache_lookup(
                    cache="script_draft",
                    result="hit",
                    avoided_calls=1,
                )

            # Never cached. run_checks() is model-free and deterministic, so the
            # cache saved no provider call -- and it is also where grounding
            # remediation runs, so a hit skipped the repair and replayed a stale
            # verdict. That made a retry a no-op and a code fix invisible: one
            # production run reached attempt 13 re-reading the same checks.json,
            # each time rejecting on a `missing_grounding` that the remediation
            # in the deployed build would have repaired.
            stage("checking_draft")
            self._ensure_script_ready(project_id, script)
            with tracing.span("script.checking_draft", component="script") as span:
                checks = self.run_checks(project_id)
                span.set(verdict=checks.verdict)

            verification = self.script_store.load_verification_optional(project_id)
            if verification is None:
                if checks.verdict == "reject":
                    self._ensure_script_verifying(project_id, script)
                    verification = VerificationDraft(
                        verdict="revise",
                        issues=[],
                        unsupported_claim_ratio=0,
                    )
                    self.script_store.save_verification(project_id, verification)
                else:
                    stage("verifying_draft")
                    self._ensure_script_ready(project_id, script)
                    with tracing.span("script.verifying_draft", component="script") as span:
                        verification = self.verify_script(
                            project_id,
                            model=verifier_model,
                            prompt_version=prompt_version,
                        )
                        span.set(verdict=verification.verdict)
                        if verification.quality is not None:
                            span.measure(quality_overall=verification.quality.overall)
                            emit_quality_label(
                                label_source="script_verifier",
                                subject_type="script",
                                subject_id=str(project_id),
                                verdict=verification.verdict,
                                score=verification.quality.overall,
                            )

            if revision_is_required(checks, verification):
                revised = self.script_store.load_script_optional(project_id, revised=True)
                if revised is None:
                    stage("revising")
                    self._ensure_script_verifying(project_id, script)
                    with tracing.span("script.revising", component="script"):
                        revised = self.revise_script(
                            project_id,
                            model=reviser_model,
                            prompt_version=prompt_version,
                        )
                else:
                    self._ensure_script_ready(project_id, revised)

                # Not cached, for the same reason as the draft checks above.
                stage("checking_revision")
                self._ensure_script_ready(project_id, revised)
                with tracing.span("script.checking_revision", component="script") as span:
                    revised_checks = self.run_checks(project_id, revised=True)
                    span.set(verdict=revised_checks.verdict)
                original_script = self.script_store.load_script(project_id)
                # By turn_id, not position: a cached revised script can be
                # stale relative to a freshly (re)computed original -- e.g.
                # after an episode_plan repair retry changes segment/turn
                # composition upstream -- and a positional zip(strict=True)
                # crashed on any count mismatch instead of comparing what it
                # safely could.
                original_by_turn_id = {turn.turn_id: turn for turn in original_script.turns}
                changed_turn_count = sum(
                    1
                    for after in revised.turns
                    if (before := original_by_turn_id.get(after.turn_id)) is not None
                    and before.spoken_text_fa != after.spoken_text_fa
                )
                original_overall = (
                    verification.quality.overall if verification.quality is not None else None
                )
                original_issue_count = len(checks.issues) + len(verification.issues)
                # A revision whose checks aren't "pass" is not auto-rejected here:
                # is_better() below already exists to make exactly this call, verdict-
                # rank-aware, for a revision that DOES pass checks but scores worse on
                # verification. Judging by checks alone and stopping the whole build
                # before verification ever ran was a stricter, redundant gate ahead of
                # a comparison that already handles "worse revision, keep the original"
                # by falling through with the original untouched -- the pipeline should
                # not need an operator retry for an outcome it can already resolve.
                revised_verification = self.script_store.load_verification_optional(
                    project_id,
                    revised=True,
                )
                if revised_verification is None:
                    stage("verifying_revision")
                    self._ensure_script_ready(project_id, revised)
                    with tracing.span("script.verifying_revision", component="script") as span:
                        revised_verification = self.verify_script(
                            project_id,
                            model=verifier_model,
                            revised=True,
                            prompt_version=prompt_version,
                        )
                        span.set(verdict=revised_verification.verdict)
                        if revised_verification.quality is not None:
                            span.measure(quality_overall=revised_verification.quality.overall)
                revised_overall = (
                    revised_verification.quality.overall
                    if revised_verification.quality is not None
                    else None
                )
                delta = (
                    round(revised_overall - original_overall, 4)
                    if original_overall is not None and revised_overall is not None
                    else None
                )
                accepted = is_better(
                    (revised_checks, revised_verification),
                    (checks, verification),
                )
                decision = RevisionDecision(
                    project_id=project_id,
                    accepted=accepted,
                    reason=(
                        "The revision ranked higher than the original."
                        if accepted
                        else "The original ranked equal to or higher than the revision."
                    ),
                    original_verdict=verification.verdict,
                    revised_verdict=revised_verification.verdict,
                    original_overall=original_overall,
                    revised_overall=revised_overall,
                    delta=delta,
                    original_issue_count=original_issue_count,
                    revised_issue_count=(
                        len(revised_checks.issues) + len(revised_verification.issues)
                    ),
                    changed_turn_count=changed_turn_count,
                )
                self.script_store.save_revision_decision(decision)
                if decision.accepted:
                    script = revised
                    checks = revised_checks
                    verification = revised_verification
                else:
                    # Recoverable: is_better() already chose the original; record it.
                    self.script_store.append_quality_notes(
                        project_id,
                        [
                            make_quality_note(
                                stage="script_pipeline",
                                kind="revision_rejected",
                                subject=str(project_id),
                            )
                        ],
                    )

            quality_ledger = self.script_store.load_quality_notes_optional(project_id)
            quality_notes = quality_ledger.notes if quality_ledger is not None else []
            project = self.workspace_store.load_project(project_id)
            segment_count = (
                len(project.episode_plan.segments) if project.episode_plan is not None else 0
            )
            outcome, reason = script_outcome(
                checks,
                verification,
                min_overall=(self.min_quality_overall if self.quality_gate_enabled else None),
                quality_notes=quality_notes,
                segment_count=segment_count,
            )
            if outcome == "rejected":
                raise ValueError(f"Script rejected: {reason}")
            self._ensure_script_verifying(project_id, script)
            project = self.workspace_store.load_project(project_id)
            manifest = self.script_store.load_manifest(project_id)
            project.script = script
            if outcome == "review_required":
                transition(project, ProjectState.SCRIPT_REVIEW_REQUIRED)
                manifest.status = "review_required"
                manifest.last_error = reason
            else:
                transition(project, ProjectState.SCRIPT_VERIFIED)
                manifest.status = "verified"
                manifest.last_error = None
                if project.delivery == DeliveryMode.TEXT:
                    # Text delivery has no audio stage: the verified prose script
                    # (written via `self.prose_writer` above) is the finished product.
                    transition(project, ProjectState.COMPLETE)
            self.workspace_store.save_project(project)
            manifest.updated_at = datetime.now(UTC)
            self.script_store.save_manifest(manifest)
            if project.episode_plan is not None and project.episode_plan.parts:
                self._save_part_scripts(project_id, script, project.episode_plan)
            if outcome != "review_required" and project.delivery == DeliveryMode.BOTH:
                with tracing.span("script.building_prose_supplement", component="script"):
                    self._build_prose_supplement(
                        project_id,
                        project,
                        model=writer_model,
                        prompt_version=prompt_version,
                    )
            return ScriptPipelineResult(
                glossary=glossary,
                script=script,
                checks=checks,
                verification=verification,
            )
        except (FileNotFoundError, ModelError, ValueError) as exc:
            self._mark_failed(project_id, str(exc))
            raise

    def _save_part_scripts(
        self,
        project_id: UUID,
        script: Script,
        episode_plan: EpisodePlan,
    ) -> None:
        """Materialize a per-part slice of the verified script (`10c` P3 Step 9).

        Purely a read-side view: turns are grouped by which part their segment
        belongs to, in the whole script's own turn order. Nothing here is
        re-checked or re-verified -- the whole script already was, as one unit.
        """

        part_by_segment = {
            segment.segment_id: segment.part_index for segment in episode_plan.segments
        }
        turns_by_part: dict[int, list[ScriptTurn]] = {}
        for turn in script.turns:
            part_index = part_by_segment.get(turn.segment_id)
            if part_index is None:
                continue
            turns_by_part.setdefault(part_index, []).append(turn)
        for part_index, turns in turns_by_part.items():
            part_title = next(
                (part.title_fa for part in episode_plan.parts if part.part_index == part_index),
                script.title,
            )
            self.script_store.save_part_script(
                project_id,
                part_index,
                Script(
                    title=part_title,
                    turns=turns,
                    glossary_terms_used=script.glossary_terms_used,
                ),
            )

    def _build_prose_supplement(
        self,
        project_id: UUID,
        project: Project,
        *,
        model: str,
        prompt_version: str | None,
    ) -> None:
        """`delivery == both`: a written-lesson supplement alongside the dialogue script.

        Scope decision (`10c` P4, the same kind of call as the step-22 per-part
        decision in STATUS.md): the supplement is grounded -- the prose writer's own
        validator still enforces claim/evidence membership against the same evidence
        packs -- but it does not run its own check/verify/revise cycle. Doing so would
        duplicate the whole script state machine for a bonus artifact; the dialogue
        script (checked, verified, possibly revised) remains the project's one
        pipeline-gated product.
        """

        if self.prose_writer is None or project.brief is None or project.episode_plan is None:
            return
        glossary = self.script_store.load_glossary(project_id)
        graph = self.episode_store.load_disagreement_graph(project_id)
        pack_by_segment = {
            pack.segment_id: pack for pack in self.episode_store.load_evidence_packs(project_id)
        }
        turns: list[ScriptTurn] = []
        segment_count = len(project.episode_plan.segments)
        for index, segment in enumerate(project.episode_plan.segments, start=1):
            pack = pack_by_segment.get(segment.segment_id)
            if pack is None:
                continue
            draft = self.script_store.load_prose_segment_draft_optional(
                project_id, segment.segment_id
            )
            if draft is None:
                result = self.prose_writer.write_segment(
                    project_id=project_id,
                    brief=project.brief,
                    segment=segment,
                    evidence_pack=pack,
                    glossary=glossary,
                    disagreement_graph=graph,
                    model=model,
                    prompt_version=prompt_version,
                    segment_index=index,
                    segment_count=segment_count,
                )
                turns.extend(result.turns)
                self.script_store.save_prose_segment_draft(
                    project_id, segment.segment_id, result.draft
                )
            else:
                turns.extend(self._materialize_prose_segment_turns(segment.segment_id, draft))
        prose_script = Script(
            title=project.episode_plan.title,
            turns=turns,
            glossary_terms_used=[term.preferred_persian for term in glossary.terms],
        )
        self.script_store.save_prose_script(project_id, prose_script)
        if project.episode_plan.parts:
            part_by_segment = {
                segment.segment_id: segment.part_index for segment in project.episode_plan.segments
            }
            turns_by_part: dict[int, list[ScriptTurn]] = {}
            for turn in turns:
                part_index = part_by_segment.get(turn.segment_id)
                if part_index is None:
                    continue
                turns_by_part.setdefault(part_index, []).append(turn)
            for part_index, part_turns in turns_by_part.items():
                part_title = next(
                    (
                        part.title_fa
                        for part in project.episode_plan.parts
                        if part.part_index == part_index
                    ),
                    prose_script.title,
                )
                self.script_store.save_part_prose_script(
                    project_id,
                    part_index,
                    Script(
                        title=part_title,
                        turns=part_turns,
                        glossary_terms_used=prose_script.glossary_terms_used,
                    ),
                )

    def _seed_quality_notes_from_episode(self, project_id: UUID) -> None:
        """Copy plan-time notes into the script ledger once per pipeline binding."""

        if self.script_store.load_quality_notes_optional(project_id) is not None:
            return
        episode_ledger = self.episode_store.load_quality_notes_optional(project_id)
        notes: list[QualityNote] = episode_ledger.notes if episode_ledger is not None else []
        self.script_store.replace_quality_notes(project_id, notes)
        # Fresh script binding: clear prior absorption telemetry so D6 is per-run.
        self.script_store.replace_absorbed_faults(project_id, [], substantive_turn_count=0)

    def _load_claims(self, project_id: UUID) -> list[ClaimRecord]:
        definitions, claims, _cells = self._load_glossary_inputs(project_id)
        del definitions
        return claims

    def _load_glossary_inputs(
        self, project_id: UUID
    ) -> tuple[list[ExtractedDefinition], list[ClaimRecord], list[ConceptCell]]:
        project = self.workspace_store.load_project(project_id)
        claim_ready_ids = self.source_store.list_claim_ready_source_ids(project_id)
        source_ids = [source.source_id for source in project.sources if source.usable_as_evidence]
        if not project.sources:
            source_ids = claim_ready_ids
        if not source_ids:
            raise ValueError("The project has no confirmed evidence sources.")
        missing = sorted(set(source_ids) - set(claim_ready_ids), key=str)
        if missing:
            raise ValueError(
                "Confirmed corpus contains sources that are not claim-ready: "
                + ", ".join(str(source_id) for source_id in missing)
            )
        claims: list[ClaimRecord] = []
        definitions: list[ExtractedDefinition] = []
        concept_cells: list[ConceptCell] = []
        for source_id in source_ids:
            ledger = self.source_store.load_claim_ledger(project_id, source_id)
            claims.extend(ledger.claims)
            definitions.extend(ledger.definitions)
            concept_map = self.source_store.load_concept_map_optional(project_id, source_id)
            if concept_map is not None:
                concept_cells.extend(concept_map.cells)
        return definitions, claims, concept_cells

    def _ensure_script_drafting(self, project_id: UUID) -> None:
        project = self.workspace_store.load_project(project_id)
        if project.state == ProjectState.SCRIPT_DRAFTING:
            return
        if project.state in {
            ProjectState.EPISODE_PLANNED,
            ProjectState.FAILED_RETRYABLE,
            ProjectState.SCRIPT_READY,
            ProjectState.SCRIPT_VERIFYING,
            ProjectState.SCRIPT_REVIEW_REQUIRED,
        }:
            transition(project, ProjectState.SCRIPT_DRAFTING)
        else:
            raise ValueError(f"Cannot restore script drafting from {project.state.value}.")
        self.workspace_store.save_project(project)

    def _ensure_script_ready(self, project_id: UUID, script: Script) -> None:
        project = self.workspace_store.load_project(project_id)
        if project.state == ProjectState.SCRIPT_READY:
            if project.script != script:
                project.script = script
                self.workspace_store.save_project(project)
            return
        if project.state == ProjectState.SCRIPT_VERIFYING:
            transition(project, ProjectState.SCRIPT_DRAFTING)
        if project.state in {ProjectState.EPISODE_PLANNED, ProjectState.FAILED_RETRYABLE}:
            transition(project, ProjectState.SCRIPT_DRAFTING)
        if project.state != ProjectState.SCRIPT_DRAFTING:
            raise ValueError(f"Cannot restore script readiness from {project.state.value}.")
        project.script = script
        transition(project, ProjectState.SCRIPT_READY)
        self.workspace_store.save_project(project)

    def _ensure_script_verifying(self, project_id: UUID, script: Script) -> None:
        project = self.workspace_store.load_project(project_id)
        if project.state == ProjectState.SCRIPT_VERIFYING:
            return
        self._ensure_script_ready(project_id, script)
        project = self.workspace_store.load_project(project_id)
        transition(project, ProjectState.SCRIPT_VERIFYING)
        self.workspace_store.save_project(project)

    @staticmethod
    def _materialize_segment_turns(
        segment_id: str,
        draft: SegmentScriptDraft,
    ) -> list[ScriptTurn]:
        return [
            ScriptTurn(
                turn_id=f"{segment_id}-turn-{index:03d}",
                segment_id=segment_id,
                speaker=turn.speaker,
                spoken_text_fa=turn.spoken_text_fa.strip(),
                claim_ids=turn.claim_ids,
                evidence_ids=turn.evidence_ids,
                editorial_only=turn.editorial_only,
            )
            for index, turn in enumerate(draft.turns, start=1)
        ]

    @staticmethod
    def _materialize_prose_segment_turns(
        segment_id: str,
        draft: ProseLessonDraft,
    ) -> list[ScriptTurn]:
        return [
            ScriptTurn(
                turn_id=f"{segment_id}-turn-{index:03d}",
                segment_id=segment_id,
                speaker="A",
                spoken_text_fa=paragraph.text_fa.strip(),
                claim_ids=paragraph.claim_ids,
                evidence_ids=paragraph.evidence_ids,
                editorial_only=paragraph.editorial_only,
                heading_level=paragraph.heading_level,
            )
            for index, paragraph in enumerate(draft.paragraphs, start=1)
        ]

    @staticmethod
    def _require_state(actual: ProjectState, expected: ProjectState) -> None:
        if actual != expected:
            raise ValueError(f"Expected {expected.value} state, found {actual.value}.")

    @staticmethod
    def _enter_script_drafting(project: Project) -> None:
        if project.state in {
            ProjectState.EPISODE_PLANNED,
            ProjectState.FAILED_RETRYABLE,
            ProjectState.SCRIPT_READY,
            ProjectState.SCRIPT_VERIFYING,
            ProjectState.SCRIPT_REVIEW_REQUIRED,
        }:
            transition(project, ProjectState.SCRIPT_DRAFTING)
        elif project.state != ProjectState.SCRIPT_DRAFTING:
            raise ValueError(f"Cannot draft script from project state {project.state.value}.")

    def _mark_failed(self, project_id: UUID, message: str) -> None:
        project = self.workspace_store.load_project(project_id)
        if project.state == ProjectState.EPISODE_PLANNED:
            return
        if project.state == ProjectState.SCRIPT_READY:
            # SCRIPT_READY cannot transition directly to FAILED_RETRYABLE. Move
            # through the existing retryable drafting state so deterministic
            # rejection still uses the normal failure contract.
            transition(project, ProjectState.SCRIPT_DRAFTING)
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
