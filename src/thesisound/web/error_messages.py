"""Short Persian failure copy that distinguishes common error classes.

Raw exception text stays for operators/logs; the UI gets a clear reason.
"""

from __future__ import annotations

import re

_PERSIAN_CHAR = re.compile(r"[\u0600-\u06FF]")


def user_facing_error(
    error: Exception | str | None,
    *,
    action: str,
) -> str:
    """Return one short Persian sentence for the given failure."""
    raw = _raw_text(error)
    kind = _classify(raw)
    if kind == "persian" and raw:
        return raw if len(raw) <= 280 else f"{raw[:277]}…"
    return _message_for(kind, action=action)


def _raw_text(error: Exception | str | None) -> str:
    if error is None:
        return ""
    if isinstance(error, BaseException):
        return str(error).strip()
    return str(error).strip()


def _classify(raw: str) -> str:
    if not raw:
        return "unknown"
    if _looks_persian(raw) and not _looks_technical(raw):
        return "persian"

    lowered = raw.casefold()
    if any(
        token in lowered
        for token in (
            "resource_exhausted",
            "rate limit",
            "quota",
            "429",
            "too many requests",
        )
    ):
        return "rate_limit"
    if any(
        token in lowered
        for token in (
            "unauthenticated",
            "access_token_type_unsupported",
            "invalid api key",
            "api key",
            "permission_denied",
            "401",
            "403",
        )
    ) or "کلید" in raw:
        return "auth"
    if any(
        token in lowered
        for token in (
            "prerequisites are incomplete",
            "gemini-api-key",
            "see `/system-check`",
            "not set in the environment",
        )
    ):
        return "preflight"
    if any(
        token in lowered
        for token in (
            "filenotfound",
            "no such file",
            "original upload is missing",
            "upload is missing",
        )
    ) or isinstance_hint(raw, "FileNotFoundError"):
        return "missing_file"
    if any(
        token in lowered
        for token in (
            "selection is locked",
            "retry-unavailable",
            "not retryable",
            "cannot rewind",
            "invalid state",
            "wrong state",
        )
    ):
        return "locked"
    if any(
        token in lowered
        for token in (
            "timeout",
            "timed out",
            "deadline",
            "connection",
            "network",
            "temporarily unavailable",
            "503",
            "502",
        )
    ):
        return "network"
    if any(
        token in lowered
        for token in ("ffmpeg", "audio", "wav", "mp3", "synthesis", "tts")
    ):
        return "audio"
    if any(
        token in lowered
        for token in ("parse", "parser", "pdf", "epub", "docx", "extract")
    ):
        return "parse"
    return "unknown"


def isinstance_hint(raw: str, type_name: str) -> bool:
    return raw.startswith(type_name) or f" {type_name}" in raw


def _looks_persian(raw: str) -> bool:
    return bool(_PERSIAN_CHAR.search(raw))


def _looks_technical(raw: str) -> bool:
    lowered = raw.casefold()
    return any(
        token in lowered
        for token in (
            "traceback",
            "exception",
            "error:",
            "runtimeerror",
            "valueerror",
            "filenotfounderror",
            "status=",
            "httpx",
            "google.genai",
        )
    )


