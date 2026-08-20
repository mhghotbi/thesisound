from uuid import uuid4

import pytest

from thesisound.concepts import ConceptCell, ConceptEdgeDraft, ConceptEdgesDraft, SourceChapter
from thesisound.modeling import DeterministicValidationError, ModelUsage, StructuredModelResponse
from thesisound.prompt_loader import PromptLoader
from thesisound.services.concept_map_builder import (
    _validate_edges,
    build_cross_chapter_edges,
    build_edges_for_chapter,
    chapter_edge_cap,
    iter_chapter_pairs_within_window,
)
from thesisound.services.model_run_store import WorkspaceModelRunStore
from thesisound.services.model_runner import ModelRunner


def _cell(
    cell_key: str,
    *,
    chapter_index: int | None = None,
    label_fa: str | None = None,
) -> ConceptCell:
    number = int(cell_key.split("-c")[1])
    chapter = int(cell_key[2:4]) if chapter_index is None else chapter_index
    return ConceptCell(
        cell_key=cell_key,
        label_fa=label_fa or f"مفهوم {number}",
        label_source=None,
        kind="definition",
        tier=2,
        chapter_index=chapter,
        section_ids=[f"s{number:03d}"],
        block_ids=[f"b{number:04d}"],
        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
        estimated_minutes=5.0,
    )


def _edge_draft(
    source_key: str,
    target_key: str,
    *,
    type: str = "prerequisite",
    weight: float = 0.8,
    confidence: float = 0.9,
    rationale_fa: str = "رابطه در منبع آمده است.",
) -> ConceptEdgeDraft:
    return ConceptEdgeDraft(
        source_key=source_key,
        target_key=target_key,
        type=type,  # type: ignore[arg-type]
        weight=weight,
        confidence=confidence,
        rationale_fa=rationale_fa,
    )


def _draft(*edges: ConceptEdgeDraft) -> ConceptEdgesDraft:
    return ConceptEdgesDraft(edges=list(edges), warnings=[])


def _validate(
    draft: ConceptEdgesDraft,
    *,
    keys: set[str] | None = None,
    cap: int = 60,
    attempt: int = 1,
    max_attempts: int = 2,
    chapter_by_key: dict[str, int] | None = None,
    require_cross_chapter: bool = False,
) -> None:
    if keys is None:
        keys = {edge.source_key for edge in draft.edges} | {edge.target_key for edge in draft.edges}
    _validate_edges(
        draft,
        known_keys=keys,
        cap=cap,
        attempt=attempt,
        max_attempts=max_attempts,
        chapter_by_key=chapter_by_key,
        require_cross_chapter=require_cross_chapter,
    )


def _chapter(index: int, title: str = "") -> SourceChapter:
    return SourceChapter(
        chapter_index=index,
        title=title or f"فصل {index}",
        heading_path=[title or f"فصل {index}"],
        block_ids=[f"b{index:04d}"],
        estimated_minutes=10.0,
        detected_from="heading",
        detection_agreement="agreed",
    )


class TestUnknownKeysAndSelfLoops:
    def test_unknown_key_is_rejected(self) -> None:
        draft = _draft(_edge_draft("ch00-c001", "ch00-c099"))
        with pytest.raises(DeterministicValidationError, match="Unknown cell keys"):
            _validate(draft, keys={"ch00-c001", "ch00-c002"})

    def test_self_loop_is_rejected(self) -> None:
        draft = _draft(_edge_draft("ch00-c001", "ch00-c001"))
        with pytest.raises(DeterministicValidationError, match="Self-loop"):
            _validate(draft, keys={"ch00-c001"})


class TestDedup:
    def test_duplicate_src_dst_type_keeps_the_stronger_edge(self) -> None:
        draft = _draft(
            _edge_draft("ch00-c001", "ch00-c002", type="related", weight=0.3, confidence=0.4),
            _edge_draft("ch00-c001", "ch00-c002", type="related", weight=0.8, confidence=0.9),
            _edge_draft("ch00-c001", "ch00-c002", type="prerequisite", weight=0.7),
        )
        _validate(draft, keys={"ch00-c001", "ch00-c002"})
        kept = {(edge.source_key, edge.target_key, edge.type, edge.weight) for edge in draft.edges}
        assert kept == {
            ("ch00-c001", "ch00-c002", "related", 0.8),
            ("ch00-c001", "ch00-c002", "prerequisite", 0.7),
        }
        assert any("duplicate" in warning for warning in draft.warnings)


