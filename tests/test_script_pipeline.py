from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

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
    SupportStatus,
    TopicType,
    VerificationIssue,
)
from thesisound.episode import (
    DisagreementGraph,
    SegmentEvidencePack,
)
from thesisound.modeling import ModelExecution, ModelRunRecord
from thesisound.pipeline import WorkspaceStore
from thesisound.script import (
    GlossaryDraft,
    GlossaryTermDraft,
    RevisedTurnDraft,
    ScriptTurnDraft,
    SegmentScriptDraft,
    TargetedRevisionDraft,
    VerificationDraft,
)
from thesisound.services.episode_artifact_store import EpisodeArtifactStore
from thesisound.services.glossary_builder import GlossaryBuilderService
from thesisound.services.persian_script_writer import PersianScriptWriterService
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
    def __init__(self) -> None:
        self.verification_calls = 0

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
                )
            else:
                output = VerificationDraft(
                    verdict="pass",
                    issues=[],
                    unsupported_claim_ratio=0,
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
                        spoken_text_fa=_spoken("اصلاح", 50),
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


def _seed(root: Path) -> tuple[UUID, str]:
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
    episode_store.save_disagreement_graph(
        DisagreementGraph(project_id=project_id)
    )
    return project_id, claim_id


def _service(root: Path, runner: FakeScriptRunner) -> ScriptPipelineService:
    return ScriptPipelineService(
        workspace_store=WorkspaceStore(root),
        source_store=SourceArtifactStore(root),
        episode_store=EpisodeArtifactStore(root),
        script_store=ScriptArtifactStore(root),
        glossary_builder=GlossaryBuilderService(runner),
        script_writer=PersianScriptWriterService(runner),
        script_checker=ScriptChecker(words_per_minute=20),
        verifier=ScriptVerifierService(runner),
        reviser=TargetedScriptReviserService(runner),
    )


def test_script_pipeline_revises_only_flagged_turn_and_verifies(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    project_id, _ = _seed(root)
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


def test_script_turn_contract_rejects_substantive_turn_without_evidence() -> None:
    from pydantic import ValidationError

    try:
        ScriptTurnDraft(
            speaker="A",
            spoken_text_fa="این یک ادعای محتوایی است.",
            claim_ids=["clm-1"],
            evidence_ids=[],
        )
    except ValidationError:
        return
    raise AssertionError("Substantive turn without evidence IDs must be rejected.")
