"""Helpers for decision-ready cache, review, and quality lineage events."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from thesisound import tracing


def emit_cache_lookup(
    *,
    cache: str,
    result: str,
    component: str = "cache",
    subject_type: str | None = None,
    subject_id: str | None = None,
    project_id: UUID | None = None,
    lookup_key: str | None = None,
    artifact_id: str | None = None,
    artifact_hash: str | None = None,
    invalidation_reason: str | None = None,
    forced_refresh: bool | None = None,
    avoided_calls: int | None = None,
    avoided_tokens_est: int | None = None,
    **extra: Any,
) -> None:
    """Emit a ``cache.lookup`` event with the R4 attribute contract.

    Existing callers may still pass only ``cache`` + ``result``; new fields are
    optional and backward compatible with rollups that only read those two.
    Explicit ``project_id`` links the event when ambient span context is absent.
    """

    attributes: dict[str, Any] = {
        "cache": cache,
        "result": result,
        **extra,
    }
    if lookup_key is not None:
        attributes["lookup_key"] = lookup_key
    if artifact_id is not None:
        attributes["artifact_id"] = artifact_id
    if artifact_hash is not None:
        attributes["artifact_hash"] = artifact_hash
    if invalidation_reason is not None:
        attributes["invalidation_reason"] = invalidation_reason
    if forced_refresh is not None:
        attributes["forced_refresh"] = forced_refresh
    if avoided_calls is not None:
        attributes["avoided_calls"] = avoided_calls
    if avoided_tokens_est is not None:
        attributes["avoided_tokens_est"] = avoided_tokens_est
    tracing.event(
        "cache.lookup",
        component=component,
        subject_type=subject_type,
        subject_id=subject_id,
        project_id=project_id,
        **attributes,
    )


def emit_review_decision(
    *,
    disposition: str,
    subject_type: str,
    subject_id: str | None = None,
    reason_code: str | None = None,
    reviewer: str | None = None,
    regenerated_stage: str | None = None,
    component: str = "review",
    **extra: Any,
) -> None:
    """Emit a ``review.decision`` event linked via ambient workflow context."""

    attributes: dict[str, Any] = {
        "disposition": disposition,
        **extra,
    }
    if reason_code is not None:
        attributes["reason_code"] = reason_code
    if reviewer is not None:
        attributes["reviewer"] = reviewer
    if regenerated_stage is not None:
        attributes["regenerated_stage"] = regenerated_stage
    tracing.event(
        "review.decision",
        component=component,
        subject_type=subject_type,
        subject_id=subject_id,
        **attributes,
    )


def emit_quality_label(
    *,
    label_source: str,
    subject_type: str,
    subject_id: str | None = None,
    verdict: str | None = None,
    score: float | None = None,
    component: str = "quality",
    **extra: Any,
) -> None:
    """Emit a machine ``quality.label`` (auxiliary, not human ground truth)."""

    attributes: dict[str, Any] = {
        "label_source": label_source,
        **extra,
    }
    if verdict is not None:
        attributes["verdict"] = verdict
    if score is not None:
        attributes["score"] = score
    tracing.event(
        "quality.label",
        component=component,
        subject_type=subject_type,
        subject_id=subject_id,
        **attributes,
    )
