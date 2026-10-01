"""The script page's turn grid must collapse cleanly to one column on a phone.

On desktop a transcript turn is a two-column grid (speaker | text) and its later
rows are pinned to column 2. Below 760px the grid becomes one column, so every
row pinned to column 2 has to be moved back to column 1. A row left behind makes
the browser invent an implicit second column sized to that row's content; the
real column shrinks to ~22px and whatever sits in it — the «این گفته از کجا آمد؟»
evidence toggle — breaks one word per line.
"""

import re
from pathlib import Path

CSS = Path(__file__).parents[1] / "src" / "thesisound" / "web" / "static" / "app.css"
TURN_ROW = re.compile(r"\.(?:transcript-turn__[a-z-]+|evidence-drawer)\b")


def _media_block(css: str, query: str) -> str:
    start = css.index(query)
    depth = 0
    for i in range(css.index("{", start), len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[start:i]
    raise AssertionError(f"unterminated {query}")


def _selectors_setting(css: str, declaration: str) -> set[str]:
    found: set[str] = set()
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if re.search(declaration, body):
            for selector in selectors.split(","):
                if TURN_ROW.fullmatch(selector.strip()):
                    found.add(selector.strip())
    return found


def test_every_turn_row_pinned_to_column_two_returns_to_column_one_on_a_phone() -> None:
    css = CSS.read_text(encoding="utf-8")
    mobile = _media_block(css, "@media (max-width: 760px)")
    desktop = css.replace(mobile, "")

    pinned = _selectors_setting(desktop, r"grid-column:\s*2\b")
    reset = _selectors_setting(mobile, r"grid-column:\s*1\b")

    assert ".transcript-turn__grounding" in pinned, "the source line sits under the text on desktop"
    missing = sorted(pinned - reset)
    assert not missing, f"rows pinned to column 2 but not reset on mobile: {missing}"
