"""The four stages of the analysis path, and how each one is actually doing.

The rail used to carry one bit per stage — done or not done — and the template gave
the pulsing `--accent` mark to the first stage that was not done. `--accent` is the one
colour DESIGN.md reserves for "this is running right now", so a run that had stopped and
asked for a decision still pulsed as if work were happening; four hundred pixels down the
same page said "منتظر تصمیم شما · blocked".

A stage's status is not derivable from its own completeness. It comes from the run that
owns it, so that is what this module resolves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from thesisound.domain import ProjectState

#: `waiting` is "the inputs are ready and nothing has started"; `blocked` is "it ran and
#: refused". Both wait on a person, and only one of them is a verdict about the work.
StageStatus = Literal["complete", "running", "blocked", "stopped", "waiting", "pending"]

_STATE_WORDS: dict[StageStatus, str] = {
    "complete": "انجام شد",
    "running": "در جریان",
    "blocked": "منتظر تصمیم شما",
    "stopped": "متوقف شد",
    "waiting": "هنوز شروع نشده",
    "pending": "در نوبت",
}

_BEFORE_SOURCES = {
    ProjectState.DRAFT,
    ProjectState.BRIEF_READY,
    ProjectState.SOURCES_COLLECTING,
    ProjectState.SOURCE_SELECTION_REQUIRED,
}

_AFTER_CORPUS = {
    ProjectState.CORPUS_READY,
    ProjectState.EPISODE_PLANNING,
    ProjectState.EPISODE_PLANNED,
    ProjectState.SCRIPT_DRAFTING,
    ProjectState.SCRIPT_READY,
    ProjectState.SCRIPT_VERIFYING,
    ProjectState.SCRIPT_VERIFIED,
    ProjectState.AUDIO_GENERATING,
    ProjectState.AUDIO_READY,
    ProjectState.AUDIO_VERIFYING,
    ProjectState.COMPLETE,
}

_AFTER_PLAN = {
    ProjectState.EPISODE_PLANNED,
    ProjectState.SCRIPT_DRAFTING,
    ProjectState.SCRIPT_READY,
    ProjectState.SCRIPT_VERIFYING,
    ProjectState.SCRIPT_VERIFIED,
    ProjectState.AUDIO_GENERATING,
    ProjectState.AUDIO_READY,
    ProjectState.AUDIO_VERIFYING,
    ProjectState.COMPLETE,
}


@dataclass(frozen=True, slots=True)
class ProcessingStage:
    label: str
    status: StageStatus

    @property
    def complete(self) -> bool:
        return self.status == "complete"

    @property
    def is_current(self) -> bool:
        """The stage the run is standing on, whatever it is doing there."""
        return self.status not in {"complete", "pending"}

    @property
    def state_word(self) -> str:
        return _STATE_WORDS[self.status]


def _run_status(run: object | None) -> StageStatus:
    """Translate one run's own status into what its stage should say."""
    status = getattr(run, "status", None)
    if status in {"queued", "running"}:
        return "running"
    if status == "blocked":
        return "blocked"
    if status == "failed":
        return "stopped"
    # No run yet, or a run whose status this rail does not model: nothing is happening,
    # which is a quieter statement than either "running" or "stopped".
    return "waiting"


def build_processing_stages(
    state: ProjectState,
    corpus_run: object | None,
    planning_run: object | None,
) -> list[ProcessingStage]:
    after_sources = corpus_run is not None or state not in _BEFORE_SOURCES
    corpus_ready = (
        getattr(corpus_run, "status", None) == "succeeded" or state in _AFTER_CORPUS
    )
    plan_ready = (
        getattr(planning_run, "status", None) == "succeeded" or state in _AFTER_PLAN
    )

    # (label, complete, the run that owns this stage). `None` means no run owns it —
    # the brief and the source set are confirmed by a person, not produced by a run.
    steps: list[tuple[str, bool, object | None]] = [
        ("موضوع و هدف", True, None),
        ("منابع", after_sources, None),
        ("تحلیل منابع و استخراج شاهدها", corpus_ready, corpus_run),
        ("سنجش کفایت منابع و طرح گفتار", plan_ready, planning_run),
    ]

    stages: list[ProcessingStage] = []
    current_found = False
    for label, complete, run in steps:
        if complete:
            stages.append(ProcessingStage(label, "complete"))
            continue
        if current_found:
            stages.append(ProcessingStage(label, "pending"))
            continue
        current_found = True
        stages.append(ProcessingStage(label, _run_status(run)))
    return stages
