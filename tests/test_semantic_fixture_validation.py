from __future__ import annotations

from pathlib import Path

from thesisound.services.semantic_fixture_validation import validate_semantic_fixture


def test_r13_accepts_clean_persian_fixture(tmp_path: Path) -> None:
    sentence = "این متنِ فارسی می\u200cتواند، با نشانه\u200cگذاری عادی، دقیقاً بازیابی شود."
    path = tmp_path / "clean-fa.txt"
    path.write_text("\n\n".join([sentence] * 80), encoding="utf-8")

    report = validate_semantic_fixture(
        path,
        artifact_id="test-fa",
        expected_language="fa",
        intended_scope="complete test document",
    )

    assert report.status == "pass"
    assert report.metrics["zwnj_count"] > 0
    assert report.metrics["arabic_presentation_forms_count"] == 0
    assert report.exact_span_matching["recovered_span_count"] == 20
    assert report.normalization_checks["zwnj_and_punctuation_compatible"] is True


def test_r13_rejects_presentation_forms_and_replacement_characters(tmp_path: Path) -> None:
    path = tmp_path / "broken-fa.txt"
    path.write_text(("\ufefb\ufefc\ufffd " * 400), encoding="utf-8")

    report = validate_semantic_fixture(
        path,
        artifact_id="test-broken-fa",
        expected_language="fa",
        intended_scope="complete test document",
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
