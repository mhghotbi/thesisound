from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
WEB_ROOT = ROOT / "src" / "thesisound" / "web"
TEMPLATES_ROOT = WEB_ROOT / "templates"

FORBIDDEN_UI_TERMS = (
    "Thesisound",
    "maqal",
    "پروژه",
    "اپیزود",
    "سناریو",
    "هدف و برداشت",
    "در حال پردازش",
    "پردازش منابع",
    "ارزیابی پوشش",
    "پوشش منابع",
    "حکم پوشش",
    "نکته‌های پوشش",
    "شواهد",
    "ادعا",
    "بلوک معنایی",
    "بلوک‌های معنایی",
    "تولید صوت",
    "کنترل صوت",
    "ساخت صوت",
    "متن اپیزود",
    "طرح اپیزود",
)

BROKEN_HALF_SPACES = (
    "به صورت",
    "می شود",
    "می شوند",
    "قابل استفاده",
    "انتخاب شده",
    "انتخاب شده‌اند",
    "تأیید شده",
    "تأیید شده‌اند",
    "تکمیل شده",
    "بایگانی شده",
    "ساخته شده",
    "ذخیره شده",
    "یک بار مصرف",
)


def _python_strings(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _ui_strings() -> list[tuple[Path, int, str]]:
    values: list[tuple[Path, int, str]] = []
    for path in sorted(TEMPLATES_ROOT.rglob("*.html")):
        values.extend(
            (path, number, line)
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
        )
    for path in sorted(WEB_ROOT.glob("*.py")):
        values.extend((path, number, value) for number, value in _python_strings(path))
    for path in sorted((WEB_ROOT / "static").glob("*.js")):
        values.extend(
            (path, number, line)
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
        )
    return values


def _violations(terms: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for path, number, value in _ui_strings():
        for term in terms:
            if term in value:
                relative = path.relative_to(ROOT)
                violations.append(f"{relative}:{number}: {term}")
    return violations


def test_brand_and_ui_terminology_are_consistent() -> None:
    assert _violations(FORBIDDEN_UI_TERMS) == []


def test_common_persian_half_space_errors_do_not_return() -> None:
    assert _violations(BROKEN_HALF_SPACES) == []


def test_maqaal_storage_keys_are_canonical() -> None:
    base = (TEMPLATES_ROOT / "base.html").read_text(encoding="utf-8")
    app_js = (WEB_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'localStorage.getItem("maqaal-theme")' in base
    assert 'localStorage.getItem("maqaal-mode")' in base
    assert 'localStorage.setItem("maqaal-theme", theme)' in app_js
    assert 'localStorage.setItem("maqaal-mode", mode)' in app_js
