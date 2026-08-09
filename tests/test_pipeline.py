from pathlib import Path

import pytest

from thesisound import tracing
from thesisound.domain import Project, ProjectState
from thesisound.pipeline import InvalidTransitionError, WorkspaceStore, transition


def test_project_round_trip(tmp_path: Path) -> None:
    store = WorkspaceStore(tmp_path)
    project = Project(raw_input="آرنت و مفهوم کنش")

    store.save_project(project)
    loaded = store.load_project(project.project_id)

    assert loaded == project
    assert loaded.raw_input == "آرنت و مفهوم کنش"


def test_valid_transition() -> None:
    project = Project(raw_input="Nietzsche")

    transition(project, ProjectState.BRIEF_READY)

    assert project.state == ProjectState.BRIEF_READY


def test_invalid_transition_is_rejected() -> None:
    project = Project(raw_input="Žižek")

    with pytest.raises(InvalidTransitionError):
        transition(project, ProjectState.SCRIPT_READY)


def test_valid_transition_emits_a_state_changed_event(recording_tracer: tracing.Tracer) -> None:
    project = Project(raw_input="Nietzsche")

    transition(project, ProjectState.BRIEF_READY)

    event = recording_tracer.sink.events[0]
    assert event.name == "project.state_changed"
    assert event.project_id == project.project_id
    assert event.attributes == {"previous": "draft", "current": "brief_ready"}


def test_invalid_transition_emits_a_rejected_warning_event(
    recording_tracer: tracing.Tracer,
) -> None:
    project = Project(raw_input="Žižek")

    with pytest.raises(InvalidTransitionError):
        transition(project, ProjectState.SCRIPT_READY)

    event = recording_tracer.sink.events[0]
    assert event.name == "project.transition_rejected"
    assert event.level == "warn"
    assert event.attributes == {"previous": "draft", "attempted": "script_ready"}
