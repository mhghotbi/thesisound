
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

PageRoute = Literal["native", "lightweight_ocr", "layout_ocr", "vlm_fallback"]
ScriptKind = Literal["persian", "latin", "mixed", "unknown"]

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]")
_MULTI_COLUMN = re.compile(r"(?:^|\n).{0,60}\s{8,}.{0,60}(?:\n|$)")
_PERSIAN = set("پچژگک")


class OcrPagePlan(BaseModel):
    page_number: int = Field(ge=1)
    route: PageRoute
    script_hint: ScriptKind = "unknown"
    reasons: list[str] = Field(default_factory=list)


def native_text_is_reliable(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 80:
        return False
    printable = sum(char.isprintable() or char.isspace() for char in stripped) / len(stripped)
    if printable < 0.97 or _CONTROL.search(stripped):
        return False
    words = re.findall(r"\w+", stripped, flags=re.UNICODE)
    return len(words) >= 12


def likely_complex_layout(text: str, *, explicit_signal: bool = False) -> bool:
    if explicit_signal:
        return True
    return bool(text and _MULTI_COLUMN.search(text))


def detect_script(text: str) -> ScriptKind:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return "unknown"
    arabic = sum("\u0600" <= char <= "\u06ff" for char in letters)
    latin = sum(("a" <= char.lower() <= "z") for char in letters)
    total = max(1, arabic + latin)
    if arabic / total >= 0.75:
        return "persian" if any(char in _PERSIAN for char in text) else "persian"
    if latin / total >= 0.75:
        return "latin"
    if arabic and latin:
        return "mixed"
    return "unknown"


def plan_page(
    page_number: int,
    *,
    native_text: str,
    is_image: bool = False,
    explicit_complex_layout: bool = False,
) -> OcrPagePlan:
    script = detect_script(native_text)
    reliable = native_text_is_reliable(native_text)
    complex_layout = likely_complex_layout(native_text, explicit_signal=explicit_complex_layout)
    if reliable and not complex_layout and not is_image:
        return OcrPagePlan(
            page_number=page_number,
            route="native",
            script_hint=script,
            reasons=["The page has a healthy extractable text layer."],
        )
    if complex_layout:
        return OcrPagePlan(
            page_number=page_number,
            route="layout_ocr",
            script_hint=script,
            reasons=["The page needs block detection and explicit reading-order recovery."],
        )
    return OcrPagePlan(
        page_number=page_number,
        route="lightweight_ocr",
        script_hint=script,
        reasons=["The page has no reliable text layer and can use lightweight OCR first."],
    )
