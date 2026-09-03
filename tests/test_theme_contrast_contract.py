"""Every theme token must clear WCAG AA on every ground it actually renders on.

The root cause this locks down: `--muted-light` and `--muted` were tuned against
`--paper` alone, then used on five different grounds, so they cleared 4.5:1 in
the one place they were checked and failed in the other four. Nothing in the
system compared a token against all four themes either, which is how olive's
`--accent` sat at 3.18:1 while the other three themes were comfortably above 5.

Pairs below come from a live sweep of twelve pages in all four themes, so this
is a record of what the interface really paints, not a cartesian product.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS = Path(__file__).parents[1] / "src" / "thesisound" / "web" / "static" / "app.css"
THEMES = ("cobalt", "olive", "wood", "slate")

AA_NORMAL = 4.5
#: WCAG 1.4.11 for the visual boundary of a control, and 1.4.3's large-text step.
NON_TEXT = 3.0

#: (foreground token, ground token, floor, what renders in this pair)
REQUIRED: tuple[tuple[str, str, float, str], ...] = (
    ("muted", "paper", AA_NORMAL, "supporting copy on a sheet"),
    ("muted", "paper-raised", AA_NORMAL, "metadata inside a card"),
    ("muted", "paper-muted", AA_NORMAL, "notice body copy"),
    ("muted", "paper-strong", AA_NORMAL, "stage copy on the active row"),
    ("muted-light", "paper", AA_NORMAL, "peripheral metadata"),
    ("muted-light", "paper-muted", AA_NORMAL, "the workflow rail lock reason"),
    ("ink", "paper", AA_NORMAL, "body text"),
    ("ink-soft", "paper", AA_NORMAL, "field labels"),
    ("brand", "paper", AA_NORMAL, "link text and the focused field border"),
    ("brand-strong", "paper", AA_NORMAL, "link text on paper"),
    ("accent", "paper", AA_NORMAL, "the running label — the one 'work is happening' signal"),
    ("accent", "paper-raised", AA_NORMAL, "the running label inside a card"),
    ("success", "success-wash", AA_NORMAL, "a passing status label"),
    ("warning", "warning-wash", AA_NORMAL, "a warning status label"),
    ("danger", "danger-wash", AA_NORMAL, "an error status label"),
    ("info", "info-wash", AA_NORMAL, "an informational status label"),
    ("warning", "paper-strong", AA_NORMAL, "the readiness status label"),
    ("paper", "header", AA_NORMAL, "the wordmark on the app bar"),
    ("brand-soft", "header", AA_NORMAL, "quiet header text"),
    # Non-text: the field fill is within 1.1:1 of the sheet behind it, so this
    # border is the only thing identifying the control.
    ("border-strong", "paper", NON_TEXT, "the sole visual boundary of every field and chip"),
    # A disabled button is drawn as --paper-strong on --paper-raised, which is within
    # 1.1:1 of its surroundings, so this border is the whole control again.
    ("border-strong", "paper-raised", NON_TEXT, "the boundary of a disabled control on a card"),
    # --disabled marks genuinely inactive components, which SC 1.4.3 exempts, so
    # it carries the non-text floor rather than 4.5. It must never be used for
    # live content; see the transcript speaker label, which uses --muted.
    ("disabled", "paper-muted", NON_TEXT, "locked rail steps (inactive components)"),
)


def _palette_block(css: str) -> str:
    match = re.search(r"^:root \{(.*?)\n\}", css, re.S | re.M)
    assert match, "no palette block at the top of the stylesheet"
    return match.group(1)


def _theme_block(css: str, theme: str) -> str:
    if theme == "cobalt":
        pattern = r'html\[data-theme="cobalt"\],\s*:root \{(.*?)\n\}'
    else:
        pattern = rf'html\[data-theme="{theme}"\] \{{(.*?)\n\}}'
    match = re.search(pattern, css, re.S)
    assert match, f"no theme block for {theme}"
    return match.group(1)


def _tokens(theme: str) -> dict[str, str]:
    """Resolved hexes for one theme, following the palette indirection.

    A token may name a shared palette constant instead of a literal (--brand does,
    so the theme menu's four swatches and the theme itself cannot drift apart).
    What matters to a contrast floor is the colour that renders, so resolve first.
    """
    css = CSS.read_text(encoding="utf-8")
    palette = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6});", _palette_block(css)))
    block = _theme_block(css, theme)
    tokens = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6});", block))
    for name, ref in re.findall(r"--([a-z-]+):\s*var\(--([a-z-]+)\);", block):
        assert ref in palette, f"--{name} points at --{ref}, which no palette defines"
        tokens[name] = palette[ref]
    return tokens


def _luminance(value: str) -> float:
    v = value.lstrip("#")
    channels = []
    for i in (0, 2, 4):
        c = int(v[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize(("fg", "bg", "floor", "usage"), REQUIRED)
def test_token_pair_clears_its_floor(
    theme: str, fg: str, bg: str, floor: float, usage: str
) -> None:
    tokens = _tokens(theme)
    assert fg in tokens, f"--{fg} missing from {theme}"
    assert bg in tokens, f"--{bg} missing from {theme}"
    ratio = contrast(tokens[fg], tokens[bg])
    assert ratio >= floor, (
        f"{theme}: --{fg} ({tokens[fg]}) on --{bg} ({tokens[bg]}) is {ratio:.2f}:1, "
        f"needs {floor}:1 — {usage}"
    )


@pytest.mark.parametrize("theme", THEMES)
def test_recession_ladder_stays_ordered(theme: str) -> None:
    """muted recedes to muted-light recedes to disabled, in that order.

    Raising all three to clear AA is only correct if they stay distinguishable;
    a ladder that collapses would meet the contrast floor and lose the meaning.
    """
    tokens = _tokens(theme)
    paper = tokens["paper"]
    muted, light, disabled = (
        contrast(tokens[t], paper) for t in ("muted", "muted-light", "disabled")
    )
    assert muted > light > disabled, (
        f"{theme}: recession ladder out of order — "
        f"muted={muted:.2f}, muted-light={light:.2f}, disabled={disabled:.2f}"
    )


def test_every_token_exists_in_every_theme() -> None:
    """A token defined in one theme and missing in another silently inherits."""
    per_theme = {theme: set(_tokens(theme)) for theme in THEMES}
    reference = per_theme["cobalt"]
    for theme, names in per_theme.items():
        assert names == reference, f"{theme} token set differs: {reference ^ names}"
