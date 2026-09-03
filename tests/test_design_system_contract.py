"""DESIGN.md is only a design system if the stylesheet cannot quietly leave it.

Every rule here was a live gap between the document and what actually rendered:
a type ladder with four sizes off it, two weights the system never declared, a
fifth breakpoint, a second table vocabulary, a third shadow intent, and four
brand hexes written twice. None of them is visible as a bug — which is exactly
why they need a test rather than an eye.

The tests read the stylesheet as text on purpose. A rule that only fires in a
browser cannot fail in CI, and every one of these regressions arrives as a line
someone adds to app.css.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).parents[1] / "src" / "thesisound" / "web"
CSS_PATH = WEB / "static" / "app.css"
TEMPLATES = WEB / "templates"
CSS = CSS_PATH.read_text(encoding="utf-8")

RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)


COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _rules() -> list[tuple[str, str]]:
    """(selector, body) for every declaration block, at-rule wrappers skipped."""
    return [
        (" ".join(COMMENT.sub("", m.group(1)).split()), m.group(2))
        for m in RULE.finditer(CSS)
    ]


def _line_of(needle: str) -> int:
    return CSS[: CSS.index(needle)].count("\n") + 1


# --- F-26: the ladder -----------------------------------------------------------

#: DESIGN.md §Typography: 35 → 26 → 17 → 16 → 15 → 14 → 13 → 12 → 11, where the
#: top two steps are fluid and everything below them is fixed.
LADDER = {
    "clamp(24px, 3vw, 35px)",  # Display
    "clamp(20px, 2.4vw, 26px)",  # Headline
    "clamp(14px, 1.5vw, 16px)",  # Body→Title, both endpoints on the ladder
    "17px",
    "16px",
    "15px",
    "14px",
    "13px",
    "12px",
    "11px",
    "inherit",
}


def test_every_font_size_is_a_step_on_the_ladder() -> None:
    """9px, 24px and `.92em` all shipped; the last one resolved differently per parent."""
    sizes = re.findall(r"font-size:\s*([^;}]+)", CSS)
    shorthand = re.findall(r"font:\s*\d{3}\s+([\d.]+px)", CSS)
    off = sorted({s.strip() for s in sizes + shorthand} - LADDER)
    assert off == [], off


def test_nothing_sizes_type_relatively() -> None:
    """`code { font-size: .92em }` was 10.12px inside a caption and 13.8px in body text.

    An identifier read character by character does not get to be a fraction of
    whatever happens to contain it.
    """
    relative = [
        s.strip()
        for s in re.findall(r"font-size:\s*([^;}]+)", CSS)
        if re.search(r"\d\s*(?:r?em|%)\s*$", s.strip())
    ]
    assert relative == [], relative


def test_no_size_falls_below_the_persian_floor() -> None:
    """11px is the floor of the whole system, and a numeral is not an exception."""
    px = [int(m) for m in re.findall(r"font-size:\s*(\d+)px", CSS)]
    px += [int(m) for m in re.findall(r"font:\s*\d{3}\s+(\d+)px", CSS)]
    assert min(px) >= 11, sorted(px)[:5]


# --- F-31: the weights ----------------------------------------------------------


def test_weight_500_is_not_a_weight_in_this_system() -> None:
    """DESIGN.md declares 400 for reading, 700 for labels and controls, 800 for titles.

    26 selectors carried 500 anyway. The font ships the face, so nothing looked
    broken — the ladder had simply stopped being a ladder.
    """
    assert "font-weight: 500" not in CSS


def test_weight_600_belongs_to_the_11px_caption_and_nowhere_else() -> None:
    """600 is Caption's weight. Used at any other size it is a sixth step."""
    for selector, body in _rules():
        if re.search(r"font-weight:\s*600", body):
            size = re.search(r"font-size:\s*([^;}]+)", body)
            if size is None:
                # Inherits its size; the only such rule sits inside an 11px rail.
                assert "workflow-rail__rewind" in selector, selector
                continue
            assert size.group(1).strip() == "11px", (selector, size.group(1))


def test_a_bold_element_that_should_not_be_bold_says_so() -> None:
    """Removing a 500 from a `<strong>` hands it the UA default, which is 700.

    The stage name is Dense (400) and the current row's is 700; letting the base
    fall back to bold would have made every stage look like the current one.
    """
    rule = re.search(r"\.stage-row__copy strong \{([^}]*)\}", CSS)
    assert rule and "font-weight: 400" in rule.group(1), rule and rule.group(1)
    assert ".stage-row.is-current .stage-row__copy strong" in CSS


