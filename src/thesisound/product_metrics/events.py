"""Closed product-event vocabulary and typed payloads. No I/O."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProductEvent(StrEnum):
    AUTH_CODE_REQUESTED = "auth.code_requested"
    AUTH_CODE_VERIFIED = "auth.code_verified"
    AUTH_CODE_FAILED = "auth.code_failed"
    AUTH_PASSWORD_SUCCEEDED = "auth.password_succeeded"
    AUTH_PASSWORD_FAILED = "auth.password_failed"
    AUTH_LOCKED_OUT = "auth.locked_out"
    AUTH_LOGGED_OUT = "auth.logged_out"
    USER_REGISTERED = "user.registered"

    PROJECT_CREATED = "project.created"
    PROJECT_STAGE_ENTERED = "project.stage_entered"
    PROJECT_STAGE_FAILED = "project.stage_failed"
    PROJECT_RECOVERED = "project.recovered"
    PROJECT_TRANSITION_REJECTED = "project.transition_rejected"

    GATE_BRIEF_CONFIRMED = "gate.brief_confirmed"
    GATE_BRIEF_EDITED = "gate.brief_edited"
    GATE_CORPUS_CONFIRMED = "gate.corpus_confirmed"
    GATE_SOURCE_TOGGLED = "gate.source_toggled"
    GATE_SOURCE_DELETED = "gate.source_deleted"
    GATE_SCRIPT_APPROVED = "gate.script_approved"
    GATE_SCRIPT_REVIEW_REQUESTED = "gate.script_review_requested"
    GATE_BLOCKED = "gate.blocked"
    GATE_RESOLVED = "gate.resolved"
    WORKFLOW_REWOUND = "workflow.rewound"
    EPISODE_AUDIO_DOWNLOADED = "episode.audio_downloaded"
    EPISODE_SOURCE_TRACE_OPENED = "episode.source_trace_opened"
    EPISODE_EVIDENCE_JUDGED = "episode.evidence_judged"
    PLAN_REVIEWED = "plan.reviewed"
    PLAN_OMITTED_LIST_OPENED = "plan.omitted_list_opened"
    PLAN_DURATION_CHANGED = "plan.duration_changed"


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthCodeRequested(_Payload):
    channel: Literal["sms"] = "sms"


class AuthCodeVerified(_Payload):
    method: Literal["otp"] = "otp"


class AuthCodeFailed(_Payload):
    reason: Literal["invalid", "expired", "locked", "other"] = "other"


class AuthPasswordSucceeded(_Payload):
    pass


class AuthPasswordFailed(_Payload):
    reason: Literal["invalid", "locked", "other"] = "invalid"


class AuthLockedOut(_Payload):
    method: Literal["password", "otp"] = "password"


class AuthLoggedOut(_Payload):
    pass


class UserRegistered(_Payload):
    method: Literal["otp", "password"] = "otp"


class ProjectCreated(_Payload):
    topic_type: str
    entry_mode: Literal["web", "cli"] = "web"


class ProjectStageEntered(_Payload):
    stage: int = Field(ge=1, le=7)
    from_stage: int | None = Field(default=None, ge=1, le=7)
    state: str
    from_state: str


class ProjectStageFailed(_Payload):
    stage: int = Field(ge=1, le=7)
    state: str
    permanent: bool
    error_class: Literal["parser", "model", "coverage", "timeout", "other", "unknown"]


class ProjectRecovered(_Payload):
    stage: int = Field(ge=1, le=7)
    failed_for_seconds: int = Field(ge=0)


class ProjectTransitionRejected(_Payload):
    from_state: str
    attempted_state: str


class GateBriefConfirmed(_Payload):
    pass


class GateBriefEdited(_Payload):
    pass


class GateCorpusConfirmed(_Payload):
    source_count: int = Field(ge=0)


class GateSourceToggled(_Payload):
    selected: bool | None = None


class GateSourceDeleted(_Payload):
    pass


class GateScriptApproved(_Payload):
    pass


class GateScriptReviewRequested(_Payload):
    decision: Literal["accept", "send_back"] | None = None


class GateBlocked(_Payload):
    gate_name: str
    reason: Literal[
        "coverage",
        "quality",
        "preflight",
        "selection",
        "other",
    ] = "other"


class GateResolved(_Payload):
    gate_name: str
    blocked_seconds: int = Field(ge=0)


class WorkflowRewound(_Payload):
    from_stage: int | None = Field(default=None, ge=1, le=7)
    target: Literal["brief", "sources"]


class EpisodeAudioDownloaded(_Payload):
    format: Literal["wav", "mp3"]


class EpisodeSourceTraceOpened(_Payload):
    pass


class EpisodeEvidenceJudged(_Payload):
    verdict: Literal["correct", "incorrect"]
    reason: (
        Literal[
            "excerpt_does_not_support",
            "wrong_locator",
            "claim_mismatch",
            "other",
        ]
        | None
    ) = None


class PlanReviewed(_Payload):
    has_omitted: bool
    has_unused_must_not_be_lost: bool


class PlanOmittedListOpened(_Payload):
    origin: Literal["omitted", "must_not_be_lost"]


class PlanDurationChanged(_Payload):
    direction: Literal["up", "down"]
    from_blocked: bool
    reextraction_required: bool


PAYLOAD_MODELS: dict[ProductEvent, type[BaseModel]] = {
    ProductEvent.AUTH_CODE_REQUESTED: AuthCodeRequested,
    ProductEvent.AUTH_CODE_VERIFIED: AuthCodeVerified,
    ProductEvent.AUTH_CODE_FAILED: AuthCodeFailed,
    ProductEvent.AUTH_PASSWORD_SUCCEEDED: AuthPasswordSucceeded,
    ProductEvent.AUTH_PASSWORD_FAILED: AuthPasswordFailed,
    ProductEvent.AUTH_LOCKED_OUT: AuthLockedOut,
    ProductEvent.AUTH_LOGGED_OUT: AuthLoggedOut,
    ProductEvent.USER_REGISTERED: UserRegistered,
    ProductEvent.PROJECT_CREATED: ProjectCreated,
    ProductEvent.PROJECT_STAGE_ENTERED: ProjectStageEntered,
    ProductEvent.PROJECT_STAGE_FAILED: ProjectStageFailed,
    ProductEvent.PROJECT_RECOVERED: ProjectRecovered,
    ProductEvent.PROJECT_TRANSITION_REJECTED: ProjectTransitionRejected,
    ProductEvent.GATE_BRIEF_CONFIRMED: GateBriefConfirmed,
    ProductEvent.GATE_BRIEF_EDITED: GateBriefEdited,
    ProductEvent.GATE_CORPUS_CONFIRMED: GateCorpusConfirmed,
    ProductEvent.GATE_SOURCE_TOGGLED: GateSourceToggled,
    ProductEvent.GATE_SOURCE_DELETED: GateSourceDeleted,
    ProductEvent.GATE_SCRIPT_APPROVED: GateScriptApproved,
    ProductEvent.GATE_SCRIPT_REVIEW_REQUESTED: GateScriptReviewRequested,
    ProductEvent.GATE_BLOCKED: GateBlocked,
    ProductEvent.GATE_RESOLVED: GateResolved,
    ProductEvent.WORKFLOW_REWOUND: WorkflowRewound,
    ProductEvent.EPISODE_AUDIO_DOWNLOADED: EpisodeAudioDownloaded,
    ProductEvent.EPISODE_SOURCE_TRACE_OPENED: EpisodeSourceTraceOpened,
    ProductEvent.EPISODE_EVIDENCE_JUDGED: EpisodeEvidenceJudged,
    ProductEvent.PLAN_REVIEWED: PlanReviewed,
    ProductEvent.PLAN_OMITTED_LIST_OPENED: PlanOmittedListOpened,
    ProductEvent.PLAN_DURATION_CHANGED: PlanDurationChanged,
}
