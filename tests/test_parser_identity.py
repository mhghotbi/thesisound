from __future__ import annotations

import types

from thesisound.adapters.parsers.docling_adapter import DoclingParser
from thesisound.adapters.parsers.epub_adapter import EpubDocumentParser
from thesisound.adapters.parsers.local_ocr_adapter import LocalOcrParser
from thesisound.adapters.parsers.mineru_adapter import MineruParser
from thesisound.adapters.parsers.native_adapter import NativeDocumentParser
from thesisound.services import document_identity, parser_identity
from thesisound.services.parser_identity import module_fingerprint, package_version


def test_module_fingerprint_is_stable_across_calls() -> None:
    first = module_fingerprint(parser_identity)
    second = module_fingerprint(parser_identity)

    assert first == second
    assert first is not None
    assert len(first) == 64


def test_module_fingerprint_differs_for_a_different_module() -> None:
    this_module = module_fingerprint(parser_identity)
    other_module = module_fingerprint(document_identity)

    assert this_module != other_module


def test_module_fingerprint_is_none_when_a_module_has_no_file() -> None:
    synthetic = types.ModuleType("thesisound-test-synthetic-module")

    assert module_fingerprint(synthetic) is None


def test_package_version_reports_absent_for_an_uninstalled_name() -> None:
    assert package_version("definitely-not-a-real-package-xyz") == "absent"


def test_native_parser_identity_is_a_flat_string_mapping() -> None:
    identity = NativeDocumentParser().identity()

    assert identity is not None
    assert identity["parser"] == "native"
    assert all(isinstance(value, str) for value in identity.values())


def test_epub_parser_identity_is_a_flat_string_mapping() -> None:
    identity = EpubDocumentParser().identity()

    assert identity is not None
    assert identity["parser"] == "epub"
    assert all(isinstance(value, str) for value in identity.values())


def test_mineru_identity_is_none_when_a_runner_is_injected() -> None:
    parser = MineruParser(runner=lambda *_: None)

    assert parser.identity() is None


def test_mineru_identity_is_none_when_a_version_resolver_is_injected() -> None:
    parser = MineruParser(version_resolver=lambda: "3.test")

    assert parser.identity() is None


def test_mineru_identity_is_none_when_the_cli_version_is_unresolvable() -> None:
    parser = MineruParser(command="thesisound-test-nonexistent-mineru-binary")

    assert parser.identity() is None


def test_docling_identity_is_none_when_a_converter_factory_is_injected() -> None:
    parser = DoclingParser(converter_factory=lambda: object())

    assert parser.identity() is None


def test_docling_identity_is_none_when_a_version_resolver_is_injected() -> None:
    parser = DoclingParser(version_resolver=lambda: "2.test")

    assert parser.identity() is None


def test_local_ocr_identity_is_none_when_a_runner_is_injected() -> None:
    parser = LocalOcrParser(runner=lambda *_: None)

    assert parser.identity() is None
