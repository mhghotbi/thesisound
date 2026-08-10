from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from thesisound.adapters.parsers.native_adapter import NativeDocumentParser
from thesisound.services.block_builder import BlockBuilder
from thesisound.services.document_identity import block_sequence_key, parsed_document_key
from thesisound.services.document_ingestion import ingest_document
from thesisound.services.excerpt_matching import locate_excerpt, normalize_for_match
from thesisound.services.token_counter import estimate_tokens

_REPORT_SCHEMA_VERSION = "thesisound.semantic-fixture-validation.v1"
_MIN_EXTRACTABLE_CHARACTERS = 800
_EXACT_SPAN_COUNT = 20
_EXACT_SPAN_CHARACTERS = 40
_ARABIC_SCRIPT_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x0870, 0x089F),
    (0x08A0, 0x08FF),
)
_ARABIC_PRESENTATION_RANGES = ((0xFB50, 0xFDFF), (0xFE70, 0xFEFF))
_PERSIAN_SPECIFIC = frozenset("پچژگکییۀ")
_ARABIC_VARIANTS = frozenset("يكۀةى")
_MOJIBAKE_MARKERS = ("Ã", "Â", "Ø", "Ù", "â€", "ï¿½")
_ALLOWED_CONTROLS = frozenset("\n\r\t")


class SemanticFixtureValidationReport(BaseModel):
    schema_version: str = _REPORT_SCHEMA_VERSION
    artifact_id: str
    artifact_filename: str
    intended_scope: str
    expected_language: str
    status: Literal["pass", "fail"]
    diagnostic_hash_notice: str = (
        "normalized_text_sha256 is an R13 diagnostic, not a source-package freeze record"
    )
    metrics: dict[str, Any]
    production_ingestion: dict[str, Any]
    language_sanity: dict[str, Any]
    locator_viability: dict[str, Any]
    exact_span_matching: dict[str, Any]
    normalization_checks: dict[str, Any]
    gates: list[dict[str, Any]]
    warnings: list[str] = Field(default_factory=list)


