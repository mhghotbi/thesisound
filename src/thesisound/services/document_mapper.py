from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any
from uuid import UUID

from thesisound import tracing
from thesisound.domain import (
    CrossSectionThread,
    DocumentMap,
    DocumentMapSection,
    Locator,
)
from thesisound.modeling import DeterministicValidationError, ModelError, ModelRunRecord
from thesisound.services.document_identity import partition_block_key
from thesisound.services.document_map_part_cache import DocumentMapPartCache
from thesisound.services.lineage_events import emit_cache_lookup
from thesisound.services.model_runner import ModelRunner
from thesisound.source_analysis import (
    DocumentMapDraft,
    DocumentMapDraftSection,
    DocumentMapMergeDraft,
    SourceDocumentBlock,
)

# Evidence extraction tolerates a failed block, so its breaker waits for three
# consecutive failures. A failed partition is fatal here -- the document map must
# cover every content block -- so the first failure already aborts the stage. The
# breaker is therefore a single probe: prove the provider answers once before
# paying for the fan-out. document_map_part is the largest call class in the
# pipeline (60% of all input tokens on the 2026-08-09 run).
_PROBE_PARTITIONS = 1


class DocumentMapperService:
    """Build a complete map without sending an unbounded document in one prompt.

    Small documents use one model call. Large documents are partitioned only at
    semantic-block boundaries, preferably at heading boundaries, then a reduce
    pass connects the resulting sections. No text is truncated or sampled.
    """

    def __init__(
        self,
        model_runner: ModelRunner,
        *,
        maximum_input_characters: int = 250_000,
        maximum_merge_payload_characters: int = 250_000,
        part_cache: DocumentMapPartCache | None = None,
        max_workers: int = 1,
    ) -> None:
        if maximum_input_characters < 1:
            raise ValueError("maximum_input_characters must be positive.")
        if maximum_merge_payload_characters < 1:
            raise ValueError("maximum_merge_payload_characters must be positive.")
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1.")
        self.model_runner = model_runner
        # Two separate budgets on purpose. maximum_input_characters bounds the
        # source text in one partition prompt, so lowering it makes partitions
        # smaller and more numerous. The merge payload is section metadata, one
        # entry per section, so it grows with the partition count: measuring it
        # against the text budget would make a smaller budget overflow sooner.
        self.maximum_input_characters = maximum_input_characters
        self.maximum_merge_payload_characters = maximum_merge_payload_characters
        # None means no caching. The service has no workspace root of its own, so
        # it must never construct a cache implicitly.
        self.part_cache = part_cache
        self.max_workers = max_workers

    def map_document(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        blocks: list[SourceDocumentBlock],
        model: str,
        prompt_version: str | None = None,
    ) -> tuple[DocumentMap, ModelRunRecord | None]:
        if not blocks:
            raise ValueError("Cannot map a document without semantic blocks.")

        partitions = _partition_blocks(blocks, self.maximum_input_characters)
        if len(partitions) == 1:
            draft, run = self._map_partition(
                project_id=project_id,
                source_id=source_id,
                blocks=blocks,
                model=model,
                prompt_version=prompt_version,
                part_number=None,
            )
            return _materialize_document_map(source_id, blocks, draft), run

        drafts, records = self._map_partitions(
            project_id=project_id,
            source_id=source_id,
            partitions=partitions,
            model=model,
            prompt_version=prompt_version,
        )
        part_drafts = [_namespace_draft(draft, index + 1) for index, draft in enumerate(drafts)]
        last_part_record = next(
            (record for record in reversed(records) if record is not None),
            None,
        )

        sections = [section for draft in part_drafts for section in draft.sections]
        known_section_ids = {section.section_id for section in sections}
        merge_variables = {
            "source_id": str(source_id),
            "partition_count": len(partitions),
            "partitions": [
                {
                    "part_number": index,
                    "scope": scope_locator(partition).model_dump(mode="json"),
                    "working_thesis": draft.working_thesis,
                    "sections": [_merge_section_payload(section) for section in draft.sections],
                    "cross_section_threads": [
                        thread.model_dump(mode="json") for thread in draft.cross_section_threads
                    ],
                    "warnings": draft.warnings,
                }
                for index, (partition, draft) in enumerate(
                    zip(partitions, part_drafts, strict=True),
                    start=1,
                )
            ],
        }
        payload_characters = len(json.dumps(merge_variables["partitions"], ensure_ascii=False))

        def validate_merge(draft: DocumentMapMergeDraft) -> None:
            _validate_merge_draft(draft, known_section_ids)

        merge_draft = DocumentMapMergeDraft()
        merge_record = last_part_record
        merge_failure: str | None = None
        if payload_characters > self.maximum_merge_payload_characters:
            # Every partition call is already paid for at this point, so an
            # oversized payload must not discard them. Skip the merge and say so.
            merge_failure = (
                "Cross-partition merge was skipped: the partition payload is "
                f"{payload_characters:,} characters across {len(partitions)} partitions, "
                f"over the {self.maximum_merge_payload_characters:,}-character merge budget. "
                "The document map is the union of the partition maps with no cross-partition "
                "links; raise maximum_merge_payload_characters to enable the merge."
            )
        else:
            try:
                merge_execution = self.model_runner.run(
                    project_id=project_id,
                    stage="document_map_merge",
                    prompt_name="document_map_merge",
                    variables=merge_variables,
                    output_type=DocumentMapMergeDraft,
                    model=model,
                    prompt_version=prompt_version,
                    validator=validate_merge,
                )
            except ModelError as exc:
                merge_failure = (
                    f"Cross-partition merge failed ({type(exc).__name__}: {exc}); the document "
                    f"map is the union of {len(partitions)} partition maps with no "
                    "cross-partition links."
                )
            else:
                merge_draft = merge_execution.output
                merge_record = merge_execution.record
        merged = _merge_part_drafts(part_drafts, merge_draft)
        if merge_failure is not None:
            merged.warnings.append(merge_failure)
        merged.warnings.append(
            "Document was mapped hierarchically across "
            f"{len(partitions)} complete semantic partitions; no blocks were omitted."
        )
        known_block_ids = {block.block_id for block in blocks}
        content_block_ids = {
            block.block_id for block in blocks if block.block_type != "front_matter"
        }
        _normalize_map_draft(merged, known_ids=known_block_ids)
        _validate_map_draft(
            merged,
            known_ids=known_block_ids,
            content_ids=content_block_ids,
            minimum_coverage=1.0,
        )
        return _materialize_document_map(source_id, blocks, merged), merge_record

    def _map_partitions(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        partitions: list[list[SourceDocumentBlock]],
        model: str,
        prompt_version: str | None,
    ) -> tuple[list[DocumentMapDraft], list[ModelRunRecord | None]]:
        """One draft per partition, in partition order, reusing the cache.

        Lookups stay on this thread and in order: they are local reads, a fully
        cached document must not start a pool, and `cache.lookup` has to arrive in
        a stable order. The cost is that two partitions with identical text are
        both mapped instead of the second reading what the first just wrote --
        rare, and cheaper than remapping block IDs for a second-chance lookup.
        """

        drafts: list[DocumentMapDraft | None] = [None] * len(partitions)
        records: list[ModelRunRecord | None] = [None] * len(partitions)
        pending: list[int] = []
        for index, partition in enumerate(partitions):
            cached = self._load_cached_partition(project_id, partition)
            if cached is None:
                pending.append(index)
            else:
                drafts[index] = cached

        def work(index: int) -> tuple[int, DocumentMapDraft, ModelRunRecord]:
            partition = partitions[index]
            with tracing.span(
                "corpus.map_partition",
                component="corpus",
                project_id=project_id,
                subject_type="partition",
                subject_id=f"part-{index + 1:04d}",
            ):
                draft, record = self._map_partition(
                    project_id=project_id,
                    source_id=source_id,
                    blocks=partition,
                    model=model,
                    prompt_version=prompt_version,
                    part_number=index + 1,
                    require_complete_coverage=True,
                )
            # Inside the worker on purpose: when one partition fails, the ones
            # still in flight were already paid for and must reach the cache.
            self._save_cached_partition(partition, draft)
            return index, draft, record

        workers = min(self.max_workers, len(pending))
        if workers <= 1:
            for index in pending:
                _, draft, record = work(index)
                drafts[index] = draft
                records[index] = record
        else:
            self._fan_out_partitions(work, pending, workers, drafts, records)

        complete = [draft for draft in drafts if draft is not None]
        if len(complete) != len(partitions):
            raise AssertionError("A document-map partition finished without a draft.")
        return complete, records

    def _fan_out_partitions(
        self,
        work: Callable[[int], tuple[int, DocumentMapDraft, ModelRunRecord]],
        pending: list[int],
        workers: int,
        drafts: list[DocumentMapDraft | None],
        records: list[ModelRunRecord | None],
    ) -> None:
        """Probe one partition, then run the rest concurrently.

        Never more futures in flight than the pool has threads, so nothing sits
        queued and nothing is cancelled: leaving the `with` block on an exception
        waits for the calls already running and keeps what they cached. The first
        failure observed is the one that propagates, unwrapped -- a failed
        partition aborts the whole map, so there is nothing to degrade to.
        """

        bound_work = tracing.bind_context(work)
        position = 0
        futures: set[Future[tuple[int, DocumentMapDraft, ModelRunRecord]]] = set()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for _ in range(min(_PROBE_PARTITIONS, len(pending))):
                futures.add(pool.submit(bound_work, pending[position]))
                position += 1
            while futures:
                future = next(as_completed(futures))
                futures.discard(future)
                index, draft, record = future.result()
                drafts[index] = draft
                records[index] = record
                # Reached only after a success, which is what releases the probe.
                while len(futures) < workers and position < len(pending):
                    futures.add(pool.submit(bound_work, pending[position]))
                    position += 1

    def _map_partition(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        blocks: list[SourceDocumentBlock],
        model: str,
        prompt_version: str | None,
        part_number: int | None,
        require_complete_coverage: bool = False,
    ) -> tuple[DocumentMapDraft, ModelRunRecord]:
        variables = {
            "source_id": str(source_id),
            "part_number": part_number,
            "scope": scope_locator(blocks).model_dump(mode="json"),
            "blocks": [block.model_dump(mode="json") for block in blocks],
        }
        known_ids = {block.block_id for block in blocks}
        content_ids = {block.block_id for block in blocks if block.block_type != "front_matter"}

        def validate(draft: DocumentMapDraft) -> None:
            _normalize_map_draft(draft, known_ids=known_ids)
            _validate_map_draft(
                draft,
                known_ids=known_ids,
                content_ids=content_ids,
                minimum_coverage=1.0 if require_complete_coverage else 0.9,
            )

        execution = self.model_runner.run(
            project_id=project_id,
            stage="document_map" if part_number is None else "document_map_part",
            prompt_name="document_map",
            variables=variables,
            output_type=DocumentMapDraft,
            model=model,
            prompt_version=prompt_version,
            validator=validate,
        )
        return execution.output, execution.record

    def _load_cached_partition(
        self,
        project_id: UUID,
        partition: list[SourceDocumentBlock],
    ) -> DocumentMapDraft | None:
        if self.part_cache is None:
            return None
        content_key = partition_block_key(partition)
        draft = self.part_cache.load(content_key, partition)
        emit_cache_lookup(
            cache="document_map_part",
            result="hit" if draft is not None else "miss",
            lookup_key=content_key[:16],
            artifact_hash=content_key[:16] if draft is not None else None,
            avoided_calls=1 if draft is not None else None,
        )
        return draft

    def _save_cached_partition(
        self,
        partition: list[SourceDocumentBlock],
        draft: DocumentMapDraft,
    ) -> None:
        if self.part_cache is None:
            return
        self.part_cache.save(partition_block_key(partition), partition, draft)


