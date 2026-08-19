from uuid import uuid4

import pytest

from thesisound.concepts import (
    ConceptCell,
    ConceptCellsConsolidateDraft,
    ConsolidateActionDraft,
)
from thesisound.modeling import DeterministicValidationError, ModelUsage, StructuredModelResponse
from thesisound.prompt_loader import PromptLoader
from thesisound.services.concept_map_builder import (
    _apply_consolidate_actions,
    _validate_consolidate_draft,
    consolidate_chapter,
)
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner


def _cell(
    cell_key: str,
    *,
    label_fa: str | None = None,
    tier: int = 2,
    section_ids: list[str] | None = None,
    block_ids: list[str] | None = None,
    estimated_minutes: float = 5.0,
) -> ConceptCell:
    number = int(cell_key.split("-c")[1])
    return ConceptCell(
        cell_key=cell_key,
        label_fa=label_fa or f"مفهوم {number}",
        label_source=None,
        kind="definition",
        tier=tier,  # type: ignore[arg-type]
        chapter_index=0,
        section_ids=section_ids or [f"s{number:03d}"],
        block_ids=block_ids or [f"b{number:04d}"],
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=estimated_minutes,
    )


def _action(
    cell_key: str,
    action: str,
    *,
    merge_into: str | None = None,
    reason: str = "هم‌پوشانی مفهومی.",
) -> ConsolidateActionDraft:
    return ConsolidateActionDraft(
        cell_key=cell_key,
        action=action,  # type: ignore[arg-type]
        merge_into=merge_into,
        reason=reason,
    )


def _draft(*actions: ConsolidateActionDraft) -> ConceptCellsConsolidateDraft:
    return ConceptCellsConsolidateDraft(actions=list(actions))


def _keep_all(cells: list[ConceptCell]) -> ConceptCellsConsolidateDraft:
    return _draft(*[_action(cell.cell_key, "keep", reason="متمایز است.") for cell in cells])


def _validate(
    draft: ConceptCellsConsolidateDraft,
    cells: list[ConceptCell],
    budget: int = 6,
) -> None:
    _validate_consolidate_draft(draft, cells, budget)


class TestUnknownAndMissingKeys:
    def test_unknown_cell_key_is_rejected(self) -> None:
        cells = [_cell("ch00-c001"), _cell("ch00-c002")]
        draft = _draft(
            _action("ch00-c001", "keep"),
            _action("ch00-c002", "keep"),
            _action("ch00-c099", "remove"),
        )
        with pytest.raises(DeterministicValidationError, match="Unknown cell_key"):
            _validate(draft, cells)

    def test_missing_action_is_rejected(self) -> None:
        cells = [_cell("ch00-c001"), _cell("ch00-c002")]
        draft = _draft(_action("ch00-c001", "keep"))
        with pytest.raises(DeterministicValidationError, match="missing"):
            _validate(draft, cells)

    def test_duplicate_action_for_same_key_is_rejected(self) -> None:
        cells = [_cell("ch00-c001"), _cell("ch00-c002")]
        draft = _draft(
            _action("ch00-c001", "keep"),
            _action("ch00-c001", "remove"),
            _action("ch00-c002", "keep"),
        )
        with pytest.raises(DeterministicValidationError, match="Duplicate actions"):
            _validate(draft, cells)


