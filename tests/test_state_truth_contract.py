"""One project, one story — on the list, the overview, the readiness page and the script.

Before this, a single project could be four different things at once. `9c4e58b0` at
`SCRIPT_VERIFIED` told the list and the overview "متن گفتار تأیید شد · آمادهٔ ساخت
نسخهٔ شنیداری" with a button to build audio, told `/readiness` that four checks were
stopped behind a changed episode plan, and rendered `/script` as a header over blank
paper. Nothing was corrupt: the stored state recorded how far the pipeline got, and the
gates re-derived whether that was still true. Only the interface refused to notice they
had parted company.

Two rules hold the surfaces together, and this file is about both:

* the read model never sends a reader past a gate the evidence says is shut, and
* `health` and `ownership` stay independent, so a verified script cannot be drawn with
  a warning triangle just because it is also waiting on a human.
"""

from __future__ import annotations

import pytest

from thesisound.domain import (
    EpisodePlan,
    EpisodeSegment,
    Project,
    ProjectState,
    ResearchBrief,
    TopicType,
)
from thesisound.pipeline import WorkspaceStore
from thesisound.services.plan_approval import EpisodePlanApprovalStore
from thesisound.services.readiness import project_readiness
from thesisound.web.read_models import build_project_read_model
from thesisound.web.readiness_views import ReadinessView, build_readiness_view

HEALTH_VALUES = {"success", "warning", "danger", "neutral"}
OWNERSHIP_VALUES = {"you", "system", "none"}

#: Every mark `status_label` knows how to draw. A tone outside this set renders the
#: bare ring, which is how `health="warning"` would have silently lost its triangle.
DRAWABLE_TONES = {"success", "attention", "danger", "running", "neutral"}


def _project(state: ProjectState = ProjectState.EPISODE_PLANNED) -> Project:
    return Project(
        raw_input="topic",
        state=state,
        brief=ResearchBrief(
            normalized_topic="topic",
            topic_type=TopicType.CONCEPT,
            central_question="What is the argument?",
            target_duration_minutes=10,
        ),
        episode_plan=EpisodePlan(
            title="Plan",
            listener_outcome="Understand the argument",
            estimated_duration_minutes=10,
            segments=[
                EpisodeSegment(
                    segment_id="seg-1",
                    title="Argument",
                    purpose="Explain",
                    estimated_minutes=10,
                    claim_ids=["claim-1"],
                    key_question="Why?",
                    speaker_dynamic="explanation",
                )
            ],
        ),
    )


def _view(*, action_url: str | None) -> ReadinessView:
    return ReadinessView(
        headline="تأیید طرح قسمت مانع است.",
        explanation="طرح قسمت بعد از تأیید تغییر کرده است.",
        tone="attention",
        action_label="بازبینی و تأیید طرح قسمت",
        action_url=action_url,
        blocking_code="episode-plan-approval",
    )


# --- the two axes ------------------------------------------------------------


@pytest.mark.parametrize("state", list(ProjectState))
def test_every_state_names_both_axes(state: ProjectState) -> None:
    model = build_project_read_model(_project(state))
    assert model.health in HEALTH_VALUES
    assert model.ownership in OWNERSHIP_VALUES


@pytest.mark.parametrize("state", list(ProjectState))
def test_every_state_composes_a_mark_the_macro_can_draw(state: ProjectState) -> None:
    assert build_project_read_model(_project(state)).status_tone in DRAWABLE_TONES


@pytest.mark.parametrize("state", [ProjectState.SCRIPT_VERIFIED, ProjectState.COMPLETE])
def test_a_success_never_wears_a_warning_triangle(state: ProjectState) -> None:
    """The defect that forced the split: shape said problem, the words said verified."""
    model = build_project_read_model(_project(state))
    assert model.health == "success"
    assert model.status_tone == "success"


def test_waiting_on_a_person_is_not_a_health_problem() -> None:
    """`SCRIPT_VERIFIED` is healthy *and* waiting; one fact must not colour the other."""
    model = build_project_read_model(_project(ProjectState.SCRIPT_VERIFIED))
    assert (model.health, model.ownership) == ("success", "you")
    assert model.requires_action is True


@pytest.mark.parametrize("state", list(ProjectState))
def test_requires_action_tracks_ownership(state: ProjectState) -> None:
    model = build_project_read_model(_project(state))
    assert model.requires_action == (model.ownership == "you")