def _partition_blocks(
    blocks: list[SourceDocumentBlock],
    maximum_characters: int,
) -> list[list[SourceDocumentBlock]]:
    total = sum(len(block.text) for block in blocks)
    if total <= maximum_characters:
        return [blocks]

    atomic_groups = _semantic_groups(blocks, maximum_characters, heading_depth=0)
    partitions: list[list[SourceDocumentBlock]] = []
    current: list[SourceDocumentBlock] = []
    current_size = 0
    for group in atomic_groups:
        group_size = sum(len(block.text) for block in group)
        if current and current_size + group_size > maximum_characters:
            partitions.append(current)
            current = []
            current_size = 0
        current.extend(group)
        current_size += group_size
    if current:
        partitions.append(current)

    flattened_ids = [block.block_id for part in partitions for block in part]
    expected_ids = [block.block_id for block in blocks]
    if flattened_ids != expected_ids:
        raise AssertionError("Document partitioning changed block order or coverage.")
    return partitions


def _semantic_groups(
    blocks: list[SourceDocumentBlock],
    maximum_characters: int,
    *,
    heading_depth: int,
) -> list[list[SourceDocumentBlock]]:
    groups = _contiguous_heading_groups(blocks, heading_depth)
    result: list[list[SourceDocumentBlock]] = []
    for group in groups:
        size = sum(len(block.text) for block in group)
        if size <= maximum_characters:
            result.append(group)
            continue
        has_deeper_heading = any(len(block.heading_path) > heading_depth + 1 for block in group)
        if has_deeper_heading:
            result.extend(
                _semantic_groups(
                    group,
                    maximum_characters,
                    heading_depth=heading_depth + 1,
                )
            )
            continue
        result.extend(_split_at_block_boundaries(group, maximum_characters))
    return result


