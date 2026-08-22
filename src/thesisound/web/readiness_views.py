"""Persian presentation layer for the readiness gates.

``thesisound.services.gates`` is the engineering contract: English labels, code
references, and audit detail that belong in logs and operator traces. This module
turns one run of that contract into what the reader actually needs — a verdict, a
grouped summary, and Persian rows — without touching the record itself.

The same split as :mod:`thesisound.web.error_messages`: raw text stays for
operators, the UI gets a clear reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _fa(value: object) -> str:
    return str(value).translate(_FA_DIGITS)


# --- gate presentation -------------------------------------------------------

#: Persian label per gate code. Order here is not meaningful; grouping owns order.
_LABELS: dict[str, str] = {
    "brief-confirmed": "تأیید موضوع و هدف",
    "source-selection-confirmed": "تأیید مجموعه منابع",
    "parse-quality": "کیفیت استخراج متن",
    "evidence-validation": "وارسی شواهد و نقل‌قول‌ها",
    "evidence-retention": "نگه‌داشت شواهد",
    "coverage-duration": "پوشش و مدت پشتیبانی‌شده",
    "episode-plan-approval": "تأیید طرح قسمت",
    "script-checks": "بررسی‌های قطعی متن",
    "independent-verification": "وارسی مستقل",
    "script-review-decision": "تصمیم بازبینی متن",
    "audio-start": "شروع ساخت صدا",
    "audio-qa": "کنترل کیفیت صدا",
    "final-listen": "شنیدن نهایی",
}

_STATUS_LABELS: dict[str, str] = {
    "pass": "گذشت",
    "blocked": "متوقف",
    "not_reached": "هنوز نرسیده",
    "unknown": "نامعلوم",
}

_STATUS_TONES: dict[str, str] = {
    "pass": "success",
    "blocked": "attention",
    "not_reached": "neutral",
    "unknown": "danger",
}

#: Persian detail per (gate code, status). Falls back to the group sentence.
_DETAILS: dict[tuple[str, str], str] = {
    ("brief-confirmed", "pass"): "کار از روی موضوع تأییدشده پیش رفت.",
    ("brief-confirmed", "blocked"): "موضوع و هدف گفتار هنوز ثبت نشده است.",
    ("source-selection-confirmed", "pass"): "کار با مجموعهٔ منابع تأییدشده پیش رفت.",
    ("source-selection-confirmed", "blocked"): "مجموعهٔ منابع هنوز تأیید نشده است.",
    ("parse-quality", "blocked"): "دست‌کم یک منبع برای استخراج مدعا امن نیست.",
    ("evidence-validation", "blocked"): "دست‌کم یک نقل‌قول با متن منبع نمی‌خواند.",
    ("evidence-retention", "blocked"): "بخش زیادی از شواهد برنامه‌ریزی‌شده در استخراج از دست رفت.",
    ("coverage-duration", "blocked"): "شواهد موجود مدت درخواستی را پشتیبانی نمی‌کنند.",
    ("episode-plan-approval", "pass"): "طرح قسمت تأیید شده و از آن زمان تغییر نکرده است.",
    ("episode-plan-approval", "blocked"): "طرح قسمت بعد از تأیید تغییر کرده است.",
    ("script-checks", "blocked"): "متن موجود به طرح قسمت دیگری بسته است.",
    ("independent-verification", "blocked"): "متن موجود به طرح قسمت دیگری بسته است.",
    ("script-review-decision", "blocked"): "متن موجود به طرح قسمت دیگری بسته است.",
    ("audio-start", "blocked"): "ساخت صدا هنوز شروع نشده است.",
    ("audio-qa", "not_reached"): "هنوز فایل کنترل کیفیتی وجود ندارد.",
    ("final-listen", "not_reached"): "صدای نهایی هنوز برای شنیدن آماده نیست.",
}

_NOT_REACHED_FALLBACK = "این مرحله هنوز آغاز نشده است."
_UNKNOWN_FALLBACK = "وضعیت این کنترل خوانده نشد."

# Numbers worth surfacing live in the sentence. Narrow on purpose: an unmatched
# pattern falls back to the static sentence rather than guessing.
_COUNT_RE = re.compile(r"for (\d+) source")
_COVERAGE_RE = re.compile(r"is (\d+) minutes; the audit supports (\d+) minutes")
_RETENTION_RE = re.compile(r"Kept (\d+)% of planned token mass; minimum is (\d+)%")


def _detail_for(code: str, status: str, raw: str) -> str:
    if status == "pass":
        if code in {"parse-quality", "evidence-validation"}:
            match = _COUNT_RE.search(raw or "")
            if match:
                count = _fa(match.group(1))
                verb = "کیفیت استخراج" if code == "parse-quality" else "شواهد"
                return f"{verb} برای {count} منبع دوباره سنجیده شد."
        if code == "coverage-duration":
            match = _COVERAGE_RE.search(raw or "")
            if match:
                asked, supported = _fa(match.group(1)), _fa(match.group(2))
                return f"درخواست شما {asked} دقیقه است و شواهد {supported} دقیقه را پشتیبانی می‌کنند."
        if code == "evidence-retention":
            match = _RETENTION_RE.search(raw or "")
            if match:
                kept, floor = _fa(match.group(1)), _fa(match.group(2))
                return f"{kept}٪ حجم شواهد برنامه‌ریزی‌شده نگه داشته شد؛ کف لازم {floor}٪ است."
    known = _DETAILS.get((code, status))
    if known:
        return known
    if status == "not_reached":
        return _NOT_REACHED_FALLBACK
    if status == "unknown":
        return _UNKNOWN_FALLBACK
    return "این کنترل گذشت."


# --- grouping ----------------------------------------------------------------

_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "evidence",
        "شواهد، پوشش و مدت",
        (
            "brief-confirmed",
            "source-selection-confirmed",
            "parse-quality",
            "evidence-validation",
            "evidence-retention",
            "coverage-duration",
        ),
    ),
    (
        "script",
        "طرح قسمت و متن گفتار",
        (
            "episode-plan-approval",
            "script-checks",
            "independent-verification",
            "script-review-decision",
        ),
    ),
    ("audio", "صدا", ("audio-start", "audio-qa", "final-listen")),
)

#: Where the reader goes to clear a blocked human gate.
_ACTIONS: dict[str, tuple[str, str]] = {
    "brief-confirmed": ("ثبت موضوع و هدف", "brief"),
    "source-selection-confirmed": ("بازبینی و تأیید منابع", "sources"),
    "episode-plan-approval": ("بازبینی و تأیید طرح قسمت", "episode"),
    "script-review-decision": ("بازبینی متن گفتار", "script"),
    "audio-start": ("شروع ساخت صدا", "audio"),
}

#: A blocked machine gate is never the thing to act on; name the human gate it waits for.
_UPSTREAM: dict[str, str] = {
    "parse-quality": "source-selection-confirmed",
    "evidence-validation": "source-selection-confirmed",
    "evidence-retention": "source-selection-confirmed",
    "coverage-duration": "source-selection-confirmed",
    "script-checks": "episode-plan-approval",
    "independent-verification": "episode-plan-approval",
    "audio-qa": "audio-start",
}


@dataclass(frozen=True)
class ReadinessRow:
    code: str
    label: str
    status: str
    status_label: str
    tone: str
    actor: str
    detail: str
    evidence: str | None
    raw_detail: str


@dataclass(frozen=True)
class ReadinessGroup:
    key: str
    title: str
    rows: list[ReadinessRow]
    summary: str
    tone: str
    is_blocking: bool


@dataclass(frozen=True)
class ReadinessView:
    headline: str
    explanation: str
    tone: str
    action_label: str | None
    action_url: str | None
    facts: list[tuple[str, str]] = field(default_factory=list)
    groups: list[ReadinessGroup] = field(default_factory=list)
    rows: list[ReadinessRow] = field(default_factory=list)


def _trim_evidence(evidence: str | None, workspace_root: str | None) -> str | None:
    """Keep the locating part of a path, drop the machine it happens to live on."""
    if not evidence:
        return None
    text = str(evidence)
    if workspace_root and text.startswith(str(workspace_root)):
        text = text[len(str(workspace_root)) :].lstrip("\\/")
    elif "\\" in text or "/" in text:
        text = re.split(r"[\\/]", text)[-1]
    return text or None


def _summary(rows: list[ReadinessRow]) -> tuple[str, str, bool]:
    blocked = [row for row in rows if row.status == "blocked"]
    passed = [row for row in rows if row.status == "pass"]
    waiting = [row for row in rows if row.status in {"not_reached", "unknown"}]
    if blocked:
        return f"{_fa(len(blocked))} بررسی متوقف", "attention", True
    if waiting and not passed:
        return f"{_fa(len(waiting))} بررسی هنوز نرسیده", "neutral", False
    if waiting:
        return f"{_fa(len(passed))} بررسی گذشت، {_fa(len(waiting))} هنوز نرسیده", "neutral", False
    return f"{_fa(len(passed))} بررسی گذشت", "success", False


def build_readiness_view(
    gate_results: Iterable[object],
    *,
    project_id: object,
    target_duration_minutes: int | None = None,
    workspace_root: object | None = None,
) -> ReadinessView:
    """Turn one readiness run into the verdict-first view the page renders."""
    root = str(workspace_root) if workspace_root is not None else None
    by_code: dict[str, ReadinessRow] = {}
    for result in gate_results:
        code = getattr(result, "code", "")
        status = getattr(result, "status", "unknown")
        raw = getattr(result, "detail", "") or ""
        by_code[code] = ReadinessRow(
            code=code,
            label=_LABELS.get(code, getattr(result, "label", code)),
            status=status,
            status_label=_STATUS_LABELS.get(status, status),
            tone=_STATUS_TONES.get(status, "neutral"),
            actor="شما" if getattr(result, "actor", "") == "human" else "سامانه",
            detail=_detail_for(code, status, raw),
            evidence=_trim_evidence(getattr(result, "evidence", None), root),
            raw_detail=raw,
        )

    grouped: list[tuple[str, str, list[ReadinessRow]]] = []
    ordered: list[ReadinessRow] = []
    for key, title, codes in _GROUPS:
        rows = [by_code[code] for code in codes if code in by_code]
        if not rows:
            continue
        ordered.extend(rows)
        grouped.append((key, title, rows))

    # Only the group holding the first blocked gate carries the rail. Everything
    # downstream is blocked *because* of it, and a second rail would say otherwise.
    first_blocked = next((row for row in ordered if row.status == "blocked"), None)
    groups: list[ReadinessGroup] = []
    for key, title, rows in grouped:
        summary, tone, _ = _summary(rows)
        groups.append(
            ReadinessGroup(key, title, rows, summary, tone, first_blocked in rows)
        )
    # Any gate the registry grew but this module has not grouped yet still shows.
    for code, row in by_code.items():
        if row not in ordered:
            ordered.append(row)

    blocking = first_blocked
    evidence_group = next((g for g in groups if g.key == "evidence"), None)
    sources_are_sound = bool(
        evidence_group and all(row.status == "pass" for row in evidence_group.rows)
    )

    facts: list[tuple[str, str]] = []
    if target_duration_minutes:
        facts.append(("مدت درخواستی", f"{_fa(target_duration_minutes)} دقیقه"))
    coverage = by_code.get("coverage-duration")
    if coverage is not None:
        match = _COVERAGE_RE.search(coverage.raw_detail)
        if match:
            facts.append(("مدتی که شواهد پشتیبانی می‌کنند", f"{_fa(match.group(2))} دقیقه"))
    retention = by_code.get("evidence-retention")
    if retention is not None:
        match = _RETENTION_RE.search(retention.raw_detail)
        if match:
            facts.append(
                ("نگه‌داشت شواهد", f"{_fa(match.group(1))}٪ — کف لازم {_fa(match.group(2))}٪")
            )
    passed = sum(1 for row in ordered if row.status == "pass")
    facts.append(("بررسی‌های گذشته", f"{_fa(passed)} از {_fa(len(ordered))}"))

    if blocking is None:
        waiting = [row for row in ordered if row.status != "pass"]
        if waiting:
            return ReadinessView(
                headline="تا اینجا مانعی نیست.",
                explanation="هیچ بررسی‌ای متوقف نشده است. مراحل باقی‌مانده هنوز آغاز نشده‌اند.",
                tone="neutral",
                action_label=None,
                action_url=None,
                facts=facts,
                groups=groups,
                rows=ordered,
            )
        return ReadinessView(
            headline="همه‌چیز آماده است.",
            explanation="هر سیزده بررسی گذشت. گفتار شما کامل و قابل‌ردیابی است.",
            tone="success",
            action_label=None,
            action_url=None,
            facts=facts,
            groups=groups,
            rows=ordered,
        )

    act_on = blocking.code
    if act_on not in _ACTIONS:
        act_on = _UPSTREAM.get(blocking.code, blocking.code)
    action = _ACTIONS.get(act_on)
    action_label, action_url = (None, None)
    if action is not None:
        action_label = action[0]
        action_url = f"/projects/{project_id}/{action[1]}"

    blocked_count = sum(1 for row in ordered if row.status == "blocked")
    lead = "منابع کافی‌اند؛ " if sources_are_sound and blocking.code != "coverage-duration" else ""
    headline = f"{lead}{blocking.label} مانع است."
    explanation = blocking.detail
    if blocked_count > 1:
        explanation = (
            f"{explanation} تا رفع این مورد، "
            f"{_fa(blocked_count - 1)} بررسی پایین‌دستی هم متوقف می‌ماند."
        )

    return ReadinessView(
        headline=headline,
        explanation=explanation,
        tone="attention",
        action_label=action_label,
        action_url=action_url,
        facts=facts,
        groups=groups,
        rows=ordered,
    )
