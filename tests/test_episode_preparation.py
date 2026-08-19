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
    EvidenceExtraction,
    EvidenceItem,
    ExtractedAuxiliaryPoint,
    ExtractedDefinition,
    Locator,
    Project,
    ProjectState,
    ResearchBrief,
    SupportStatus,
    TopicType,
)
from thesisound.episode import (
    ClaimPriorityRecord,
    ClaimPriorityReport,
    CoverageAuditDraft,
    CoverageReport,
    DisagreementGraph,
    EpisodeBudgetReport,
    EpisodePlanDraft,
    EpisodeSegmentDraft,
    ObjectiveCoverageDraft,
)
from thesisound.modeling import ModelExecution, ModelRunRecord
from thesisound.pipeline import WorkspaceStore
from thesisound.services.claim_prioritizer import ClaimPrioritizer
from thesisound.services.coverage_auditor import CoverageAuditorService
from thesisound.services.disagreement_graph import DisagreementGraphBuilder
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.episode_budget import EpisodeBudgetEstimator
from thesisound.services.episode_planner import EpisodePlannerService
from thesisound.services.episode_preparation_service import (
    CorpusArtifacts,
    EpisodePreparationService,
)
from thesisound.services.evidence_pack_builder import EvidencePackBuilder
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import (
    AnalysisProfile,
    BlockBuildReport,
    BlockEvidenceExtraction,
    ClaimLedger,
    EvidenceExtractionPlan,
    SourceAnalysisManifest,
    SourceDocumentBlock,
)