class TestMergeIntoMustBeKeep:
    def test_merge_into_a_merge_cell_is_rejected(self) -> None:
        cells = [_cell("ch00-c001"), _cell("ch00-c002"), _cell("ch00-c003")]
        draft = _draft(
            _action("ch00-c001", "keep"),
            _action("ch00-c002", "merge", merge_into="ch00-c001"),
            _action("ch00-c003", "merge", merge_into="ch00-c002"),
        )
        with pytest.raises(DeterministicValidationError, match="must be a keep"):
            _validate(draft, cells)

    def test_merge_into_a_removed_cell_is_rejected(self) -> None:
        cells = [_cell("ch00-c001"), _cell("ch00-c002")]
        draft = _draft(
            _action("ch00-c001", "remove"),
            _action("ch00-c002", "merge", merge_into="ch00-c001"),
        )
        with pytest.raises(DeterministicValidationError, match="must be a keep"):
            _validate(draft, cells)

    def test_merge_without_merge_into_is_rejected(self) -> None:
        cells = [_cell("ch00-c001"), _cell("ch00-c002")]
        draft = _draft(
            _action("ch00-c001", "keep"),
            _action("ch00-c002", "merge"),
        )
        with pytest.raises(DeterministicValidationError, match="requires merge_into"):
            _validate(draft, cells)

    def test_self_merge_is_rejected(self) -> None:
        cells = [_cell("ch00-c001"), _cell("ch00-c002")]
        draft = _draft(
            _action("ch00-c001", "keep"),
            _action("ch00-c002", "merge", merge_into="ch00-c002"),
        )
        with pytest.raises(DeterministicValidationError, match="cannot merge into itself"):
            _validate(draft, cells)

    def test_merge_into_unknown_key_is_rejected(self) -> None:
        cells = [_cell("ch00-c001"), _cell("ch00-c002")]
        draft = _draft(
            _action("ch00-c001", "keep"),
            _action("ch00-c002", "merge", merge_into="ch00-c099"),
        )
        with pytest.raises(DeterministicValidationError, match="not a cell"):
            _validate(draft, cells)

    def test_keep_must_not_set_merge_into(self) -> None:
        cells = [_cell("ch00-c001"), _cell("ch00-c002")]
        draft = _draft(
            _action("ch00-c001", "keep", merge_into="ch00-c002"),
            _action("ch00-c002", "keep"),
        )
        with pytest.raises(DeterministicValidationError, match="must not set merge_into"):
            _validate(draft, cells)


class TestSectionCoverage:
    def test_removing_a_sections_last_cell_is_rejected(self) -> None:
        cells = [
            _cell("ch00-c001", section_ids=["s001"], block_ids=["b0001"]),
            _cell("ch00-c002", section_ids=["s002"], block_ids=["b0002"]),
        ]
        draft = _draft(
            _action("ch00-c001", "keep"),
            _action("ch00-c002", "remove"),
        )
        with pytest.raises(DeterministicValidationError, match="lose its last cell"):
            _validate(draft, cells)

    def test_merge_preserves_the_absorbed_cells_section(self) -> None:
        cells = [
            _cell("ch00-c001", section_ids=["s001"], block_ids=["b0001"]),
            _cell("ch00-c002", section_ids=["s002"], block_ids=["b0002"]),
        ]
        draft = _draft(
            _action("ch00-c001", "keep"),
            _action("ch00-c002", "merge", merge_into="ch00-c001"),
        )
        _validate(draft, cells, budget=1)
        applied = _apply_consolidate_actions(cells, draft)
        assert [cell.cell_key for cell in applied] == ["ch00-c001"]
        assert applied[0].section_ids == ["s001", "s002"]

    def test_remove_is_allowed_when_another_cell_covers_the_section(self) -> None:
        cells = [
            _cell("ch00-c001", section_ids=["s001"], block_ids=["b0001"]),
            _cell("ch00-c002", section_ids=["s001"], block_ids=["b0002"]),
        ]
        draft = _draft(
            _action("ch00-c001", "keep"),
            _action("ch00-c002", "remove"),
        )
        _validate(draft, cells, budget=1)


class TestCountCap:
    def test_keeping_more_than_budget_is_rejected(self) -> None:
        cells = [_cell(f"ch00-c{n:03d}") for n in range(1, 5)]
        with pytest.raises(DeterministicValidationError, match="budget 2"):
            _validate(_keep_all(cells), cells, budget=2)

    def test_merge_down_to_budget_is_accepted(self) -> None:
        cells = [_cell(f"ch00-c{n:03d}") for n in range(1, 4)]
        draft = _draft(
            _action("ch00-c001", "keep"),
            _action("ch00-c002", "keep"),
            _action("ch00-c003", "merge", merge_into="ch00-c001"),
        )
        _validate(draft, cells, budget=2)


