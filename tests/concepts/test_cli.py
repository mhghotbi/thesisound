from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from thesisound.cli_with_audio import app
from thesisound.concepts import (
    ConceptCellDraft,
    ConceptCellsConsolidateDraft,
    ConceptCellsDraft,
    ConceptEdgeDraft,
    ConceptEdgesDraft,
    ConsolidateActionDraft,
)
from thesisound.modeling import ModelUsage, StructuredModelResponse
from thesisound.services.concept_map_pipeline import parse_chapter_selector
from thesisound.source_analysis import (
    DocumentMapDraft,
    DocumentMapDraftSection,
    DocumentMapMergeDraft,
)

runner = CliRunner()
_TAG = re.compile(r"<(?P<name>[A-Z0-9_]+)>\s*(?P<body>.*?)\s*</(?P=name)>", re.DOTALL)


def test_parse_chapter_selector_one_based() -> None:
    assert parse_chapter_selector("1,3") == (0, 2)
    assert parse_chapter_selector(None) is None
    assert parse_chapter_selector("  ") is None


def test_parse_chapter_selector_rejects_zero() -> None:
    try:
        parse_chapter_selector("0,1")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


class CombinedFakeModel:
    """Fake model covering document-map and concept-map prompts for CLI smoke."""

    provider = "fake"

    def generate_structured(self, **kwargs):
        output_type = kwargs["output_type"]
        user_prompt = kwargs["user_prompt"]
        if output_type is DocumentMapDraft:
            blocks = _json_tag(user_prompt, "SEMANTIC_BLOCKS_JSON")
            block_ids = [item["block_id"] for item in blocks]
            output = DocumentMapDraft(
                sections=[
                    DocumentMapDraftSection(
                        section_id="section-1",
                        source_block_ids=block_ids,
                        title="Mapped partition",
                        function="argument",
                    )
                ]
            )
        elif output_type is DocumentMapMergeDraft:
            output = DocumentMapMergeDraft()
        elif output_type is ConceptCellsDraft:
            sections = _json_tag(user_prompt, "SECTIONS_JSON")
            kinds = (
                "definition",
                "argument",
                "distinction",
                "example",
                "position",
                "objection",
            )
            cells = []
            for index, section in enumerate(sections):
                block_ids = section.get("source_block_ids") or []
                if not block_ids:
                    continue
                cells.append(
                    ConceptCellDraft(
                        label_fa=f"مفهوم مستقل {section['section_id']} {index}",
                        kind=kinds[index % len(kinds)],
                        tier=(index % 3) + 1,
                        section_ids=[section["section_id"]],
                        block_ids=[block_ids[0]],
                        granularity_rationale="یک واحد مستقل و قابل ردیابی است.",
                        estimated_minutes=5.0,
                    )
                )
            output = ConceptCellsDraft(cells=cells)
        elif output_type is ConceptCellsConsolidateDraft:
            cells = _json_tag(user_prompt, "CELLS_JSON")
            output = ConceptCellsConsolidateDraft(
                actions=[
                    ConsolidateActionDraft(
                        cell_key=item["cell_key"],
                        action="keep",
                        reason="در بودجه می‌گنجد.",
                    )
                    for item in cells
                ]
            )
        elif output_type is ConceptEdgesDraft:
            cells = _json_tag(user_prompt, "CELLS_JSON")
            edges = []
            if len(cells) >= 2:
                edges.append(
                    ConceptEdgeDraft(
                        source_key=cells[0]["cell_key"],
                        target_key=cells[1]["cell_key"],
                        type="related",
                        weight=0.7,
                        confidence=0.8,
                        rationale_fa="هر دو در یک بحث آمده‌اند.",
                    )
                )
            output = ConceptEdgesDraft(edges=edges)
        else:
            raise AssertionError(f"unexpected output type {output_type}")
        return StructuredModelResponse(
            output=output,
            provider="fake",
            model="fake-fast",
            usage=ModelUsage(),
            latency_ms=1,
            finish_reason="STOP",
        )


def _json_tag(prompt: str, name: str):
    match = _TAG.search(prompt)
    while match:
        if match.group("name") == name:
            return json.loads(match.group("body"))
        match = _TAG.search(prompt, match.end())
    raise AssertionError(f"missing tag {name}")


def _markdown_source() -> str:
    parts: list[str] = []
    for title, tag in (("فصل یک", "one"), ("فصل دو", "two")):
        parts.append(f"# {title}")
        parts.append("")
        for index in range(4):
            unique = " ".join(f"{tag}{index}w{n}" for n in range(90))
            parts.append(
                f"در {title} بند {index} استدلال مستقلی می‌آید. {unique}"
            )
            parts.append("")
    return "\n".join(parts)


def test_concept_map_cli_help() -> None:
    result = runner.invoke(app, ["concept-map", "--help"])
    assert result.exit_code == 0
    assert "--chapters" in result.output
    assert "--rebuild" in result.output
    assert "--json" in result.output


def test_concept_map_cli_smoke_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "thesisound.services.concept_map_pipeline.structured_model_from_settings",
        lambda _settings: CombinedFakeModel(),
    )
    source = tmp_path / "book.md"
    source.write_text(_markdown_source(), encoding="utf-8")
    workspace = tmp_path / "workspaces"
    result = runner.invoke(
        app,
        [
            "concept-map",
            str(source),
            "--json",
            "--workspace-root",
            str(workspace),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["chapters"]
    assert "detection_agreement" in payload["chapters"][0]
    assert "cells_per_tier" in payload
    assert "estimated_tokens" in payload
    assert payload["estimated_tokens"]["map"] >= 0
    assert payload["estimated_tokens"]["cells"] >= payload["estimated_tokens"]["map"]
    assert payload["statistics"]["cell_count"] >= 1
