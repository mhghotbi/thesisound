"""Conditional glossary (§2) and reviser explicitness (§3.3)."""

from __future__ import annotations

from uuid import UUID, uuid4

from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    EpisodePlan,
    EpisodeSegment,
    EvidenceItem,
    ExtractedDefinition,
    GlossaryTerm,
    Locator,
    Script,
    ScriptTurn,
    SupportStatus,
)
from thesisound.episode import SegmentEvidencePack
from thesisound.script import (
    Glossary,
    GlossaryDraft,
    GlossaryTermDraft,
    ScriptCheckReport,
    VerificationDraft,
)
from thesisound.services.deterministic_glossary import build_deterministic_glossary
from thesisound.services.glossary_builder import GlossaryBuilderService
from thesisound.services.script_checks import ScriptChecker
from thesisound.services.script_pipeline_service import revision_is_required
from thesisound.source_analysis import SourceDocumentBlock


def _locator() -> Locator:
    return Locator(page_start=1, page_end=1)


def _block(source_id: UUID) -> SourceDocumentBlock:
    return SourceDocumentBlock(
        block_id="block-1",
        source_id=source_id,
        locator=_locator(),
        heading_path=["Section"],
        block_type="argument",
        text="متن نمونه برای بلوک سند.",
        estimated_token_count=40,
        source_block_keys=["p1"],
    )


def _definition(
    *,
    source_id: UUID,
    term: str,
    definition: str,
    block_id: str = "block-1",
) -> ExtractedDefinition:
    return ExtractedDefinition(
        term=term,
        definition=definition,
        source_id=source_id,
        block_id=block_id,
        locator=_locator(),
    )


def _pack(*, claim: str, excerpt: str, source_id: UUID) -> SegmentEvidencePack:
    return SegmentEvidencePack(
        segment_id="seg-001",
        claim_ids=["c1"],
        evidence_items=[
            EvidenceItem(
                evidence_id="ev-1",
                source_id=source_id,
                block_id="block-1",
                claim=claim,
                claim_type=ClaimType.AUTHOR_POSITION,
                supporting_excerpt=excerpt,
                locator=_locator(),
                support_kind="direct",
                confidence=0.9,
            )
        ],
        original_blocks=[_block(source_id)],
        token_budget=1000,
        actual_tokens=40,
    )


def _claim(text: str) -> ClaimRecord:
    return ClaimRecord(
        claim_id="c1",
        claim=text,
        claim_type=ClaimType.AUTHOR_POSITION,
        evidence_ids=["ev-1"],
        support_status=SupportStatus.STRONG,
    )


def test_deterministic_glossary_extracts_terms() -> None:
    source_id = uuid4()
    project_id = uuid4()
    result = build_deterministic_glossary(
        project_id=project_id,
        definitions=[
            _definition(
                source_id=source_id,
                term="Labor",
                definition="زحمت یکی از فعالیت‌های بنیادی است.",
            )
        ],
        evidence_packs=[
            _pack(
                claim="Labor differs from work.",
                excerpt="Labor is distinct from Work",
                source_id=source_id,
            )
        ],
        claims=[_claim("Labor differs from work.")],
    )
    assert result.corpus_has_latin_tokens
    assert any(term.source_term == "Labor" for term in result.glossary.terms)
    labor = next(term for term in result.glossary.terms if term.source_term == "Labor")
    assert "زحمت" in labor.preferred_persian or labor.preferred_persian == "زحمت"
    assert result.glossary.build_kind == "deterministic"
    # Labor resolved; Work remains open → needs model unless Work also resolved.
    assert result.needs_model


