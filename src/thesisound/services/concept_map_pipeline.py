"""Build a source concept map from a local document (CLI composition)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from thesisound.adapters.models.gemini import GeminiStructuredModel
from thesisound.concepts import SourceConceptMap
from thesisound.config import Settings
from thesisound.domain import Project
from thesisound.pipeline import WorkspaceStore
from thesisound.prompt_loader import PromptLoader
from thesisound.services.block_builder import BlockBuilder
from thesisound.services.concept_map_builder import ConceptMapBuilder, detect_chapters
from thesisound.services.cost_estimate import estimate_tokens
from thesisound.services.document_ingestion import ingest_document
from thesisound.services.document_map_part_cache import DocumentMapPartCache
from thesisound.services.document_mapper import DocumentMapperService
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner
from thesisound.services.source_artifact_store import SourceArtifactStore
from thesisound.source_analysis import SourceDocumentBlock

_CLI_NAMESPACE = uuid5(NAMESPACE_URL, "thesisound.concept-map")


@dataclass(frozen=True)
class ConceptMapCliResult:
    project_id: UUID
    source_id: UUID
    concept_map: SourceConceptMap
    estimated_tokens: dict[str, int]
    path: Path


def parse_chapter_selector(raw: str | None) -> tuple[int, ...] | None:
    """Parse ``--chapters 1,3`` into 0-based ``chapter_index`` values."""

    if raw is None or not raw.strip():
        return None
    indexes: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            number = int(token)
        except ValueError as exc:
            raise ValueError(f"Invalid chapter number: {token!r}.") from exc
        if number < 1:
            raise ValueError("Chapter numbers are 1-based and must be >= 1.")
        indexes.append(number - 1)
    if not indexes:
        return None
    return tuple(dict.fromkeys(indexes))


def chapter_token_total(
    blocks: list[SourceDocumentBlock],
    chapter_block_ids: list[str],
) -> int:
    wanted = set(chapter_block_ids)
    return sum(block.estimated_token_count for block in blocks if block.block_id in wanted)


def concept_map_summary(
    result: ConceptMapCliResult,
) -> dict[str, object]:
    """JSON payload printed by ``thesisound concept-map --json``."""

    concept_map = result.concept_map
    stats = concept_map.statistics
    return {
        "path": str(result.path),
        "project_id": str(result.project_id),
        "source_id": str(result.source_id),
        "source_fingerprint": concept_map.source_fingerprint,
        "chapters": [
            {
                "number": chapter.chapter_index + 1,
                "chapter_index": chapter.chapter_index,
                "title": chapter.title,
                "detected_from": chapter.detected_from,
                "detection_agreement": chapter.detection_agreement,
                "estimated_minutes": chapter.estimated_minutes,
                "block_count": len(chapter.block_ids),
            }
            for chapter in concept_map.chapters
        ],
        "cells_per_tier": {str(key): value for key, value in stats.cells_per_tier.items()},
        "promoted_cell_keys": list(stats.promoted_cell_keys),
        "edges": [
            {
                "source_key": edge.source_key,
                "target_key": edge.target_key,
                "type": edge.type,
                "weight": edge.weight,
                "created_by": edge.created_by,
                "is_cross_chapter": edge.is_cross_chapter,
            }
            for edge in concept_map.edges
        ],
        "statistics": stats.model_dump(mode="json"),
        "warnings": list(concept_map.warnings),
        "estimated_tokens": result.estimated_tokens,
    }


def structured_model_from_settings(settings: Settings) -> object:
    """Composition seam so tests can inject the existing fake model."""

    return GeminiStructuredModel(api_keys=settings.gemini_api_keys)


def build_concept_map_from_path(
    path: Path,
    *,
    workspace_root: Path,
    settings: Settings,
    chapters: tuple[int, ...] | None = None,
    rebuild: bool = False,
    model_runner: ModelRunner | None = None,
) -> ConceptMapCliResult:
    """Parse, map, and build a concept map for one local file."""

    from thesisound.cli import _artifact_writer, _parse_cache, _parsers

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Document not found: {resolved}")

    writer = _artifact_writer(settings, None)
    ingestion = ingest_document(
        resolved,
        parsers=_parsers(settings, writer),
        parser_name="auto",
        artifact_writer=writer,
        parse_cache=_parse_cache(settings, None),
    )
    if ingestion.parsed is None:
        raise ValueError("Ingestion produced no parsed document.")
    if not ingestion.safe_for_claim_extraction:
        raise ValueError("Ingestion did not pass the claim-extraction quality gate.")

    project_id = uuid5(_CLI_NAMESPACE, f"project:{ingestion.inspection.sha256}")
    source_id = uuid5(_CLI_NAMESPACE, f"source:{ingestion.inspection.sha256}")
    workspace = WorkspaceStore(workspace_root)
    try:
        workspace.load_project(project_id)
    except FileNotFoundError:
        workspace.save_project(Project(project_id=project_id, raw_input=resolved.name))

    runner = model_runner or ModelRunner(
        structured_model_from_settings(settings),  # type: ignore[arg-type]
        PromptLoader(),
        WorkspaceModelRunStore(workspace_root, keep_prompts=settings.keep_rendered_prompts),
        base_retry_delay_seconds=settings.model_retry_base_seconds,
    )
    artifacts = SourceArtifactStore(workspace_root)
    blocks, report = BlockBuilder().build(ingestion.parsed, source_id=source_id)
    if not blocks:
        raise ValueError("Block builder produced no analyzable content.")
    artifacts.save_ingestion(project_id, source_id, ingestion)
    artifacts.save_blocks(project_id, source_id, blocks, report)

    detected = detect_chapters(blocks, ingestion.parsed)
    if chapters is not None:
        available = {chapter.chapter_index for chapter in detected}
        missing = [index for index in chapters if index not in available]
        if missing:
            listed = ", ".join(str(chapter.chapter_index + 1) for chapter in detected)
            requested = ", ".join(str(index + 1) for index in missing)
            raise ValueError(
                f"Requested chapter(s) {requested} not found. Available: {listed or 'none'}."
            )
        selected = [chapter for chapter in detected if chapter.chapter_index in set(chapters)]
    else:
        selected = detected

    by_id = {block.block_id: block for block in blocks}
    partitions = [
        [by_id[block_id] for block_id in chapter.block_ids if block_id in by_id]
        for chapter in selected
    ]
    mapper = DocumentMapperService(
        runner,
        part_cache=DocumentMapPartCache(workspace_root),
        max_workers=settings.document_map_workers,
    )
    document_map, _run = mapper.map_document(
        project_id=project_id,
        source_id=source_id,
        blocks=blocks,
        model=settings.model_fast,
        partitions=partitions,
    )
    artifacts.save_document_map(project_id, source_id, document_map)

    builder = ConceptMapBuilder(runner, workspace_root=workspace_root)
    concept_map = builder.build(
        project_id,
        source_id,
        blocks,
        document_map,
        ingestion.parsed,
        model_fast=settings.model_fast,
        rebuild=rebuild,
        chapter_indexes=chapters,
    )
    artifacts.save_concept_map(project_id, source_id, concept_map)
    in_scope_ids = [block_id for chapter in concept_map.chapters for block_id in chapter.block_ids]
    estimated = estimate_tokens(chapter_token_total(blocks, in_scope_ids))
    return ConceptMapCliResult(
        project_id=project_id,
        source_id=source_id,
        concept_map=concept_map,
        estimated_tokens=estimated,
        path=resolved,
    )
