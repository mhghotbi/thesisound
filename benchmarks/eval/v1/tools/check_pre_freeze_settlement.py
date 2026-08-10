from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from thesisound.domain import ResearchBrief, TopicType
from thesisound.services.analysis_profile import build_analysis_profile

REQUIRED_CONFIG_FIELDS = {
    "target_duration_minutes",
    "modes",
    "prior_knowledge",
    "audience",
    "output_language",
    "source_behavior",
    "research_brief",
}
SEMANTIC_HOLDOUT_KEYS = {
    "author",
    "authors",
    "brief",
    "capability",
    "failure_mode",
    "gold",
    "source",
    "sources",
    "topic",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Phase-2.5 settlement invariants.")
    parser.add_argument(
        "--pre-freeze-root",
        type=Path,
        default=Path("benchmarks/eval/v1/pre-freeze"),
    )
    parser.add_argument(
        "--holdout-manifest",
        type=Path,
        default=Path("benchmarks/eval/holdouts/public-manifest.json"),
    )
    args = parser.parse_args()

    root = args.pre_freeze_root.resolve()
    package = _read(root / "source-package-manifest.json")
    configs = _read(root / "pinned-case-configs.json")
    offline = _read(root / "offline-collation-references.json")
    holdouts = _read(args.holdout_manifest.resolve())

    errors: list[str] = []
    expected_core = {
        "C01", "C02", "C03", "C04", "C05R", "C06",
        "C07", "C08", "C09", "C10", "C11", "V15",
    }
    expected_challenge = {"V13", "V14"}
    if set(package["visible_core"]) != expected_core:
        errors.append("visible_core does not equal the reconciled 12-case set")
    if set(package["visible_challenge_non_gating"]) != expected_challenge:
        errors.append("visible challenge tier does not equal V13/V14")

    visible = expected_core | expected_challenge
    if set(configs["cases"]) != visible:
        errors.append("pinned configuration cases do not equal all 14 visible cases")
    for case_id, config in configs["cases"].items():
        missing = REQUIRED_CONFIG_FIELDS - set(config)
        if missing:
            errors.append(f"{case_id} has unpinned fields: {sorted(missing)}")
        behavior = config.get("source_behavior", {})
        if (
            behavior.get("kind") != "source_bound"
            or behavior.get("external_research") != "forbidden"
        ):
            errors.append(f"{case_id} is not explicitly source-bound")

    c10 = dict(configs["cases"]["C10"])
    c11 = dict(configs["cases"]["C11"])
    c10_duration = c10.pop("target_duration_minutes")
    c11_duration = c11.pop("target_duration_minutes")
    if (c10_duration, c11_duration) != (20, 40):
        errors.append("C10/C11 durations are not exactly 20/40")
    if c10 != c11:
        errors.append("C10/C11 differ in fields other than target_duration_minutes")

    computed_pair: dict[str, Any] = {}
    fixture_tokens = configs["controlled_pair"]["shared_fixture_token_estimate"]
    for case_id in ("C10", "C11"):
        config = configs["cases"][case_id]
        brief = ResearchBrief(
            normalized_topic="Ostrom polycentric governance",
            topic_type=TopicType.CONCEPT,
            central_question=config["research_brief"],
            audience=config["audience"],
            prior_knowledge=config["prior_knowledge"],
            target_duration_minutes=config["target_duration_minutes"],
            output_language=config["output_language"],
            modes=config["modes"],
        )
        profile = build_analysis_profile(brief)
        target_tokens = min(
            fixture_tokens,
            math.ceil(fixture_tokens * profile.block_coverage_target * 1.10),
            profile.evidence_input_token_budget,
        )
        expected = configs["controlled_pair"][case_id]
        actual = {
            "depth": profile.depth,
            "block_coverage_target": profile.block_coverage_target,
            "evidence_input_token_budget": profile.evidence_input_token_budget,
            "max_claims_per_block": profile.max_claims_per_block,
            "neighbor_context_blocks": profile.neighbor_context_blocks,
            "include_examples": profile.include_examples,
            "include_objections_and_responses": profile.include_objections_and_responses,
            "target_source_tokens_with_10_percent_headroom": target_tokens,
        }
        computed_pair[case_id] = actual
        for key, value in actual.items():
            if expected.get(key) != value:
                errors.append(
                    f"{case_id} computed {key}={value!r}, "
                    f"manifest has {expected.get(key)!r}"
                )

    for case_id, case in package["packages"].items():
        seen: set[str] = set()
        for source in case["sources"]:
            logical_id = source["logical_source_id"]
            if logical_id in seen:
                errors.append(f"{case_id} repeats logical source {logical_id}")
            seen.add(logical_id)
            fixture = source.get("ingested_fixture")
            report_path = source.get("r13_report")
            if fixture is not None:
                if not report_path:
                    errors.append(f"{case_id}/{logical_id} has an ingested fixture without R13")
                    continue
                report = _read(root / report_path)
                if report.get("status") != "pass":
                    errors.append(f"{case_id}/{logical_id} ingested fixture does not pass R13")
        if case["readiness"].startswith("ready"):
            for source in case["sources"]:
                if source.get("ingested_fixture") is None:
                    errors.append(
                        f"ready package {case_id} has no ingested fixture for "
                        f"{source['logical_source_id']}"
                    )

    if any(reference.get("ingest") is not False for reference in offline["references"]):
        errors.append("an offline reference is not explicitly marked ingest=false")

    slots = holdouts.get("slots", [])
    if len(slots) != 3:
        errors.append("public holdout manifest does not contain exactly three opaque slots")
    for record in slots:
        leaked = SEMANTIC_HOLDOUT_KEYS & set(record)
        if leaked:
            errors.append(f"opaque holdout {record.get('opaque_id')} leaks keys: {sorted(leaked)}")
        for field in ("fixture_sha256", "gold_sha256"):
            if record.get(field) is not None:
                errors.append(f"unprovisioned opaque holdout has a non-null {field}")

    result = {
        "schema_version": "thesisound.semantic-golden-set.pre-freeze-check.v1",
        "status": "pass" if not errors else "fail",
        "visible_core_count": len(expected_core),
        "visible_challenge_count": len(expected_challenge),
        "computed_duration_pair": computed_pair,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