# --- F-27: wide content scrolls inside its own container ------------------------


def test_every_table_scrolls_inside_its_own_container() -> None:
    """15 of 19 tables had no wrapper, and they carry trace ids and ISO timestamps.

    PRODUCT.md: the whole workflow must be completable on a phone, and the page
    body never scrolls sideways. A table without `.table-wrap` makes it do so.
    """
    unwrapped: list[str] = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        html = path.read_text(encoding="utf-8")
        for match in re.finditer(r"<table\b", html):
            before = html[: match.start()]
            opens = before.count('<div class="table-wrap">')
            # Every wrap in this codebase closes before the next one opens, so a
            # table is inside one exactly when an odd number of them is still open.
            closes = before.count("</div>", before.rfind('<div class="table-wrap">') + 1)
            if opens == 0 or closes > 0:
                line = before.count("\n") + 1
                unwrapped.append(f"{path.relative_to(TEMPLATES)}:{line}")
    assert unwrapped == [], unwrapped


def test_the_scroll_container_is_the_only_one_of_its_kind() -> None:
    """`.obs-table` grew a second, breakpoint-gated one. There is one wrapper."""
    assert ".table-wrap { max-width: 100%; overflow-x: auto; }" in CSS
    assert "obs-table" not in CSS


# --- F-28 / F-32: no island keeps its own copy of the system --------------------


def test_the_stylesheet_declares_exactly_the_three_system_breakpoints() -> None:
    """A fifth at 720px existed for two observability elements, 40px off the system."""
    widths = sorted({int(w) for w in re.findall(r"@media \(max-width: (\d+)px\)", CSS)})
    assert widths == [470, 760, 980], widths


def test_muted_text_uses_the_token_rather_than_opacity() -> None:
    """`opacity: .7` over 11px text silently undercuts every number the token guarantees.

    The contrast contract validates --muted against its grounds; an opacity layer
    on top of it means the measured value is not the rendered one.
    """
    for selector, body in _rules():
        if "opacity:" not in body or "font-size" not in body:
            continue
        opacity = re.search(r"opacity:\s*([\d.]+)", body)
        assert opacity and float(opacity.group(1)) == 1, (selector, body.strip())


# --- F-30: two shadows, and the difference between them means something ---------


def test_there_is_no_third_shadow() -> None:
    """DESIGN.md: sheet or floater; anything else needs a hairline, not depth."""
    depths = {
        s.strip()
        for s in re.findall(r"box-shadow:\s*([^;}]+)", CSS)
        if not s.strip().startswith("0 0 0")  # rings and hairlines, not depth
    }
    assert depths <= {"var(--shadow)", "var(--shadow-soft)", "none"}, depths


def test_the_fixed_mobile_navigation_is_a_floater() -> None:
    """Page content passes underneath it, which is the whole of the Floating Test."""
    rule = re.search(r"\.mobile-nav \{([^}]*)\}", CSS)
    assert rule and "box-shadow: var(--shadow)" in rule.group(1)


def test_the_audio_player_is_a_sheet_like_its_siblings() -> None:
    """It was the one container that opted out of the shadow and drew a --brand box.

    DESIGN.md names it a sheet, and borders enclose with --border-strong; --brand
    is not a border colour anywhere else in the system.
    """
    rule = re.search(r"\.audio-player \{([^}]*)\}", CSS)
    assert rule is not None
    assert "box-shadow" not in rule.group(1), rule.group(1)
    assert "border" not in rule.group(1), rule.group(1)
    group = re.search(r"\.audio-player,\n\.empty-state \{([^}]*)\}", CSS)
    assert group and "box-shadow: var(--shadow-soft)" in group.group(1)


# --- F-29: borders are quiet ----------------------------------------------------


def test_no_separator_is_heavier_than_the_system_allows() -> None:
    """A 3px --ink rule sat under the header, above every page — three times any other.

    Borders separate and enclose, and DESIGN.md says they are quiet: 1px, with
    1.5px where a control has to read as enclosed and 2px to mark a current item.
    The one exception the document itself grants is the stage rail, below.
    """
    heavy: list[tuple[str, str]] = []
    for selector, body in _rules():
        for prop, width in re.findall(r"border(-[a-z-]+)?:\s*([\d.]+)px", body):
            if "radius" in (prop or "") or float(width) <= 2:
                continue
            heavy.append((selector, f"border{prop or ''}: {width}px"))
    assert heavy == [(".stage-row.is-current", "border-inline-start: 3px")], heavy


