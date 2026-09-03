from __future__ import annotations

import json
from pathlib import Path

from thesisound.services.prompt_prefix_report import (
    IMPLICIT_CACHE_MIN_TOKENS,
    common_prefix_length,
    report_from_run_dirs,
)


def _run_dir(root: Path, name: str, *, stage: str, system: str, user: str) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "request.json").write_text(
        json.dumps({"stage": stage, "raw_prompts_stored": True}), encoding="utf-8"
    )
    (directory / "rendered-prompts.json").write_text(
        json.dumps({"system_prompt": system, "user_prompt": user}), encoding="utf-8"
    )
    return directory


def test_common_prefix_length_handles_the_degenerate_cases() -> None:
    assert common_prefix_length([]) == 0
    assert common_prefix_length(["abc"]) == 3
    assert common_prefix_length(["abc", "abd"]) == 2
    assert common_prefix_length(["abc", "xyz"]) == 0
    # A string that is itself a prefix of the others must not over-report.
    assert common_prefix_length(["ab", "abcd", "abzz"]) == 2


def test_reports_the_shared_prefix_share_per_stage(tmp_path: Path) -> None:
    shared = "S" * 100
    _run_dir(tmp_path, "a", stage="evidence_extraction", system=shared, user="block-one")
    _run_dir(tmp_path, "b", stage="evidence_extraction", system=shared, user="block-two")

    (report,) = report_from_run_dirs(sorted(tmp_path.iterdir()))

    assert report.stage == "evidence_extraction"
    assert report.call_count == 2
    # The system prompt plus the newline plus "block-" is common; the calls
    # diverge at "one"/"two".
    assert report.shared_prefix_chars == len(shared) + 1 + len("block-")
    assert 0.9 < report.shared_share < 1.0


def test_a_stage_whose_variable_part_comes_first_shows_no_shared_prefix(tmp_path: Path) -> None:
    """The failure mode the tool exists to catch: the same material on every
    call, ordered so none of it is a common prefix."""

    constant = "C" * 500
    _run_dir(tmp_path, "a", stage="writer", system="", user=f"SEGMENT-1\n{constant}")
    _run_dir(tmp_path, "b", stage="writer", system="", user=f"SEGMENT-2\n{constant}")

    (report,) = report_from_run_dirs(sorted(tmp_path.iterdir()))

    assert report.shared_prefix_chars == len("\nSEGMENT-")
    assert report.shared_share < 0.05
    assert report.below_floor is True


def test_below_floor_tracks_the_documented_minimum(tmp_path: Path) -> None:
    big = "S" * (IMPLICIT_CACHE_MIN_TOKENS * 4)
    _run_dir(tmp_path, "a", stage="document_map", system=big, user="one")
    _run_dir(tmp_path, "b", stage="document_map", system=big, user="two")

    (report,) = report_from_run_dirs(sorted(tmp_path.iterdir()))

    assert report.approx_prefix_tokens >= IMPLICIT_CACHE_MIN_TOKENS
    assert report.below_floor is False


def test_runs_without_stored_prompts_are_skipped_not_counted(tmp_path: Path) -> None:
    """keep_rendered_prompts defaults off; those runs carry nothing to measure
    and must not be reported as a zero-length prefix."""

    _run_dir(tmp_path, "a", stage="glossary", system="x", user="y")
    bare = tmp_path / "b"
    bare.mkdir()
    (bare / "request.json").write_text(
        json.dumps({"stage": "glossary", "raw_prompts_stored": False}), encoding="utf-8"
    )

    (report,) = report_from_run_dirs(sorted(tmp_path.iterdir()))

    assert report.call_count == 1
    # One call has no second call to share a prefix with.
    assert report.shared_prefix_chars == 0


def test_unreadable_run_directories_do_not_abort_the_report(tmp_path: Path) -> None:
    _run_dir(tmp_path, "a", stage="glossary", system="x", user="y")
    broken = tmp_path / "b"
    broken.mkdir()
    (broken / "request.json").write_text("{not json", encoding="utf-8")
    (broken / "rendered-prompts.json").write_text("{}", encoding="utf-8")

    reports = report_from_run_dirs(sorted(tmp_path.iterdir()))

    assert [item.stage for item in reports] == ["glossary"]
