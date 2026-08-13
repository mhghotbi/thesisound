"""Apply human script review decisions (spec 12 D4)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from uuid import UUID

from thesisound.domain import Project, ProjectState
from thesisound.pipeline import WorkspaceStore, transition
from thesisound.script import QualityNote, ScriptReviewDecision
from thesisound.services.lineage_events import emit_review_decision
from thesisound.services.plan_approval import episode_plan_hash
from thesisound.services.script_artifact_store import ScriptArtifactStore
from thesisound.services.script_run import ScriptBuildRunService

# Kept for the legacy /script/review path and send_back disclosures.
DEFAULT_REVIEW_REASON = {
    "accept": "پذیرفته شد؛ یادداشت‌های کیفیت پیش از ادامه نمایش داده شده بود.",
    "send_back": "برای بازنویسی فرستاده شد.",
}

ACCEPTED_WITH_NOTES = "accepted_with_notes"


def notable_notes_disclosure_token(notes: list[QualityNote]) -> str:
    """Stable proof that a specific set of notable notes was rendered with the CTA."""
    notable = [note for note in notes if note.severity == "notable"]
    if not notable:
        return ""
    payload = "\n".join(sorted(f"{note.kind}\0{note.subject}" for note in notable))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def require_notable_notes_disclosed(
    notes: list[QualityNote],
    submitted_token: str | None,
) -> None:
    expected = notable_notes_disclosure_token(notes)
    if not expected:
        return
    if (submitted_token or "").strip() != expected:
        raise ValueError(
            "Audio cannot start until the quality notes on this screen have been shown."
        )


def apply_script_review_decision(
    *,
    workspace: WorkspaceStore,
    script_store: ScriptArtifactStore,
    project: Project,
    decision: str,
    reviewer: str,
    reason: str,
    builder: ScriptBuildRunService | None = None,
    reason_code: str | None = None,
    require_preflight: Callable[[], None] | None = None,
    on_send_back: Callable[[], None] | None = None,
) -> ScriptReviewDecision:
    if project.state != ProjectState.SCRIPT_REVIEW_REQUIRED:
        raise ValueError("This script is not awaiting a review decision.")
    if decision not in {"accept", "send_back"}:
        raise ValueError("Unknown script review decision.")
    clean_reason = reason.strip() or DEFAULT_REVIEW_REASON[decision]
    if decision == "send_back":
        if builder is None:
            raise ValueError("Script builder is required to send a review back.")
        if require_preflight is not None:
            require_preflight()
    plan_hash = episode_plan_hash(project.episode_plan) if project.episode_plan else ""
    checks = script_store.load_latest_checks(project.project_id)
    verification = script_store.load_latest_verification(project.project_id)
    review = ScriptReviewDecision(
        project_id=project.project_id,
        decision="accepted" if decision == "accept" else "sent_back",
        reviewer=reviewer,
        reason=clean_reason,
        plan_hash=plan_hash,
        checks_verdict=checks.verdict,
        verification_verdict=verification.verdict,
        unsupported_claim_ratio=verification.unsupported_claim_ratio,
        quality_overall=(
            verification.quality.overall if verification.quality is not None else None
        ),
    )
    script_store.save_review_decision(review)
    emit_review_decision(
        disposition=review.decision,
        subject_type="script",
        subject_id=str(project.project_id),
        reviewer=review.reviewer,
        reason_code=(reason_code or clean_reason)[:120],
        regenerated_stage="script" if decision == "send_back" else None,
    )
    manifest = script_store.load_manifest(project.project_id)
    if decision == "accept":
        transition(project, ProjectState.SCRIPT_VERIFIED)
        manifest.status = "verified"
        manifest.last_error = None
    else:
        transition(project, ProjectState.SCRIPT_DRAFTING)
        manifest.last_error = clean_reason
    workspace.save_project(project)
    script_store.save_manifest(manifest)
    if decision == "send_back":
        assert builder is not None
        builder.send_back(project.project_id)
        if on_send_back is not None:
            on_send_back()
    return review


def load_quality_notes(script_store: ScriptArtifactStore, project_id: UUID) -> list[QualityNote]:
    ledger = script_store.load_quality_notes_optional(project_id)
    return list(ledger.notes) if ledger is not None else []