def _contiguous_heading_groups(
    blocks: list[SourceDocumentBlock],
    heading_depth: int,
) -> list[list[SourceDocumentBlock]]:
    groups: list[list[SourceDocumentBlock]] = []
    current: list[SourceDocumentBlock] = []
    current_key: str | None = None
    for block in blocks:
        key = block.heading_path[heading_depth] if len(block.heading_path) > heading_depth else None
        if current and key != current_key:
            groups.append(current)
            current = []
        current.append(block)
        current_key = key
    if current:
        groups.append(current)
    return groups


def _split_at_block_boundaries(
    blocks: list[SourceDocumentBlock],
    maximum_characters: int,
) -> list[list[SourceDocumentBlock]]:
    result: list[list[SourceDocumentBlock]] = []
    current: list[SourceDocumentBlock] = []
    current_size = 0
    for block in blocks:
        block_size = len(block.text)
        if block_size > maximum_characters:
            raise ValueError(
                "A semantic block is larger than the document-map input budget. "
                f"Block {block.block_id} has {block_size:,} characters; split it in "
                "BlockBuilder before mapping so locators and evidence remain intact."
            )
        if current and current_size + block_size > maximum_characters:
            result.append(current)
            current = []
            current_size = 0
        current.append(block)
        current_size += block_size
    if current:
        result.append(current)
    return result


