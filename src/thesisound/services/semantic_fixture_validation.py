from __future__ import annotations

import hashlib
import json
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
_NO_IDENTITY_CATEGORIES = frozenset({"Cc", "Cs", "Co"})
_COLLATION_REQUIRED_LANGUAGES = frozenset({"fa", "mixed"})
_COLLATION_ATTESTATIONS = (
    "reading_order_correct",
    "footnote_and_margin_separation_correct",
    "script_rendering_correct",
    "zwnj_loss_meaning_preserving",
)
_CANONICALIZATION_RULE = (
    "Drop a Cc/Cs/Co code point only when it is isolated -- every neighbour is "
    "absent or whitespace. Isolated marks are page furniture (footnote symbols, "
    "separators, stray font glyphs): removing them changes no word, no locator "
    "and no excerpt span. A code point adjacent to any non-space character is "
    "semantic corruption, because it may stand for a letter whose identity is "
    "unknown, and recovering it would need source-specific repair, which R13 forbids."
)


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
    canonicalization: dict[str, Any]
    production_text_parity: dict[str, Any]
    scope_fidelity: dict[str, Any]
    human_collation: dict[str, Any]
    gates: list[dict[str, Any]]
    warnings: list[str] = Field(default_factory=list)


def validate_semantic_fixture(
    path: Path,
    *,
    artifact_id: str,
    expected_language: str,
    intended_scope: str,
    collation_record: Path | None = None,
    scope_contract: Path | None = None,
) -> SemanticFixtureValidationReport:
    """Validate one prospective semantic fixture through Thesisound's native path.

    R13 forbids silently rescuing a failed semantic fixture with OCR. This function
    therefore selects the production native parser explicitly and treats any unsafe
    result as a failure. Scans and facsimiles belong in offline references and must
    never be passed to this validator as semantic fixtures.

    Not every nonstandard code point is fatal. Code points with no Unicode identity
    are split by ``canonicalize_semantic_text`` into marks that a general, deterministic,
    source-independent rule can drop without touching a word, and residue that would
    need source-specific repair. Only the residue rejects the fixture. Every dropped
    code point is itemised in the report so the same canonicalization can be applied
    to the ingested artifact rather than assumed.
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
    canonical_text, canonicalization = canonicalize_semantic_text(extracted_text)
    control_anomalies = canonicalization["residual_control_or_surrogate_code_points"]
    residual_private_use = canonicalization["residual_private_use_character_count"]
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
    production_text_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    canonical_text_hash = canonicalization["canonical_text_sha256"]
    production_text_parity = {
        "result": "pass" if production_text_hash == canonical_text_hash else "fail",
        "production_ingested_normalized_text_sha256": production_text_hash,
        "r13_canonical_normalized_text_sha256": canonical_text_hash,
        "reason": (
            "the production-ingested artifact is already canonical"
            if production_text_hash == canonical_text_hash
            else (
                "R13 would drop characters that the production ingestion path still sees; "
                "ingest a canonicalized derivative or apply the identical canonicalizer "
                "before semantic ingestion"
            )
        ),
    }
    scope_fidelity = _scope_fidelity(
        canonical_text,
        scope_contract,
        artifact_id=artifact_id,
    )
    collation = _human_collation(
        collation_record,
        artifact_id=artifact_id,
        expected_language=expected_language,
        normalized_text_sha256=canonical_text_hash,
    )

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
        "residual_private_use_character_count": residual_private_use,
        "canonicalizable_character_count": canonicalization["dropped_character_count"],
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
            "no_residual_control_character_anomalies",
            not control_anomalies,
            f"distinct_code_points={len(control_anomalies)}; "
            f"occurrences={canonicalization['residual_control_or_surrogate_count']}",
        ),
        (
            "no_residual_private_use_characters",
            residual_private_use == 0,
            f"residual={residual_private_use} of {private_use_count} total",
        ),
        (
            "canonicalization_preserves_words",
            canonicalization["word_sequence_preserved"],
            f"dropped={canonicalization['dropped_character_count']}; "
            f"word_sequence_preserved={canonicalization['word_sequence_preserved']}",
        ),
        (
            "production_text_matches_r13_canonical_text",
            production_text_parity["result"] == "pass",
            production_text_parity["reason"],
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
        (
            "declared_scope_fidelity",
            scope_fidelity["result"] == "pass",
            scope_fidelity["reason"],
        ),
        ("human_collation_attested", collation["result"] == "pass", collation["reason"]),
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
        canonicalization=canonicalization,
        production_text_parity=production_text_parity,
        scope_fidelity=scope_fidelity,
        human_collation=collation,
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


def canonicalize_semantic_text(text: str) -> tuple[str, dict[str, Any]]:
    """Split code points with no Unicode identity into droppable and fatal residue.

    The governing question R13 answers is not "is this code point standard?" but
    "can canonical text be derived by a general, deterministic, source-independent
    rule that preserves semantic content, locators and exact-span reproducibility?"
    Isolation answers it: a mark with whitespace on both sides is its own token, so
    deleting it removes a token that carried no letters and leaves every other word,
    page and span untouched. A mark wedged against a letter or digit may *be* that
    text, and guessing which is source-specific repair.
    """

    dropped: dict[str, int] = {}
    residual: dict[str, dict[str, Any]] = {}
    kept: list[str] = []
    for index, char in enumerate(text):
        if char in _ALLOWED_CONTROLS or char == "\u200c":
            kept.append(char)
            continue
        category = unicodedata.category(char)
        if category not in _NO_IDENTITY_CATEGORIES:
            kept.append(char)
            continue
        key = f"U+{ord(char):04X} {unicodedata.name(char, 'UNNAMED')}"
        before = text[index - 1] if index else ""
        after = text[index + 1] if index + 1 < len(text) else ""
        if (not before or before.isspace()) and (not after or after.isspace()):
            dropped[key] = dropped.get(key, 0) + 1
            continue
        record = residual.setdefault(
            key,
            {
                "code_point": key,
                "category": category,
                "count": 0,
                "sample_neighbours": f"{before!r} .. {after!r}",
            },
        )
        record["count"] += 1
        kept.append(char)

    canonical = "".join(kept)
    droppable = set(dropped)
    expected_tokens = [
        token
        for token in re.findall(r"\S+", text)
        if not all(
            f"U+{ord(char):04X} {unicodedata.name(char, 'UNNAMED')}" in droppable
            for char in token
        )
    ]
    residual_records = [residual[key] for key in sorted(residual)]
    report = {
        "rule": _CANONICALIZATION_RULE,
        "applied_to": "text extracted through the production native parser",
        "dropped_code_points": [
            {"code_point": key, "count": dropped[key], "disposition": "isolated_non_semantic_mark"}
            for key in sorted(dropped)
        ],
        "dropped_character_count": sum(dropped.values()),
        "word_sequence_preserved": re.findall(r"\S+", canonical) == expected_tokens,
        "residual_code_points": residual_records,
        "residual_control_or_surrogate_code_points": [
            {"code_point": record["code_point"], "count": record["count"]}
            for record in residual_records
            if record["category"] in {"Cc", "Cs"}
        ],
        "residual_control_or_surrogate_count": sum(
            record["count"] for record in residual_records if record["category"] in {"Cc", "Cs"}
        ),
        "residual_private_use_character_count": sum(
            record["count"] for record in residual_records if record["category"] == "Co"
        ),
        "canonicalization_required_before_ingestion": bool(dropped),
        "canonical_text_sha256": hashlib.sha256(
            normalize_for_match(canonical)[0].encode("utf-8")
        ).hexdigest(),
    }
    return canonical, report


def _scope_fidelity(
    text: str,
    contract_path: Path | None,
    *,
    artifact_id: str,
) -> dict[str, Any]:
    """Evaluate a declarative bounded-source contract against extracted text.

    R13 text-quality checks cannot prove that a preparer selected the intended
    chapters. A scope contract makes that separate claim machine-checkable without
    embedding source-specific logic in the validator. Markers use the evaluator's
    exact normalization, so harmless typography differences do not mask a scope
    error.
    """

    if contract_path is None:
        return {
            "declared": False,
            "result": "pass",
            "reason": "no bounded-scope contract declared",
            "contract_filename": None,
            "contract_sha256": None,
            "checks": [],
        }
    try:
        contract_bytes = contract_path.read_bytes()
        contract = json.loads(contract_bytes.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        return {
            "declared": True,
            "result": "fail",
            "reason": f"scope contract could not be read: {error}",
            "contract_filename": contract_path.name,
            "contract_sha256": None,
            "checks": [],
        }

    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, evidence: str) -> None:
        checks.append(
            {"check": name, "status": "pass" if passed else "fail", "evidence": evidence}
        )

    add(
        "artifact_id_matches",
        contract.get("artifact_id") == artifact_id,
        f"contract={contract.get('artifact_id')!r}; fixture={artifact_id!r}",
    )
    normalized, _ = normalize_for_match(text)
    positions: list[int] = []
    for index, marker in enumerate(contract.get("required_markers_in_order", []), start=1):
        label = marker.get("label") or f"marker_{index}"
        needle, _ = normalize_for_match(str(marker.get("text", "")))
        count = normalized.count(needle) if needle else 0
        expected_count = int(marker.get("expected_count", 1))
        position = normalized.find(needle) if needle else -1
        positions.append(position)
        add(
            f"required_marker:{label}",
            bool(needle) and count == expected_count,
            f"normalized_occurrences={count}; expected={expected_count}; offset={position}",
        )
    valid_positions = all(position >= 0 for position in positions)
    add(
        "required_markers_ordered",
        valid_positions and positions == sorted(positions),
        f"normalized_offsets={positions}",
    )

    for index, marker in enumerate(contract.get("forbidden_markers", []), start=1):
        if isinstance(marker, str):
            label = f"forbidden_{index}"
            marker_text = marker
        else:
            label = marker.get("label") or f"forbidden_{index}"
            marker_text = str(marker.get("text", ""))
        needle, _ = normalize_for_match(marker_text)
        count = normalized.count(needle) if needle else 0
        add(
            f"forbidden_marker:{label}",
            bool(needle) and count == 0,
            f"normalized_occurrences={count}",
        )

    start = contract.get("start_boundary")
    if isinstance(start, dict):
        needle, _ = normalize_for_match(str(start.get("text", "")))
        offset = normalized.find(needle) if needle else -1
        maximum = int(start.get("maximum_normalized_offset", 0))
        add(
            "start_boundary",
            bool(needle) and 0 <= offset <= maximum,
            f"offset={offset}; maximum={maximum}",
        )

    end = contract.get("end_boundary")
    if isinstance(end, dict):
        needle, _ = normalize_for_match(str(end.get("text", "")))
        offset = normalized.rfind(needle) if needle else -1
        trailing = len(normalized) - (offset + len(needle)) if offset >= 0 else len(normalized)
        maximum = int(end.get("maximum_trailing_normalized_characters", 0))
        add(
            "end_boundary",
            bool(needle) and offset >= 0 and trailing <= maximum,
            f"trailing_normalized_characters={trailing}; maximum={maximum}",
        )

    minimum = contract.get("minimum_extractable_characters")
    if minimum is not None:
        add(
            "minimum_extractable_characters",
            len(text) >= int(minimum),
            f"actual={len(text)}; minimum={int(minimum)}",
        )
    maximum = contract.get("maximum_extractable_characters")
    if maximum is not None:
        add(
            "maximum_extractable_characters",
            len(text) <= int(maximum),
            f"actual={len(text)}; maximum={int(maximum)}",
        )

    failures = [item["check"] for item in checks if item["status"] == "fail"]
    return {
        "declared": True,
        "result": "fail" if failures else "pass",
        "reason": (
            f"failed checks: {', '.join(failures)}"
            if failures
            else "all declared bounded-scope checks passed"
        ),
        "contract_filename": contract_path.name,
        "contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "checks": checks,
    }


def _human_collation(
    record_path: Path | None,
    *,
    artifact_id: str,
    expected_language: str,
    normalized_text_sha256: str,
) -> dict[str, Any]:
    """R13 Gate E. Fail-closed: an unmeasured fixture is rejected, never assumed clean.

    Required for every Persian and mixed-script fixture, where extraction can be
    lossy in ways no counting gate sees -- reversed bidi runs, footnote apparatus
    hoisted into body text, running heads spliced mid-argument.
    """

    required = expected_language in _COLLATION_REQUIRED_LANGUAGES
    if record_path is None:
        return {
            "required": required,
            "result": "fail" if required else "pass",
            "reason": (
                "no human collation record supplied for a fixture whose language "
                "requires one"
                if required
                else "not required for this fixture language"
            ),
            "record": None,
        }
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return {
            "required": required,
            "result": "fail",
            "reason": f"collation record could not be read: {error}",
            "record": None,
        }

    problems: list[str] = []
    if record.get("artifact_id") != artifact_id:
        problems.append("artifact_id does not match the fixture under validation")
    if record.get("fixture_normalized_text_sha256") != normalized_text_sha256:
        problems.append("fixture_normalized_text_sha256 does not bind this exact fixture text")
    for field in ("reviewer", "reviewed_on"):
        if not record.get(field):
            problems.append(f"missing {field}")
    pages = record.get("pages_checked")
    if not isinstance(pages, list) or len(pages) < 3:
        problems.append("fewer than three pages recorded as checked")
    for attestation in _COLLATION_ATTESTATIONS:
        if record.get(attestation) is not True:
            problems.append(f"{attestation} is not attested true")
    return {
        "required": required,
        "result": "pass" if not problems else "fail",
        "reason": "; ".join(problems) if problems else "human collation attested",
        "record": {
            "artifact_id": record.get("artifact_id"),
            "reviewer": record.get("reviewer"),
            "reviewed_on": record.get("reviewed_on"),
            "pages_checked": pages if isinstance(pages, list) else None,
            "fixture_normalized_text_sha256": record.get(
                "fixture_normalized_text_sha256"
            ),
        },
    }


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
