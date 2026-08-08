from pathlib import Path

ROOT = Path(__file__).parents[1]
TEMPLATES_ROOT = ROOT / "src" / "thesisound" / "web" / "templates"
STATIC_ROOT = ROOT / "src" / "thesisound" / "web" / "static"


def _lines(path: str) -> list[str]:
    return (TEMPLATES_ROOT / path).read_text(encoding="utf-8").splitlines()


def _assert_terms_are_operator_only(path: str, terms: tuple[str, ...]) -> None:
    violations: list[str] = []
    for number, line in enumerate(_lines(path), start=1):
        for term in terms:
            if term in line and "operator-only" not in line:
                violations.append(f"{path}:{number}: {term}")
    assert violations == []


def test_sensitive_operational_terms_are_hidden_from_simple_mode() -> None:
    _assert_terms_are_operator_only(
        "projects/sources.html",
        ("Gemini", "quality gate", "quality-gate", "stale"),
    )
    _assert_terms_are_operator_only(
        "projects/processing.html",
        ("artifact", "Artifact", "ETA", "stage only"),
    )
    _assert_terms_are_operator_only(
        "projects/episode.html",
        ("corpus ناکافی", "artifact", "Artifact", "ETA"),
    )
    _assert_terms_are_operator_only(
        "projects/script.html",
        ("Verifier مستقل", "artifact", "Artifact", "ETA"),
    )
    _assert_terms_are_operator_only(
        "projects/audio.html",
        ("artifact", "Artifact", "ETA", "ASR", "Similarity", "Verdict"),
    )


def test_source_file_input_uses_an_accessible_custom_control() -> None:
    source = (TEMPLATES_ROOT / "projects" / "sources.html").read_text(
        encoding="utf-8"
    )
    assert 'aria-label="انتخاب فایل منبع"' in source
    assert "position:absolute" in source
    assert "clip:rect(0,0,0,0)" in source
    assert "display:none" not in source


def test_prior_knowledge_has_persian_simple_labels() -> None:
    for path in ("projects/overview.html", "projects/brief.html"):
        source = (TEMPLATES_ROOT / path).read_text(encoding="utf-8")
        for label in ("بدون آشنایی", "مقدماتی", "متوسط", "پیشرفته"):
            assert label in source
        assert "project.brief.prior_knowledge }}</bdi>" in source
        assert "operator-only" in source


def test_theme_brand_colors_do_not_leak_into_component_rules() -> None:
    css = (STATIC_ROOT / "app.css").read_text(encoding="utf-8")
    component_lines = [
        line
        for line in css.splitlines()
        if not line.startswith("  --")
        and ".theme-option[data-theme-value" not in line
    ]
    component_css = "\n".join(component_lines).lower()

    for brand_color in ("#1d4268", "#7d4a26", "#5a6140"):
        assert brand_color not in component_css
