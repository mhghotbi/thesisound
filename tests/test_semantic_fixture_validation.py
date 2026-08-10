from __future__ import annotations

import hashlib
import json
from pathlib import Path

from thesisound.services.excerpt_matching import normalize_for_match
from thesisound.services.semantic_fixture_validation import (
    canonicalize_semantic_text,
    validate_semantic_fixture,
)

_PERSIAN_SENTENCE = "این متنِ فارسی می‌تواند، با نشانه‌گذاری عادی، دقیقاً بازیابی شود."


def _collation_record(
    tmp_path: Path,
    artifact_id: str,
    *,
    fixture: Path,
    **overrides: object,
) -> Path:
    canonical, _ = canonicalize_semantic_text(fixture.read_text(encoding="utf-8"))
    normalized, _ = normalize_for_match(canonical)
    payload: dict[str, object] = {
        "artifact_id": artifact_id,
        "fixture_normalized_text_sha256": hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest(),
        "reviewer": "fluent Persian reader",
        "reviewed_on": "2026-08-11",
        "pages_checked": [1, 2, 3],
        "reading_order_correct": True,
        "footnote_and_margin_separation_correct": True,
        "script_rendering_correct": True,
        "zwnj_loss_meaning_preserving": True,
    }
    payload.update(overrides)
    path = tmp_path / f"{artifact_id}-collation.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_r13_accepts_clean_persian_fixture(tmp_path: Path) -> None:
    path = tmp_path / "clean-fa.txt"
    path.write_text("\n\n".join([_PERSIAN_SENTENCE] * 80), encoding="utf-8")

    report = validate_semantic_fixture(
        path,
        artifact_id="test-fa",
        expected_language="fa",
        intended_scope="complete test document",
        collation_record=_collation_record(tmp_path, "test-fa", fixture=path),
    )

    assert report.status == "pass"
    assert report.metrics["zwnj_count"] > 0
    assert report.metrics["arabic_presentation_forms_count"] == 0
    assert report.exact_span_matching["recovered_span_count"] == 20
    assert report.normalization_checks["zwnj_and_punctuation_compatible"] is True


def test_r13_rejects_presentation_forms_and_replacement_characters(tmp_path: Path) -> None:
    path = tmp_path / "broken-fa.txt"
    path.write_text(("ﻻﻼ� " * 400), encoding="utf-8")

    report = validate_semantic_fixture(
        path,
        artifact_id="test-broken-fa",
        expected_language="fa",
        intended_scope="complete test document",
        collation_record=_collation_record(tmp_path, "test-broken-fa", fixture=path),
    )

    assert report.status == "fail"
    failed = {gate["gate"] for gate in report.gates if gate["status"] == "fail"}
    assert "no_replacement_characters" in failed
    assert "presentation_forms_not_primary" in failed


