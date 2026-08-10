from __future__ import annotations

import argparse
import json
from pathlib import Path

from thesisound.services.semantic_fixture_validation import validate_semantic_fixture


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic R13 validation for a pre-freeze semantic fixture."
    )
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--language", required=True, choices=("en", "fa", "mixed"))
    parser.add_argument("--scope", required=True)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument(
        "--collation-record",
        type=Path,
        default=None,
        help="Human collation attestation (R13 Gate E); required for fa/mixed fixtures",
    )
    parser.add_argument(
        "--scope-contract",
        type=Path,
        default=None,
        help="Declarative bounded-scope contract checked against production-extracted text",
    )
    args = parser.parse_args()

    result = validate_semantic_fixture(
        args.fixture,
        artifact_id=args.artifact_id,
        expected_language=args.language,
        intended_scope=args.scope,
        collation_record=args.collation_record,
        scope_contract=args.scope_contract,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
