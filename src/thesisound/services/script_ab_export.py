from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from thesisound.domain import Script
from thesisound.script import ScriptCheckReport
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_checks import (
    _filler_in_first_sentence,
    _is_substantive_turn,
    _normalize_spoken,
)

_ARTIFACTS = ("arm-1.md", "arm-2.md", "key.json", "metrics.md")


@dataclass(frozen=True, slots=True)
class _Arm:
    label: str
    project_id: UUID
    script: Script
    checks: ScriptCheckReport


class ScriptAbExporter:
    """Create a blind, deterministic two-arm script review packet."""

    def __init__(self, workspace_root: Path) -> None:
        self.script_store = ScriptArtifactStore(workspace_root)

    def export(
        self,
        project_a: UUID,
        project_b: UUID,
        out_dir: Path,
    ) -> dict[str, object]:
        if project_a == project_b:
            raise ValueError("Blind A/B export requires two distinct projects.")
        directory = out_dir.expanduser().resolve()
        self._require_dedicated_directory(directory)
        project_ids = sorted((project_a, project_b), key=str)
        arms = [
            _Arm(
                label=f"arm-{index}",
                project_id=project_id,
                script=self.script_store.load_latest_script(project_id),
                checks=self.script_store.load_latest_checks(project_id),
            )
            for index, project_id in enumerate(project_ids, start=1)
        ]
        directory.mkdir(parents=True, exist_ok=True)
        for arm in arms:
            (directory / f"{arm.label}.md").write_text(
                _render_arm(arm.script),
                encoding="utf-8",
            )
        (directory / "key.json").write_text(
            json.dumps(
                {arm.label: str(arm.project_id) for arm in arms},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (directory / "metrics.md").write_text(_render_metrics(arms), encoding="utf-8")
        return {"out": str(directory), "files": list(_ARTIFACTS)}

    @staticmethod
    def _require_dedicated_directory(directory: Path) -> None:
        if directory == directory.parent:
            raise ValueError("Blind A/B export cannot target the filesystem root.")
        if not directory.exists():
            return
        if not directory.is_dir():
            raise ValueError(f"Blind A/B export target is not a directory: {directory}")
        unexpected = sorted(
            item.name for item in directory.iterdir() if item.name not in _ARTIFACTS
        )
        if unexpected:
            raise ValueError(
                "Blind A/B export requires a dedicated directory; unexpected existing "
                f"entries: {', '.join(unexpected[:5])}"
            )


def _render_arm(script: Script) -> str:
    return "\n".join(f"{turn.speaker}: {turn.spoken_text_fa}" for turn in script.turns) + "\n"


def _render_metrics(arms: list[_Arm]) -> str:
    rows = [
        ("editorial word ratio", *(f"{arm.checks.editorial_word_ratio:.3f}" for arm in arms)),
        ("speaker A words", *(str(arm.checks.speaker_a_word_count) for arm in arms)),
        ("speaker B words", *(str(arm.checks.speaker_b_word_count) for arm in arms)),
        ("speaker A turns", *(str(_speaker_turn_count(arm.script, "A")) for arm in arms)),
        ("speaker B turns", *(str(_speaker_turn_count(arm.script, "B")) for arm in arms)),
        (
            "speaker B substantive turns",
            *(str(arm.checks.speaker_b_substantive_turn_count) for arm in arms),
        ),
        (
            "claims per segment minute",
            *(f"{arm.checks.claims_per_segment_minute:.2f}" for arm in arms),
        ),
        ("claims used in more than two turns", *(str(_claim_repeats(arm.script)) for arm in arms)),
        ("affirmative openers", *(str(_affirmative_openers(arm.script)) for arm in arms)),
    ]
    lines = ["| metric | arm-1 | arm-2 |", "| --- | ---: | ---: |"]
    lines.extend(f"| {name} | {first} | {second} |" for name, first, second in rows)
    return "\n".join(lines) + "\n"


def _speaker_turn_count(script: Script, speaker: str) -> int:
    return sum(turn.speaker == speaker for turn in script.turns)


def _claim_repeats(script: Script) -> int:
    counts: Counter[tuple[str, str]] = Counter(
        (turn.segment_id, claim_id) for turn in script.turns for claim_id in set(turn.claim_ids)
    )
    return sum(count > 2 for count in counts.values())


def _affirmative_openers(script: Script) -> int:
    return sum(
        not _is_substantive_turn(turn)
        and _filler_in_first_sentence(_normalize_spoken(turn.spoken_text_fa)) is not None
        for turn in script.turns
    )