def _merge_section_payload(section: DocumentMapDraftSection) -> dict[str, Any]:
    """The section fields the merge pass is allowed to reason about.

    Block IDs are omitted on purpose: the merge prompt may only reference section
    IDs, block IDs are the largest field in the payload, and a model that never
    sees a block ID cannot emit one.
    """

    return {
        "section_id": section.section_id,
        "title": section.title,
        "function": section.function,
        "key_concepts": section.key_concepts,
        "depends_on_section_ids": section.depends_on_section_ids,
        "required_for_global_understanding": section.required_for_global_understanding,
        "unresolved_context": section.unresolved_context,
        "block_count": len(section.source_block_ids),
    }


def _namespace_draft(draft: DocumentMapDraft, part_number: int) -> DocumentMapDraft:
    prefix = f"part-{part_number:04d}:"
    id_map = {section.section_id: prefix + section.section_id for section in draft.sections}
    return DocumentMapDraft(
        working_thesis=draft.working_thesis,
        sections=[
            section.model_copy(
                update={
                    "section_id": id_map[section.section_id],
                    "depends_on_section_ids": [
                        id_map[dependency] for dependency in section.depends_on_section_ids
                    ],
                }
            )
            for section in draft.sections
        ],
        cross_section_threads=[
            thread.model_copy(
                update={"section_ids": [id_map[section_id] for section_id in thread.section_ids]}
            )
            for thread in draft.cross_section_threads
        ],
        warnings=draft.warnings.copy(),
    )