class FakeEpisodeRunner:
    def __init__(self, fail_stages: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self.fail_stages = fail_stages or set()

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
        self.calls.append(stage)
        if stage in self.fail_stages:
            raise ValueError(f"{stage} failed")
        if output_type is CoverageAuditDraft:
            brief = variables["research_brief"]
            claims = variables["claims"]
            assert isinstance(brief, dict)
            assert isinstance(claims, list)
            claim_ids = [item["claim_id"] for item in claims]
            output = CoverageAuditDraft(
                central_question_status="well_covered",
                central_question_claim_ids=[claim_ids[0]],
                objective_coverage=[
                    ObjectiveCoverageDraft(
                        objective=objective,
                        status="well_covered",
                        claim_ids=[claim_ids[index % len(claim_ids)]],
                        rationale="A grounded claim directly supports this objective.",
                    )
                    for index, objective in enumerate(brief["learning_objectives"])
                ],
                max_supported_minutes=brief["target_duration_minutes"],
                recommendation="continue",
                recommendation_reason="The corpus supports the requested duration.",
            )
        elif output_type is EpisodePlanDraft:
            brief = variables["research_brief"]
            priorities = variables["claim_priorities"]
            assert isinstance(brief, dict)
            assert isinstance(priorities, dict)
            selected = [
                item["claim_id"]
                for item in priorities["priorities"]
                if item["level"] in {"must_include", "supporting", "optional"}
            ]
            midpoint = max(1, len(selected) // 2)
            first = selected[:midpoint]
            second = selected[midpoint:]
            duration = brief["target_duration_minutes"]
            segments = [
                EpisodeSegmentDraft(
                    title="Core distinction",
                    purpose="Introduce the central conceptual distinction.",
                    target_minutes=duration / 2,
                    claim_ids=first,
                    key_question="What is the central distinction?",
                    speaker_dynamic="explanation",
                )
            ]
            if second:
                segments.append(
                    EpisodeSegmentDraft(
                        title="Implications",
                        purpose="Develop the implications without repeating claims.",
                        target_minutes=duration / 2,
                        claim_ids=second,
                        prerequisite_claim_ids=[first[0]],
                        key_question="What follows from this distinction?",
                        speaker_dynamic="questioning",
                    )
                )
            else:
                segments[0].target_minutes = duration
            output = EpisodePlanDraft(
                title="Action and fabrication",
                listener_outcome="The listener can explain the central distinction.",
                segments=segments,
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


def _brief(duration: int = 10) -> ResearchBrief:
    return ResearchBrief(
        normalized_topic="Arendt and action",
        topic_type=TopicType.CONCEPT,
        central_question="What distinguishes action from fabrication?",
        target_duration_minutes=duration,
        learning_objectives=[
            "Distinguish action from fabrication.",
            "Explain why plurality matters.",
        ],
    )


def _claim(index: int, evidence_id: str) -> ClaimRecord:
    return ClaimRecord(
        claim_id=f"clm-{index}",
        claim=f"Grounded claim {index}",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=[evidence_id],
        support_status=SupportStatus.STRONG,
    )


def _seed_source(root: Path, project_id: UUID, *, offset: int = 0) -> UUID:
    """Seed one claim-ready source; `offset` keeps a second source's IDs distinct."""

    source_id = uuid4()
    store = SourceArtifactStore(root)
    first, last = 1 + offset, 3 + offset
    blocks = [
        SourceDocumentBlock(
            block_id=f"block-{index}",
            source_id=source_id,
            locator=Locator(page_start=index, page_end=index),
            heading_path=["Action"],
            block_type="argument",
            text=f"Original grounded passage number {index} explains action and plurality.",
            estimated_token_count=80,
            source_block_keys=[f"p{index}"],
            previous_block_id=f"block-{index - 1}" if index > first else None,
            next_block_id=f"block-{index + 1}" if index < last else None,
        )
        for index in range(first, last + 1)
    ]
    store.save_blocks(
        project_id,
        source_id,
        blocks,
        BlockBuildReport(
            source_id=source_id,
            input_block_count=3,
            output_block_count=3,
        ),
    )
    records = []
    claims = []
    for index, block in enumerate(blocks, start=first):
        evidence = EvidenceItem(
            evidence_id=f"ev-{index}",
            source_id=source_id,
            block_id=block.block_id,
            claim=f"Grounded claim {index}",
            claim_type=ClaimType.AUTHOR_POSITION,
            supporting_excerpt=f"Original grounded passage number {index}",
            locator=block.locator,
            support_kind="direct",
            confidence=0.95,
        )
        records.append(
            BlockEvidenceExtraction(
                source_id=source_id,
                block_id=block.block_id,
                extraction=EvidenceExtraction(
                    segment_function="argument",
                    claims=[evidence],
                ),
            )
        )
        claims.append(_claim(index, evidence.evidence_id))
    store.save_evidence(project_id, source_id, records)
    store.save_claim_ledger(
        project_id,
        source_id,
        ClaimLedger(source_id=source_id, claims=claims),
    )
    store.save_extraction_plan(
        project_id,
        source_id,
        EvidenceExtractionPlan(
            source_id=source_id,
            profile=AnalysisProfile(
                depth="deep",
                target_duration_minutes=30,
                block_coverage_target=1,
                evidence_input_token_budget=20_000,
                max_claims_per_block=5,
                neighbor_context_blocks=1,
                include_examples=True,
                include_objections_and_responses=True,
                second_pass_for_core_sections=False,
            ),
            selected_block_ids=[block.block_id for block in blocks],
            selected_source_tokens=240,
            total_source_tokens=240,
            achieved_token_coverage=1,
        ),
    )
    store.save_manifest(
        SourceAnalysisManifest(
            project_id=project_id,
            source_id=source_id,
            source_sha256="a" * 64,
            status="claims_ready",
            block_count=3,
            selected_block_count=3,
            evidence_count=3,
            claim_count=3,
        )
    )
    return source_id


def _service(root: Path, runner: FakeEpisodeRunner | None = None) -> EpisodePreparationService:
    runner = runner or FakeEpisodeRunner()
    return EpisodePreparationService(
        workspace_store=WorkspaceStore(root),
        source_store=SourceArtifactStore(root),
        episode_store=EpisodeArtifactStore(root),
        coverage_auditor=CoverageAuditorService(runner),
        claim_prioritizer=ClaimPrioritizer(),
        budget_estimator=EpisodeBudgetEstimator(),
        disagreement_builder=DisagreementGraphBuilder(),
        episode_planner=EpisodePlannerService(runner),
        evidence_pack_builder=EvidencePackBuilder(),
    )


def test_prepare_episode_writes_plan_and_grounded_packs(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    project = Project(
        raw_input="Arendt and action",
        state=ProjectState.CORPUS_READY,
        brief=_brief(10),
    )
    workspace.save_project(project)
    _seed_source(root, project.project_id)

    coverage, priorities, budget, graph, plan, packs = _service(root).prepare_episode(
        project.project_id,
        coverage_model="fake-strong",
        planning_model="fake-strong",
    )

    episode_dir = root / str(project.project_id) / "episode"
    assert coverage.can_plan_episode is True
    assert any(item.level == "must_include" for item in priorities.priorities)
    assert budget.effective_supported_minutes >= 8
    assert graph.project_id == project.project_id
    assert len(plan.segments) == len(packs)
    assert all(pack.original_blocks for pack in packs)
    assert all(pack.evidence_items for pack in packs)
    assert all(
        [claim.claim_id for claim in pack.claims] == pack.claim_ids for pack in packs
    )
    if len(plan.segments) > 1:
        assert plan.segments[1].prerequisite_claim_ids == [plan.segments[0].claim_ids[0]]
    assert workspace.load_project(project.project_id).state == ProjectState.EPISODE_PLANNED
    assert (episode_dir / "coverage-report.json").exists()
    assert (episode_dir / "claim-priorities.json").exists()
    assert (episode_dir / "budget-report.json").exists()
    assert (episode_dir / "disagreement-graph.json").exists()
    assert (episode_dir / "episode-plan.json").exists()
    assert (episode_dir / "evidence-packs.jsonl").exists()
    assert (episode_dir / "must-not-be-lost-review.json").exists()


class _SpyPlanRunner:
    """Captures the variables sent to the episode_plan prompt for one call."""

    def __init__(self) -> None:
        self.captured_variables: dict[str, object] | None = None

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
        assert output_type is EpisodePlanDraft
        self.captured_variables = variables
        output = EpisodePlanDraft(
            title="Action and fabrication",
            listener_outcome="The listener can explain the central distinction.",
            segments=[
                EpisodeSegmentDraft(
                    title="Core distinction",
                    purpose="Introduce the central conceptual distinction.",
                    target_minutes=10,
                    claim_ids=["clm-1"],
                    key_question="What is the central distinction?",
                    speaker_dynamic="explanation",
                )
            ],
        )
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


def test_episode_planner_sends_grounded_auxiliary_evidence_to_the_prompt() -> None:
    """The prompt must receive real extracted content, not be left to invent it."""

    project_id = uuid4()
    claim = ClaimRecord(
        claim_id="clm-1",
        claim="Action occurs directly between persons.",
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=["ev-1"],
        support_status=SupportStatus.STRONG,
    )
    definition = ExtractedDefinition(
        term="Action",
        definition="Direct disclosure between persons.",
        source_id=project_id,
        block_id="block-1",
        locator=Locator(page_start=1, page_end=1),
    )
    example = ExtractedAuxiliaryPoint(
        text="Speech in the assembly.",
        source_id=project_id,
        block_id="block-1",
        locator=Locator(page_start=1, page_end=1),
    )
    coverage = CoverageReport(
        project_id=project_id,
        central_question_status="well_covered",
        central_question_claim_ids=[claim.claim_id],
        max_supported_minutes=10,
        recommendation="continue",
        recommendation_reason="The corpus supports the requested duration.",
        can_plan_episode=True,
        model_run_id=uuid4(),
    )
    budget = EpisodeBudgetReport(
        project_id=project_id,
        target_duration_minutes=10,
        words_per_minute=150,
        available_claim_seconds=600,
        original_evidence_tokens=1_000,
        estimated_supported_minutes=10,
        model_reported_supported_minutes=10,
        effective_supported_minutes=10,
        calibration_status="uncalibrated",
    )
    priorities = ClaimPriorityReport(
        project_id=project_id,
        target_duration_minutes=10,
        priorities=[
            ClaimPriorityRecord(
                claim_id=claim.claim_id,
                level="must_include",
                score=90,
                estimated_explanation_seconds=60,
            )
        ],
        available_content_seconds=600,
        estimated_selected_seconds=60,
    )
    graph = DisagreementGraph(project_id=project_id)

    runner = _SpyPlanRunner()
    EpisodePlannerService(runner).plan(
        project_id=project_id,
        brief=_brief(10),
        claims=[claim],
        coverage=coverage,
        budget=budget,
        priorities=priorities,
        disagreement_graph=graph,
        extraction_plans=[],
        definitions=[definition],
        distinctions=[],
        examples=[example],
        objections=[],
        responses=[],
        model="fake",
    )

    assert runner.captured_variables is not None
    assert runner.captured_variables["definitions"] == [definition.model_dump(mode="json")]
    assert runner.captured_variables["examples"] == [example.model_dump(mode="json")]
    assert runner.captured_variables["distinctions"] == []
    assert runner.captured_variables["objections"] == []
    assert runner.captured_variables["responses"] == []


def test_build_must_not_be_lost_review_distinguishes_used_and_omitted_claims() -> None:
    """Extraction 2.0 (10c P2 Step 1): the flag lives on the claim, not a block-level point."""

    project_id = uuid4()
    source_id = uuid4()

    corpus = CorpusArtifacts(
        source_ids=[source_id],
        claims=[
            ClaimRecord(
                claim_id="clm-used",
                claim="Used claim.",
                claim_type=ClaimType.AUTHOR_POSITION,
                evidence_ids=["ev-used"],
                support_status=SupportStatus.STRONG,
                must_not_be_lost=True,
            ),
            ClaimRecord(
                claim_id="clm-omitted",
                claim="Omitted claim.",
                claim_type=ClaimType.AUTHOR_POSITION,
                evidence_ids=["ev-omitted"],
                support_status=SupportStatus.STRONG,
                must_not_be_lost=True,
            ),
            ClaimRecord(
                claim_id="clm-unflagged",
                claim="Unflagged claim.",
                claim_type=ClaimType.AUTHOR_POSITION,
                evidence_ids=["ev-unflagged"],
                support_status=SupportStatus.STRONG,
            ),
        ],
        evidence_items=[
            EvidenceItem(
                evidence_id="ev-used",
                source_id=source_id,
                block_id="block-used",
                claim="Used claim.",
                claim_type=ClaimType.AUTHOR_POSITION,
                supporting_excerpt="Grounded excerpt for the used claim.",
                locator=Locator(page_start=1, page_end=1),
                support_kind="direct",
                confidence=0.9,
            ),
            EvidenceItem(
                evidence_id="ev-omitted",
                source_id=source_id,
                block_id="block-omitted",
                claim="Omitted claim.",
                claim_type=ClaimType.AUTHOR_POSITION,
                supporting_excerpt="Grounded excerpt for the omitted claim.",
                locator=Locator(page_start=1, page_end=1),
                support_kind="direct",
                confidence=0.9,
            ),
        ],
        blocks=[],
        extraction_plans=[],
    )
    plan = EpisodePlan(
        title="Title",
        listener_outcome="Outcome",
        estimated_duration_minutes=5,
        segments=[
            EpisodeSegment(
                segment_id="seg-001",
                title="Segment",
                purpose="Purpose",
                estimated_minutes=5,
                claim_ids=["clm-used"],
                key_question="Question?",
                speaker_dynamic="explanation",
            )
        ],
        deliberately_omitted_claims=[],
    )

    review = EpisodePreparationService._build_must_not_be_lost_review(project_id, corpus, plan)

    by_claim = {item.claim_id: item for item in review.items}
    assert set(by_claim) == {"clm-used", "clm-omitted"}
    assert by_claim["clm-used"].used_in_plan is True
    assert by_claim["clm-omitted"].used_in_plan is False
    assert review.unused_count == 1


def _prepared_project(root: Path, duration: int = 10) -> Project:
    workspace = WorkspaceStore(root)
    project = Project(
        raw_input="Arendt and action",
        state=ProjectState.CORPUS_READY,
        brief=_brief(duration),
    )
    workspace.save_project(project)
    _seed_source(root, project.project_id)
    return project


def _prepare(root: Path, project_id: UUID, runner: FakeEpisodeRunner) -> None:
    _service(root, runner).prepare_episode(
        project_id,
        coverage_model="fake-strong",
        planning_model="fake-strong",
    )


def test_replanning_an_unchanged_corpus_reuses_both_model_stages(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = _prepared_project(root)
    runner = FakeEpisodeRunner()

    _prepare(root, project.project_id, runner)
    first_plan = EpisodeArtifactStore(root).load_plan(project.project_id)
    _prepare(root, project.project_id, runner)

    assert runner.calls == ["coverage_audit", "episode_plan"]
    assert EpisodeArtifactStore(root).load_plan(project.project_id) == first_plan
    assert WorkspaceStore(root).load_project(project.project_id).state == (
        ProjectState.EPISODE_PLANNED
    )


def test_replanning_an_unchanged_corpus_emits_cache_hits_on_the_second_pass(
    tmp_path: Path, recording_tracer: tracing.Tracer
) -> None:
    root = tmp_path / "workspaces"
    project = _prepared_project(root)
    runner = FakeEpisodeRunner()

    _prepare(root, project.project_id, runner)
    _prepare(root, project.project_id, runner)

    def outcomes(cache_name: str) -> list[str]:
        return [
            event.attributes["result"]
            for event in recording_tracer.sink.events
            if event.name == "cache.lookup" and event.attributes.get("cache") == cache_name
        ]

    assert outcomes("coverage_audit") == ["miss", "hit"]
    assert outcomes("episode_plan") == ["miss", "hit"]


def test_retrying_after_a_planning_failure_reuses_the_coverage_audit(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = _prepared_project(root)
    runner = FakeEpisodeRunner(fail_stages={"episode_plan"})

    with pytest.raises(ValueError, match="episode_plan failed"):
        _prepare(root, project.project_id, runner)
    assert WorkspaceStore(root).load_project(project.project_id).state == (
        ProjectState.FAILED_RETRYABLE
    )

    runner.fail_stages.clear()
    _prepare(root, project.project_id, runner)

    assert runner.calls == ["coverage_audit", "episode_plan", "episode_plan"]
    assert WorkspaceStore(root).load_project(project.project_id).state == (
        ProjectState.EPISODE_PLANNED
    )


def test_a_shorter_duration_reuses_the_coverage_audit_and_replans(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    project = _prepared_project(root, duration=10)
    runner = FakeEpisodeRunner()
    _prepare(root, project.project_id, runner)

    shortened = workspace.load_project(project.project_id)
    assert shortened.brief is not None
    shortened.brief.target_duration_minutes = 5
    workspace.save_project(shortened)
    _prepare(root, project.project_id, runner)

    assert runner.calls == ["coverage_audit", "episode_plan", "episode_plan"]
    coverage = EpisodeArtifactStore(root).load_coverage(project.project_id)
    assert coverage.max_supported_minutes == 10  # still the audited corpus, not the request
    assert coverage.can_plan_episode is True


def test_a_changed_corpus_reruns_both_model_stages(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project = _prepared_project(root)
    runner = FakeEpisodeRunner()
    _prepare(root, project.project_id, runner)

    _seed_source(root, project.project_id, offset=3)  # a second source joins the corpus
    _prepare(root, project.project_id, runner)

    assert runner.calls == [
        "coverage_audit",
        "episode_plan",
        "coverage_audit",
        "episode_plan",
    ]


def test_a_fresh_coverage_audit_invalidates_the_stored_plan(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    project = _prepared_project(root)
    runner = FakeEpisodeRunner()
    _prepare(root, project.project_id, runner)

    # A revised question re-audits coverage, so the plan built on the old audit cannot stand.
    revised = workspace.load_project(project.project_id)
    assert revised.brief is not None
    revised.brief.central_question = "چه چیزی کنش را از ساختن جدا می‌کند؟"
    workspace.save_project(revised)
    _prepare(root, project.project_id, runner)

    assert runner.calls == [
        "coverage_audit",
        "episode_plan",
        "coverage_audit",
        "episode_plan",
    ]


def test_longer_duration_prioritizes_more_claims() -> None:
    project_id = uuid4()
    claims = [_claim(index, f"ev-{index}") for index in range(1, 9)]
    objective_items = [
        ObjectiveCoverageDraft(
            objective="Understand the argument.",
            status="well_covered",
            claim_ids=[claims[0].claim_id],
            rationale="Grounded.",
        )
    ]
    from thesisound.episode import CoverageReport

    short_coverage = CoverageReport(
        project_id=project_id,
        central_question_status="well_covered",
        central_question_claim_ids=[claims[0].claim_id],
        objective_coverage=objective_items,
        max_supported_minutes=60,
        recommendation="continue",
        recommendation_reason="Grounded.",
        can_plan_episode=True,
        model_run_id=uuid4(),
    )
    prioritizer = ClaimPrioritizer()
    short = prioritizer.prioritize(
        project_id=project_id,
        brief=_brief(5),
        claims=claims,
        coverage=short_coverage,
    )
    long = prioritizer.prioritize(
        project_id=project_id,
        brief=_brief(60),
        claims=claims,
        coverage=short_coverage,
    )
    short_selected = sum(
        item.level in {"must_include", "supporting"} for item in short.priorities
    )
    long_selected = sum(
        item.level in {"must_include", "supporting"} for item in long.priorities
    )
    assert long_selected > short_selected


def test_evidence_pack_rejects_missing_evidence() -> None:
    claim = _claim(1, "missing-evidence")
    from thesisound.domain import EpisodePlan, EpisodeSegment

    plan = EpisodePlan(
        title="Test",
        listener_outcome="Test",
        estimated_duration_minutes=5,
        segments=[
            EpisodeSegment(
                segment_id="seg-001",
                title="Test",
                purpose="Test",
                estimated_minutes=5,
                claim_ids=[claim.claim_id],
                key_question="Test?",
                speaker_dynamic="explanation",
            )
        ],
    )
    with pytest.raises(Exception, match="missing evidence"):
        EvidencePackBuilder().build(
            episode_plan=plan,
            claims=[claim],
            evidence_items=[],
            blocks=[],
            extraction_plans=[],
        )
