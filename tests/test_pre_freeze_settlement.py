from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _checker_module():
    path = (
        Path(__file__).parents[1]
        / "benchmarks"
        / "eval"
        / "v1"
        / "tools"
        / "check_pre_freeze_settlement.py"
    )
    spec = importlib.util.spec_from_file_location("pre_freeze_checker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_controlled_pair_token_estimate_is_derived_from_r13(tmp_path: Path) -> None:
    module = _checker_module()
    report_path = Path("validation/r13/shared.json")
    absolute_report = tmp_path / report_path
    absolute_report.parent.mkdir(parents=True)
    package = {
        "packages": {
            case_id: {
                "sources": [
                    {
                        "ingested_fixture": "private/shared.pdf",
                        "r13_report": report_path.as_posix(),
                    }
                ]
            }
            for case_id in ("C10", "C11")
        }
    }

    absolute_report.write_text(
        json.dumps({"metrics": {"token_estimate": 32_032}}),
        encoding="utf-8",
    )
    first, source = module.derive_controlled_pair_fixture_tokens(tmp_path, package)

    absolute_report.write_text(
        json.dumps({"metrics": {"token_estimate": 28_500}}),
        encoding="utf-8",
    )
    second, _ = module.derive_controlled_pair_fixture_tokens(tmp_path, package)

    assert source == report_path.as_posix()
    assert first == 32_032
    assert second == 28_500
    assert second != first


def test_pinned_pair_has_no_stale_fixture_token_constant() -> None:
    root = Path(__file__).parents[1] / "benchmarks" / "eval" / "v1" / "pre-freeze"
    configs = json.loads((root / "pinned-case-configs.json").read_text(encoding="utf-8"))

    assert "shared_fixture_token_estimate" not in configs["controlled_pair"]
