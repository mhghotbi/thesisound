"""Deterministic pre-run token estimates (`10b` B1.8).

This step only exposes ``estimate_tokens``. Pricing from
``config/model-pricing.toml`` arrives later (step 18 / P3).
"""

from __future__ import annotations

# Initial ledger-calibrated multipliers (`10b` B1.8).
MAP_TOKEN_MULTIPLIER = 1.0
CELLS_TOKEN_MULTIPLIER = 1.1


def estimate_tokens(chapter_tokens: int) -> dict[str, int]:
    """Input-token estimate per concept-map model pass, from in-scope chapter tokens.

    ``map`` is Pass 1 (document map, 1.0×). ``cells`` is Pass 2 (1.1×). Other
    B1.8 stages (extraction, plan/script/verify) are not estimated here.
    """

    if chapter_tokens < 0:
        raise ValueError("chapter_tokens must be >= 0.")
    mapped = round(chapter_tokens * MAP_TOKEN_MULTIPLIER)
    cells = round(chapter_tokens * CELLS_TOKEN_MULTIPLIER)
    return {"map": mapped, "cells": cells, "total": mapped + cells}
