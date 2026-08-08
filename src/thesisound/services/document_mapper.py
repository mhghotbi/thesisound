from __future__ import annotations

from uuid import UUID

from thesisound.domain import (
    CrossSectionThread,
    DocumentMap,
    DocumentMapSection,
    Locator,
)
from thesisound.modeling import DeterministicValidationError, ModelRunRecord
from thesisound.services.model_runner import ModelRunner
from thesisound.source_analysis import DocumentMapDraft, SourceDocumentBlock


class DocumentMapperService:
    def __init__(
        self,
        model_runner: ModelRunner,
        *,
        maximum_input_characters: int = 250_000,
    ) -> None:
        self.model_runner = model_runner
        self.maximum_input_characters = maximum_input_characters

    def map_document(
        self,
        *,
        project_id: UUID,
        source_id: UUID,
        blocks: list[SourceDocumentBlock],
        model: str,
        prompt_version: str | None = None,
    ) -> tuple[DocumentMap, ModelRunRecord]:
        if not blocks:
            raise ValueError("Cannot map a document without semantic blocks.")
        total_characters = sum(len(block.text) for block in blocks)
        if total_characters > self.maximum_input_characters:
            raise ValueError(
                "Document map input is too large for the one-source vertical slice; "
                "analyze a chapter or a smaller document scope."
            )

        variables = {
            "source_id": str(source_id),
            "blocks": [block.model_dump(mode="json") for block in blocks],
        }
        known_ids = {block.block_id for block in blocks}
        content_ids = {
            block.block_id for block in blocks if block.block_type != "front_matter"
        }

        def validate(draft: DocumentMapDraft) -> None:
            _validate_map_draft(draft, known_ids=known_ids, content_ids=content_ids)

        execution = self.model_runner.run(
            project_id=project_id,
            stage="document_map",
            prompt_name="document_map",
            variables=variables,
            output_type=DocumentMapDraft,
            model=model,
            prompt_version=prompt_version,
            validator=validate,
        )
        document_map = DocumentMap(
            source_id=source_id,
            scope_locator=_scope_locator(blocks),
            working_thesis=execution.output.working_thesis,
            sections=[
                DocumentMapSection(
                    section_id=section.section_id,
                    source_block_ids=section.source_block_ids,
                    title=section.title,
                    function=section.function,
                    key_concepts=section.key_concepts,
                    depends_on_section_ids=section.depends_on_section_ids,
                    required_for_global_understanding=(
                        section.required_for_global_understanding
                    ),
                    unresolved_context=section.unresolved_context,
                )
                for section in execution.output.sections
            ],
            cross_section_threads=[
                CrossSectionThread(
                    label=thread.label,
                    section_ids=thread.section_ids,
                    description=thread.description,
                )
                for thread in execution.output.cross_section_threads
            ],
            warnings=execution.output.warnings,
        )
        return document_map, execution.record


def _validate_map_draft(
    draft: DocumentMapDraft,
    *,
    known_ids: set[str],
    content_ids: set[str],
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
                "Document map referenced unknown blocks: "
                f"{', '.join(sorted(unknown_blocks))}."
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
            "Blocks may belong to only one map section: "
            f"{', '.join(sorted(duplicates))}."
        )
    mapped_content = set(mapped) & content_ids
    coverage = len(mapped_content) / len(content_ids) if content_ids else 1
    if coverage < 0.9:
        raise DeterministicValidationError(
            f"Document map covered only {coverage:.0%} of non-front-matter blocks."
        )
    for thread in draft.cross_section_threads:
        unknown = set(thread.section_ids) - known_sections
        if unknown:
            raise DeterministicValidationError(
                "Cross-section thread referenced unknown sections: "
                f"{', '.join(sorted(unknown))}."
            )


def _scope_locator(blocks: list[SourceDocumentBlock]) -> Locator:
    starts = [
        block.locator.page_start
        for block in blocks
        if block.locator.page_start is not None
    ]
    ends = [
        block.locator.page_end
        for block in blocks
        if block.locator.page_end is not None
    ]
    first_heading = next((block.heading_path for block in blocks if block.heading_path), [])
    return Locator(
        page_start=min(starts) if starts else None,
        page_end=max(ends) if ends else None,
        chapter=first_heading[0] if first_heading else None,
        section=first_heading[-1] if first_heading else None,
    )
