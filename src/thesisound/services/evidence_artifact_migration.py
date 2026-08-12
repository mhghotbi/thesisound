"""Backfill BlockEvidenceExtraction artifacts to the current schema version."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from thesisound.services.evidence_artifact_upgrade import (
    EvidenceArtifactUpgradeError,
    resolve_block_locator,
    upgrade_block_extraction_payload,
)
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import BlockEvidenceExtraction


@dataclass(frozen=True, slots=True)
class SourceMigrationStats:
    project_id: UUID
    source_id: UUID
    as_is: int
    upgraded: int
    unfixable: int


@dataclass(frozen=True, slots=True)
class EvidenceArtifactMigrationReport:
    sources: list[SourceMigrationStats]
    dry_run: bool

    @property
    def as_is(self) -> int:
        return sum(item.as_is for item in self.sources)

    @property
    def upgraded(self) -> int:
        return sum(item.upgraded for item in self.sources)

    @property
    def unfixable(self) -> int:
        return sum(item.unfixable for item in self.sources)


def migrate_evidence_artifacts(
    *,
    workspace_root: Path,
    project_id: UUID | None = None,
    dry_run: bool = True,
) -> EvidenceArtifactMigrationReport:
    """Upgrade stored extractions in place (or report what would change)."""

    root = workspace_root.expanduser().resolve()
    store = SourceArtifactStore(root)
    project_ids = (
        [project_id]
        if project_id is not None
        else _list_project_ids(root)
    )
    results: list[SourceMigrationStats] = []
    for pid in project_ids:
        sources_root = root / str(pid) / "sources"
        if not sources_root.exists():
            continue
        for source_dir in sorted(path for path in sources_root.iterdir() if path.is_dir()):
            try:
                sid = UUID(source_dir.name)
            except ValueError:
                continue
            stats = _migrate_source(
                store=store,
                project_id=pid,
                source_id=sid,
                dry_run=dry_run,
            )
            if stats is not None:
                results.append(stats)
    return EvidenceArtifactMigrationReport(sources=results, dry_run=dry_run)


def _migrate_source(
    *,
    store: SourceArtifactStore,
    project_id: UUID,
    source_id: UUID,
    dry_run: bool,
) -> SourceMigrationStats | None:
    extraction_dir = store.block_extractions_dir(project_id, source_id)
    jsonl_path = store.source_dir(project_id, source_id) / "evidence-extractions.jsonl"
    has_json = extraction_dir.exists() and any(extraction_dir.glob("*.json"))
    has_jsonl = jsonl_path.exists()
    if not has_json and not has_jsonl:
        return None

    try:
        blocks = store.load_blocks(project_id, source_id)
    except (OSError, ValueError, FileNotFoundError):
        # Count every extraction artifact as unfixable when blocks are missing.
        # File ops here must not raise — the caller already failed to load blocks,
        # and a corrupted jsonl must still report as unfixable rather than crash.
        return SourceMigrationStats(
            project_id=project_id,
            source_id=source_id,
            as_is=0,
            upgraded=0,
            unfixable=_count_artifacts_without_blocks(
                extraction_dir=extraction_dir,
                jsonl_path=jsonl_path,
                has_json=has_json,
                has_jsonl=has_jsonl,
            ),
        )

    block_locators = {block.block_id: block.locator for block in blocks}
    as_is = upgraded = unfixable = 0
    rewritten: list[BlockEvidenceExtraction] = []

    if has_json:
        for path in sorted(extraction_dir.glob("*.json")):
            outcome, record = _upgrade_file(path, block_locators)
            if outcome == "as_is":
                as_is += 1
                assert record is not None
                rewritten.append(record)
            elif outcome == "upgraded":
                upgraded += 1
                assert record is not None
                rewritten.append(record)
            else:
                unfixable += 1
            if not dry_run and record is not None:
                store.save_block_extraction(project_id, source_id, record)

    elif has_jsonl:
        # Prefer per-block JSON files when present; otherwise migrate the aggregate.
        try:
            items = store._read_jsonl(jsonl_path)
        except (OSError, UnicodeError, json.JSONDecodeError):
            # Match per-JSON handling: unreadable aggregate counts as unfixable
            # rather than aborting the whole migration run.
            return SourceMigrationStats(
                project_id=project_id,
                source_id=source_id,
                as_is=0,
                upgraded=0,
                unfixable=1,
            )
        for item in items:
            outcome, record = _upgrade_payload(item, block_locators)
            if outcome == "as_is":
                as_is += 1
                assert record is not None
                rewritten.append(record)
            elif outcome == "upgraded":
                upgraded += 1
                assert record is not None
                rewritten.append(record)
            else:
                unfixable += 1

    if not dry_run and rewritten:
        # Rebuild the aggregate from the upgraded records (or leave as-is copies).
        if has_json:
            # Reload after per-file writes so jsonl matches stamped disk state.
            rewritten = store.load_block_extractions(
                project_id, source_id, block_locators=block_locators
            )
        store.save_evidence(project_id, source_id, rewritten)

    return SourceMigrationStats(
        project_id=project_id,
        source_id=source_id,
        as_is=as_is,
        upgraded=upgraded,
        unfixable=unfixable,
    )


def _upgrade_file(
    path: Path,
    block_locators: dict[str, Any],
) -> tuple[str, BlockEvidenceExtraction | None]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "unfixable", None
    return _upgrade_payload(raw, block_locators)


def _upgrade_payload(
    raw: dict[str, Any],
    block_locators: dict[str, Any],
) -> tuple[str, BlockEvidenceExtraction | None]:
    try:
        locator = resolve_block_locator(raw, block_locators)
        upgraded = upgrade_block_extraction_payload(raw, block_locator=locator)
        record = BlockEvidenceExtraction.model_validate(upgraded)
    except (EvidenceArtifactUpgradeError, ValueError, KeyError, TypeError):
        return "unfixable", None

    if _needs_field_upgrade(raw):
        return "upgraded", record
    return "as_is", record


def _needs_field_upgrade(raw: dict[str, Any]) -> bool:
    """True when aux items still use the pre-provenance shapes."""

    extraction = raw.get("extraction")
    if not isinstance(extraction, dict):
        return True
    for field in ("definitions", "distinctions"):
        for item in extraction.get(field) or []:
            if not isinstance(item, dict):
                return True
            if "source_id" not in item or "block_id" not in item:
                return True
    for field in ("examples", "objections", "responses", "must_not_be_lost"):
        for item in extraction.get(field) or []:
            if isinstance(item, str):
                return True
            if not isinstance(item, dict):
                return True
            if "source_id" not in item or "block_id" not in item or "text" not in item:
                return True
    return False


def _count_artifacts_without_blocks(
    *,
    extraction_dir: Path,
    jsonl_path: Path,
    has_json: bool,
    has_jsonl: bool,
) -> int:
    """Best-effort artifact count when blocks cannot be loaded.

    Never raises: an unreadable directory or jsonl still counts as unfixable
    (at least one) so migration reports degrade instead of aborting.
    """

    count = 0
    if has_json:
        try:
            count += len(list(extraction_dir.glob("*.json")))
        except OSError:
            count += 1
    if has_jsonl:
        try:
            count += sum(
                1
                for line in jsonl_path.read_text(encoding="utf-8").splitlines()
                if line
            )
        except (OSError, UnicodeError):
            count += 1
    return count


def _list_project_ids(root: Path) -> list[UUID]:
    ids: list[UUID] = []
    for path in sorted(root.glob("*/project.json")):
        try:
            ids.append(UUID(path.parent.name))
        except ValueError:
            continue
    return ids