class TestApplyUnionsAndLowerTier:
    def test_merge_unions_blocks_and_keeps_the_lower_tier(self) -> None:
        cells = [
            _cell("ch00-c001", tier=3, section_ids=["s001"], block_ids=["b0001"]),
            _cell("ch00-c002", tier=1, section_ids=["s002"], block_ids=["b0002"]),
        ]
        draft = _draft(
            _action("ch00-c001", "keep"),
            _action("ch00-c002", "merge", merge_into="ch00-c001"),
        )
        applied = _apply_consolidate_actions(cells, draft)
        assert len(applied) == 1
        kept = applied[0]
        assert kept.cell_key == "ch00-c001"
        assert kept.tier == 1
        assert kept.block_ids == ["b0001", "b0002"]
        assert kept.section_ids == ["s001", "s002"]

    def test_keep_order_follows_the_original_cell_order(self) -> None:
        cells = [
            _cell("ch00-c001"),
            _cell("ch00-c002"),
            _cell("ch00-c003"),
        ]
        draft = _draft(
            _action("ch00-c003", "keep"),
            _action("ch00-c001", "keep"),
            _action("ch00-c002", "remove"),
        )
        applied = _apply_consolidate_actions(cells, draft)
        assert [cell.cell_key for cell in applied] == ["ch00-c001", "ch00-c003"]


class TestConsolidateChapter:
    def test_skips_the_model_when_count_is_at_or_under_budget(self, tmp_path) -> None:
        cells = [_cell("ch00-c001"), _cell("ch00-c002")]

        class ForbiddenModel:
            provider = "fake"

            def generate_structured(self, **_kwargs):
                raise AssertionError("Pass 3 must not call the model at or under budget.")

        runner = ModelRunner(
            ForbiddenModel(),
            PromptLoader(),
            WorkspaceModelRunStore(tmp_path / "workspaces"),
            sleeper=lambda _: None,
        )
        result = consolidate_chapter(
            cells,
            budget=6,
            model_runner=runner,
            project_id=uuid4(),
            model="fake-fast",
            chapter_title="فصل یکم",
        )
        assert result.skipped is True
        assert result.record is None
        assert [cell.cell_key for cell in result.cells] == ["ch00-c001", "ch00-c002"]

    def test_applies_a_valid_merge_and_sends_metadata_only(self, tmp_path) -> None:
        cells = [
            _cell(
                "ch00-c001",
                label_fa="تعریف ارزش مبادله",
                tier=2,
                section_ids=["s001"],
                block_ids=["b0001"],
            ),
            _cell(
                "ch00-c002",
                label_fa="تعریف ارزش مبادله در حاشیه",
                tier=3,
                section_ids=["s002"],
                block_ids=["b0002"],
            ),
            _cell("ch00-c003", label_fa="موضع نویسنده", section_ids=["s003"]),
        ]
        output = _draft(
            _action("ch00-c001", "keep", reason="مفهوم اصلی فصل است."),
            _action(
                "ch00-c002",
                "merge",
                merge_into="ch00-c001",
                reason="همان تعریف با برچسب نزدیک است.",
            ),
            _action("ch00-c003", "keep", reason="موضع جداگانه‌ای است."),
        )
        secret_block = "verbatim source paragraph that must not reach consolidate"

        class FakeConsolidateModel:
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

        model = FakeConsolidateModel()
        runner = ModelRunner(
            model,
            PromptLoader(),
            WorkspaceModelRunStore(tmp_path / "workspaces"),
            sleeper=lambda _: None,
        )
        result = consolidate_chapter(
            cells,
            budget=2,
            model_runner=runner,
            project_id=uuid4(),
            model="fake-fast",
            chapter_title="فصل یکم",
            section_titles={"s001": "ارزش", "s002": "حاشیه", "s003": "موضع"},
        )
        assert result.skipped is False
        assert [cell.cell_key for cell in result.cells] == ["ch00-c001", "ch00-c003"]
        kept = result.cells[0]
        assert kept.tier == 2
        assert kept.block_ids == ["b0001", "b0002"]
        assert kept.section_ids == ["s001", "s002"]
        prompt = model.prompts[0]
        assert "فصل یکم" in prompt
        assert "ch00-c001" in prompt
        assert "تعریف ارزش مبادله" in prompt
        assert "ارزش" in prompt
        assert secret_block not in prompt
        assert "b0001" not in prompt
        assert any("ch00-c002" in warning for warning in result.warnings)
        assert result.record is not None
        assert result.record.prompt_id == "concept_cells_consolidate"
        assert result.record.prompt_version == "1.0.0"
