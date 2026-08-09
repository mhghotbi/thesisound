from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from thesisound import tracing
from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    EpisodePlan,
    EpisodeSegment,
    EvidenceItem,
    Locator,
    Project,
    ProjectState,
    ResearchBrief,
    SourceAccess,
    SourceCandidate,
    SourceDecision,
    SourceRole,
    SupportStatus,
    TopicType,
    VerificationIssue,
)
from thesisound.episode import DisagreementGraph, SegmentEvidencePack
from thesisound.modeling import ModelExecution, ModelRunRecord
from thesisound.pipeline import WorkspaceStore
from thesisound.script import (
    GlossaryDraft,
    GlossaryTermDraft,
    RevisedTurnDraft,
    ScriptQualityScore,
    ScriptTurnDraft,
    SegmentScriptDraft,
    TargetedRevisionDraft,
    VerificationDraft,
)
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.glossary_builder import GlossaryBuilderService
from thesisound.services.persian_script_writer import PersianScriptWriterService
from thesisound.services.plan_approval import EpisodePlanApprovalStore
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_checks import ScriptChecker
from thesisound.services.script_pipeline_service import ScriptPipelineService
from thesisound.services.script_reviser import TargetedScriptReviserService
from thesisound.services.script_verifier import ScriptVerifierService
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    BlockBuildReport,
    ClaimLedger,
    SourceAnalysisManifest,
    SourceDocumentBlock,
)


class FakeScriptRunner:
    def __init__(
        self,
        *,
        revision_verdict: str = "pass",
        revision_quality: ScriptQualityScore | None = None,
        revision_text_prefix: str = "اصلاح",
    ) -> None:
        self.verification_calls = 0
        self.segment_calls = 0
        self.revision_verdict = revision_verdict
        self.revision_quality = revision_quality
        self.revision_text_prefix = revision_text_prefix

    def run(
        self,
        *,
        project_id: UUID,
        stage: str,
        variables: dict[str, object],
        output_type,
        model: str,
        validator=None,
        **_: object,
    ):
        if output_type is GlossaryDraft:
            output = GlossaryDraft(
                terms=[
                    GlossaryTermDraft(
                        source_term="action",
                        preferred_persian="کنش",
                        first_use_form="کنش",
                        subsequent_use_form="کنش",
                        translation_status="standard",
                    )
                ]
            )
        elif output_type is SegmentScriptDraft:
            self.segment_calls += 1
            segment = variables["segment"]
            pack = variables["evidence_pack"]
            assert isinstance(segment, dict)
            assert isinstance(pack, dict)
            claim_id = segment["claim_ids"][0]
            evidence_id = pack["evidence_items"][0]["evidence_id"]
            output = SegmentScriptDraft(
                turns=[
                    ScriptTurnDraft(
                        speaker="A",
                        spoken_text_fa=_spoken("الف", 50),
                        claim_ids=[claim_id],
                        evidence_ids=[evidence_id],
                    ),
                    ScriptTurnDraft(
                        speaker="B",
                        spoken_text_fa=_spoken("ب", 50),
                        claim_ids=[claim_id],
                        evidence_ids=[evidence_id],
                    ),
                ]
            )
        elif output_type is VerificationDraft:
            self.verification_calls += 1
            script = variables["script"]
            assert isinstance(script, dict)
            turn_id = script["turns"][0]["turn_id"]
            if self.verification_calls == 1:
                output = VerificationDraft(
                    verdict="revise",
                    issues=[
                        VerificationIssue(
                            turn_id=turn_id,
                            severity="high",
                            issue_type="lost_qualification",
                            explanation="The spoken wording drops a material qualification.",
                            required_revision="Restore the qualification without adding facts.",
                        )
                    ],
                    unsupported_claim_ratio=0,
                    quality=ScriptQualityScore(
                        evidence_fidelity=0.55,
                        qualification_preservation=0.50,
                        stance_and_disagreement=0.70,
                        terminology_consistency=0.80,
                        listenability=0.85,
                        actionable_feedback="Restore the dropped qualification.",
                    ),
                )
            else:
                quality = self.revision_quality or ScriptQualityScore(
                    evidence_fidelity=0.95,
                    qualification_preservation=0.90,
                    stance_and_disagreement=0.90,
                    terminology_consistency=0.90,
                    listenability=0.90,
                    actionable_feedback=(
                        "" if self.revision_verdict == "pass" else "The revision still needs work."
                    ),
                )
                output = VerificationDraft(
                    verdict=self.revision_verdict,
                    issues=(
                        []
                        if self.revision_verdict == "pass"
                        else [
                            VerificationIssue(
                                turn_id=turn_id,
                                severity="high",
                                issue_type="lost_qualification",
                                explanation="The revision still drops a qualification.",
                                required_revision="Restore the qualification.",
                            )
                        ]
                    ),
                    unsupported_claim_ratio=0,
                    quality=quality,
                )
        elif output_type is TargetedRevisionDraft:
            targets = variables["target_turns"]
            assert isinstance(targets, list)
            target = targets[0]
            output = TargetedRevisionDraft(
                revised_turns=[
                    RevisedTurnDraft(
                        turn_id=target["turn_id"],
                        speaker=target["speaker"],
                        spoken_text_fa=_spoken(self.revision_text_prefix, 50),
                        claim_ids=target["claim_ids"],
                        evidence_ids=target["evidence_ids"],
                        editorial_only=target["editorial_only"],
                    )
                ]
            )
        else:
            raise AssertionError(f"Unexpected output type: {output_type}")
        if validator is not None:
            validator(output)
        record = ModelRunRecord(
            project_id=project_id,
            stage=stage,
            prompt_id=stage,
            prompt_version="test",
            prompt_hash="test",
            input_hash="test",
            provider="fake",
            model=model,
            output_model=output_type.__name__,
            status="succeeded",
        )
        return ModelExecution(output=output, record=record)