def test_glossary_inconsistency_fires_on_deterministic_glossary() -> None:
    project_id = uuid4()
    source_id = uuid4()
    glossary = Glossary(
        project_id=project_id,
        build_kind="deterministic",
        model_run_id=uuid4(),
        terms=[
            GlossaryTerm(
                source_term="Labor",
                preferred_persian="زحمت",
                first_use_form="زحمت",
                subsequent_use_form="زحمت",
                translation_status="standard",
            )
        ],
    )
    plan = EpisodePlan(
        title="t",
        listener_outcome="o",
        estimated_duration_minutes=5,
        segments=[
            EpisodeSegment(
                segment_id="seg-001",
                title="s",
                purpose="p",
                estimated_minutes=5,
                claim_ids=["c1"],
                key_question="q",
                speaker_dynamic="explanation",
            )
        ],
    )
    pack = _pack(claim="claim", excerpt="excerpt", source_id=source_id)
    claim = _claim("claim text فارسی")
    script = Script(
        project_id=project_id,
        title="glossary inconsistency fixture",
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa="در اینجا Labor بدون فرم فارسی می‌آید.",
                claim_ids=["c1"],
                evidence_ids=["ev-1"],
            ),
            ScriptTurn(
                turn_id="t2",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa="ادامه بحث درباره همان مفهوم است.",
                claim_ids=["c1"],
                evidence_ids=["ev-1"],
            ),
        ],
    )
    report = ScriptChecker(words_per_minute=20).check(
        project_id=project_id,
        script=script,
        episode_plan=plan,
        evidence_packs=[pack],
        claims=[claim],
        glossary=glossary,
    )
    glossary_issues = [
        issue for issue in report.issues if issue.issue_type == "glossary_inconsistency"
    ]
    assert glossary_issues
    assert any(issue.severity == "high" for issue in glossary_issues)


def test_glossary_build_kind_defaults_for_legacy_artifact() -> None:
    glossary = Glossary.model_validate(
        {
            "project_id": str(uuid4()),
            "terms": [],
            "warnings": [],
            "model_run_id": str(uuid4()),
        }
    )
    assert glossary.build_kind == "model"
    assert glossary.corpus_had_latin_tokens is False


def test_model_glossary_skipped_when_no_open_decisions() -> None:
    source_id = uuid4()
    project_id = uuid4()

    class CountingRunner:
        def __init__(self) -> None:
            self.glossary_calls = 0

        def run(self, **kwargs: object):
            self.glossary_calls += 1
            raise AssertionError("model must not run when no open decisions")

    from thesisound.domain import (
        EpisodePlan,
        EpisodeSegment,
        ResearchBrief,
        TopicType,
    )
    from thesisound.episode import DisagreementGraph

    runner = CountingRunner()
    builder = GlossaryBuilderService(runner)  # type: ignore[arg-type]
    brief = ResearchBrief(
        normalized_topic="کنش",
        topic_type=TopicType.CONCEPT,
        central_question="چرا؟",
        target_duration_minutes=5,
        output_language="fa",
        learning_objectives=["آ"],
    )
    plan = EpisodePlan(
        title="t",
        listener_outcome="o",
        estimated_duration_minutes=5,
        segments=[
            EpisodeSegment(
                segment_id="seg-001",
                title="s",
                purpose="p",
                estimated_minutes=5,
                claim_ids=["c1"],
                key_question="q",
                speaker_dynamic="explanation",
            )
        ],
    )
    glossary, record = builder.build(
        project_id=project_id,
        brief=brief,
        episode_plan=plan,
        evidence_packs=[
            _pack(
                claim="کنش به کثرت وابسته است.",
                excerpt="کنش بدون دیگران ممکن نیست.",
                source_id=source_id,
            )
        ],
        disagreement_graph=DisagreementGraph(project_id=project_id),
        definitions=[
            _definition(
                source_id=source_id,
                term="کنش",
                definition="کنش فعالیتی است که در جمع دیگران رخ می‌دهد.",
            )
        ],
        claims=[_claim("کنش به کثرت وابسته است.")],
        model="fake",
    )
    assert runner.glossary_calls == 0
    assert glossary.build_kind == "deterministic"
    assert glossary.terms
    assert any(term.source_term == "کنش" for term in glossary.terms)
    assert record.provider == "none"


