from __future__ import annotations

from thesisound.services.excerpt_matching import locate_excerpt


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


def test_excerpt_matching_rejects_invented_text() -> None:
    source = "Action occurs directly between persons in the public realm."
    assert locate_excerpt("This sentence is invented entirely.", source) is None
