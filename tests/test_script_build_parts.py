"""Per-part script slicing (`10c` P3 Step 9): `ScriptPipelineService._save_part_scripts`."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from thesisound.concepts import LessonPart
from thesisound.domain import EpisodePlan, EpisodeSegment, Script, ScriptTurn
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_pipeline_service import ScriptPipelineService


def _plan_with_two_parts() -> EpisodePlan:
    return EpisodePlan(
        title="عنوان",
        listener_outcome="فهم",
        estimated_duration_minutes=2.0,
        segments=[
            EpisodeSegment(
                segment_id="seg-001",
                title="بخش ۱",
                purpose="شرح",
                estimated_minutes=1.0,
                claim_ids=["clm-1"],
                key_question="چرا؟",
                speaker_dynamic="explanation",
                part_index=1,
            ),
            EpisodeSegment(
                segment_id="seg-002",
                title="بخش ۲",
                purpose="شرح",
                estimated_minutes=1.0,
                claim_ids=["clm-2"],
                key_question="چگونه؟",
                speaker_dynamic="explanation",
                part_index=2,
            ),
        ],
        parts=[
            LessonPart(
                part_index=1,
                title_fa="بخش ۱",
                cell_keys=["ch00-c001"],
                claim_ids=["clm-1"],
                estimated_minutes=1.0,
            ),
            LessonPart(
                part_index=2,
                title_fa="بخش ۲",
                cell_keys=["ch00-c002"],
                claim_ids=["clm-2"],
                estimated_minutes=1.0,
            ),
        ],
    )


def _script() -> Script:
    return Script(
        title="عنوان کل",
        turns=[
            ScriptTurn(
                turn_id="seg-001-turn-001",
                segment_id="seg-001",
                speaker="A",
                spoken_text_fa="متن بخش یک.",
                claim_ids=["clm-1"],
                evidence_ids=["ev-1"],
            ),
            ScriptTurn(
                turn_id="seg-002-turn-001",
                segment_id="seg-002",
                speaker="A",
                spoken_text_fa="متن بخش دو.",
                claim_ids=["clm-2"],
                evidence_ids=["ev-2"],
            ),
        ],
        glossary_terms_used=["اصطلاح"],
    )


def test_turns_are_grouped_by_the_owning_segments_part(tmp_path: Path) -> None:
    project_id = uuid4()
    store = ScriptArtifactStore(tmp_path / "workspaces")
    service = ScriptPipelineService.__new__(ScriptPipelineService)
    service.script_store = store

    service._save_part_scripts(project_id, _script(), _plan_with_two_parts())

    assert store.list_part_scripts(project_id) == [1, 2]
    part_one = store.load_part_script(project_id, 1)
    part_two = store.load_part_script(project_id, 2)
    assert [turn.turn_id for turn in part_one.turns] == ["seg-001-turn-001"]
    assert [turn.turn_id for turn in part_two.turns] == ["seg-002-turn-001"]
    assert part_one.title == "بخش ۱"
    assert part_two.title == "بخش ۲"
    assert part_one.glossary_terms_used == ["اصطلاح"]
