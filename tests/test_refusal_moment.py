"""When the app refuses, it has to look like a refusal.

The moment the pipeline stops and says "these sources cannot support what you asked
for" is the behaviour nothing else in this category does. It was also the least
designed moment in the product: a stage rail pulsing in the colour reserved for live
work while the run had stopped to ask a question, and the ruling itself rendered as a
13px line at the bottom of the page, under two paragraphs about never faking progress.
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest

from thesisound.domain import ProjectState
from thesisound.services.corpus_building import CorpusBuildRun, CorpusSourceRun
from thesisound.services.episode_planning_run import EpisodePlanningRun
from thesisound.web.processing_views import build_processing_stages

CSS = Path(__file__).parents[1] / "src" / "thesisound" / "web" / "static" / "app.css"

PLAN_STAGE = 3
CORPUS_STAGE = 2


def _corpus(status: str) -> CorpusBuildRun:
    return CorpusBuildRun(
        project_id=uuid4(),
        status=status,  # type: ignore[arg-type]
        sources=[
            CorpusSourceRun(
                source_id=uuid4(),
                filename="one.pdf",
                ingestion_path="sources/one/ingestion-result.json",
            )
        ],
    )


def _planning(status: str, stage: str = "auditing_coverage") -> EpisodePlanningRun:
    return EpisodePlanningRun(
        project_id=uuid4(),
        status=status,  # type: ignore[arg-type]
        stage=stage,  # type: ignore[arg-type]
        target_duration_minutes=20,
    )


# --- F-22: the reserved colour must not claim work that stopped ----------------


def test_a_blocked_plan_run_is_blocked_not_running() -> None:
    """The defect, exactly: this row pulsed in --accent while asking for a decision."""
    stages = build_processing_stages(
        ProjectState.EPISODE_PLANNING,
        _corpus("succeeded"),
        _planning("blocked", stage="blocked"),
    )
    assert stages[PLAN_STAGE].status == "blocked"
    assert stages[PLAN_STAGE].is_current is True
    assert stages[PLAN_STAGE].state_word == "منتظر تصمیم شما"


def test_a_stopped_corpus_run_is_stopped_not_running() -> None:
    stages = build_processing_stages(
        ProjectState.FAILED_RETRYABLE,
        _corpus("failed"),
        None,
    )
    assert stages[CORPUS_STAGE].status == "stopped"
    assert stages[CORPUS_STAGE].is_current is True


def test_a_live_run_is_the_only_thing_that_reads_as_running() -> None:
    stages = build_processing_stages(
        ProjectState.CORPUS_BUILDING,
        _corpus("running"),
        None,
    )
    assert stages[CORPUS_STAGE].status == "running"
    assert [stage.status for stage in stages if stage.status == "running"] == ["running"]


def test_a_stage_with_no_run_yet_waits_quietly() -> None:
    """Nothing has started, which is a quieter statement than running or stopped."""
    stages = build_processing_stages(ProjectState.CORPUS_READY, _corpus("succeeded"), None)
    assert stages[PLAN_STAGE].status == "waiting"
    assert stages[PLAN_STAGE].state_word == "هنوز شروع نشده"


@pytest.mark.parametrize(
    ("corpus_status", "planning_status"),
    [
        ("running", None),
        ("failed", None),
        ("succeeded", "queued"),
        ("succeeded", "running"),
        ("succeeded", "blocked"),
        ("succeeded", "failed"),
        ("succeeded", "succeeded"),
    ],
)
def test_at_most_one_stage_is_the_current_one(
    corpus_status: str,
    planning_status: str | None,
) -> None:
    stages = build_processing_stages(
        ProjectState.EPISODE_PLANNING,
        _corpus(corpus_status),
        _planning(planning_status) if planning_status else None,
    )
    assert sum(stage.is_current for stage in stages) <= 1


@pytest.mark.parametrize("state", list(ProjectState))
def test_a_complete_stage_never_borrows_a_run_status(state: ProjectState) -> None:
    """A finished stage says "انجام شد" whatever the runs are doing now."""
    stages = build_processing_stages(state, _corpus("failed"), _planning("blocked"))
    for stage in stages:
        if stage.complete:
            assert stage.state_word == "انجام شد"
            assert stage.is_current is False


def test_the_accent_pulse_belongs_to_running_stages_alone() -> None:
    """The root cause was in CSS: the pulse hung off `is-current`, which is not a status.

    `--accent` is the one colour DESIGN.md reserves for "work is happening right now",
    so a rule that animates any current stage can make a stopped one claim it again.
    """
    css = CSS.read_text(encoding="utf-8")
    animated = re.findall(r"^\.stage-row\.(is-[a-z]+)[^\n{]*\{[^}]*status-pulse", css, re.M)
    assert animated == ["is-running"], animated

    accented = re.findall(r"^\.stage-row\.(is-[a-z]+)[^\n{]*\{[^}]*--accent", css, re.M)
    assert accented == ["is-running"], accented


# --- F-24: what the plan left out is reported, never hidden --------------------


def test_the_omitted_lists_open_by_default_and_carry_a_marker() -> None:
    """Their only affordance used to be `cursor: pointer`, which is a hover state.

    PRODUCT.md forbids depending on hover, and the product's own non-negotiable says a
    claim with no place in the plan is carried to the report rather than hidden. A
    collapsed `<details>` whose summary is styled exactly like every static heading on
    the page met neither.
    """
    html = (
        Path(__file__).parents[1]
        / "src" / "thesisound" / "web" / "templates" / "projects" / "episode.html"
    ).read_text(encoding="utf-8")

    openings = re.findall(r"<details class=\"plan-list-details\"([^>]*)>", html)
    assert len(openings) == 2, openings
    assert all(" open" in opening for opening in openings), openings
    assert html.count("plan-list-details__marker") == 2

    css = CSS.read_text(encoding="utf-8")
    assert ".plan-list-details[open] > summary .plan-list-details__marker" in css
    # The summary is a control, so it carries the same 44px floor as any other.
    summary_rule = re.search(r"\.plan-list-details > summary \{([^}]*)\}", css)
    assert summary_rule and "min-height: 44px" in summary_rule.group(1)


# --- F-25: one confirmation pattern, and a legible disabled state --------------


def test_a_disabled_button_is_not_a_faded_copy_of_an_enabled_one() -> None:
    """`opacity: .55` over --brand took the source-confirm label to roughly 2.4:1.

    That label is the one a reader must read: the hint beside it explains why the
    button is off. An inactive control gets its own colours instead.
    """
    css = CSS.read_text(encoding="utf-8")
    rule = re.search(r"\.button:disabled \{([^}]*)\}", css)
    assert rule, "no .button:disabled rule"
    body = rule.group(1)
    assert "opacity" not in body, body
    assert "color: var(--muted)" in body
    assert "background: var(--paper-strong)" in body