def test_r13_report_is_stable_and_does_not_expose_absolute_path(tmp_path: Path) -> None:
    path = tmp_path / "clean-en.md"
    path.write_text(
        "Evidence can be recovered from this stable paragraph. " * 80,
        encoding="utf-8",
    )

    first = validate_semantic_fixture(
        path,
        artifact_id="test-en",
        expected_language="en",
        intended_scope="complete test document",
    )
    second = validate_semantic_fixture(
        path,
        artifact_id="test-en",
        expected_language="en",
        intended_scope="complete test document",
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.artifact_filename == "clean-en.md"
    assert str(tmp_path) not in first.model_dump_json()


def test_r13_classifies_but_does_not_ingest_isolated_private_use_marks(tmp_path: Path) -> None:
    """The C02 shape: a symbol-font footnote marker standing alone between spaces.

    It has no Unicode identity, but it is its own token, so dropping it cannot
    alter a word. R13 records that classification while failing parity until the
    artifact presented to production has actually been canonicalized.
    """

    body = "\n\n".join([_PERSIAN_SENTENCE] * 80)
    path = tmp_path / "marker-fa.txt"
    path.write_text(f"احمد عبادی  دانشیار فلسفه\n\n نویسنده مسئول\n\n{body}", encoding="utf-8")

    report = validate_semantic_fixture(
        path,
        artifact_id="test-marker-fa",
        expected_language="fa",
        intended_scope="complete test document",
        collation_record=_collation_record(
            tmp_path,
            "test-marker-fa",
            fixture=path,
        ),
    )

    assert report.status == "fail"
    assert report.metrics["private_use_character_count"] == 2
    assert report.metrics["residual_private_use_character_count"] == 0
    assert report.canonicalization["dropped_character_count"] == 2
    assert report.canonicalization["word_sequence_preserved"] is True
    assert report.canonicalization["canonicalization_required_before_ingestion"] is True
    dropped = report.canonicalization["dropped_code_points"]
    assert {entry["code_point"].split()[0] for entry in dropped} == {"U+F02A", "U+F0AF"}
    assert report.production_text_parity["result"] == "fail"


def test_r13_canonicalized_derivative_has_production_parity(tmp_path: Path) -> None:
    body = "\n\n".join([_PERSIAN_SENTENCE] * 80)
    raw = f"احمد عبادی  دانشیار فلسفه\n\n نویسنده مسئول\n\n{body}"
    canonical, canonicalization = canonicalize_semantic_text(raw)
    path = tmp_path / "canonical-fa.txt"
    path.write_text(canonical, encoding="utf-8")

    report = validate_semantic_fixture(
        path,
        artifact_id="test-canonical-fa",
        expected_language="fa",
        intended_scope="complete test document",
        collation_record=_collation_record(
            tmp_path,
            "test-canonical-fa",
            fixture=path,
        ),
    )

    assert canonicalization["dropped_character_count"] == 2
    assert report.status == "pass"
    assert report.canonicalization["dropped_character_count"] == 0
    assert report.production_text_parity["result"] == "pass"
    assert (
        report.production_text_parity["production_ingested_normalized_text_sha256"]
        == report.production_text_parity["r13_canonical_normalized_text_sha256"]
    )


def test_r13_rejects_word_internal_private_use_characters(tmp_path: Path) -> None:
    """A private-use code point wedged inside a word may *be* a letter.

    Recovering it would take source-specific substitution, so the fixture fails.
    """

    path = tmp_path / "glyph-fa.txt"
    path.write_text("\n\n".join([f"دانشگاه {_PERSIAN_SENTENCE}"] * 80), encoding="utf-8")

    report = validate_semantic_fixture(
        path,
        artifact_id="test-glyph-fa",
        expected_language="fa",
        intended_scope="complete test document",
        collation_record=_collation_record(tmp_path, "test-glyph-fa", fixture=path),
    )

    assert report.status == "fail"
    failed = {gate["gate"] for gate in report.gates if gate["status"] == "fail"}
    assert "no_residual_private_use_characters" in failed
    assert report.metrics["residual_private_use_character_count"] == 80
    assert report.canonicalization["dropped_character_count"] == 0


def test_r13_rejects_glyph_offset_control_separators(tmp_path: Path) -> None:
    """The C06 OECD shape: a subset font with no ToUnicode map.

    Words extract as shifted ASCII and U+0003 stands in for the space. Every
    control character is adjacent to a letter, so none is canonicalizable and the
    fixture is rejected -- correctly, since only a source-specific shift could
    recover the text.
    """

    path = tmp_path / "shifted-en.md"
    path.write_text(
        "Ordinary readable prose survives on this page. "
        + ("6RFLDO\x03&RQQHFWLRQV (QYLURQPHQWDO\x034XDOLW\\ " * 60),
        encoding="utf-8",
    )

    report = validate_semantic_fixture(
        path,
        artifact_id="test-shifted-en",
        expected_language="en",
        intended_scope="complete test document",
    )

    assert report.status == "fail"
    failed = {gate["gate"] for gate in report.gates if gate["status"] == "fail"}
    assert "no_residual_control_character_anomalies" in failed
    assert report.canonicalization["dropped_character_count"] == 0
    assert report.canonicalization["residual_control_or_surrogate_count"] == 120


def test_r13_gate_e_is_fail_closed_for_persian_fixtures(tmp_path: Path) -> None:
    path = tmp_path / "uncollated-fa.txt"
    path.write_text("\n\n".join([_PERSIAN_SENTENCE] * 80), encoding="utf-8")

    missing = validate_semantic_fixture(
        path,
        artifact_id="test-uncollated-fa",
        expected_language="fa",
        intended_scope="complete test document",
    )
    unattested = validate_semantic_fixture(
        path,
        artifact_id="test-uncollated-fa",
        expected_language="fa",
        intended_scope="complete test document",
        collation_record=_collation_record(
            tmp_path,
            "test-uncollated-fa",
            fixture=path,
            reading_order_correct=False,
            pages_checked=[1],
        ),
    )

    assert missing.status == "fail"
    assert missing.human_collation["required"] is True
    assert "human_collation_attested" in {
        gate["gate"] for gate in missing.gates if gate["status"] == "fail"
    }
    assert unattested.status == "fail"
    assert "reading_order_correct is not attested true" in unattested.human_collation["reason"]
    assert "fewer than three pages" in unattested.human_collation["reason"]


def test_r13_does_not_require_collation_for_english_fixtures(tmp_path: Path) -> None:
    path = tmp_path / "plain-en.md"
    path.write_text("Evidence can be recovered from this stable paragraph. " * 80, encoding="utf-8")

    report = validate_semantic_fixture(
        path,
        artifact_id="test-plain-en",
        expected_language="en",
        intended_scope="complete test document",
    )

    assert report.status == "pass"
    assert report.human_collation["required"] is False


def test_r13_machine_scope_contract_rejects_wrong_or_extra_scope(tmp_path: Path) -> None:
    fixture = tmp_path / "bounded.md"
    fixture.write_text(
        "# Bounded work\n\nCHAPTER I.\n\n" + ("First evidence. " * 80)
        + "\n\nCHAPTER III.\n\n"
        + ("Final evidence. " * 80)
        + "\n\nPROJECT GUTENBERG LICENSE\n",
        encoding="utf-8",
    )
    contract = tmp_path / "scope.json"
    contract.write_text(
        json.dumps(
            {
                "artifact_id": "test-bounded",
                "required_markers_in_order": [
                    {"label": "one", "text": "CHAPTER I.", "expected_count": 1},
                    {"label": "three", "text": "CHAPTER III.", "expected_count": 1},
                ],
                "forbidden_markers": [
                    {"label": "gutenberg", "text": "PROJECT GUTENBERG LICENSE"}
                ],
                "start_boundary": {
                    "text": "CHAPTER I.",
                    "maximum_normalized_offset": 30,
                },
                "end_boundary": {
                    "text": "Final evidence.",
                    "maximum_trailing_normalized_characters": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    report = validate_semantic_fixture(
        fixture,
        artifact_id="test-bounded",
        expected_language="en",
        intended_scope="chapters I and III",
        scope_contract=contract,
    )

    assert report.status == "fail"
    assert report.scope_fidelity["result"] == "fail"
    failures = {
        check["check"]
        for check in report.scope_fidelity["checks"]
        if check["status"] == "fail"
    }
    assert "forbidden_marker:gutenberg" in failures
    assert "end_boundary" in failures


def test_r13_machine_scope_contract_passes_exact_bounded_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "bounded.md"
    fixture.write_text(
        "# Bounded work\n\nCHAPTER I.\n\n" + ("First evidence. " * 80)
        + "\n\nCHAPTER III.\n\n"
        + ("Final evidence. " * 80),
        encoding="utf-8",
    )
    contract = tmp_path / "scope.json"
    contract.write_text(
        json.dumps(
            {
                "artifact_id": "test-bounded",
                "required_markers_in_order": [
                    {"label": "one", "text": "CHAPTER I.", "expected_count": 1},
                    {"label": "three", "text": "CHAPTER III.", "expected_count": 1},
                ],
                "forbidden_markers": ["PROJECT GUTENBERG LICENSE"],
                "start_boundary": {
                    "text": "CHAPTER I.",
                    "maximum_normalized_offset": 30,
                },
                "end_boundary": {
                    "text": "Final evidence.",
                    "maximum_trailing_normalized_characters": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    report = validate_semantic_fixture(
        fixture,
        artifact_id="test-bounded",
        expected_language="en",
        intended_scope="chapters I and III",
        scope_contract=contract,
    )

    assert report.status == "pass"
    assert report.scope_fidelity["result"] == "pass"