class TestCycleDetection:
    def test_two_cycle_errors_on_early_attempt(self) -> None:
        draft = _draft(
            _edge_draft("ch00-c001", "ch00-c002", weight=0.9),
            _edge_draft("ch00-c002", "ch00-c001", weight=0.2),
        )
        with pytest.raises(DeterministicValidationError, match="Cycle among prerequisite"):
            _validate(draft, attempt=1, max_attempts=2)

    def test_final_attempt_drops_lowest_weight_edge_and_warns(self) -> None:
        draft = _draft(
            _edge_draft("ch00-c001", "ch00-c002", weight=0.9),
            _edge_draft("ch00-c002", "ch00-c001", weight=0.2),
        )
        _validate(draft, attempt=2, max_attempts=2)
        assert [(edge.source_key, edge.target_key) for edge in draft.edges] == [
            ("ch00-c001", "ch00-c002")
        ]
        assert any(
            "break cycle" in warning and "ch00-c002→ch00-c001" in warning
            for warning in draft.warnings
        )

    def test_three_cycle_is_repaired_on_final_attempt(self) -> None:
        draft = _draft(
            _edge_draft("ch00-c001", "ch00-c002", weight=0.9),
            _edge_draft("ch00-c002", "ch00-c003", weight=0.8),
            _edge_draft("ch00-c003", "ch00-c001", weight=0.1),
        )
        _validate(draft, attempt=2, max_attempts=2)
        pairs = {(edge.source_key, edge.target_key) for edge in draft.edges}
        assert ("ch00-c003", "ch00-c001") not in pairs
        assert len(pairs) == 2

    def test_related_edges_do_not_count_as_a_cycle(self) -> None:
        draft = _draft(
            _edge_draft("ch00-c001", "ch00-c002", type="related", weight=0.5),
            _edge_draft("ch00-c002", "ch00-c001", type="prerequisite", weight=0.8),
        )
        _validate(draft, attempt=1, max_attempts=2)
        assert len(draft.edges) == 2


class TestCap:
    def test_keeps_highest_weight_when_over_cap(self) -> None:
        draft = _draft(
            _edge_draft("ch00-c001", "ch00-c002", type="related", weight=0.2),
            _edge_draft("ch00-c001", "ch00-c003", type="related", weight=0.9),
            _edge_draft("ch00-c002", "ch00-c003", type="related", weight=0.5),
            _edge_draft("ch00-c003", "ch00-c001", type="contrasts", weight=0.7),
        )
        _validate(draft, keys={"ch00-c001", "ch00-c002", "ch00-c003"}, cap=2)
        weights = sorted(edge.weight for edge in draft.edges)
        assert weights == [0.7, 0.9]
        assert any("cap 2" in warning for warning in draft.warnings)

    def test_intra_chapter_cap_is_min_of_twice_n_and_sixty(self) -> None:
        assert chapter_edge_cap(3) == 6
        assert chapter_edge_cap(40) == 60
        assert chapter_edge_cap(0) == 0


class TestClamp:
    def test_weight_and_confidence_are_clamped_to_unit_interval(self) -> None:
        edge = ConceptEdgeDraft.model_construct(
            source_key="ch00-c001",
            target_key="ch00-c002",
            type="related",
            weight=1.4,
            confidence=-0.2,
            rationale_fa="نرمال‌سازی وزن.",
        )
        draft = _draft(edge)
        _validate(draft, keys={"ch00-c001", "ch00-c002"})
        assert draft.edges[0].weight == 1.0
        assert draft.edges[0].confidence == 0.0


class TestCrossChapterFilter:
    def test_intra_chapter_edges_are_dropped_from_a_cross_chapter_call(self) -> None:
        draft = _draft(
            _edge_draft("ch00-c001", "ch01-c001", type="related", weight=0.6),
            _edge_draft("ch00-c001", "ch00-c002", type="related", weight=0.9),
        )
        _validate(
            draft,
            keys={"ch00-c001", "ch00-c002", "ch01-c001"},
            chapter_by_key={"ch00-c001": 0, "ch00-c002": 0, "ch01-c001": 1},
            require_cross_chapter=True,
        )
        assert [(edge.source_key, edge.target_key) for edge in draft.edges] == [
            ("ch00-c001", "ch01-c001")
        ]
        assert any("intra-chapter" in warning for warning in draft.warnings)


