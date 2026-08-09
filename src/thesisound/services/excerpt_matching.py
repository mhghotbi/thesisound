from __future__ import annotations

import unicodedata

_QUOTE_MAP = {
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u201f": '"',
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
}
_DASH_CHARS = frozenset(
    {
        "\u2010",
        "\u2011",
        "\u2012",
        "\u2013",
        "\u2014",
        "\u2015",
        "\u2212",
    }
)
_SPACE_LIKE = frozenset(
    {
        "\u00a0",  # NBSP
        "\u2007",  # figure space
        "\u2008",  # punctuation space
        "\u2009",  # thin space
        "\u202f",  # narrow no-break space
    }
)
_DROP_CHARS = frozenset(
    {
        "\u00ad",  # soft hyphen
        "\u200b",  # zero-width space
        "\u200c",  # ZWNJ
        "\u200d",  # ZWJ
        "\u200e",  # LRM
        "\u200f",  # RLM
        "\ufeff",  # BOM
    }
)
_LETTER_MAP = {
    "ي": "ی",
    "ك": "ک",
    "ة": "ه",
}


def normalize_for_match(text: str) -> tuple[str, list[int]]:
    """Return (normalized, index_map) where index_map[i] is the offset in
    `text` that produced normalized[i]."""

    pieces: list[str] = []
    index_map: list[int] = []
    for index, char in enumerate(text):
        if char in _DROP_CHARS or "\u064b" <= char <= "\u0652":
            continue
        if char == "\u2026":
            replacement = "..."
        elif char in _QUOTE_MAP:
            replacement = _QUOTE_MAP[char]
        elif char in _DASH_CHARS:
            replacement = "-"
        elif char in _SPACE_LIKE or char.isspace():
            replacement = " "
        elif char in _LETTER_MAP:
            replacement = _LETTER_MAP[char]
        else:
            digit = _fold_digit(char)
            replacement = digit if digit is not None else char
        for folded_char in replacement.casefold():
            pieces.append(folded_char)
            index_map.append(index)

    collapsed_chars: list[str] = []
    collapsed_map: list[int] = []
    previous_space = False
    for char, source_index in zip(pieces, index_map, strict=True):
        if char == " ":
            if previous_space:
                continue
            previous_space = True
        else:
            previous_space = False
        collapsed_chars.append(char)
        collapsed_map.append(source_index)

    start = 0
    end = len(collapsed_chars)
    while start < end and collapsed_chars[start] == " ":
        start += 1
    while end > start and collapsed_chars[end - 1] == " ":
        end -= 1
    return "".join(collapsed_chars[start:end]), collapsed_map[start:end]


def locate_excerpt(excerpt: str, source_text: str) -> str | None:
    needle, _ = normalize_for_match(excerpt)
    haystack, index_map = normalize_for_match(source_text)
    if not needle:
        return None
    position = haystack.find(needle)
    if position == -1:
        return None
    start = index_map[position]
    end = index_map[position + len(needle) - 1] + 1
    return source_text[start:end]


def _fold_digit(char: str) -> str | None:
    try:
        return str(unicodedata.digit(char))
    except (TypeError, ValueError):
        return None
