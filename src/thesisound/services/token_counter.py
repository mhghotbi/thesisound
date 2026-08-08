from __future__ import annotations

import math


def estimate_tokens(text: str) -> int:
    """Estimate model tokens without coupling core logic to one tokenizer.

    The heuristic is deliberately conservative for mixed Persian/English text.
    It is used only for chunk-size control; provider usage metadata remains the
    source of truth for billing and actual token counts.
    """

    normalized = " ".join(text.split())
    if not normalized:
        return 0
    return max(1, math.ceil(len(normalized) / 3.5))