class TestWindow:
    def test_pairs_cover_distance_one_and_two(self) -> None:
        chapters = [_chapter(i) for i in range(4)]
        pairs = [
            (left.chapter_index, right.chapter_index)
            for left, right in iter_chapter_pairs_within_window(chapters)
        ]
        assert pairs == [(0, 1), (0, 2), (1, 2), (1, 3), (2, 3)]


class TestBuildEdgesForChapter:
    def test_skips_the_model_when_fewer_than_two_cells(self, tmp_path) -> None:
        class ForbiddenModel:
            provider = "fake"

            def generate_structured(self, **_kwargs):
                raise AssertionError("Pass 4 must not run with fewer than two cells.")

        runner = ModelRunner(
            ForbiddenModel(),
            PromptLoader(),
            WorkspaceModelRunStore(tmp_path / "workspaces"),
            sleeper=lambda _: None,
        )
        result = build_edges_for_chapter(
            [_cell("ch00-c001")],
            model_runner=runner,
            project_id=uuid4(),
            model="fake-fast",
            chapter_title="فصل یکم",
        )
        assert result.skipped is True
        assert result.edges == ()
        assert result.record is None

    def test_sends_metadata_only_and_returns_validated_edges(self, tmp_path) -> None:
        cells = [_cell("ch00-c001"), _cell("ch00-c002"), _cell("ch00-c003")]
        output = _draft(
            _edge_draft("ch00-c001", "ch00-c002", weight=0.9),
            _edge_draft("ch00-c002", "ch00-c003", type="related", weight=0.4),
        )
        secret = "verbatim source paragraph that must not reach the edge prompt"

        class FakeEdgesModel:
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

        model = FakeEdgesModel()
        runner = ModelRunner(
            model,
            PromptLoader(),
            WorkspaceModelRunStore(tmp_path / "workspaces"),
            sleeper=lambda _: None,
        )
        result = build_edges_for_chapter(
            cells,
            model_runner=runner,
            project_id=uuid4(),
            model="fake-fast",
            chapter_title="فصل یکم",
            section_titles={"s001": "تعریف", "s002": "ادامه"},
        )
        assert result.skipped is False
        assert [edge.source_key for edge in result.edges] == ["ch00-c001", "ch00-c002"]
        assert all(edge.is_cross_chapter is False for edge in result.edges)
        prompt = model.prompts[0]
        assert "chapter 0: فصل یکم" in prompt
        assert "ch00-c001" in prompt
        assert "تعریف" in prompt
        assert secret not in prompt
        assert "b0001" not in prompt
        assert result.record is not None
        assert result.record.prompt_id == "concept_edges"
        assert result.record.prompt_version == "1.0.0"

    def test_cross_chapter_call_asks_only_for_crossing_edges(self, tmp_path) -> None:
        cells_a = [_cell("ch00-c001"), _cell("ch00-c002")]
        cells_b = [_cell("ch01-c001")]
        output = _draft(
            _edge_draft("ch00-c001", "ch01-c001", type="extends", weight=0.7),
            _edge_draft("ch00-c001", "ch00-c002", type="related", weight=0.9),
        )

        class FakeEdgesModel:
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

        model = FakeEdgesModel()
        runner = ModelRunner(
            model,
            PromptLoader(),
            WorkspaceModelRunStore(tmp_path / "workspaces"),
            sleeper=lambda _: None,
        )
        result = build_cross_chapter_edges(
            cells_a,
            cells_b,
            10,
            model_runner=runner,
            project_id=uuid4(),
            model="fake-fast",
        )
        assert len(result.edges) == 1
        assert result.edges[0].source_key == "ch00-c001"
        assert result.edges[0].target_key == "ch01-c001"
        assert result.edges[0].is_cross_chapter is True
        prompt = model.prompts[0]
        assert "chapters 0 and 1" in prompt
        assert "Return only edges that cross the two chapters" in prompt
        assert result.record is not None
        assert result.record.stage == "concept_edges:ch00-ch01"