def test_model_glossary_runs_on_conflicting_forms() -> None:
    source_a = uuid4()
    source_b = uuid4()
    project_id = uuid4()

    class CountingRunner:
        def __init__(self) -> None:
            self.glossary_calls = 0

        def run(self, **kwargs: object):
            self.glossary_calls += 1
            from thesisound.modeling import ModelRunRecord

            output = GlossaryDraft(
                terms=[
                    GlossaryTermDraft(
                        source_term="action",
                        preferred_persian="کنش",
                        first_use_form="کنش",
                        subsequent_use_form="کنش",
                        translation_status="contested",
                    )
                ]
            )
            record = ModelRunRecord(
                project_id=project_id,
                stage="glossary",
                prompt_id="glossary",
                prompt_version="1.0.0",
                prompt_hash="h",
                input_hash="i",
                provider="fake",
                model="fake",
                output_model="GlossaryDraft",
                status="succeeded",
            )

            class Execution:
                pass

            execution = Execution()
            execution.output = output
            execution.record = record
            return execution

    from thesisound.domain import EpisodePlan, EpisodeSegment, ResearchBrief, TopicType
    from thesisound.episode import DisagreementGraph

    runner = CountingRunner()
    builder = GlossaryBuilderService(runner)  # type: ignore[arg-type]
    brief = ResearchBrief(
        normalized_topic="کنش",
        topic_type=TopicType.CONCEPT,
        central_question="چرا؟",
        target_duration_minutes=5,
        output_language="fa",
        learning_objectives=["آ"],
    )
    plan = EpisodePlan(
        title="t",
        listener_outcome="o",
        estimated_duration_minutes=5,
        segments=[
            EpisodeSegment(
                segment_id="seg-001",
                title="s",
                purpose="p",
                estimated_minutes=5,
                claim_ids=["c1"],
                key_question="q",
                speaker_dynamic="explanation",
            )
        ],
    )
    glossary, _ = builder.build(
        project_id=project_id,
        brief=brief,
        episode_plan=plan,
        evidence_packs=[
            _pack(
                claim="کنش مهم است.",
                excerpt="کنش در جمع.",
                source_id=source_a,
            )
        ],
        disagreement_graph=DisagreementGraph(project_id=project_id),
        definitions=[
            _definition(source_id=source_a, term="action", definition="کنش"),
            _definition(source_id=source_b, term="action", definition="عمل"),
        ],
        claims=[_claim("کنش مهم است.")],
        model="fake",
    )
    assert runner.glossary_calls == 1
    assert glossary.build_kind == "model"


def test_empty_deterministic_glossary_flags_latin_corpus() -> None:
    project_id = uuid4()
    source_id = uuid4()
    glossary = Glossary(
        project_id=project_id,
        build_kind="deterministic",
        model_run_id=uuid4(),
        terms=[],
        corpus_had_latin_tokens=True,
    )
    plan = EpisodePlan(
        title="t",
        listener_outcome="o",
        estimated_duration_minutes=5,
        segments=[
            EpisodeSegment(
                segment_id="seg-001",
                title="s",
                purpose="p",
                estimated_minutes=5,
                claim_ids=["c1"],
                key_question="q",
                speaker_dynamic="explanation",
            )
        ],
    )
    pack = _pack(claim="claim", excerpt="excerpt", source_id=source_id)
    claim = _claim("متن فارسی بدون اصطلاح لاتین")
    script = Script(
        project_id=project_id,
        title="empty glossary fixture",
        turns=[
            ScriptTurn(
                turn_id="t1",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa="این یک توضیح کوتاه فارسی است درباره موضوع.",
                claim_ids=["c1"],
                evidence_ids=["ev-1"],
            ),
            ScriptTurn(
                turn_id="t2",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa="و این ادامه همان توضیح برای تعادل گویندگان است.",
                claim_ids=["c1"],
                evidence_ids=["ev-1"],
            ),
        ],
    )
    report = ScriptChecker(words_per_minute=20).check(
        project_id=project_id,
        script=script,
        episode_plan=plan,
        evidence_packs=[pack],
        claims=[claim],
        glossary=glossary,
    )
    glossary_issues = [
        issue for issue in report.issues if issue.issue_type == "glossary_inconsistency"
    ]
    assert len(glossary_issues) == 1
    assert glossary_issues[0].severity == "medium"


def test_revision_is_required_helper() -> None:
    pass_checks = ScriptCheckReport(
        project_id=uuid4(),
        verdict="pass",
        issues=[],
        word_count=20,
        estimated_minutes=1.0,
        substantive_turn_count=2,
        editorial_word_ratio=0.1,
        speaker_a_word_count=10,
        speaker_b_word_count=10,
        speaker_b_substantive_turn_count=2,
        claims_per_segment_minute=0.5,
    )
    revise_checks = pass_checks.model_copy(update={"verdict": "revise"})
    pass_verification = VerificationDraft(
        verdict="pass", issues=[], unsupported_claim_ratio=0.0
    )
    revise_verification = VerificationDraft(
        verdict="revise", issues=[], unsupported_claim_ratio=0.1
    )
    assert revision_is_required(pass_checks, pass_verification) is False
    assert revision_is_required(revise_checks, pass_verification) is True
    assert revision_is_required(pass_checks, revise_verification) is True


