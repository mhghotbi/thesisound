from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from thesisound.domain import EpisodePlan, EpisodeSegment, Script, ScriptTurn
from thesisound.episode import SegmentEvidencePack
from thesisound.prompt_loader import PromptLoader
from thesisound.script import Glossary, ScriptCheckReport, ScriptTurnDraft, SegmentScriptDraft
from thesisound.services.persian_script_writer import (
    SpeakerBalancePolicy,
    _speaker_balance_failures,
)
from thesisound.services.script_ab_export import ScriptAbExporter
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_checks import ScriptChecker


def _segment(*claim_ids: str) -> EpisodeSegment:
    return EpisodeSegment(
        segment_id="seg-001",
        title="بخش",
        purpose="آزمون",
        estimated_minutes=1,
        claim_ids=list(claim_ids or ("clm-1",)),
        key_question="پرسش چیست؟",
        speaker_dynamic="questioning",
    )


def _draft(*turns: ScriptTurnDraft) -> SegmentScriptDraft:
    return SegmentScriptDraft(turns=list(turns))


def _substantive(speaker: str, text: str, claim_id: str = "clm-1") -> ScriptTurnDraft:
    return ScriptTurnDraft(
        speaker=speaker,
        spoken_text_fa=text,
        claim_ids=[claim_id],
        evidence_ids=["ev-1"],
    )


def _editorial(speaker: str, text: str) -> ScriptTurnDraft:
    return ScriptTurnDraft(speaker=speaker, spoken_text_fa=text, editorial_only=True)


@pytest.mark.parametrize(
    ("is_opening", "editorial_words", "expect_f1"),
    [
        (False, 1, False),  # 1/4 = 25%, inclusive.
        (False, 2, True),  # 2/5 = 40%.
        (True, 3, False),  # 3/6 = 50% would fail; overridden below.
    ],
)
def test_editorial_floor_boundaries(
    is_opening: bool,
    editorial_words: int,
    expect_f1: bool,
) -> None:
    if is_opening:
        draft = _draft(_editorial("B", "x x x"), _substantive("A", "x x x"))
        expect_f1 = True  # 50% exceeds the opening 35% allowance.
    else:
        draft = _draft(
            _editorial("B", " ".join(["x"] * editorial_words)),
            _substantive("A", "x x x"),
        )
    failures = _speaker_balance_failures(
        draft,
        _segment("clm-1"),
        SpeakerBalancePolicy(),
        is_opening=is_opening,
    )
    assert any(item.startswith("F1") for item in failures) is expect_f1


def test_opening_segment_allows_thirty_percent_editorial_words() -> None:
    failures = _speaker_balance_failures(
        _draft(_editorial("B", "x x x"), _substantive("A", "x x x x x x x")),
        _segment("clm-1"),
        SpeakerBalancePolicy(),
        is_opening=True,
    )
    assert not any(item.startswith("F1") for item in failures)


def test_b_substantive_requirement_exempts_one_claim_segments() -> None:
    editorial_b = _draft(_substantive("A", "x x"), _editorial("B", "x x"))
    policy = SpeakerBalancePolicy()
    assert not any(
        item.startswith("F2")
        for item in _speaker_balance_failures(
            editorial_b, _segment("clm-1"), policy, is_opening=False
        )
    )
    assert any(
        item.startswith("F2")
        for item in _speaker_balance_failures(
            editorial_b, _segment("clm-1", "clm-2"), policy, is_opening=False
        )
    )


def test_floor_reports_f1_f2_f3_in_order_and_can_be_disabled() -> None:
    draft = _draft(
        _editorial("B", "x x x x"),
        _substantive("A", "x", "clm-1"),
        _substantive("A", "x", "clm-1"),
        _substantive("A", "x", "clm-1"),
    )
    segment = _segment("clm-1", "clm-2")
    failures = _speaker_balance_failures(draft, segment, SpeakerBalancePolicy(), is_opening=False)
    assert [item[:2] for item in failures] == ["F1", "F2", "F3"]
    assert _speaker_balance_failures(
        draft,
        segment,
        SpeakerBalancePolicy(enabled=False),
        is_opening=False,
    ) == []


