from __future__ import annotations

from pathlib import Path

import pytest

from thesisound.ports import DocumentInspection, ParsedBlock, ParsedDocument
from thesisound.services.parsed_document_cache import ParsedDocumentCache, parse_cache_key


def _inspection(**overrides: object) -> DocumentInspection:
    values: dict[str, object] = dict(
        path=Path("sample.pdf"),
        mime_type="application/pdf",
        extension=".pdf",
        file_size_bytes=1000,
        sha256="a" * 64,
        page_count=2,
        encrypted=False,
        sampled_text_characters=500,
        image_only_ratio=0.0,
        likely_complex_layout=False,
    )
    values.update(overrides)
    return DocumentInspection(**values)


def _parsed_document(**overrides: object) -> ParsedDocument:
    values: dict[str, object] = dict(
        parser_name="native",
        parser_version="1",
        blocks=[
            ParsedBlock(source_block_key="p1", text="First paragraph.", kind="text"),
            ParsedBlock(source_block_key="p2", text="Second paragraph.", kind="text"),
        ],
        warnings=[],
    )
    values.update(overrides)
    return ParsedDocument(**values)


def test_parse_cache_key_differs_when_extension_differs() -> None:
    identity = {"parser": "native", "impl": "x"}
    pdf_key = parse_cache_key(
        _inspection(extension=".pdf"), parser_name="native", identity=identity
    )
    txt_key = parse_cache_key(
        _inspection(extension=".txt"), parser_name="native", identity=identity
    )

    assert pdf_key != txt_key


def test_parse_cache_key_differs_when_an_identity_value_differs() -> None:
    inspection = _inspection()

    first = parse_cache_key(inspection, parser_name="native", identity={"impl": "a"})
    second = parse_cache_key(inspection, parser_name="native", identity={"impl": "b"})

    assert first != second


def test_parse_cache_key_ignores_fields_no_parser_reads() -> None:
    """mime_type, page_count, image_only_ratio, file_size_bytes and
    sampled_text_characters all drift with the installed pypdf or the OS
    mimetypes registry, and no parser consults them -- they must not
    silently discard a cache entry."""

    identity = {"parser": "native", "impl": "x"}
    base = _inspection()
    drifted = _inspection(
        mime_type="text/plain",
        page_count=99,
        image_only_ratio=1.0,
        file_size_bytes=1,
        sampled_text_characters=0,
    )

    assert parse_cache_key(base, parser_name="native", identity=identity) == parse_cache_key(
        drifted, parser_name="native", identity=identity
    )


def test_parse_cache_key_is_stable_across_identity_dict_ordering() -> None:
    inspection = _inspection()

    first = parse_cache_key(inspection, parser_name="native", identity={"a": "1", "b": "2"})
    second = parse_cache_key(inspection, parser_name="native", identity={"b": "2", "a": "1"})

    assert first == second


def test_round_trip_preserves_blocks_and_drops_raw_artifact_ref(tmp_path: Path) -> None:
    cache = ParsedDocumentCache(tmp_path)
    parsed = _parsed_document(raw_artifact_ref="C:/other-project/artifacts/output.json")
    key = "a" * 64

    cache.save(key, parsed, source_sha256="b" * 64, identity={"parser": "native", "impl": "x"})
    loaded = cache.load(key, parser_name=parsed.parser_name)

    assert loaded is not None
    assert loaded.raw_artifact_ref is None
    assert loaded.parser_name == parsed.parser_name
    assert loaded.parser_version == parsed.parser_version
    assert [block.model_dump() for block in loaded.blocks] == [
        block.model_dump() for block in parsed.blocks
    ]
    assert loaded.warnings == parsed.warnings


def test_load_rejects_a_record_stored_under_a_different_parser_name(tmp_path: Path) -> None:
    cache = ParsedDocumentCache(tmp_path)
    parsed = _parsed_document(parser_name="docling")
    key = "a" * 64
    cache.save(key, parsed, source_sha256="b" * 64, identity={"parser": "docling"})

    assert cache.load(key, parser_name="mineru") is None
    assert cache.load(key, parser_name="docling") is not None


def test_load_returns_none_for_truncated_json(tmp_path: Path) -> None:
    cache = ParsedDocumentCache(tmp_path)
    key = "a" * 64
    cache.path(key).parent.mkdir(parents=True, exist_ok=True)
    cache.path(key).write_text("{not valid json", encoding="utf-8")

    assert cache.load(key, parser_name="native") is None


def test_load_rejects_a_record_whose_cache_key_field_disagrees_with_its_filename(
    tmp_path: Path,
) -> None:
    cache = ParsedDocumentCache(tmp_path)
    parsed = _parsed_document()
    key_a = "a" * 64
    key_b = "b" * 64
    cache.save(key_a, parsed, source_sha256="c" * 64, identity={"parser": "native"})
    content = cache.path(key_a).read_text(encoding="utf-8")
    cache.path(key_b).write_text(content, encoding="utf-8")

    assert cache.load(key_b, parser_name="native") is None


def test_save_with_no_blocks_writes_nothing(tmp_path: Path) -> None:
    cache = ParsedDocumentCache(tmp_path)
    empty = _parsed_document(blocks=[])
    key = "a" * 64

    result = cache.save(key, empty, source_sha256="b" * 64, identity={"parser": "native"})

    assert result is None
    assert not cache.path(key).exists()


def test_save_twice_is_idempotent_and_does_not_rewrite_the_record(tmp_path: Path) -> None:
    cache = ParsedDocumentCache(tmp_path)
    parsed = _parsed_document()
    key = "a" * 64

    first_path = cache.save(key, parsed, source_sha256="b" * 64, identity={"parser": "native"})
    assert first_path is not None
    first_bytes = first_path.read_bytes()

    second_path = cache.save(key, parsed, source_sha256="b" * 64, identity={"parser": "native"})

    assert second_path == first_path
    assert second_path.read_bytes() == first_bytes


def test_path_rejects_a_non_sha256_key(tmp_path: Path) -> None:
    cache = ParsedDocumentCache(tmp_path)

    with pytest.raises(ValueError, match="sha256"):
        cache.path("not-a-sha256-key")


def test_save_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    cache = ParsedDocumentCache(tmp_path)
    parsed = _parsed_document()
    key = "a" * 64

    cache.save(key, parsed, source_sha256="b" * 64, identity={"parser": "native"})

    leftovers = [path for path in cache.root.iterdir() if path.suffix == ".tmp"]
    assert leftovers == []