# --- agreement between surfaces ----------------------------------------------


@pytest.mark.parametrize("state", list(ProjectState))
def test_no_state_walks_the_reader_past_a_shut_gate(state: ProjectState) -> None:
    project = _project(state)
    elsewhere = f"/projects/{project.project_id}/episode"
    model = build_project_read_model(project, readiness=_view(action_url=elsewhere))
    if model.ownership != "you" or model.health == "danger":
        # The machine owns the next move, or a failed run already has a better
        # account of itself than any gate can give.
        return
    assert model.primary_action_url in {
        elsewhere,
        f"/projects/{project.project_id}/readiness",
    }


@pytest.mark.parametrize("state", list(ProjectState))
def test_agreement_rewrites_nothing(state: ProjectState) -> None:
    """When both name the same screen there is no disagreement to report."""
    project = _project(state)
    plain = build_project_read_model(project)
    agreed = build_project_read_model(
        project,
        readiness=_view(action_url=plain.primary_action_url),
    )
    assert agreed == plain


@pytest.mark.parametrize("state", list(ProjectState))
def test_a_clear_readiness_run_rewrites_nothing(state: ProjectState) -> None:
    project = _project(state)
    clear = ReadinessView(
        headline="همه‌چیز آماده است.",
        explanation="هر سیزده بررسی گذشت.",
        tone="success",
        action_label=None,
        action_url=None,
    )
    assert build_project_read_model(project, readiness=clear) == build_project_read_model(project)


def test_a_failed_run_keeps_its_own_account() -> None:
    project = _project(ProjectState.FAILED_RETRYABLE)
    model = build_project_read_model(
        project,
        failure_action_url=f"/projects/{project.project_id}/processing",
        readiness=_view(action_url=f"/projects/{project.project_id}/episode"),
    )
    assert model.primary_action_url.endswith("/processing")
    assert model.health == "danger"


def test_a_missing_readiness_run_falls_back_to_the_state() -> None:
    """A workspace can hold a half-written project; that is not a reason to fail a page."""
    project = _project(ProjectState.SCRIPT_VERIFIED)
    assert build_project_read_model(project, readiness=None) == build_project_read_model(project)


# --- the real thing, end to end ----------------------------------------------


def test_a_plan_edited_after_approval_makes_every_surface_say_the_same_thing(tmp_path) -> None:
    """The exact shape of `9c4e58b0`: verified script, plan moved underneath it."""
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    project = _project(ProjectState.EPISODE_PLANNED)
    workspace.save_project(project)
    EpisodePlanApprovalStore(root).approve(project, approved_by="reviewer")
    # The run goes on to write and verify a script, and then the plan is edited.
    project.state = ProjectState.SCRIPT_VERIFIED
    project.episode_plan.title = "Edited after approval"
    workspace.save_project(project)

    gate_results = project_readiness(project_id=project.project_id, workspace_root=root)
    readiness = build_readiness_view(
        gate_results,
        project_id=project.project_id,
        workspace_root=root,
    )

    # The gates: the approval is what stops the run.
    assert readiness.blocking_code == "episode-plan-approval"

    stale = build_project_read_model(project)
    honest = build_project_read_model(project, readiness=readiness)

    # What the stored state alone would have said, and why it was wrong.
    assert stale.primary_action_url.endswith("/audio")
    assert stale.health == "success"

    # What the row says now: the gate's own sentence, and a route to the page that
    # owns it rather than a button deeper into work that cannot be trusted.
    assert honest.attention_label == readiness.headline
    assert honest.overview_summary == readiness.explanation
    assert honest.primary_action_url.endswith("/readiness")
    assert honest.health == "warning"
    assert honest.requires_action is True


def test_a_project_whose_evidence_still_holds_is_left_alone(tmp_path) -> None:
    """The healthy half of the same state: nothing to disagree about, nothing rewritten."""
    root = tmp_path / "workspaces"
    workspace = WorkspaceStore(root)
    project = _project(ProjectState.EPISODE_PLANNED)
    workspace.save_project(project)

    gate_results = project_readiness(project_id=project.project_id, workspace_root=root)
    readiness = build_readiness_view(
        gate_results,
        project_id=project.project_id,
        workspace_root=root,
    )

    model = build_project_read_model(project, readiness=readiness)
    assert model.primary_action_url.endswith("/episode")
    assert readiness.action_url == model.primary_action_url
