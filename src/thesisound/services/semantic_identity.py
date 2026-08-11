"""Semantic identity helpers for reuse gates that must invalidate on model/prompt/algorithm change.

Parse/map/TTS already version their keys. Evidence, plan, script, ASR, and QA reuse
historically keyed only on content shape; these helpers fold behavior-changing inputs
into stable hashes and produce field-level invalidation reasons for cache lineage.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any

EVIDENCE_EXTRACTOR_VERSION = 1
CLAIM_RECONCILER_VERSION = 1
COVERAGE_AUDITOR_VERSION = 1
EPISODE_PLANNER_VERSION = 1
SCRIPT_CHECKER_VERSION = 1
AUDIO_QA_VERSION = 1


def normalize_prompt_version(prompt_version: str | None) -> str:
    """Collapse unset prompt versions to a stable sentinel for identity compare."""

    if prompt_version is None or not str(prompt_version).strip():
        return "default"
    return str(prompt_version).strip()


def canonical_hash(payload: Mapping[str, Any]) -> str:
    """SHA-256 of sorted JSON; same style as planning_input_key / parse_cache_key."""

    canonical = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def first_mismatch(
    stored: Mapping[str, Any] | None,
    current: Mapping[str, Any],
    fields: Sequence[str],
) -> str | None:
    """Return ``{field}_mismatch`` for the first differing field, or ``identity_missing``.

    ``None`` means every listed field matches. Missing stored identity is safer as a
    miss than silent reuse of pre-versioning artifacts.
    """

    if stored is None:
        return "identity_missing"
    for field in fields:
        if field not in stored or stored[field] is None:
            return "identity_missing"
        if stored[field] != current[field]:
            return f"{field}_mismatch"
    return None


def evidence_extraction_identity(
    *,
    model: str,
    prompt_version: str | None,
    extractor_version: int = EVIDENCE_EXTRACTOR_VERSION,
) -> dict[str, Any]:
    return {
        "model": model,
        "prompt_version": normalize_prompt_version(prompt_version),
        "extractor_version": extractor_version,
    }


def claim_reconciler_identity(
    *,
    model: str,
    prompt_version: str | None,
    reconciler_version: int = CLAIM_RECONCILER_VERSION,
    extractor_version: int = EVIDENCE_EXTRACTOR_VERSION,
) -> dict[str, Any]:
    return {
        "model": model,
        "prompt_version": normalize_prompt_version(prompt_version),
        "reconciler_version": reconciler_version,
        "extractor_version": extractor_version,
    }


def planning_semantic(
    *,
    model: str,
    prompt_version: str | None,
    stage_version: int,
) -> dict[str, Any]:
    return {
        "model": model,
        "prompt_version": normalize_prompt_version(prompt_version),
        "stage_version": stage_version,
    }


def script_pipeline_identity(
    *,
    glossary_model: str,
    glossary_prompt_version: str | None,
    writer_model: str,
    writer_prompt_version: str | None,
    verifier_model: str,
    verifier_prompt_version: str | None,
    reviser_model: str,
    reviser_prompt_version: str | None,
    checker_version: int = SCRIPT_CHECKER_VERSION,
) -> dict[str, Any]:
    return {
        "glossary_model": glossary_model,
        "glossary_prompt_version": normalize_prompt_version(glossary_prompt_version),
        "writer_model": writer_model,
        "writer_prompt_version": normalize_prompt_version(writer_prompt_version),
        "verifier_model": verifier_model,
        "verifier_prompt_version": normalize_prompt_version(verifier_prompt_version),
        "reviser_model": reviser_model,
        "reviser_prompt_version": normalize_prompt_version(reviser_prompt_version),
        "checker_version": checker_version,
    }


def script_pipeline_key(plan_hash: str, identity: Mapping[str, Any]) -> str:
    """One wipe-gate key: approved plan plus script pipeline semantics."""

    return canonical_hash({"plan_hash": plan_hash, "pipeline": dict(identity)})


def audio_qa_identity(
    *,
    pass_threshold: float,
    review_threshold: float,
    missing_sentence_threshold: float,
    qa_version: int = AUDIO_QA_VERSION,
) -> dict[str, Any]:
    return {
        "qa_version": qa_version,
        "pass_threshold": pass_threshold,
        "review_threshold": review_threshold,
        "missing_sentence_threshold": missing_sentence_threshold,
    }