def _merge_part_drafts(
    part_drafts: list[DocumentMapDraft],
    merge: DocumentMapMergeDraft,
) -> DocumentMapDraft:
    sections = [
        section.model_copy(deep=True) for draft in part_drafts for section in draft.sections
    ]
    by_id = {section.section_id: section for section in sections}
    for update in merge.section_updates:
        section = by_id[update.section_id]
        section.depends_on_section_ids = _unique(
            [*section.depends_on_section_ids, *update.depends_on_section_ids]
        )
        section.unresolved_context = _unique(
            [*section.unresolved_context, *update.unresolved_context]
        )
    for section_id in merge.globally_required_section_ids:
        by_id[section_id].required_for_global_understanding = True

    local_threads = [thread for draft in part_drafts for thread in draft.cross_section_threads]
    threads = _deduplicate_threads([*local_threads, *merge.cross_section_threads])
    warnings = _unique(
        [
            *(warning for draft in part_drafts for warning in draft.warnings),
            *merge.warnings,
        ]
    )
    working_thesis = merge.working_thesis
    if not working_thesis:
        working_thesis = next(
            (draft.working_thesis for draft in part_drafts if draft.working_thesis), None
        )
        if working_thesis:
            warnings = [
                *warnings,
                "The merge pass returned no global thesis; the first partition's thesis is "
                "used for the whole document.",
            ]
    return DocumentMapDraft(
        working_thesis=working_thesis,
        sections=sections,
        cross_section_threads=threads,
        warnings=warnings,
    )


def _normalize_map_draft(draft: DocumentMapDraft, *, known_ids: set[str]) -> None:
    """Repair exclusive block ownership before the quality gate.

    Models sometimes invent out-of-partition IDs or put the same block in two
    adjacent sections. Drop unknown IDs and keep the first section claim so
    coverage validation still rejects genuine omissions.
    """

    claimed: set[str] = set()
    dropped_unknown: list[str] = []
    dropped_duplicates: list[str] = []
    kept_sections: list = []
    for section in draft.sections:
        cleaned: list[str] = []
        for block_id in section.source_block_ids:
            if block_id not in known_ids:
                dropped_unknown.append(block_id)
                continue
            if block_id in claimed:
                dropped_duplicates.append(block_id)
                continue
            claimed.add(block_id)
            cleaned.append(block_id)
        if not cleaned:
            continue
        section.source_block_ids = cleaned
        kept_sections.append(section)

    if not kept_sections:
        raise DeterministicValidationError(
            "Document map has no sections left after removing unknown or duplicate blocks."
        )

    removed_section_ids = {section.section_id for section in draft.sections} - {
        section.section_id for section in kept_sections
    }
    draft.sections = kept_sections
    for section in draft.sections:
        section.depends_on_section_ids = [
            dependency
            for dependency in section.depends_on_section_ids
            if dependency not in removed_section_ids and dependency != section.section_id
        ]
    cleaned_threads = []
    for thread in draft.cross_section_threads:
        section_ids = [
            section_id for section_id in thread.section_ids if section_id not in removed_section_ids
        ]
        if not section_ids:
            continue
        thread.section_ids = _unique(section_ids)
        cleaned_threads.append(thread)
    draft.cross_section_threads = cleaned_threads

    if dropped_unknown:
        draft.warnings.append(
            "Removed unknown block IDs from document map: "
            f"{', '.join(sorted(set(dropped_unknown)))}."
        )
    if dropped_duplicates:
        draft.warnings.append(
            "Assigned overlapping blocks to their first map section only: "
            f"{', '.join(sorted(set(dropped_duplicates)))}."
        )