def validate_semantic_fixture(
    path: Path,
    *,
    artifact_id: str,
    expected_language: str,
    intended_scope: str,
) -> SemanticFixtureValidationReport:
    """Validate one prospective semantic fixture through Thesisound's native path.

    R13 forbids silently rescuing a failed semantic fixture with OCR. This function
    therefore selects the production native parser explicitly and treats any unsafe
    result as a failure. Scans and facsimiles belong in offline references and must
    never be passed to this validator as semantic fixtures.
    """

    resolved = path.expanduser().resolve()
    data = resolved.read_bytes()
    _decoded_text, decode_success, text_encoding = _decode_if_text(resolved, data)
    ingestion = ingest_document(
        resolved,
        parsers={"native": NativeDocumentParser()},
        parser_name="native",
    )
    parsed = ingestion.parsed
    extracted_text = ""
    if parsed is not None:
        extracted_text = "\n\n".join(
            block.text.strip() for block in parsed.blocks if block.text.strip()
        )
    if resolved.suffix.casefold() not in {".pdf", ".docx"}:
        decode_success = decode_success and parsed is not None
    elif parsed is not None:
        decode_success = True

    normalized_text, _ = normalize_for_match(extracted_text)
    blocks = []
    sequence_key: str | None = None
    parsed_key: str | None = None
    if parsed is not None:
        parsed_key = parsed_document_key(parsed)
        blocks, _ = BlockBuilder().build(parsed, source_id=UUID(int=0))
        sequence_key = block_sequence_key(blocks)

    pdf_metrics = _pdf_metrics(resolved) if resolved.suffix.casefold() == ".pdf" else {}
    control_anomalies = _control_anomalies(extracted_text)
    private_use_count = sum(unicodedata.category(char) == "Co" for char in extracted_text)
    presentation_count = _count_ranges(extracted_text, _ARABIC_PRESENTATION_RANGES)
    arabic_script_count = _count_ranges(extracted_text, _ARABIC_SCRIPT_RANGES)
    replacement_count = extracted_text.count("\ufffd")
    mojibake_count = sum(extracted_text.count(marker) for marker in _MOJIBAKE_MARKERS)
    language_sanity = _language_sanity(
        extracted_text,
        expected_language=expected_language,
        arabic_script_count=arabic_script_count,
        presentation_count=presentation_count,
        mojibake_count=mojibake_count,
    )
    locator = _locator_viability(parsed, page_count=ingestion.inspection.page_count)
    spans = _exact_span_check(extracted_text)
    normalization_checks = _normalization_checks()

    metrics: dict[str, Any] = {
        "byte_size": len(data),
        "file_format": resolved.suffix.casefold().lstrip(".") or "unknown",
        "mime_type": ingestion.inspection.mime_type,
        "text_encoding": text_encoding,
        "page_count": ingestion.inspection.page_count,
        "extractable_character_count": len(extracted_text),
        "word_estimate": len(re.findall(r"\S+", extracted_text)),
        "token_estimate": estimate_tokens(extracted_text),
        "embedded_image_count": pdf_metrics.get("embedded_image_count"),
        "pages_with_extractable_text": pdf_metrics.get("pages_with_extractable_text"),
        "unicode_decode_success": decode_success,
        "nul_byte_count": data.count(b"\x00"),
        "extracted_nul_character_count": extracted_text.count("\x00"),
        "arabic_presentation_forms_count": presentation_count,
        "replacement_character_count": replacement_count,
        "control_character_anomaly_count": len(control_anomalies),
        "control_character_anomalies": control_anomalies,
        "private_use_character_count": private_use_count,
        "zwnj_count": extracted_text.count("\u200c"),
        "bidi_control_count": sum(
            extracted_text.count(char) for char in ("\u061c", "\u200e", "\u200f")
        ),
        "mojibake_marker_count": mojibake_count,
        "normalized_text_sha256": hashlib.sha256(
            normalized_text.encode("utf-8")
        ).hexdigest(),
        "parsed_document_key": parsed_key,
        "block_sequence_key": sequence_key,
        "semantic_block_count": len(blocks),
    }
    production_ingestion = {
        "requested_parser": "native",
        "selected_parser": ingestion.selected_parser,
        "ocr_used": bool(ingestion.selected_parser and "ocr" in ingestion.selected_parser),
        "safe_for_claim_extraction": ingestion.safe_for_claim_extraction,
        "quality_verdict": ingestion.quality.verdict if ingestion.quality else None,
        "quality_issues": [
            issue.model_dump(mode="json")
            for issue in (ingestion.quality.issues if ingestion.quality else [])
        ],
        "parser_warnings": list(parsed.warnings) if parsed else [],
    }

    glyph_only = bool(
        resolved.suffix.casefold() == ".pdf"
        and (
            len(extracted_text) < _MIN_EXTRACTABLE_CHARACTERS
            or (expected_language == "fa" and language_sanity["normal_script_ratio"] < 0.95)
        )
    )
    language_sanity["glyph_only_pdf_text_layer"] = glyph_only

    gate_inputs = [
        ("non_empty_bytes", len(data) > 0, f"{len(data)} bytes"),
        (
            "substantive_text_present",
            len(extracted_text) >= _MIN_EXTRACTABLE_CHARACTERS,
            f"{len(extracted_text)} extractable characters",
        ),
        ("unicode_decode", decode_success, f"encoding={text_encoding}"),
        (
            "no_nul_bytes_in_decoded_text_format",
            resolved.suffix.casefold() in {".pdf", ".docx"} or data.count(b"\x00") == 0,
            (
                "not applicable to binary container; raw count recorded"
                if resolved.suffix.casefold() in {".pdf", ".docx"}
                else f"count={data.count(b'\x00')}"
            ),
        ),
        (
            "no_extracted_nul_characters",
            extracted_text.count("\x00") == 0,
            f"count={extracted_text.count(chr(0))}",
        ),
        (
            "no_replacement_characters",
            replacement_count == 0,
            f"count={replacement_count}",
        ),
        (
            "no_control_character_anomalies",
            not control_anomalies,
            f"count={len(control_anomalies)}",
        ),
        (
            "no_private_use_characters",
            private_use_count == 0,
            f"count={private_use_count}",
        ),
        (
            "presentation_forms_not_primary",
            language_sanity["presentation_forms_ratio"] <= 0.05,
            f"ratio={language_sanity['presentation_forms_ratio']:.6f}",
        ),
        ("language_sanity", language_sanity["result"] == "pass", language_sanity["reason"]),
        ("not_glyph_only_pdf", not glyph_only, f"glyph_only={glyph_only}"),
        (
            "production_ingestion_safe",
            ingestion.safe_for_claim_extraction,
            f"verdict={production_ingestion['quality_verdict']}",
        ),
        ("no_ocr", not production_ingestion["ocr_used"], "native parser selected explicitly"),
        ("locators_viable", locator["result"] == "pass", locator["reason"]),
        (
            "exact_span_matching_reliable",
            spans["can_operate_reliably"],
            f"recovered={spans['recovered_span_count']}/{spans['requested_span_count']}",
        ),
        (
            "persian_normalization_compatible",
            normalization_checks["zwnj_and_punctuation_compatible"],
            normalization_checks["normalized_probe"],
        ),
    ]
    gates = [
        {"gate": name, "status": "pass" if passed else "fail", "evidence": evidence}
        for name, passed, evidence in gate_inputs
    ]
    warnings: list[str] = []
    if expected_language == "fa" and extracted_text.count("\u200c") == 0:
        warnings.append(
            "No ZWNJ characters survived extraction; verify this is faithful "
            "to the source typography."
        )
    if pdf_metrics.get("page_extraction_failures"):
        warnings.append("One or more PDF pages raised a text-extraction error.")

    return SemanticFixtureValidationReport(
        artifact_id=artifact_id,
        artifact_filename=resolved.name,
        intended_scope=intended_scope,
        expected_language=expected_language,
        status="pass" if all(item[1] for item in gate_inputs) else "fail",
        metrics=metrics,
        production_ingestion=production_ingestion,
        language_sanity=language_sanity,
        locator_viability=locator,
        exact_span_matching=spans,
        normalization_checks=normalization_checks,
        gates=gates,
        warnings=warnings,
    )