def test_deterministic_skip_produces_nonempty_terms_with_latin() -> None:
    """§6.1 — no model call, Latin in corpus, non-empty terms."""

    source_id = uuid4()
    result = build_deterministic_glossary(
        project_id=uuid4(),
        definitions=[
            _definition(
                source_id=source_id,
                term="Labor",
                definition="زحمت یکی از مفاهیم بنیادین است.",
            )
        ],
        evidence_packs=[
            _pack(
                claim="زحمت با کار تفاوت دارد.",
                excerpt="در متن Labor به معنای زحمت آمده است.",
                source_id=source_id,
            )
        ],
        claims=[_claim("زحمت با کار تفاوت دارد.")],
    )
    assert result.corpus_has_latin_tokens
    assert result.glossary.terms
    assert result.needs_model is False


def _definition_claim(*, term: str, text: str, claim_id: str) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        claim=text,
        claim_type=ClaimType.DEFINITION,
        evidence_ids=["ev-1"],
        support_status=SupportStatus.STRONG,
        term=term,
    )


def test_persian_definition_claims_seed_a_nonempty_glossary() -> None:
    result = build_deterministic_glossary(
        project_id=uuid4(),
        definitions=[],
        evidence_packs=[],
        claims=[
            _definition_claim(
                term="کنش",
                text="کنش فعالیتی است که در حضور دیگران رخ می‌دهد.",
                claim_id="c-def-1",
            )
        ],
    )
    assert result.glossary.terms
    assert any(term.source_term == "کنش" for term in result.glossary.terms)
    assert result.needs_model is False
    assert result.corpus_has_latin_tokens is False


def test_concept_cell_source_labels_seed_terms_and_need_model() -> None:
    from thesisound.concepts import ConceptCell

    cell = ConceptCell(
        cell_key="ch01-c001",
        label_fa="پراکسیس",
        label_source="پراکسیس",
        kind="definition",
        tier=1,
        chapter_index=1,
        section_ids=["s001"],
        block_ids=["b0001"],
        granularity_rationale="تعریف مستقل از متن منبع.",
        estimated_minutes=4.0,
    )
    result = build_deterministic_glossary(
        project_id=uuid4(),
        definitions=[],
        evidence_packs=[],
        claims=[],
        concept_cells=[cell],
    )
    assert any(term.source_term == "پراکسیس" for term in result.glossary.terms)
    assert result.needs_model is True


def test_five_definition_claims_need_model() -> None:
    claims = [
        _definition_claim(
            term=f"مفهوم{index}",
            text=f"مفهوم{index} در متن فارسی تعریف شده است.",
            claim_id=f"c-def-{index}",
        )
        for index in range(1, 6)
    ]
    result = build_deterministic_glossary(
        project_id=uuid4(),
        definitions=[],
        evidence_packs=[],
        claims=claims,
    )
    assert len(result.glossary.terms) == 5
    assert result.needs_model is True


def test_latest_glossary_prompt_is_1_1_0_and_renders_seed_blocks() -> None:
    from thesisound.prompt_loader import PromptLoader

    loader = PromptLoader()
    contract = loader.load_contract("glossary")
    assert contract.version == "1.1.0"
    bundle = loader.load_bundle(
        "glossary",
        {
            "research_brief": {},
            "episode_plan": {},
            "evidence_packs": [],
            "disagreement_graph": {},
            "concept_cells": [{"label_fa": "کنش", "label_source": "action"}],
            "definition_claims": [{"term": "کنش", "claim": "تعریف کنش"}],
        },
    )
    assert "CONCEPT_CELLS_JSON" in bundle.system_prompt
    assert "<CONCEPT_CELLS_JSON>" in bundle.user_prompt
    assert "<DEFINITION_CLAIMS_JSON>" in bundle.user_prompt
    assert "کنش" in bundle.user_prompt