def _spoken(prefix: str, count: int) -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))


def _seed(root: Path) -> tuple[UUID, UUID, str]:
    project_id = uuid4()
    source_id = uuid4()
    claim_id = "clm-1"
    evidence_id = "ev-1"
    block = SourceDocumentBlock(
        block_id="block-1",
        source_id=source_id,
        locator=Locator(page_start=1, page_end=1),
        heading_path=["Action"],
        block_type="argument",
        text="Action depends on plurality and cannot be reduced to fabrication.",
        estimated_token_count=80,
        source_block_keys=["p1"],
    )
    evidence = EvidenceItem(
        evidence_id=evidence_id,
        source_id=source_id,
        block_id=block.block_id,
        claim="Action depends on plurality.",
        claim_type=ClaimType.AUTHOR_POSITION,
        supporting_excerpt="Action depends on plurality",
        locator=block.locator,
        support_kind="direct",
        qualifications=["Within Arendt's account of the vita activa."],
        confidence=0.95,
    )
    claim = ClaimRecord(
        claim_id=claim_id,
        claim="Action depends on plurality.",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=[evidence_id],
        support_status=SupportStatus.STRONG,
        qualifications=["Within Arendt's account of the vita activa."],
    )
    plan = EpisodePlan(
        title="کنش و کثرت",
        listener_outcome="شنونده نسبت کنش و کثرت را توضیح می‌دهد.",
        estimated_duration_minutes=5,
        segments=[
            EpisodeSegment(
                segment_id="seg-001",
                title="کنش و کثرت",
                purpose="توضیح وابستگی کنش به کثرت",
                estimated_minutes=5,
                claim_ids=[claim_id],
                key_question="چرا کنش به کثرت وابسته است؟",
                speaker_dynamic="explanation",
            )
        ],
    )
    project = Project(
        project_id=project_id,
        raw_input="آرنت و کنش",
        state=ProjectState.EPISODE_PLANNED,
        brief=ResearchBrief(
            normalized_topic="آرنت و کنش",
            topic_type=TopicType.CONCEPT,
            central_question="چرا کنش به کثرت وابسته است؟",
            target_duration_minutes=5,
            output_language="fa",
            learning_objectives=["توضیح نسبت کنش و کثرت"],
        ),
        sources=[
            SourceCandidate(
                source_id=source_id,
                title="منبع اصلی",
                role=SourceRole.PRIMARY,
                source_type="book",
                origin="fixture",
                access=SourceAccess.FULL_TEXT,
                user_decision=SourceDecision.INCLUDE,
            )
        ],
        episode_plan=plan,
    )
    WorkspaceStore(root).save_project(project)
    source_store = SourceArtifactStore(root)
    source_store.save_blocks(
        project_id,
        source_id,
        [block],
        BlockBuildReport(
            source_id=source_id,
            input_block_count=1,
            output_block_count=1,
        ),
    )
    source_store.save_claim_ledger(
        project_id,
        source_id,
        ClaimLedger(source_id=source_id, claims=[claim]),
    )
    source_store.save_manifest(
        SourceAnalysisManifest(
            project_id=project_id,
            source_id=source_id,
            source_sha256="a" * 64,
            status="claims_ready",
            block_count=1,
            evidence_count=1,
            claim_count=1,
        )
    )
    episode_store = EpisodeArtifactStore(root)
    episode_store.save_evidence_packs(
        project_id,
        [
            SegmentEvidencePack(
                segment_id="seg-001",
                claim_ids=[claim_id],
                evidence_items=[evidence],
                original_blocks=[block],
                token_budget=7_000,
                actual_tokens=80,
            )
        ],
    )
    episode_store.save_disagreement_graph(DisagreementGraph(project_id=project_id))
    return project_id, source_id, claim_id


