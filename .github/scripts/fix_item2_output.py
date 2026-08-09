from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new and new in text:
        return
    if old not in text:
        if not new:
            return
        raise RuntimeError(f"Missing item 2 correction anchor in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace(
    "src/thesisound/web/source_discovery.py",
    "from thesisound.adapters.models.gemini import GeminiStructuredModel\n"
    "from thesisound import tracing\n",
    "from thesisound import tracing\n"
    "from thesisound.adapters.models.gemini import GeminiStructuredModel\n",
)
replace(
    "src/thesisound/web/source_discovery.py",
    "from thesisound.ports import RawSearchResult\n",
    "",
)
replace(
    "tests/test_url_probe.py",
    '''def _settings(**overrides: object) -> Settings:\n    return Settings(_env_file=None, http_proxy="none", **overrides)\n''',
    '''def _settings(**overrides: object) -> Settings:\n    values = {"http_proxy": "none", **overrides}\n    return Settings(_env_file=None, **values)\n''',
)
replace(
    "tests/test_url_probe.py",
    '''        ("http://127.0.0.1:10809", {"http": "http://127.0.0.1:10809", "https": "http://127.0.0.1:10809"}),\n''',
    '''        (\n            "http://127.0.0.1:10809",\n            {\n                "http": "http://127.0.0.1:10809",\n                "https": "http://127.0.0.1:10809",\n            },\n        ),\n''',
)
replace(
    "tests/test_web_source_discovery.py",
    '''    assert first == second\n    assert CountingSearchPort.calls == 1\n''',
    '''    assert [(item.title, str(item.url)) for item in first] == [\n        (item.title, str(item.url)) for item in second\n    ]\n    assert CountingSearchPort.calls == 1\n''',
)
