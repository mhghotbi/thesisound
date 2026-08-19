from uuid import uuid4

import pytest

from thesisound.concepts import (
    ConceptCell,
    ConceptCellDraft,
    ConceptCellsDraft,
    is_banned_or_smell_label,
)
from thesisound.domain import DocumentMapSection, Locator
from thesisound.modeling import DeterministicValidationError
from thesisound.services.concept_map_builder import (
    _validate_cells_draft,
    assign_cell_keys,
    build_chapter_awareness,
    chapter_budget,
)
from thesisound.source_analysis import SourceDocumentBlock

_SOURCE_ID = uuid4()


def _section(
    section_id: str,
    *block_ids: str,
    function: str = "argument",
) -> DocumentMapSection:
    return DocumentMapSection(
        section_id=section_id,
        source_block_ids=list(block_ids) or ["b0001"],
        title=section_id,
        function=function,  # type: ignore[arg-type]
    )


def _draft_cell(
    label_fa: str,
    *,
    section_ids: list[str] | None = None,
    block_ids: list[str] | None = None,
    tier: int = 2,
    kind: str = "definition",
) -> ConceptCellDraft:
    return ConceptCellDraft(
        label_fa=label_fa,
        label_source=None,
        kind=kind,  # type: ignore[arg-type]
        tier=tier,  # type: ignore[arg-type]
        section_ids=section_ids or ["s001"],
        block_ids=block_ids or ["b0001"],
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=5.0,
    )


def _draft(cells: list[ConceptCellDraft]) -> ConceptCellsDraft:
    return ConceptCellsDraft(cells=cells, warnings=[])


def _validate(
    draft: ConceptCellsDraft,
    *,
    sections: list[DocumentMapSection] | None = None,
    budget: int = 6,
    attempt: int = 1,
    max_attempts: int = 3,
    known_block_ids: set[str] | None = None,
    known_section_ids: set[str] | None = None,
    accepted_cells: list[ConceptCell] | None = None,
) -> None:
    sections = sections or [_section("s001", "b0001"), _section("s002", "b0002")]
    _validate_cells_draft(
        draft,
        known_block_ids=known_block_ids or {"b0001", "b0002", "b0003"},
        known_section_ids=known_section_ids or {"s001", "s002", "s003"},
        sections=sections,
        budget=budget,
        attempt=attempt,
        max_attempts=max_attempts,
        accepted_cells=accepted_cells or (),
    )


class TestChapterBudget:
    def test_clamps_to_minimum_six(self) -> None:
        assert chapter_budget([_section("s001", "b0001")]) == 6

    def test_ignores_front_matter(self) -> None:
        sections = [
            _section("front", "b0000", function="front_matter"),
            _section("s001", "b0001"),
        ]
        assert chapter_budget(sections) == 6

    def test_scales_with_section_count(self) -> None:
        sections = [_section(f"s{i:03d}", f"b{i:04d}") for i in range(10)]
        assert chapter_budget(sections) == 15

    def test_clamps_to_maximum_forty(self) -> None:
        sections = [_section(f"s{i:03d}", f"b{i:04d}") for i in range(30)]
        assert chapter_budget(sections) == 40


class TestChapterAwareness:
    def test_empty_accepted_cells(self) -> None:
        awareness = build_chapter_awareness([], remaining_budget=8)
        assert awareness["accepted_cell_count"] == 0
        assert awareness["remaining_budget"] == 8
        assert awareness["accepted_labels"] == []

    def test_lists_accepted_labels(self) -> None:
        cell = _draft_cell("تعریف ارزش")
        awareness = build_chapter_awareness([cell], remaining_budget=2)
        assert awareness["accepted_labels"] == [
            {"label_fa": "تعریف ارزش", "kind": "definition", "tier": 2}
        ]
        assert "Do not recreate" in awareness["instruction"]


class TestUnknownIds:
    def test_unknown_block_id(self) -> None:
        draft = _draft([_draft_cell("تعریف ارزش", block_ids=["missing"])])
        with pytest.raises(DeterministicValidationError, match="Unknown block_id"):
            _validate(draft)

    def test_unknown_section_id(self) -> None:
        draft = _draft([_draft_cell("تعریف ارزش", section_ids=["no-such"])])
        with pytest.raises(DeterministicValidationError, match="Unknown section_id"):
            _validate(draft)


