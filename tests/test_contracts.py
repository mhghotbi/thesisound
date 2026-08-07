from pathlib import Path

import pytest
from pydantic import ValidationError

from thesisound.domain import (
    ClaimRecord,
    ClaimType,
    ScriptTurn,
    SupportStatus,
)
from thesisound.prompt_loader import PromptLoader


def test_non_editorial_claim_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        ClaimRecord(
            claim_id="c-1",
            claim="A grounded claim",
            claim_type=ClaimType.AUTHOR_POSITION,
            evidence_ids=[],
            support_status=SupportStatus.STRONG,
        )


def test_substantive_script_turn_requires_claim_ids() -> None:
    with pytest.raises(ValidationError):
        ScriptTurn(
            turn_id="t-1",
            segment_id="s-1",
            speaker="A",
            spoken_text_fa="این یک ادعای محتوایی است.",
            editorial_only=False,
        )


def test_editorial_turn_may_have_no_claim() -> None:
    turn = ScriptTurn(
        turn_id="t-2",
        segment_id="s-1",
        speaker="B",
        spoken_text_fa="بیایید یک لحظه مکث کنیم.",
        editorial_only=True,
    )
    assert turn.claim_ids == []


def test_prompt_loader_finds_versioned_prompt(tmp_path: Path) -> None:
    prompt_file = tmp_path / "01_example.md"
    prompt_file.write_text("example prompt", encoding="utf-8")

    loader = PromptLoader(tmp_path)

    assert loader.load("example") == "example prompt"