def _validate_merge_draft(
    draft: DocumentMapMergeDraft,
    known_section_ids: set[str],
) -> None:
    updated_ids = [update.section_id for update in draft.section_updates]
    if len(updated_ids) != len(set(updated_ids)):
        raise DeterministicValidationError("Document-map merge contains duplicate section updates.")
    referenced = set(updated_ids) | set(draft.globally_required_section_ids)
    for update in draft.section_updates:
        referenced.update(update.depends_on_section_ids)
    for thread in draft.cross_section_threads:
        referenced.update(thread.section_ids)
    unknown = referenced - known_section_ids
    if unknown:
        raise DeterministicValidationError(
            f"Document-map merge referenced unknown section IDs: {', '.join(sorted(unknown))}."
        )
    for update in draft.section_updates:
        if update.section_id in update.depends_on_section_ids:
            raise DeterministicValidationError(
                f"Section {update.section_id} cannot depend on itself."
            )


def _validate_map_draft(
    draft: DocumentMapDraft,
    *,
    known_ids: set[str],
    content_ids: set[str],
    minimum_coverage: float = 0.9,
) -> None:
    section_ids = [section.section_id for section in draft.sections]
    if len(section_ids) != len(set(section_ids)):
        raise DeterministicValidationError("Document map section IDs must be unique.")
    known_sections = set(section_ids)
    mapped: list[str] = []
    for section in draft.sections:
        unknown_blocks = set(section.source_block_ids) - known_ids
        if unknown_blocks:
            raise DeterministicValidationError(
                f"Document map referenced unknown blocks: {', '.join(sorted(unknown_blocks))}."
            )
        unknown_dependencies = set(section.depends_on_section_ids) - known_sections
        if unknown_dependencies:
            raise DeterministicValidationError(
                "Document map referenced unknown dependency sections: "
                f"{', '.join(sorted(unknown_dependencies))}."
            )
        mapped.extend(section.source_block_ids)

    duplicates = {block_id for block_id in mapped if mapped.count(block_id) > 1}
    if duplicates:
        raise DeterministicValidationError(
            f"Blocks may belong to only one map section: {', '.join(sorted(duplicates))}."
        )
    mapped_content = set(mapped) & content_ids
    coverage = len(mapped_content) / len(content_ids) if content_ids else 1
    if coverage < minimum_coverage:
        raise DeterministicValidationError(
            "Document map covered only "
            f"{coverage:.0%} of non-front-matter blocks; "
            f"required coverage is {minimum_coverage:.0%}."
        )
    for thread in draft.cross_section_threads:
        unknown = set(thread.section_ids) - known_sections
        if unknown:
            raise DeterministicValidationError(
                f"Cross-section thread referenced unknown sections: {', '.join(sorted(unknown))}."
            )


def _materialize_document_map(
    source_id: UUID,
    blocks: list[SourceDocumentBlock],
    draft: DocumentMapDraft,
) -> DocumentMap:
    return DocumentMap(
        source_id=source_id,
        scope_locator=scope_locator(blocks),
        working_thesis=draft.working_thesis,
        sections=[
            DocumentMapSection(
                section_id=section.section_id,
                source_block_ids=section.source_block_ids,
                title=section.title,
                function=section.function,
                key_concepts=section.key_concepts,
                depends_on_section_ids=section.depends_on_section_ids,
                required_for_global_understanding=(section.required_for_global_understanding),
                unresolved_context=section.unresolved_context,
            )
            for section in draft.sections
        ],
        cross_section_threads=[
            CrossSectionThread(
                label=thread.label,
                section_ids=thread.section_ids,
                description=thread.description,
            )
            for thread in draft.cross_section_threads
        ],
        warnings=draft.warnings,
    )


def _deduplicate_threads(threads: Iterable) -> list:
    result = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for thread in threads:
        key = (thread.label.casefold(), tuple(thread.section_ids))
        if key in seen:
            continue
        seen.add(key)
        result.append(thread)
    return result


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def scope_locator(blocks: list[SourceDocumentBlock]) -> Locator:
    """The span a run of blocks covers, taken from the file those blocks came from."""

    starts = [block.locator.page_start for block in blocks if block.locator.page_start is not None]
    ends = [block.locator.page_end for block in blocks if block.locator.page_end is not None]
    first_heading = next((block.heading_path for block in blocks if block.heading_path), [])
    return Locator(
        page_start=min(starts) if starts else None,
        page_end=max(ends) if ends else None,
        chapter=first_heading[0] if first_heading else None,
        section=first_heading[-1] if first_heading else None,
    )
