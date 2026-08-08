from __future__ import annotations

import json
from pathlib import Path

from thesisound.services.mineru_normalizer import normalize_mineru_output


def test_middle_json_excludes_metadata_from_text(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    payload = {
        "pdf_info": [
            {
                "page_idx": 0,
                "para_blocks": [
                    {
                        "type": "text",
                        "bbox": [0, 0, 100, 100],
                        "lines": [
                            {
                                "bbox": [0, 0, 100, 20],
                                "spans": [
                                    {
                                        "type": "text",
                                        "content": "Actual sentence",
                                        "score": 0.99,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    (output / "paper_middle.json").write_text(json.dumps(payload), encoding="utf-8")

    parsed = normalize_mineru_output(
        output,
        source_path=Path("paper.pdf"),
        parser_version="test",
    )

    assert len(parsed.blocks) == 1
    assert parsed.blocks[0].text == "Actual sentence"
    assert parsed.blocks[0].page_start == 1


def test_content_list_v2_preserves_heading_levels_and_pages(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    payload = [
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "Chapter One"}],
                    "level": 1,
                },
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {"type": "text", "content": "Opening paragraph"}
                    ]
                },
            },
        ],
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "A Subsection"}],
                    "level": 2,
                },
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {"type": "text", "content": "Detailed paragraph"}
                    ]
                },
            },
        ],
    ]
    (output / "paper_content_list_v2.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    parsed = normalize_mineru_output(
        output,
        source_path=Path("paper.pdf"),
        parser_version="test",
    )

    assert [block.text for block in parsed.blocks] == [
        "Chapter One",
        "Opening paragraph",
        "A Subsection",
        "Detailed paragraph",
    ]
    assert parsed.blocks[1].heading_path == ["Chapter One"]
    assert parsed.blocks[3].heading_path == ["Chapter One", "A Subsection"]
    assert parsed.blocks[3].page_start == 2