class TestCellWithoutBlock:
    def test_empty_block_ids(self) -> None:
        cell = ConceptCellDraft.model_construct(
            label_fa="تعریف ارزش",
            label_source=None,
            kind="definition",
            tier=2,
            section_ids=["s001"],
            block_ids=[],
            granularity_rationale="x",
            estimated_minutes=5.0,
        )
        draft = _draft([cell])
        with pytest.raises(DeterministicValidationError, match="without a source block"):
            _validate(draft)


class TestSectionCoverage:
    def test_uncovered_content_section(self) -> None:
        draft = _draft([_draft_cell("تعریف ارزش", section_ids=["s001"], block_ids=["b0001"])])
        sections = [_section("s001", "b0001"), _section("s002", "b0002")]
        with pytest.raises(DeterministicValidationError, match="uncovered: s002"):
            _validate(draft, sections=sections)

    def test_front_matter_and_transition_are_exempt(self) -> None:
        draft = _draft([_draft_cell("تعریف ارزش", section_ids=["s001"], block_ids=["b0001"])])
        sections = [
            _section("front", "b0000", function="front_matter"),
            _section("s001", "b0001"),
            _section("bridge", "b0002", function="transition"),
        ]
        _validate(draft, sections=sections)


class TestBannedLabels:
    def test_english_structural_label(self) -> None:
        draft = _draft([_draft_cell("Introduction")])
        with pytest.raises(DeterministicValidationError, match="Banned or smell"):
            _validate(draft)

    def test_persian_structural_label(self) -> None:
        draft = _draft([_draft_cell("مقدمه")])
        with pytest.raises(DeterministicValidationError, match="Banned or smell"):
            _validate(draft)

    def test_numbered_chapter_label(self) -> None:
        assert is_banned_or_smell_label("chapter 2")
        assert is_banned_or_smell_label("بخش دوم")
        draft = _draft([_draft_cell("بخش دوم")])
        with pytest.raises(DeterministicValidationError, match="Banned or smell"):
            _validate(draft)

    def test_real_concept_label_is_allowed(self) -> None:
        assert not is_banned_or_smell_label("تمایز کنش و ساخت")
        draft = _draft(
            [
                _draft_cell("تمایز کنش و ساخت", section_ids=["s001"]),
                _draft_cell("استدلال اصلی فصل", section_ids=["s002"], block_ids=["b0002"]),
            ]
        )
        _validate(draft)


class TestDuplicateLabels:
    def test_jaccard_duplicate_errors_on_early_attempt(self) -> None:
        draft = _draft(
            [
                _draft_cell(
                    "alpha beta gamma delta epsilon zeta",
                    section_ids=["s001"],
                ),
                _draft_cell(
                    "alpha beta gamma delta epsilon zeta eta",
                    section_ids=["s002"],
                    block_ids=["b0002"],
                ),
            ]
        )
        with pytest.raises(DeterministicValidationError, match="Duplicate cell labels"):
            _validate(draft, attempt=1, max_attempts=3)

    def test_auto_merges_duplicates_on_final_attempt(self) -> None:
        draft = _draft(
            [
                _draft_cell("تعریف ارزش مبادله", section_ids=["s001"], block_ids=["b0001"]),
                _draft_cell("تعریف ارزش مبادله", section_ids=["s002"], block_ids=["b0002"]),
            ]
        )
        _validate(draft, attempt=3, max_attempts=3)
        assert len(draft.cells) == 1
        assert set(draft.cells[0].block_ids) == {"b0001", "b0002"}
        assert set(draft.cells[0].section_ids) == {"s001", "s002"}
        assert any("Auto-merged" in warning for warning in draft.warnings)


class TestCountCap:
    def test_rejects_more_than_budget_times_one_and_a_half(self) -> None:
        cells = [
            _draft_cell(
                f"مفهوم مستقل شماره {index}",
                section_ids=["s001" if index < 5 else "s002"],
                block_ids=["b0001" if index < 5 else "b0002"],
                tier=2 if index % 3 else 1 if index % 2 else 3,
            )
            for index in range(10)
        ]
        draft = _draft(cells)
        with pytest.raises(DeterministicValidationError, match="exceeds the chapter cap"):
            _validate(draft, budget=6)


