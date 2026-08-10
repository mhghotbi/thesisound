from __future__ import annotations

import json
from pathlib import Path

import pytest

from thesisound.prompt_loader import (
    _TOKEN,
    PromptLoader,
    PromptRenderError,
    _placeholder_name,
)

KNOWN_UNRENDERABLE = {("document_map_merge", "1.0.0")}


def _write_prompt(tmp_path: Path, user_template: str) -> tuple[PromptLoader, Path]:
    version_dir = tmp_path / "example" / "1.0.0"
    version_dir.mkdir(parents=True)
    (version_dir / "contract.json").write_text(
        json.dumps(
            {
                "id": "example",
                "version": "1.0.0",
                "model_tier": "fast",
                "output_model": "Example",
                "max_attempts": 2,
                "retry_schema_errors": True,
                "system_file": "system.md",
                "user_file": "user.md",
            }
        ),
        encoding="utf-8",
    )
    (version_dir / "system.md").write_text("System prompt", encoding="utf-8")
    user_path = version_dir / "user.md"
    user_path.write_text(user_template, encoding="utf-8")
    return PromptLoader(tmp_path), user_path


def test_every_shipped_prompt_uses_only_supported_placeholders() -> None:
    prompt_root = PromptLoader().prompt_root
    templates = sorted(prompt_root.glob("*/*/system.md")) + sorted(
        prompt_root.glob("*/*/user.md")
    )
    assert len(templates) >= 20
    for path in templates:
        prompt_version = (path.parent.parent.name, path.parent.name)
        for match in _TOKEN.finditer(path.read_text(encoding="utf-8")):
            if prompt_version not in KNOWN_UNRENDERABLE:
                assert _placeholder_name(match.group(1)) is not None, (
                    path,
                    match.group(0),
                )


def test_known_unrenderable_prompt_version_fails_loudly() -> None:
    with pytest.raises(PromptRenderError) as exc_info:
        PromptLoader().load_bundle(
            "document_map_merge",
            {"source_id": "source", "partition_count": 1, "partitions": []},
            version="1.0.0",
        )
    assert "| tojson" in str(exc_info.value)


def test_render_rejects_filter_syntax(tmp_path: Path) -> None:
    loader, user_path = _write_prompt(tmp_path, "{{ items | tojson }}")
    with pytest.raises(PromptRenderError) as exc_info:
        loader.load_bundle("example", {"items": []})
    message = str(exc_info.value)
    assert str(user_path) in message
    assert "{{ items | tojson }}" in message


def test_render_reports_missing_variable_with_source_path(tmp_path: Path) -> None:
    loader, user_path = _write_prompt(tmp_path, "{{ present }} {{ absent }}")
    with pytest.raises(PromptRenderError) as exc_info:
        loader.load_bundle("example", {"present": "x"})
    message = str(exc_info.value)
    assert "absent" in message
    assert str(user_path) in message
    assert "system.md" not in message


def test_render_rejects_unclosed_placeholder(tmp_path: Path) -> None:
    loader, _ = _write_prompt(tmp_path, "{{ name")
    with pytest.raises(PromptRenderError, match="unclosed"):
        loader.load_bundle("example", {"name": "x"})


def test_placeholder_syntax_inside_a_variable_value_is_data(tmp_path: Path) -> None:
    loader, _ = _write_prompt(tmp_path, "{{ blocks }}")
    bundle = loader.load_bundle(
        "example",
        {"blocks": [{"text": "a template uses {{ name }} for substitution"}]},
    )
    assert "{{ name }}" in bundle.user_prompt


def test_non_string_values_are_json_encoded_without_escaping_persian(tmp_path: Path) -> None:
    loader, _ = _write_prompt(tmp_path, "{{ payload }}")
    bundle = loader.load_bundle("example", {"payload": {"b": 2, "a": "کار"}})
    assert '"کار"' in bundle.user_prompt
    assert bundle.user_prompt.index('"a"') < bundle.user_prompt.index('"b"')