def test_script_checker_populates_balance_measurements_and_high_issues() -> None:
    project_id = uuid4()
    plan = EpisodePlan(
        title="عنوان",
        listener_outcome="نتیجه",
        estimated_duration_minutes=2,
        segments=[_segment("clm-1", "clm-2")],
    )
    script = Script(
        title="عنوان",
        turns=[
            ScriptTurn(
                turn_id="seg-001-turn-001",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa="دقیقاً همین‌طور است متن",
                editorial_only=True,
            ),
            ScriptTurn(
                turn_id="seg-001-turn-002",
                segment_id="seg-001",
                speaker="B",
                spoken_text_fa="گذار",
                editorial_only=True,
            ),
        ],
    )
    report = ScriptChecker(words_per_minute=1).check(
        project_id=project_id,
        script=script,
        episode_plan=plan,
        evidence_packs=[
            SegmentEvidencePack.model_construct(
                segment_id="seg-001",
                claim_ids=["clm-1", "clm-2"],
                evidence_items=[],
                original_blocks=[],
                token_budget=1,
                actual_tokens=0,
            )
        ],
        claims=[],
        glossary=Glossary(
            project_id=project_id,
            model_run_id=uuid4(),
        ),
        speaker_balance_violations={"seg-001": ["F1 test failure"]},
    )
    assert report.editorial_word_ratio == 1
    assert report.speaker_a_word_count == 5
    assert report.speaker_b_word_count == 1
    assert report.speaker_b_substantive_turn_count == 0
    assert report.claims_per_segment_minute == 1
    assert report.verdict == "revise"
    assert {(issue.issue_type, issue.severity) for issue in report.issues} >= {
        ("speaker_balance", "high"),
        ("restatement", "medium"),
    }


def test_old_script_check_report_defaults_r10_fields() -> None:
    report = ScriptCheckReport.model_validate(
        {
            "project_id": str(uuid4()),
            "verdict": "pass",
            "word_count": 1,
            "estimated_minutes": 1,
            "substantive_turn_count": 1,
        }
    )
    assert report.editorial_word_ratio == 0
    assert report.speaker_b_substantive_turn_count == 0
    assert report.claims_per_segment_minute == 0


def test_latest_script_prompt_is_1_1_0_and_renders_position() -> None:
    loader = PromptLoader()
    variables = {
        "research_brief": {},
        "segment": {"speaker_dynamic": "questioning"},
        "evidence_pack": {},
        "glossary": {},
        "disagreement_graph": {},
        "target_word_count": 100,
        "segment_index": 2,
        "segment_count": 4,
    }
    bundle = loader.load_bundle("persian_script_segment", variables)
    assert bundle.contract.version == "1.1.0"
    assert "2 of 4" in bundle.user_prompt
    assert "{{" not in bundle.system_prompt + bundle.user_prompt
    assert "untrusted data" in bundle.system_prompt
    assert "Never add outside knowledge" in bundle.system_prompt


def test_blind_export_hides_ids_and_is_deterministic(tmp_path: Path) -> None:
    store = ScriptArtifactStore(tmp_path / "workspaces")
    first, second = sorted((uuid4(), uuid4()), key=str)
    for project_id, text in ((first, "متن نخست"), (second, "متن دوم")):
        store.save_script(
            project_id,
            Script(
                title="عنوان",
                turns=[
                    ScriptTurn(
                        turn_id="seg-001-turn-001",
                        segment_id="seg-001",
                        speaker="A",
                        spoken_text_fa=text,
                        editorial_only=True,
                    )
                ],
            ),
        )
        store.save_checks(
            ScriptCheckReport(
                project_id=project_id,
                verdict="pass",
                word_count=2,
                estimated_minutes=1,
                substantive_turn_count=0,
            )
        )
    out = tmp_path / "ab"
    exporter = ScriptAbExporter(tmp_path / "workspaces")
    exporter.export(second, first, out)
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    assert key == {"arm-1": str(first), "arm-2": str(second)}
    arms = (out / "arm-1.md").read_text(encoding="utf-8") + (out / "arm-2.md").read_text(
        encoding="utf-8"
    )
    assert str(first) not in arms and str(second) not in arms
    assert "turn-001" not in arms and "editorial_only" not in arms
    metrics = (out / "metrics.md").read_text(encoding="utf-8")
    for name in (
        "editorial word ratio",
        "speaker B substantive turns",
        "claims per segment minute",
        "affirmative openers",
    ):
        assert name in metrics