class TestTierDistribution:
    def _six_cells(self, tiers: list[int]) -> ConceptCellsDraft:
        return _draft(
            [
                _draft_cell(
                    f"مفهوم مستقل شماره {index}",
                    section_ids=["s001" if index < 3 else "s002"],
                    block_ids=["b0001" if index < 3 else "b0002"],
                    tier=tier,
                )
                for index, tier in enumerate(tiers)
            ]
        )

    def test_all_tier_two_errors_on_early_attempt(self) -> None:
        draft = self._six_cells([2, 2, 2, 2, 2, 2])
        with pytest.raises(DeterministicValidationError, match="Tier distribution"):
            _validate(draft, attempt=1, max_attempts=3)

    def test_accepts_and_flags_on_final_attempt(self) -> None:
        draft = self._six_cells([2, 2, 2, 2, 2, 2])
        _validate(draft, attempt=3, max_attempts=3)
        assert any(warning.startswith("needs_review:") for warning in draft.warnings)

    def test_valid_spread_passes(self) -> None:
        draft = self._six_cells([1, 2, 2, 2, 3, 3])
        _validate(draft, attempt=1, max_attempts=3)
        assert draft.warnings == []


class TestAssignCellKeys:
    def test_keys_follow_first_block_order(self) -> None:
        drafts = [
            _draft_cell("دوم", block_ids=["b0002"], section_ids=["s002"]),
            _draft_cell("اول", block_ids=["b0001"], section_ids=["s001"]),
        ]
        cells = assign_cell_keys(drafts, chapter_index=3, block_ids_in_order=["b0001", "b0002"])
        assert [cell.cell_key for cell in cells] == ["ch03-c001", "ch03-c002"]
        assert [cell.label_fa for cell in cells] == ["اول", "دوم"]
        assert cells[0].chapter_index == 3
        assert cells[0].created_by == "ai"


class TestExtractChapterCells:
    def test_assigns_keys_and_persists_full_block_text(self, tmp_path) -> None:
        from thesisound.concepts import SourceChapter
        from thesisound.modeling import ModelUsage, StructuredModelResponse
        from thesisound.prompt_loader import PromptLoader
        from thesisound.services.concept_map_builder import extract_chapter_cells
        from thesisound.services.model_run_store import WorkspaceModelRunStore
        from thesisound.services.model_runner import ModelRunner

        chapter = SourceChapter(
            chapter_index=1,
            title="فصل یکم",
            heading_path=["فصل یکم"],
            block_ids=["b0001", "b0002"],
            estimated_minutes=4.0,
            detected_from="heading",
            detection_agreement="agreed",
        )
        sections = [_section("s001", "b0001"), _section("s002", "b0002")]
        blocks = [
            _block("b0001", "verbatim block one text"),
            _block("b0002", "verbatim block two text"),
        ]
        output = _draft(
            [
                _draft_cell("تمایز کنش و ساخت", section_ids=["s001"], block_ids=["b0001"]),
                _draft_cell(
                    "استدلال اصلی فصل",
                    section_ids=["s002"],
                    block_ids=["b0002"],
                    kind="argument",
                ),
            ]
        )

        class FakeCellsModel:
            provider = "fake"
            prompts: list[str] = []

            def generate_structured(self, **kwargs):
                self.prompts.append(kwargs["user_prompt"])
                return StructuredModelResponse(
                    output=output,
                    provider=self.provider,
                    model="fake-fast",
                    usage=ModelUsage(),
                    latency_ms=1,
                    finish_reason="STOP",
                )

        model = FakeCellsModel()
        runner = ModelRunner(
            model,
            PromptLoader(),
            WorkspaceModelRunStore(tmp_path / "workspaces"),
            sleeper=lambda _: None,
        )
        result = extract_chapter_cells(
            runner,
            project_id=uuid4(),
            source_id=_SOURCE_ID,
            chapter=chapter,
            sections=sections,
            blocks=blocks,
            model="fake-fast",
        )
        assert [cell.cell_key for cell in result.cells] == ["ch01-c001", "ch01-c002"]
        assert "verbatim block one text" in model.prompts[0]
        assert "verbatim block two text" in model.prompts[0]


def _block(block_id: str, text: str) -> SourceDocumentBlock:
    return SourceDocumentBlock(
        block_id=block_id,
        source_id=_SOURCE_ID,
        locator=Locator(),
        heading_path=["Chapter"],
        block_type="argument",
        text=text,
        estimated_token_count=20,
        source_block_keys=[block_id],
    )
