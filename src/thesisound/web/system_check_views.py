"""Persian presentation layer for the runtime preflight checks.

``thesisound.services.runtime_preflight`` is shared with ``thesisound doctor``
and the search CLI, so its labels and details stay English: they are the
engineering record. The web page reads Persian, so this module maps one run of
that record onto Persian labels and sentences.

Two guarantees regardless of mapping coverage:

* an unmapped detail falls through in English rather than being guessed at, and
* absolute filesystem paths never reach the page, mapped or not.

Same split as :mod:`thesisound.web.error_messages` and
:mod:`thesisound.web.readiness_views`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _fa(value: object) -> str:
    return str(value).translate(_FA_DIGITS)


_LABELS: dict[str, str] = {
    "workspace": "مسیر فضای کاری پروژه‌ها",
    "ingestion-artifacts": "مسیر خروجی‌های دریافت منبع",
    "google-genai": "کتابخانهٔ مدل Gemini",
    "gemini-google-search": "جست‌وجوی وب با Gemini",
    "gemini-url-context": "خواندن نشانی وب با Gemini",
    "gemini-api-key": "کلید دسترسی سرویس Gemini",
    "model-routing": "مسیریابی مدل‌ها",
    "reviewer-independence": "استقلال وارسی‌کنندهٔ متن",
    "okian-provider": "ارائه‌دهندهٔ Okian",
    "ffmpeg": "FFmpeg",
    "parser-native": "پارسر پایه",
    "parser-epub": "پارسر EPUB",
    "parser-docling": "پارسر Docling",
    "parser-mineru": "پارسر MinerU",
}

#: Persian sentence per (code, status). Anything absent falls through in English.
_DETAILS: dict[tuple[str, str], str] = {
    ("workspace", "pass"): "پوشهٔ فضای کاری وجود دارد و قابل نوشتن است.",
    ("workspace", "fail"): "پوشهٔ فضای کاری قابل نوشتن نیست.",
    ("ingestion-artifacts", "pass"): "پوشهٔ خروجی‌های دریافت منبع وجود دارد و قابل نوشتن است.",
    ("ingestion-artifacts", "fail"): "پوشهٔ خروجی‌های دریافت منبع قابل نوشتن نیست.",
    ("google-genai", "pass"): "کتابخانهٔ مدل در محیط پایتون نصب است.",
    ("google-genai", "fail"): "کتابخانهٔ مدل نصب نیست؛ با `uv sync --extra gemini` نصبش کنید.",
    ("gemini-google-search", "pass"): "برای برداشت اولیه، کشف منبع و اصطلاح‌شناسی فعال است.",
    ("gemini-url-context", "pass"): "برای نشانی‌های عمومی که صریح در پرامپت می‌آیند فعال است.",
    ("parser-native", "pass"): "برای PDF متنی، TXT، Markdown و DOCX در دسترس است.",
    ("parser-docling", "pass"): "در محیط پایتون نصب است.",
    ("parser-docling", "warning"): "نصب نیست؛ برای PDFهای پیچیده `--extra parsers` را اضافه کنید.",
    ("parser-mineru", "pass"): "روی مسیر سیستم پیدا شد.",
    ("parser-mineru", "warning"): "روی مسیر سیستم پیدا نشد.",
    ("ffmpeg", "pass"): "روی مسیر سیستم پیدا شد.",
    ("ffmpeg", "fail"): "روی مسیر سیستم پیدا نشد؛ بدون آن ساخت صدا ممکن نیست.",
    ("okian-provider", "pass"): "تنظیم شده و پاسخ می‌دهد.",
    ("model-routing", "pass"): "پیکربندی مسیریابی مدل‌ها بارگذاری شد.",
    ("model-routing", "fail"): "پیکربندی مسیریابی مدل‌ها بارگذاری نشد.",
    ("reviewer-independence", "pass"): "وارسی‌کننده و نویسندهٔ متن یک مدل نیستند.",
    ("parser-epub", "pass"): "پارسر داخلی EPUB نسخهٔ ۲ و ۳ با خواندن manifest و spine در دسترس است.",
}

_KEY_COUNT_RE = re.compile(r"(\d+)\s+key\(s\) configured")
_DISABLED_RE = re.compile(r"^Disabled in settings\.?$", re.I)
_SKIPPED_ROUTING_RE = re.compile(r"^Skipped: model routing did not load\.?$", re.I)
_NOT_CONFIGURED_RE = re.compile(r"^Not configured and not used by any route\.?$", re.I)

# Windows drive paths and POSIX absolute paths, optionally backticked. A POSIX
# path must carry at least two separators, so a bare fraction such as the "2/3"
# in "EPUB 2/3" is never mistaken for a path and rewritten.
_ABS_PATH_RE = re.compile(r"`?(?:[A-Za-z]:[\\/][^\s`]*|/(?:[\w.\-]+/)+[\w.\-]*)`?")


def _strip_paths(text: str) -> str:
    """Replace any absolute path with its final component.

    The owner's machine layout is not product information, and it becomes an
    information leak the moment this page is served over the network.
    """

    def shorten(match: re.Match[str]) -> str:
        raw = match.group(0).strip("`")
        tail = re.split(r"[\\/]", raw)[-1]
        return f"`{tail}`" if tail else "«مسیر محلی»"

    return _ABS_PATH_RE.sub(shorten, text)


def persian_detail(code: str, status: str, detail: str) -> str:
    """One Persian sentence for a check, or the English original made safe."""
    raw = (detail or "").strip()
    if code == "gemini-api-key" and status == "pass":
        match = _KEY_COUNT_RE.search(raw)
        if match:
            return f"{_fa(match.group(1))} کلید در استخر تنظیم شده است."
    if code == "gemini-api-key" and status == "fail":
        return "هیچ کلیدی تنظیم نشده است؛ بدون آن هیچ مرحلهٔ مدلی اجرا نمی‌شود."
    if _DISABLED_RE.match(raw):
        return "در تنظیمات غیرفعال است."
    if _SKIPPED_ROUTING_RE.match(raw):
        return "بررسی نشد، چون مسیریابی مدل‌ها بارگذاری نشده بود."
    if _NOT_CONFIGURED_RE.match(raw):
        return "تنظیم نشده و هیچ مسیری از آن استفاده نمی‌کند."
    known = _DETAILS.get((code, status))
    if known:
        return known
    return _strip_paths(raw)


@dataclass(frozen=True)
class SystemCheckRow:
    code: str
    label: str
    status: str
    detail: str
    blocking: bool


def build_system_check_rows(checks: object) -> list[SystemCheckRow]:
    """Map a preflight run onto Persian rows for the system-check page."""
    rows: list[SystemCheckRow] = []
    for check in checks or []:
        code = getattr(check, "code", "")
        status = getattr(check, "status", "")
        rows.append(
            SystemCheckRow(
                code=code,
                label=_LABELS.get(code, getattr(check, "label", code)),
                status=status,
                detail=persian_detail(code, status, getattr(check, "detail", "")),
                blocking=bool(getattr(check, "blocking", status == "fail")),
            )
        )
    return rows