def _service(root: Path, runner: FakeScriptRunner) -> ScriptPipelineService:
    return ScriptPipelineService(
        workspace_store=WorkspaceStore(root),
        source_store=SourceArtifactStore(root),
        episode_store=EpisodeArtifactStore(root),
        script_store=ScriptArtifactStore(root),
        approval_store=EpisodePlanApprovalStore(root),
        glossary_builder=GlossaryBuilderService(runner),
        script_writer=PersianScriptWriterService(runner),
        script_checker=ScriptChecker(words_per_minute=20),
        verifier=ScriptVerifierService(runner),
        reviser=TargetedScriptReviserService(runner),
    )


def _approve(root: Path, project_id: UUID) -> None:
    workspace = WorkspaceStore(root)
    EpisodePlanApprovalStore(root).approve(
        workspace.load_project(project_id),
        approved_by="test-user",
    )


def test_script_pipeline_revises_only_flagged_turn_and_verifies(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project_id, _, _ = _seed(root)
    _approve(root, project_id)
    runner = FakeScriptRunner()

    result = _service(root, runner).run(
        project_id,
        glossary_model="fake",
        writer_model="fake",
        verifier_model="fake",
        reviser_model="fake",
    )

    project = WorkspaceStore(root).load_project(project_id)
    script_dir = root / str(project_id) / "script"
    assert project.state == ProjectState.SCRIPT_VERIFIED
    assert result.verification.verdict == "pass"
    assert result.verification.unsupported_claim_ratio == 0
    assert result.script.turns[0].spoken_text_fa.startswith("اصلاح")
    assert result.script.turns[1].spoken_text_fa.startswith("ب0")
    assert all(turn.evidence_ids == ["ev-1"] for turn in result.script.turns)
    assert (script_dir / "glossary.json").exists()
    assert (script_dir / "script-draft.json").exists()
    assert (script_dir / "script-revised.json").exists()
    assert (script_dir / "checks-revised.json").exists()
    assert (script_dir / "verification-revised.json").exists()
    decision = ScriptArtifactStore(root).load_revision_decision_optional(project_id)
    assert decision is not None
    assert decision.accepted is True
    assert decision.delta is not None and decision.delta > 0


def test_full_run_produces_a_span_per_stage_and_a_revision_cycle(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    root = tmp_path / "workspaces"
    project_id, _, _ = _seed(root)
    _approve(root, project_id)
    runner = FakeScriptRunner()

    with tracing.span("script.run", kind="stage", project_id=project_id) as parent:
        _service(root, runner).run(
            project_id,
            glossary_model="fake",
            writer_model="fake",
            verifier_model="fake",
            reviser_model="fake",
        )

    # The fake verifier fails once then passes, so this run takes the full
    # revise -> recheck -> reverify path, not just the happy path.
    step_names = [
        "script.building_glossary",
        "script.writing_segments",
        "script.checking_draft",
        "script.verifying_draft",
        "script.revising",
        "script.checking_revision",
        "script.verifying_revision",
    ]
    for name in step_names:
        step = recording_tracer.sink.one(name)
        assert step.parent_span_id == parent.context.span_id
        assert step.status == "ok"

    verify_span = recording_tracer.sink.one("script.verifying_draft")
    assert verify_span.attributes["verdict"] == "revise"
    assert verify_span.metrics["quality_overall"] > 0
    reverify_span = recording_tracer.sink.one("script.verifying_revision")
    assert reverify_span.attributes["verdict"] == "pass"
    # run.stage_changed events come from ScriptBuildRunService's on_stage
    # callback (see test_script_run.py), not from ScriptPipelineService
    # itself -- this test exercises the pipeline service in isolation, the
    # same way the rest of this file does, so none are expected here.


def test_resumed_run_emits_a_cache_hit_instead_of_a_glossary_span(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    """A prior attempt already built the glossary (a common resume shape
    after a mid-pipeline crash/retry): run() must skip rebuilding it and
    record that as a cache hit rather than silently doing nothing."""

    root = tmp_path / "workspaces"
    project_id, _, _ = _seed(root)
    _approve(root, project_id)
    runner = FakeScriptRunner()
    service = _service(root, runner)
    service.build_glossary(project_id, model="fake")

    service.run(
        project_id,
        glossary_model="fake",
        writer_model="fake",
        verifier_model="fake",
        reviser_model="fake",
    )

    assert recording_tracer.sink.find("script.building_glossary") == []
    cache_hits = [
        event
        for event in recording_tracer.sink.events
        if event.name == "cache.lookup" and event.attributes.get("cache") == "script_glossary"
    ]
    assert len(cache_hits) == 1
    assert cache_hits[0].attributes["result"] == "hit"
    assert runner.segment_calls > 0  # the rest of the run proceeded past the glossary step


def test_script_pipeline_requires_current_explicit_plan_approval(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project_id, _, _ = _seed(root)

    with pytest.raises(ValueError, match="not been explicitly approved"):
        _service(root, FakeScriptRunner()).run(
            project_id,
            glossary_model="fake",
            writer_model="fake",
            verifier_model="fake",
            reviser_model="fake",
        )

    assert WorkspaceStore(root).load_project(project_id).state == ProjectState.EPISODE_PLANNED


def test_script_writer_resumes_completed_segment_draft(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project_id, _, _ = _seed(root)
    _approve(root, project_id)
    runner = FakeScriptRunner()
    service = _service(root, runner)
    service.build_glossary(project_id, model="fake")
    service.write_script(project_id, model="fake")
    assert runner.segment_calls == 1

    project = WorkspaceStore(root).load_project(project_id)
    project.state = ProjectState.SCRIPT_DRAFTING
    project.script = None
    WorkspaceStore(root).save_project(project)
    (root / str(project_id) / "script" / "script-draft.json").unlink()

    service.write_script(project_id, model="fake")

    assert runner.segment_calls == 1


def test_script_claim_scope_excludes_unselected_claim_ready_source(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project_id, _, _ = _seed(root)
    stale_source = uuid4()
    SourceArtifactStore(root).save_claim_ledger(
        project_id,
        stale_source,
        ClaimLedger(
            source_id=stale_source,
            claims=[
                ClaimRecord(
                    claim_id="stale-claim",
                    claim="Stale claim",
                    claim_type=ClaimType.AUTHOR_POSITION,
                    evidence_ids=["stale-evidence"],
                    support_status=SupportStatus.STRONG,
                )
            ],
        ),
    )
    SourceArtifactStore(root).save_manifest(
        SourceAnalysisManifest(
            project_id=project_id,
            source_id=stale_source,
            source_sha256="b" * 64,
            status="claims_ready",
            claim_count=1,
        )
    )

    claims = _service(root, FakeScriptRunner())._load_claims(project_id)

    assert [claim.claim_id for claim in claims] == ["clm-1"]


def test_script_turn_contract_rejects_substantive_turn_without_evidence() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ScriptTurnDraft(
            speaker="A",
            spoken_text_fa="این یک ادعای محتوایی است.",
            claim_ids=["clm-1"],
            evidence_ids=[],
        )


def _quality_score(value: float, feedback: str) -> ScriptQualityScore:
    return ScriptQualityScore(
        evidence_fidelity=value,
        qualification_preservation=value,
        stance_and_disagreement=value,
        terminology_consistency=value,
        listenability=value,
        actionable_feedback=feedback,
    )


def test_worse_revision_is_kept_on_disk_but_the_original_is_used(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspaces"
    project_id, _, _ = _seed(root)
    _approve(root, project_id)
    runner = FakeScriptRunner(
        revision_verdict="revise",
        revision_quality=_quality_score(0.20, "The revision is worse."),
    )

    result = _service(root, runner).run(
        project_id,
        glossary_model="fake",
        writer_model="fake",
        verifier_model="fake",
        reviser_model="fake",
    )

    assert result.verification.verdict != "pass"
    assert (
        WorkspaceStore(root).load_project(project_id).state == ProjectState.SCRIPT_REVIEW_REQUIRED
    )
    store = ScriptArtifactStore(root)
    decision = store.load_revision_decision_optional(project_id)
    assert decision is not None and decision.accepted is False
    assert (store.script_dir(project_id) / "script-revised.json").exists()
    assert store.load_latest_script(project_id).turns[0].spoken_text_fa.startswith("الف0")


def test_tied_revision_keeps_the_original(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project_id, _, _ = _seed(root)
    _approve(root, project_id)
    runner = FakeScriptRunner(
        revision_verdict="revise",
        revision_quality=ScriptQualityScore(
            evidence_fidelity=0.55,
            qualification_preservation=0.50,
            stance_and_disagreement=0.70,
            terminology_consistency=0.80,
            listenability=0.85,
            actionable_feedback="Restore the dropped qualification.",
        ),
    )

    result = _service(root, runner).run(
        project_id,
        glossary_model="fake",
        writer_model="fake",
        verifier_model="fake",
        reviser_model="fake",
    )

    assert result.verification.verdict != "pass"
    assert (
        WorkspaceStore(root).load_project(project_id).state == ProjectState.SCRIPT_REVIEW_REQUIRED
    )
    decision = ScriptArtifactStore(root).load_revision_decision_optional(project_id)
    assert decision is not None and decision.accepted is False
    assert decision.delta == 0


def test_revision_failing_deterministic_checks_records_a_rejected_decision(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspaces"
    project_id, _, _ = _seed(root)
    _approve(root, project_id)
    runner = FakeScriptRunner(revision_text_prefix="system prompt")

    with pytest.raises(ValueError, match="deterministic checks; the original"):
        _service(root, runner).run(
            project_id,
            glossary_model="fake",
            writer_model="fake",
            verifier_model="fake",
            reviser_model="fake",
        )

    decision = ScriptArtifactStore(root).load_revision_decision_optional(project_id)
    assert decision is not None
    assert decision.accepted is False
    assert decision.revised_verdict is None


def test_artifacts_without_a_decision_file_still_use_the_revision(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspaces"
    project_id, _, _ = _seed(root)
    _approve(root, project_id)
    _service(root, FakeScriptRunner()).run(
        project_id,
        glossary_model="fake",
        writer_model="fake",
        verifier_model="fake",
        reviser_model="fake",
    )
    store = ScriptArtifactStore(root)
    (store.script_dir(project_id) / "revision-decision.json").unlink()

    assert store.has_revised_script(project_id) is True
    assert store.load_latest_script(project_id).turns[0].spoken_text_fa.startswith("اصلاح")
