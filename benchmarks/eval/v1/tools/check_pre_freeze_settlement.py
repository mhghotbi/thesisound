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
# Two questions, two answers. "The settlement package is internally consistent" is
# not "every release-gating core case is safe to freeze", and a checker that returns
# one verdict for both invites reading the first as the second. Only FREEZE_READY
# permits a freeze; every other value is a package that still has work to do, and
# `ready_with_...` variants are deliberately not freeze-ready by prefix accident.
FREEZE_READY_READINESS = {"ready"}
KNOWN_READINESS = {"ready", "ready_with_recorded_budget_caution", "blocked"}


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
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional machine-readable output path for the current checker result",
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
    try:
        fixture_tokens, fixture_token_source = derive_controlled_pair_fixture_tokens(
            root,
            package,
        )
    except (KeyError, OSError, TypeError, ValueError) as error:
        errors.append(f"C10/C11 fixture token estimate cannot be derived from R13: {error}")
        fixture_tokens = 0
        fixture_token_source = None
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

    c09_config = configs["cases"]["C09"]
    c09_report_path = package["packages"]["C09"]["sources"][0]["r13_report"]
    c09_tokens = _read(root / c09_report_path)["metrics"]["token_estimate"]
    c09_brief = ResearchBrief(
        normalized_topic="Darwin hierarchical reconstruction",
        topic_type=TopicType.CONCEPT,
        central_question=c09_config["research_brief"],
        audience=c09_config["audience"],
        prior_knowledge=c09_config["prior_knowledge"],
        target_duration_minutes=c09_config["target_duration_minutes"],
        output_language=c09_config["output_language"],
        modes=c09_config["modes"],
    )
    c09_profile = build_analysis_profile(c09_brief)
    c09_target_tokens = min(
        c09_tokens,
        math.ceil(c09_tokens * c09_profile.block_coverage_target * 1.10),
        c09_profile.evidence_input_token_budget,
    )
    computed_c09 = {
        "depth": c09_profile.depth,
        "block_coverage_target": c09_profile.block_coverage_target,
        "evidence_input_token_budget": c09_profile.evidence_input_token_budget,
        "max_claims_per_block": c09_profile.max_claims_per_block,
        "neighbor_context_blocks": c09_profile.neighbor_context_blocks,
        "include_examples": c09_profile.include_examples,
        "include_objections_and_responses": c09_profile.include_objections_and_responses,
        "target_source_tokens": c09_target_tokens,
        "maximum_nominal_selected_coverage": round(c09_target_tokens / c09_tokens, 6),
        "fixture_token_estimate": c09_tokens,
        "fixture_token_source": c09_report_path,
    }
    for key, value in computed_c09.items():
        expected = configs["computed_profiles"]["C09"].get(key)
        if expected != value:
            errors.append(
                f"C09 computed {key}={value!r}, manifest has {expected!r}"
            )

    freeze_blockers: list[str] = []
    for case_id, case in package["packages"].items():
        seen: set[str] = set()
        readiness = case["readiness"]
        if readiness not in KNOWN_READINESS:
            errors.append(f"{case_id} has an unrecognised readiness value {readiness!r}")
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
                scope_contract = source.get("scope_contract")
                if scope_contract is not None:
                    scope = report.get("scope_fidelity", {})
                    if scope.get("result") != "pass":
                        errors.append(
                            f"{case_id}/{logical_id} declared bounded scope does not pass"
                        )
                    expected_name = Path(scope_contract).name
                    if scope.get("contract_filename") != expected_name:
                        errors.append(
                            f"{case_id}/{logical_id} R13 scope contract does not match manifest"
                        )
        if readiness in FREEZE_READY_READINESS:
            for source in case["sources"]:
                if source.get("ingested_fixture") is None:
                    errors.append(
                        f"ready package {case_id} has no ingested fixture for "
                        f"{source['logical_source_id']}"
                    )
        if not case.get("release_gating"):
            continue
        if readiness not in FREEZE_READY_READINESS:
            reasons = case.get("blockers") or [f"readiness is {readiness!r}"]
            freeze_blockers.extend(f"{case_id}: {reason}" for reason in reasons)
        for source in case["sources"]:
            if source.get("ingested_fixture") is None:
                freeze_blockers.append(
                    f"{case_id}: no ingested fixture for {source['logical_source_id']}"
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
        "schema_version": "thesisound.semantic-golden-set.pre-freeze-check.v2",
        "settlement_consistent": not errors,
        "release_gating_core_ready": not freeze_blockers,
        "freeze_permitted": not errors and not freeze_blockers,
        "status": "pass" if not errors else "fail",
        "status_meaning": (
            "`status` reports settlement consistency ONLY. A freeze may proceed only "
            "when `freeze_permitted` is true."
        ),
        "visible_core_count": len(expected_core),
        "visible_challenge_count": len(expected_challenge),
        "computed_duration_pair": computed_pair,
        "computed_profiles": {"C09": computed_c09},
        "controlled_pair_fixture_tokens": fixture_tokens,
        "controlled_pair_fixture_token_source": fixture_token_source,
        "errors": errors,
        "release_gating_freeze_blockers": freeze_blockers,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if args.report is not None:
        report_path = args.report.resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8")
    if errors:
        return 1
    return 0 if not freeze_blockers else 3


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def derive_controlled_pair_fixture_tokens(
    root: Path,
    package: dict[str, Any],
) -> tuple[int, str]:
    """Read the C10/C11 shared token count from their actual R13 report.

    The source-package manifest is the join between case and report. Keeping this
    derivation here prevents a copied configuration constant from surviving a fixture
    replacement or a token-estimator change.
    """

    report_paths = {
        source["r13_report"]
        for case_id in ("C10", "C11")
        for source in package["packages"][case_id]["sources"]
        if source.get("ingested_fixture") is not None
    }
    if len(report_paths) != 1:
        raise ValueError(
            f"controlled pair must resolve to one shared R13 report, got {sorted(report_paths)}"
        )
    report_path = report_paths.pop()
    report = _read(root / report_path)
    token_estimate = report.get("metrics", {}).get("token_estimate")
    if not isinstance(token_estimate, int) or token_estimate <= 0:
        raise ValueError(f"invalid token_estimate in {report_path}: {token_estimate!r}")
    return token_estimate, report_path


if __name__ == "__main__":
    raise SystemExit(main())
