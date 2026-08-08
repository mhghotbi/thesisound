from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_ARABIC_TO_PERSIAN = str.maketrans({
    "ي": "ی",
    "ى": "ی",
    "ك": "ک",
    "ۀ": "هٔ",
    "ة": "ه",
    "ؤ": "و",
})
_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_ASCII_DIGITS = "0123456789"
_DIGIT_MAP = str.maketrans(
    _PERSIAN_DIGITS + _ARABIC_DIGITS,
    _ASCII_DIGITS + _ASCII_DIGITS,
)
_DIACRITICS = re.compile(r"[\u064b-\u065f\u0670\u06d6-\u06ed]")
_SPACE = re.compile(r"\s+")
_PUNCT_SPACE = re.compile(r"\s+([،؛؟!,.:%\)\]\}])")
_OPEN_SPACE = re.compile(r"([\(\[\{])\s+")


def normalize_persian(text: str, *, preserve_zwnj: bool = True) -> str:
    value = unicodedata.normalize("NFKC", text or "")
    value = value.translate(_ARABIC_TO_PERSIAN).translate(_DIGIT_MAP)
    value = _DIACRITICS.sub("", value)
    value = value.replace("\u200f", "").replace("\u200e", "")
    if not preserve_zwnj:
        value = value.replace("\u200c", " ")
    value = _SPACE.sub(" ", value).strip()
    value = _PUNCT_SPACE.sub(r"\1", value)
    value = _OPEN_SPACE.sub(r"\1", value)
    return value


def levenshtein(a: list[str], b: list[str]) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, start=1):
        current = [i]
        for j, right in enumerate(b, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (left != right),
                )
            )
        previous = current
    return previous[-1]


@dataclass(frozen=True)
class TextMetrics:
    cer: float
    wer: float
    exact: bool
    reference_characters: int
    reference_words: int


def score_text(reference: str, prediction: str) -> TextMetrics:
    ref = normalize_persian(reference)
    hyp = normalize_persian(prediction)
    ref_chars = list(ref)
    hyp_chars = list(hyp)
    ref_words = ref.split()
    hyp_words = hyp.split()
    return TextMetrics(
        cer=levenshtein(ref_chars, hyp_chars) / max(len(ref_chars), 1),
        wer=levenshtein(ref_words, hyp_words) / max(len(ref_words), 1),
        exact=ref == hyp,
        reference_characters=len(ref_chars),
        reference_words=len(ref_words),
    )
