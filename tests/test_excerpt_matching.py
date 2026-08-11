from __future__ import annotations

from thesisound.services.excerpt_matching import locate_excerpt, locate_excerpt_span


def test_excerpt_matching_repairs_typographic_variants() -> None:
    cases = [
        (
            'She called it “action” in the chapter clearly.',
            'She called it "action" in the chapter clearly.',
        ),
        (
            "The span runs from 1933–1945 in exile abroad.",
            "The span runs from 1933-1945 in exile abroad.",
        ),
        (
            "The argument continues… into the next section.",
            "The argument continues... into the next section.",
        ),
        (
            "Action\u00a0occurs between persons in plurality.",
            "Action occurs between persons in plurality.",
        ),
        (
            "کتاب\u200cها در برابر اشیاء قرار می‌گیرند اینجا.",
            "کتابها در برابر اشیاء قرار می‌گیرند اینجا.",
        ),
        (
            "این یک یای فارسی است در متن بلند.",
            "این یک يای فارسی است در متن بلند.",
        ),
    ]
    for source, model_excerpt in cases:
        located = locate_excerpt(model_excerpt, source)
        assert located == source
        assert located != model_excerpt
        span = locate_excerpt_span(model_excerpt, source)
        assert span == (0, len(source))
        assert source[span[0] : span[1]] == source


def test_excerpt_matching_rejects_invented_text() -> None:
    source = "Action occurs directly between persons in the public realm."
    assert locate_excerpt("This sentence is invented entirely.", source) is None
    assert locate_excerpt_span("This sentence is invented entirely.", source) is None


def test_locate_excerpt_span_mid_string_and_digits() -> None:
    source = "پیش‌گفتار ۱۲۳ سپس ادامهٔ متن."
    excerpt = "123 سپس"
    span = locate_excerpt_span(excerpt, source)
    assert span is not None
    start, end = span
    assert "۱۲۳" in source[start:end] or "123" in source[start:end]
    assert locate_excerpt(excerpt, source) == source[start:end]


def test_locate_excerpt_span_zwnj_variant() -> None:
    source = "کتاب\u200cها مهم هستند در این بحث بلند."
    excerpt = "کتابها مهم هستند"
    span = locate_excerpt_span(excerpt, source)
    assert span is not None
    assert locate_excerpt(excerpt, source) == source[span[0] : span[1]]
