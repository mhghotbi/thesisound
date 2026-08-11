"""R6: semantic identity invalidates evidence, plan, script, ASR, and QA reuse."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from thesisound import tracing
from thesisound.audio import AsrTranscript, AudioSegmentQa
from thesisound.domain import (
    EpisodePlan,
    EpisodeSegment,
    Project,
    ProjectState,
    ResearchBrief,
    TopicType,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.script import Glossary, ScriptTurnDraft, SegmentScriptDraft
from thesisound.services.audio_artifact_store import AudioArtifactStore
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.plan_approval import EpisodePlanApprovalStore, episode_plan_hash
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.semantic_identity import (
    AUDIO_QA_VERSION,
    SCRIPT_CHECKER_VERSION,
    audio_qa_identity,
    claim_reconciler_identity,
    evidence_extraction_identity,
    first_mismatch,
    planning_semantic,
    script_pipeline_identity,
    script_pipeline_key,
)


def test_first_mismatch_reports_identity_missing_and_field_reasons() -> None:
    current = evidence_extraction_identity(model="m1", prompt_version="1.0.0")
    assert first_mismatch(None, current, ("model", "prompt_version", "extractor_version")) == (
        "identity_missing"
    )
    assert (
        first_mismatch(
            {"model": "m1", "prompt_version": "1.0.0", "extractor_version": 1},
            current,
            ("model", "prompt_version", "extractor_version"),
        )
        is None
    )
    assert (
        first_mismatch(
            {"model": "other", "prompt_version": "1.0.0", "extractor_version": 1},
            current,
            ("model", "prompt_version", "extractor_version"),
        )
        == "model_mismatch"
    )


def test_extract_evidence_does_not_skip_when_model_differs(tmp_path: Path) -> None:
    from tests.test_evidence_scope import _prepare_equal_blocks_source

    service, project_id, source_id = _prepare_equal_blocks_source(
        tmp_path,
        duration=10,
        block_count=18,
        tokens_per_block=100,
    )
    service.extract_evidence(project_id, source_id, model="fake-a")

    skip_snapshots: list[set[str]] = []
    original = service.evidence_extractor.extract_source

    def wrapped(**kwargs):
        skip_snapshots.append(set(kwargs.get("skip_block_ids") or set()))
        return original(**kwargs)

    service.evidence_extractor.extract_source = wrapped  # type: ignore[method-assign]
    service.extract_evidence(project_id, source_id, model="fake-b")

    assert skip_snapshots[0] == set()


def test_extract_evidence_skips_when_identity_matches(tmp_path: Path) -> None:
    from tests.test_evidence_scope import _prepare_equal_blocks_source

    service, project_id, source_id = _prepare_equal_blocks_source(
        tmp_path,
        duration=10,
        block_count=18,
        tokens_per_block=100,
    )
    store = service.artifact_store
    service.extract_evidence(project_id, source_id, model="fake")

    skip_snapshots: list[set[str]] = []
    original = service.evidence_extractor.extract_source

    def wrapped(**kwargs):
        skip_snapshots.append(set(kwargs.get("skip_block_ids") or set()))
        return original(**kwargs)

    service.evidence_extractor.extract_source = wrapped  # type: ignore[method-assign]
    service.extract_evidence(project_id, source_id, model="fake")
    plan = store.load_extraction_plan(project_id, source_id)
    assert skip_snapshots[0] == set(plan.selected_block_ids)

    records = store.load_block_extractions(project_id, source_id)
    stamped = [r for r in records if r.status == "extracted"]
    assert stamped
    assert stamped[0].extraction_identity == evidence_extraction_identity(
        model="fake",
        prompt_version=None,
    )


def test_claim_carry_forward_refuses_model_change(
    tmp_path: Path,
    recording_tracer: tracing.Tracer,
) -> None:
    from tests.test_corpus_building import (
        FakeAnalysisService,
        _brief_project,
        _seed_claim_ready_artifacts,
        _service,
        _source_input,
    )

    workspace = WorkspaceStore(tmp_path / "workspaces")
    project = _brief_project()
    fake = FakeAnalysisService(workspace)
    service = _service(tmp_path, project, fake)
    source_id = uuid4()
    _seed_claim_ready_artifacts(service.source_store, project, source_id)
    ledger = service.source_store.load_claim_ledger(project.project_id, source_id)
    service.source_store.save_claim_ledger(
        project.project_id,
        source_id,
        ledger.model_copy(
            update={
                "reconciler_identity": claim_reconciler_identity(
                    model="other-model",
                    prompt_version=None,
                )
            }
        ),
    )

    run = service.queue(project.project_id, [_source_input(tmp_path, source_id, "source")])

    assert run.sources[0].status == "queued"
    miss = [
        event
        for event in recording_tracer.sink.events
        if event.name == "cache.lookup"
        and event.attributes.get("cache") == "claim_ledger"
        and event.attributes.get("result") == "miss"
    ]
    assert miss
    assert miss[0].attributes.get("invalidation_reason") == "model_mismatch"


def test_planning_key_changes_with_model(
    tmp_path: Path,
    recording_tracer: tracing.Tracer,
) -> None:
    from tests.test_episode_preparation import _prepared_project, _service

    root = tmp_path / "workspaces"
    project = _prepared_project(root)
    service = _service(root)

    service.audit_coverage(project.project_id, model="model-a")
    first_key = EpisodeArtifactStore(root).load_stage_inputs(project.project_id).coverage

    service.audit_coverage(project.project_id, model="model-b")
    second_key = EpisodeArtifactStore(root).load_stage_inputs(project.project_id).coverage

    assert first_key != second_key
    miss = [
        event
        for event in recording_tracer.sink.events
        if event.name == "cache.lookup"
        and event.attributes.get("cache") == "coverage_audit"
        and event.attributes.get("result") == "miss"
        and event.attributes.get("invalidation_reason") == "model_mismatch"
    ]
    assert miss


def test_script_pipeline_identity_change_clears_artifacts(
    tmp_path: Path,
    recording_tracer: tracing.Tracer,
) -> None:
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    project = Project(
        raw_input="موضوع",
        state=ProjectState.EPISODE_PLANNED,
        brief=ResearchBrief(
            normalized_topic="موضوع",
            topic_type=TopicType.CONCEPT,
            central_question="سؤال؟",
            target_duration_minutes=5,
        ),
        episode_plan=EpisodePlan(
            title="طرح",
            listener_outcome="فهم",
            estimated_duration_minutes=5,
            segments=[
                EpisodeSegment(
                    segment_id="seg-1",
                    title="بخش",
                    purpose="توضیح",
                    estimated_minutes=5,
                    claim_ids=["claim-1"],
                    key_question="سؤال؟",
                    speaker_dynamic="explanation",
                )
            ],
        ),
    )
    workspace.save_project(project)
    approvals = EpisodePlanApprovalStore(root)
    artifacts = ScriptArtifactStore(root)
    approval = approvals.approve(project, approved_by="operator")
    identity_a = script_pipeline_identity(
        glossary_model="m1",
        glossary_prompt_version=None,
        writer_model="m1",
        writer_prompt_version=None,
        verifier_model="m1",
        verifier_prompt_version=None,
        reviser_model="m1",
        reviser_prompt_version=None,
    )
    assert artifacts.prepare_for_pipeline(project.project_id, approval.plan_hash, identity_a) is False
    artifacts.save_segment_draft(
        project.project_id,
        "seg-1",
        SegmentScriptDraft(
            turns=[
                ScriptTurnDraft(
                    speaker="A",
                    spoken_text_fa="متن",
                    claim_ids=["claim-1"],
                    evidence_ids=["evidence-1"],
                )
            ]
        ),
    )
    artifacts.save_glossary(Glossary(project_id=project.project_id, model_run_id=uuid4()))

    identity_b = script_pipeline_identity(
        glossary_model="m1",
        glossary_prompt_version=None,
        writer_model="m2",
        writer_prompt_version=None,
        verifier_model="m1",
        verifier_prompt_version=None,
        reviser_model="m1",
        reviser_prompt_version=None,
    )
    matched = artifacts.prepare_for_pipeline(
        project.project_id,
        approval.plan_hash,
        identity_b,
    )

    assert matched is False
    assert artifacts.load_segment_draft_optional(project.project_id, "seg-1") is None
    miss = [
        event
        for event in recording_tracer.sink.events
        if event.name == "cache.lookup"
        and event.attributes.get("cache") == "script_pipeline"
        and event.attributes.get("result") == "miss"
    ]
    assert miss
    assert miss[-1].attributes.get("invalidation_reason") == "writer_model_mismatch"
    assert script_pipeline_key(approval.plan_hash, identity_a) != script_pipeline_key(
        approval.plan_hash,
        identity_b,
    )
    assert episode_plan_hash(project.episode_plan) == approval.plan_hash


def test_asr_reuse_requires_matching_model(
    tmp_path: Path,
    recording_tracer: tracing.Tracer,
) -> None:
    store = AudioArtifactStore(tmp_path / "workspaces")
    project_id = uuid4()
    transcript = AsrTranscript(
        chunk_id="audio-0001",
        chunk_hash="a" * 64,
        wav_sha256="b" * 64,
        text="متن",
        speaker="A",
        provider="fake",
        model="asr-v1",
    )
    store.save_transcript(project_id, transcript)

    assert (
        store.load_transcript_optional(
            project_id,
            "audio-0001",
            "a" * 64,
            "b" * 64,
            expected_model="asr-v1",
        )
        == transcript
    )
    assert (
        store.load_transcript_optional(
            project_id,
            "audio-0001",
            "a" * 64,
            "b" * 64,
            expected_model="asr-v2",
        )
        is None
    )
    miss = [
        event
        for event in recording_tracer.sink.events
        if event.name == "cache.lookup" and event.attributes.get("cache") == "asr_transcript"
    ]
    assert any(event.attributes.get("invalidation_reason") == "model_mismatch" for event in miss)


def test_qa_verified_gate_requires_threshold_identity(
    tmp_path: Path,
    recording_tracer: tracing.Tracer,
) -> None:
    store = AudioArtifactStore(tmp_path / "workspaces")
    project_id = uuid4()
    identity = audio_qa_identity(
        pass_threshold=0.9,
        review_threshold=0.78,
        missing_sentence_threshold=0.85,
        qa_version=AUDIO_QA_VERSION,
    )
    qa = AudioSegmentQa(
        chunk_id="audio-0001",
        chunk_hash="a" * 64,
        wav_sha256="b" * 64,
        verdict="pass",
        similarity_ratio=1,
        expected_text="متن",
        transcript_text="متن",
        **identity,
    )
    store.save_qa(project_id, qa)

    assert (
        store.load_qa_optional(
            project_id,
            "audio-0001",
            "a" * 64,
            "b" * 64,
            expected_identity=identity,
        )
        == qa
    )
    changed = audio_qa_identity(
        pass_threshold=0.95,
        review_threshold=0.78,
        missing_sentence_threshold=0.85,
    )
    assert (
        store.load_qa_optional(
            project_id,
            "audio-0001",
            "a" * 64,
            "b" * 64,
            expected_identity=changed,
        )
        is None
    )
    miss = [
        event
        for event in recording_tracer.sink.events
        if event.name == "cache.lookup" and event.attributes.get("cache") == "audio_qa"
    ]
    assert any(
        event.attributes.get("invalidation_reason") == "pass_threshold_mismatch"
        for event in miss
    )

    legacy = AudioSegmentQa(
        chunk_id="audio-0002",
        chunk_hash="c" * 64,
        wav_sha256="d" * 64,
        verdict="pass",
        similarity_ratio=1,
        expected_text="متن",
        transcript_text="متن",
    )
    store.save_qa(project_id, legacy)
    assert (
        store.load_qa_optional(
            project_id,
            "audio-0002",
            "c" * 64,
            "d" * 64,
            expected_identity=identity,
        )
        is None
    )


def test_planning_semantic_and_checker_version_are_stable() -> None:
    assert planning_semantic(model="m", prompt_version=None, stage_version=1) == {
        "model": "m",
        "prompt_version": "default",
        "stage_version": 1,
    }
    assert SCRIPT_CHECKER_VERSION == 1