def _message_for(kind: str, *, action: str) -> str:
    by_action = {
        "search": {
            "rate_limit": "جست‌وجوی وب انجام نشد چون سهمیهٔ جست‌وجوی مدل تمام شده است. چند دقیقه بعد دوباره تلاش کنید.",
            "auth": "جست‌وجوی وب انجام نشد چون احراز هویت مدل رد شد. کلید یا دسترسی را بررسی کنید.",
            "preflight": "جست‌وجو شروع نشد چون پیش‌نیازهای مدل آماده نیست.",
            "network": "جست‌وجوی وب به‌خاطر قطع ارتباط یا زمان‌پاسخ انجام نشد. دوباره تلاش کنید.",
            "unknown": "جست‌وجوی وب انجام نشد. اتصال و تنظیمات مدل را بررسی کنید.",
        },
        "retrieve": {
            "rate_limit": "بازیابی متن منبع به‌خاطر اتمام سهمیه متوقف شد. چند دقیقه بعد دوباره تلاش کنید.",
            "auth": "بازیابی متن منبع به‌خاطر رد شدن احراز هویت مدل متوقف شد.",
            "preflight": "بازیابی منبع شروع نشد چون پیش‌نیازهای مدل آماده نیست.",
            "network": "بازیابی متن منبع به‌خاطر قطع ارتباط یا زمان‌پاسخ کامل نشد.",
            "parse": "متن کامل این نشانی قابل استخراج نبود و به‌عنوان منبع وارد نشد.",
            "unknown": "بازیابی این منبع کامل نشد و وارد شاهدها نشد.",
        },
        "ingest": {
            "missing_file": "فایل بارگذاری‌شده پیدا نشد؛ استخراج ممکن نیست.",
            "parse": "فایل قابل وارسی یا استخراج متن نیست. قالب یا سلامت فایل را بررسی کنید.",
            "unknown": "وارسی فایل متوقف شد و منبع وارد گفتار نشد.",
        },
        "retry_source": {
            "missing_file": "استخراج دوباره ممکن نیست چون اصل فایل پیدا نشد.",
            "locked": "مجموعه منابع قفل است؛ برای تغییر از بازگشت به مراحل قبلی استفاده کنید.",
            "parse": "استخراج دوباره انجام نشد چون متن فایل قابل خواندن نبود.",
            "unknown": "استخراج دوباره انجام نشد. اصل فایل باقی مانده است.",
        },
        "delete_source": {
            "locked": "حذف ممکن نیست چون مجموعه منابع وارد تحلیل شده و قفل است.",
            "unknown": "حذف منبع انجام نشد. هیچ خروجی دیگری تغییر نکرد.",
        },
        "corpus": {
            "rate_limit": "تحلیل منابع به‌خاطر اتمام سهمیه مدل متوقف شد.",
            "auth": "تحلیل منابع به‌خاطر مشکل احراز هویت مدل متوقف شد.",
            "preflight": "تحلیل منابع شروع نشد چون پیش‌نیازهای مدل آماده نیست.",
            "network": "تحلیل منابع به‌خاطر قطع ارتباط یا زمان‌پاسخ متوقف شد.",
            "locked": "این اجرا در وضعیت قابل تلاش دوباره نیست.",
            "unknown": "تحلیل منابع متوقف شد؛ مرحلهٔ ناموفق وارد طرح گفتار نشده است.",
        },
        "planning": {
            "rate_limit": "سنجش کفایت منابع به‌خاطر اتمام سهمیه مدل متوقف شد.",
            "auth": "ساخت طرح گفتار به‌خاطر مشکل احراز هویت مدل متوقف شد.",
            "network": "ساخت طرح گفتار به‌خاطر قطع ارتباط یا زمان‌پاسخ متوقف شد.",
            "unknown": "سنجش کفایت منابع یا ساخت طرح گفتار متوقف شد.",
        },
        "script": {
            "rate_limit": "نگارش متن گفتار به‌خاطر اتمام سهمیه مدل متوقف شد.",
            "auth": "نگارش متن گفتار به‌خاطر مشکل احراز هویت مدل متوقف شد.",
            "network": "نگارش متن گفتار به‌خاطر قطع ارتباط یا زمان‌پاسخ متوقف شد.",
            "locked": "تأیید یا ادامهٔ نگارش در وضعیت فعلی ممکن نیست.",
            "unknown": "نگارش یا راستی‌آزمایی متن گفتار متوقف شد.",
        },
        "audio": {
            "rate_limit": "ساخت نسخهٔ شنیداری به‌خاطر اتمام سهمیه مدل متوقف شد.",
            "auth": "ساخت نسخهٔ شنیداری به‌خاطر مشکل احراز هویت مدل متوقف شد.",
            "audio": "ساخت یا وارسی قطعهٔ صوتی متوقف شد؛ قطعه‌های سالم باقی مانده‌اند.",
            "network": "ساخت نسخهٔ شنیداری به‌خاطر قطع ارتباط یا زمان‌پاسخ متوقف شد.",
            "preflight": "ساخت نسخهٔ شنیداری شروع نشد چون پیش‌نیازهای صوت آماده نیست.",
            "unknown": "ساخت یا وارسی نسخهٔ شنیداری متوقف شد.",
        },
        "workflow": {
            "locked": "بازکردن این مرحله در وضعیت فعلی ممکن نیست.",
            "unknown": "امکان بازکردن این مرحله وجود ندارد.",
        },
        "generic": {
            "rate_limit": "اجرا به‌خاطر اتمام سهمیه مدل متوقف شد. چند دقیقه بعد دوباره تلاش کنید.",
            "auth": "اجرا به‌خاطر مشکل احراز هویت مدل متوقف شد.",
            "preflight": "اجرا شروع نشد چون پیش‌نیازهای محیط آماده نیست.",
            "network": "اجرا به‌خاطر قطع ارتباط یا زمان‌پاسخ متوقف شد.",
            "locked": "این اقدام در وضعیت فعلی ممکن نیست.",
            "missing_file": "فایل لازم پیدا نشد.",
            "unknown": "اجرا متوقف شد. خروجی‌های سالم باقی مانده‌اند.",
        },
    }
    table = by_action.get(action) or by_action["generic"]
    return table.get(kind) or table.get("unknown") or by_action["generic"]["unknown"]
