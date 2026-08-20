"""Lift stored BlockEvidenceExtraction payloads to the current schema.

Upgrade is pure and read-path only: missing ``source_id`` / ``block_id`` /
``locator`` values are copied from the enclosing record and the block's own
locator. Nothing is invented.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from thesisound.domain import Locator

CURRENT_EXTRACTION_SCHEMA_VERSION = 2

_DEFINITION_FIELDS = ("definitions", "distinctions")
_TEXT_POINT_FIELDS = ("examples", "objections", "responses", "must_not_be_lost")


class EvidenceArtifactUpgradeError(ValueError):
    """A stored extraction cannot be lifted without inventing data."""


def upgrade_block_extraction_payload(
    payload: dict[str, Any],
    *,
    block_locator: Locator | None = None,
) -> dict[str, Any]:
    """Lift a stored extraction payload to the current schema.

    Pure. Uses only values already present in the payload and the block's own
    locator. Raises EvidenceArtifactUpgradeError if a required anchor is absent.

    ``block_locator`` is consulted only when a legacy (schema 1) payload has to
    be lifted; current-schema payloads already carry their own locators, so
    callers reading those do not need the blocks artifact at all. Lifting a
    legacy payload without a locator raises rather than inventing one.
    """

    if not isinstance(payload, dict):
        raise EvidenceArtifactUpgradeError("Extraction payload must be an object")

    version = payload.get("schema_version", 1)
    if not isinstance(version, int):
        raise EvidenceArtifactUpgradeError(
            f"Invalid schema_version: {version!r}"
        )

    upgraded = deepcopy(payload)
    if version >= CURRENT_EXTRACTION_SCHEMA_VERSION:
        upgraded["schema_version"] = CURRENT_EXTRACTION_SCHEMA_VERSION
        return upgraded

    source_id = upgraded.get("source_id")
    block_id = upgraded.get("block_id")
    if source_id is None or not isinstance(block_id, str) or not block_id:
        raise EvidenceArtifactUpgradeError(
            "Extraction payload is missing source_id or block_id"
        )

    extraction = upgraded.get("extraction")
    if not isinstance(extraction, dict):
        raise EvidenceArtifactUpgradeError("Extraction payload is missing extraction")

    if block_locator is None:
        raise EvidenceArtifactUpgradeError(
            "Legacy extraction payload cannot be lifted without its block locator"
        )
    locator_payload = block_locator.model_dump(mode="json")
    source_id_value = str(source_id)

    for field in _DEFINITION_FIELDS:
        items = extraction.get(field)
        if not items:
            continue
        if not isinstance(items, list):
            raise EvidenceArtifactUpgradeError(f"{field} must be a list")
        extraction[field] = [
            _inject_ids(item, source_id_value, block_id, field=field)
            for item in items
        ]

    for field in _TEXT_POINT_FIELDS:
        items = extraction.get(field)
        if not items:
            continue
        if not isinstance(items, list):
            raise EvidenceArtifactUpgradeError(f"{field} must be a list")
        extraction[field] = [
            _lift_text_point(
                item,
                source_id=source_id_value,
                block_id=block_id,
                block_locator=locator_payload,
                field=field,
            )
            for item in items
        ]

    upgraded["schema_version"] = CURRENT_EXTRACTION_SCHEMA_VERSION
    return upgraded


def resolve_block_locator(
    payload: Mapping[str, Any],
    block_locators: Mapping[str, Locator],
) -> Locator:
    """Look up the block locator for a payload, or raise."""

    block_id = payload.get("block_id")
    if not isinstance(block_id, str) or not block_id:
        raise EvidenceArtifactUpgradeError(
            "Extraction payload is missing block_id; cannot resolve locator"
        )
    locator = block_locators.get(block_id)
    if locator is None:
        raise EvidenceArtifactUpgradeError(
            f"Cannot upgrade extraction: block {block_id!r} has no locator"
        )
    return locator


def _inject_ids(
    item: Any,
    source_id: str,
    block_id: str,
    *,
    field: str,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise EvidenceArtifactUpgradeError(
            f"{field} item must be an object, got {type(item).__name__}"
        )
    out = dict(item)
    if "source_id" not in out:
        out["source_id"] = source_id
    if "block_id" not in out:
        out["block_id"] = block_id
    return out


def _lift_text_point(
    item: Any,
    *,
    source_id: str,
    block_id: str,
    block_locator: dict[str, Any],
    field: str,
) -> dict[str, Any]:
    if isinstance(item, str):
        return {
            "text": item,
            "source_id": source_id,
            "block_id": block_id,
            "locator": deepcopy(block_locator),
        }
    if isinstance(item, dict):
        out = dict(item)
        if "source_id" not in out:
            out["source_id"] = source_id
        if "block_id" not in out:
            out["block_id"] = block_id
        if "locator" not in out:
            out["locator"] = deepcopy(block_locator)
        return out
    raise EvidenceArtifactUpgradeError(
        f"{field} item must be a string or object, got {type(item).__name__}"
    )
