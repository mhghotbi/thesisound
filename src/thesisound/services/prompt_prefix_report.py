"""Measure how much of a stage's prompt is a prefix every call shares.

Gemini bills a cached prefix at a fraction of the standard input rate, but only
the *longest common prefix* of two requests can cache, and only once that prefix
clears the model's minimum. Both are properties of how a prompt template orders
its blocks, and neither is visible from token counts alone: a stage can re-send
the same 4,000 tokens on every call and still cache nothing, because the part
that repeats is scattered behind material that changes.

This reads the rendered prompts a run stores when ``keep_rendered_prompts`` is
on and reports, per stage, the share of input that a cache could actually hold.
Run one real pipeline with that setting enabled, then point this at the project:
the ``shared`` column is the ceiling on what prefix caching can save, and
``below_floor`` says whether the prefix is even large enough to be eligible.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# Gemini's documented minimum for a cacheable prefix on the 3.x Flash family.
# A shared prefix shorter than this cannot cache at all, however often it repeats.
IMPLICIT_CACHE_MIN_TOKENS = 4_096

# The renderer emits ASCII-heavy JSON and Persian prose; 3.5 characters per token
# is a deliberately rough divisor, used only to compare against the floor above.
# Anything that turns on a real decision should use the provider's token counter.
_CHARS_PER_TOKEN = 3.5


@dataclass(frozen=True)
class StagePrefixReport:
    """One stage's shared-prefix measurement."""

    stage: str
    call_count: int
    shared_prefix_chars: int
    mean_prompt_chars: int

    @property
    def shared_share(self) -> float:
        """Fraction of an average call's prompt that every call shares."""

        if not self.mean_prompt_chars:
            return 0.0
        return min(self.shared_prefix_chars / self.mean_prompt_chars, 1.0)

    @property
    def approx_prefix_tokens(self) -> int:
        return int(self.shared_prefix_chars / _CHARS_PER_TOKEN)

    @property
    def below_floor(self) -> bool:
        """True when the shared prefix is too short to be cacheable at all."""

        return self.approx_prefix_tokens < IMPLICIT_CACHE_MIN_TOKENS


def common_prefix_length(values: list[str]) -> int:
    """Length of the longest prefix every string in ``values`` shares."""

    if not values:
        return 0
    shortest = min(values, key=len)
    for index, char in enumerate(shortest):
        if any(value[index] != char for value in values):
            return index
    return len(shortest)


def report_from_run_dirs(run_dirs: list[Path]) -> list[StagePrefixReport]:
    """Build one report per stage from ``model-runs/*`` directories.

    Directories without a ``rendered-prompts.json`` are skipped: they were
    written with ``keep_rendered_prompts`` off and carry no prompt to measure.
    """

    prompts_by_stage: dict[str, list[str]] = defaultdict(list)
    for directory in run_dirs:
        rendered = directory / "rendered-prompts.json"
        request = directory / "request.json"
        if not rendered.is_file() or not request.is_file():
            continue
        try:
            stage = json.loads(request.read_text(encoding="utf-8")).get("stage")
            payload = json.loads(rendered.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not stage:
            continue
        # The system instruction is sent on every call and sits ahead of the
        # user prompt, so it is part of the prefix a cache would hold.
        prompts_by_stage[stage].append(
            f"{payload.get('system_prompt', '')}\n{payload.get('user_prompt', '')}"
        )

    reports = [
        StagePrefixReport(
            stage=stage,
            call_count=len(prompts),
            shared_prefix_chars=common_prefix_length(prompts) if len(prompts) > 1 else 0,
            mean_prompt_chars=round(sum(len(p) for p in prompts) / len(prompts)),
        )
        for stage, prompts in prompts_by_stage.items()
        if prompts
    ]
    reports.sort(key=lambda item: (-item.call_count, item.stage))
    return reports