def _decode_if_text(path: Path, data: bytes) -> tuple[str, bool, str | None]:
    if path.suffix.casefold() in {".pdf", ".docx"}:
        return "", True, None
    for encoding in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            return data.decode(encoding), True, encoding
        except UnicodeDecodeError:
            continue
    return "", False, None


def _pdf_metrics(path: Path) -> dict[str, Any]:
    from pypdf import PdfReader

    reader = PdfReader(path, strict=False)
    image_count = 0
    pages_with_text = 0
    failures: list[int] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            if (page.extract_text() or "").strip():
                pages_with_text += 1
        except Exception:
            failures.append(page_number)
        resources = page.get("/Resources") or {}
        xobjects = resources.get("/XObject") if hasattr(resources, "get") else None
        if xobjects is None:
            continue
        try:
            for item in xobjects.get_object().values():
                obj = item.get_object()
                if obj.get("/Subtype") == "/Image":
                    image_count += 1
        except Exception:
            # Image inventory is informative; text safety remains independently gated.
            continue
    return {
        "embedded_image_count": image_count,
        "pages_with_extractable_text": pages_with_text,
        "page_extraction_failures": failures,
    }


def _count_ranges(text: str, ranges: tuple[tuple[int, int], ...]) -> int:
    return sum(any(start <= ord(char) <= end for start, end in ranges) for char in text)


