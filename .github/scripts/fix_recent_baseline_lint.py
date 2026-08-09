from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Missing lint-fix anchor in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace(
    "src/thesisound/episode.py",
    "from thesisound.domain import DeliberatelyOmittedClaim, EvidenceItem, "
    "coerce_deliberately_omitted_claims\n",
    "from thesisound.domain import (\n"
    "    DeliberatelyOmittedClaim,\n"
    "    EvidenceItem,\n"
    "    coerce_deliberately_omitted_claims,\n"
    ")\n",
)
replace(
    "src/thesisound/web/error_messages.py",
    '            "rate_limit": "جست‌وجوی وب انجام نشد چون سهمیهٔ جست‌وجوی مدل تمام شده است. چند دقیقه بعد دوباره تلاش کنید.",\n',
    '            "rate_limit": (\n'
    '                "جست‌وجوی وب انجام نشد چون سهمیهٔ جست‌وجوی مدل تمام شده است. "\n'
    '                "چند دقیقه بعد دوباره تلاش کنید."\n'
    '            ),\n',
)
replace(
    "src/thesisound/web/error_messages.py",
    '            "rate_limit": "بازیابی متن منبع به‌خاطر اتمام سهمیه متوقف شد. چند دقیقه بعد دوباره تلاش کنید.",\n',
    '            "rate_limit": (\n'
    '                "بازیابی متن منبع به‌خاطر اتمام سهمیه متوقف شد. "\n'
    '                "چند دقیقه بعد دوباره تلاش کنید."\n'
    '            ),\n',
)
replace(
    "tests/test_http_proxy.py",
    "import os\n\nfrom thesisound.config import Settings\n",
    "import os\n\nimport pytest\n\nfrom thesisound.config import Settings\n",
)
replace(
    "tests/test_http_proxy.py",
    ")\nimport pytest\n",
    ")\n",
)
replace(
    "tests/test_kavenegar_otp.py",
    '.encode("utf-8")',
    ".encode()",
)
