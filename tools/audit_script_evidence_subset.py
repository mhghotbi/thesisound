#!/usr/bin/env python3
"""One-shot audit: turn.evidence_ids subset of claim.evidence_ids (Phase 0 gate).

Walks filesystem workspaces (not the SQLite ledger). Reports substantive-turn
counts, violation rate, and the §5.1 severity recommendation for
evidence_unlinked_to_claim.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_SKIP_DIRS = frozenset({"_accounts", "_observability", "_shared"})


def _load_claims(project_dir: Path) -> dict[str, set[str]]:
    claims: dict[str, set[str]] = {}
    sources = project_dir / "sources"
    if not sources.is_dir():
        return claims
    for ledger_path in sorted(sources.glob("*/claim-ledger.json")):
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
        for claim in payload.get("claims", []):
            claim_id = claim.get("claim_id")
            if not claim_id:
                continue
            claims[str(claim_id)] = set(claim.get("evidence_ids") or [])
    return claims


def _script_path(project_dir: Path) -> Path | None:
    revised = project_dir / "script" / "script-revised.json"
    draft = project_dir / "script" / "script-draft.json"
    if revised.is_file():
        return revised
    if draft.is_file():
        return draft
    return None


def audit_workspace(root: Path) -> dict[str, object]:
    substantive = 0
    violations = 0
    extra_counts: Counter[int] = Counter()
    project_rows: list[dict[str, object]] = []

    for project_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        if project_dir.name.startswith("_") or project_dir.name in _SKIP_DIRS:
            continue
        script_file = _script_path(project_dir)
        if script_file is None:
            continue
        claims = _load_claims(project_dir)
        if not claims:
            continue
        script = json.loads(script_file.read_text(encoding="utf-8"))
        proj_subst = 0
        proj_viol = 0
        for turn in script.get("turns") or []:
            if turn.get("editorial_only"):
                continue
            proj_subst += 1
            expected: set[str] = set()
            for claim_id in turn.get("claim_ids") or []:
                expected |= claims.get(str(claim_id), set())
            extra = set(turn.get("evidence_ids") or []) - expected
            if extra:
                proj_viol += 1
                extra_counts[len(extra)] += 1
        substantive += proj_subst
        violations += proj_viol
        rate = (proj_viol / proj_subst * 100.0) if proj_subst else 0.0
        project_rows.append(
            {
                "project_id": project_dir.name,
                "script": script_file.name,
                "claims": len(claims),
                "substantive_turns": proj_subst,
                "violations": proj_viol,
                "rate_pct": round(rate, 2),
            }
        )

    overall_rate = (violations / substantive) if substantive else 0.0
    severity = "blocking" if overall_rate < 0.05 else "high"
    return {
        "projects_scanned": len(project_rows),
        "substantive_turns": substantive,
        "violations": violations,
        "violation_rate": overall_rate,
        "violation_rate_pct": round(overall_rate * 100.0, 2),
        "extra_evidence_distribution": dict(sorted(extra_counts.items())),
        "recommended_severity": severity,
        "projects": project_rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspaces",
        type=Path,
        default=Path("workspaces"),
        help="Workspace root (default: ./workspaces)",
    )
    args = parser.parse_args(argv)
    root = args.workspaces.expanduser().resolve()
    if not root.is_dir():
        print(f"workspaces root not found: {root}", file=sys.stderr)
        return 1
    report = audit_workspace(root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print()
    print(
        f"Gate: {report['violations']}/{report['substantive_turns']} "
        f"({report['violation_rate_pct']}%) → severity={report['recommended_severity']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