def _control_anomalies(text: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for char in text:
        if char in _ALLOWED_CONTROLS or char == "\u200c":
            continue
        category = unicodedata.category(char)
        if category in {"Cc", "Cs", "Co"}:
            key = f"U+{ord(char):04X} {unicodedata.name(char, 'UNNAMED')}"
            counts[key] = counts.get(key, 0) + 1
    return [{"code_point": key, "count": counts[key]} for key in sorted(counts)]


def _language_sanity(
    text: str,
    *,
    expected_language: str,
    arabic_script_count: int,
    presentation_count: int,
    mojibake_count: int,
) -> dict[str, Any]:
    total_arabic = arabic_script_count + presentation_count
    presentation_ratio = presentation_count / total_arabic if total_arabic else 0.0
    normal_ratio = arabic_script_count / total_arabic if total_arabic else 0.0
    letters = [char for char in text if char.isalpha()]
    latin_count = sum("LATIN" in unicodedata.name(char, "") for char in letters)
    if expected_language == "fa":
        enough_script = arabic_script_count >= 400
        sane = enough_script and normal_ratio >= 0.95 and mojibake_count == 0
        reason = (
            f"normal Arabic/Persian script={arabic_script_count}; "
            f"presentation ratio={presentation_ratio:.4%}; mojibake markers={mojibake_count}"
        )
    elif expected_language == "en":
        latin_ratio = latin_count / len(letters) if letters else 0.0
        sane = latin_count >= 400 and latin_ratio >= 0.80 and mojibake_count == 0
        reason = f"Latin letters={latin_count}; letter ratio={latin_ratio:.4%}"
    else:
        sane = bool(letters or arabic_script_count) and mojibake_count == 0
        reason = "mixed/other language sanity requires substantive letters and no mojibake markers"
    return {
        "expected_language": expected_language,
        "result": "pass" if sane else "fail",
        "reason": reason,
        "normal_arabic_persian_script_count": arabic_script_count,
        "persian_specific_letter_count": sum(text.count(char) for char in _PERSIAN_SPECIFIC),
        "arabic_variant_letter_count": sum(text.count(char) for char in _ARABIC_VARIANTS),
        "presentation_forms_count": presentation_count,
        "presentation_forms_ratio": round(presentation_ratio, 8),
        "normal_script_ratio": round(normal_ratio, 8),
        "latin_letter_count": latin_count,
        "mojibake_marker_count": mojibake_count,
    }


def _locator_viability(parsed, *, page_count: int | None) -> dict[str, Any]:
    if parsed is None or not parsed.blocks:
        return {"result": "fail", "reason": "no parsed blocks", "coverage": 0.0}
    non_empty = [block for block in parsed.blocks if block.text.strip()]
    if page_count is not None:
        located = [block for block in non_empty if block.page_start is not None]
        coverage = len(located) / len(non_empty) if non_empty else 0.0
        pages = {
            page
            for block in located
            for page in range(block.page_start or 0, (block.page_end or block.page_start or 0) + 1)
        }
        page_coverage = len(pages) / page_count if page_count else 0.0
        passed = coverage >= 0.95 and page_coverage >= 0.80
        return {
            "result": "pass" if passed else "fail",
            "reason": (
                f"block locator coverage={coverage:.2%}; page coverage={page_coverage:.2%}"
            ),
            "locator_type": "page",
            "coverage": round(coverage, 8),
            "page_coverage": round(page_coverage, 8),
        }
    unique_keys = {block.source_block_key for block in non_empty}
    coverage = len(unique_keys) / len(non_empty) if non_empty else 0.0
    passed = coverage == 1.0
    return {
        "result": "pass" if passed else "fail",
        "reason": f"stable unique source-block keys={len(unique_keys)}/{len(non_empty)}",
        "locator_type": "source_block_key",
        "coverage": round(coverage, 8),
        "page_coverage": None,
    }


def _exact_span_check(text: str) -> dict[str, Any]:
    normalized, _ = normalize_for_match(text)
    if len(normalized) < _EXACT_SPAN_CHARACTERS:
        return {
            "requested_span_count": _EXACT_SPAN_COUNT,
            "tested_span_count": 0,
            "recovered_span_count": 0,
            "recovery_ratio": 0.0,
            "can_operate_reliably": False,
            "sample_normalized_hashes": [],
        }
    maximum_start = len(normalized) - _EXACT_SPAN_CHARACTERS
    starts = [
        round(index * maximum_start / (_EXACT_SPAN_COUNT - 1))
        for index in range(_EXACT_SPAN_COUNT)
    ]
    samples = [normalized[start : start + _EXACT_SPAN_CHARACTERS] for start in starts]
    recovered = sum(locate_excerpt(sample, text) is not None for sample in samples)
    return {
        "requested_span_count": _EXACT_SPAN_COUNT,
        "tested_span_count": len(samples),
        "recovered_span_count": recovered,
        "recovery_ratio": round(recovered / len(samples), 8),
        "can_operate_reliably": recovered == _EXACT_SPAN_COUNT,
        "sample_normalized_hashes": [
            hashlib.sha256(sample.encode("utf-8")).hexdigest() for sample in samples
        ],
    }


def _normalization_checks() -> dict[str, Any]:
    probe = "می\u200cرود، آیا؟ كی يک ۱۲٣"
    normalized, _ = normalize_for_match(probe)
    # The evaluator deliberately drops ZWNJ rather than turning it into a space;
    # the important property is that both source and excerpt take the same path.
    expected = "میرود، آیا؟ کی یک 123"
    return {
        "probe": probe,
        "normalized_probe": normalized,
        "expected_normalized_probe": expected,
        "zwnj_and_punctuation_compatible": normalized == expected,
        "normalizer": "thesisound.services.excerpt_matching.normalize_for_match",
    }