def test_the_only_3px_rail_is_the_row_the_reader_is_standing_on() -> None:
    """The Current-Row Rule: a leading-edge rail marks the current row and nothing else.

    DESIGN.md grants the stage rail its 3px explicitly, and requires the rail to
    be redundant with ground, weight and state word — never the only signal.
    """
    rule = re.search(r"\.stage-row\.is-current \{([^}]*)\}", CSS)
    assert rule is not None
    body = rule.group(1)
    assert "border-inline-start: 3px" in body
    assert "background: var(--paper-strong)" in body, body
    bolder = ".stage-row.is-current .stage-row__copy strong"
    assert f"{bolder} {{ color: var(--ink); font-weight: 700; }}" in CSS


# --- a disclosure summary is a control, so it carries the control floor --------


def test_every_disclosure_summary_meets_the_44px_target() -> None:
    """Two of them shipped at `min-height: 32px`, one on a page a reader reaches.

    PRODUCT.md binds a 44px minimum in the smallest dimension. Phase 2 swept the
    rendered pages and these two sat behind conditions that were off at the time,
    which is exactly the failure mode a source-level check does not have.
    """
    for selector, body in _rules():
        # The rule that makes the summary a control is the one that gives it a
        # pointer; overrides and hover states inherit the box from it.
        if not selector.endswith("> summary") or "cursor: pointer" not in body:
            continue
        height = re.search(r"min-height:\s*(\d+)px", body)
        assert height and int(height.group(1)) >= 44, (selector, body.strip())
        assert body.count("min-height") == 1, selector


# --- F-33: containers do not nest ----------------------------------------------

CARDS = frozenset(
    {"card", "form-sheet", "data-panel", "audio-player", "empty-state", "interpretation"}
)


def test_no_card_sits_inside_another_card() -> None:
    """`new.html` put a .data-panel inside a .form-sheet — same ground, same radius,
    same shadow. It broke the rule and was invisible while doing it."""
    tag = re.compile(r"<(\w+)([^>]*)>|</(\w+)>")
    void = {"br", "img", "input", "hr", "meta", "link", "path", "circle", "source"}
    nested: list[str] = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        html = path.read_text(encoding="utf-8")
        stack: list[tuple[str, frozenset[str]]] = []
        for m in tag.finditer(html):
            if m.group(3):
                while stack and stack[-1][0] != m.group(3):
                    stack.pop()
                if stack:
                    stack.pop()
                continue
            name, attrs = m.group(1), m.group(2)
            if name in void or attrs.rstrip().endswith("/"):
                continue
            found = re.search(r'class="([^"]*)"', attrs)
            hit = frozenset(found.group(1).split()) & CARDS if found else frozenset()
            if hit and any(outer for _, outer in stack):
                line = html[: m.start()].count("\n") + 1
                nested.append(f"{path.relative_to(TEMPLATES)}:{line} {sorted(hit)}")
            stack.append((name, hit))
    assert nested == [], nested


# --- F-34: one source for a colour ---------------------------------------------

THEMES = ("cobalt", "olive", "wood", "slate")


@pytest.mark.parametrize("theme", THEMES)
def test_a_theme_swatch_cannot_drift_from_the_theme_it_names(theme: str) -> None:
    """The four dots are on screen together, so none of them can read --brand.

    They repeated the hex instead, which meant re-branding a theme silently left
    its own dot behind. Both now read one named token.
    """
    swatch = re.search(
        rf'\[data-theme-value="{theme}"\] \.theme-option__swatch \{{ background: ([^;]+);',
        CSS,
    )
    assert swatch, theme
    assert swatch.group(1).strip() == f"var(--brand-{theme})"

    block = re.search(rf'html\[data-theme="{theme}"\][^{{]*\{{(.*?)\n\}}', CSS, re.S)
    assert block, theme
    brand = re.search(r"\n  --brand:\s*([^;]+);", block.group(1))
    assert brand and brand.group(1).strip() == f"var(--brand-{theme})"


def test_the_brand_hexes_are_written_once() -> None:
    literals = re.findall(r"--brand-(?:cobalt|olive|wood|slate):\s*(#[0-9a-f]{6})", CSS)
    assert len(literals) == 4
    assert len(set(literals)) == 4, literals
    # The place the repeat used to live. A literal anywhere in a swatch rule is
    # the drift this test exists to catch.
    assert not re.search(r"\.theme-option__swatch \{ background: #", CSS)
