from __future__ import annotations

from typing import Final

from thesisound.script import QualityNote, QualityNoteKind, QualityNoteSeverity

# Fixed Persian templates — context-free, no internal identifiers.
_LISTENER_IMPACT: Final[dict[QualityNoteKind, str]] = {
    "claim_omitted": (
        "یک نکتهٔ انتخاب‌شده در هیچ بخشی قرار نگرفت و از طرح حذف شد."
    ),
    "citation_dropped": (
        "در بازنویسی، ارجاع ساختگی حذف شد و ارجاع‌های معتبر ماند."
    ),
    "turn_not_revised": (
        "یک گفته با متن اصلی ماند چون بازنویسی پیوندش به منبع را از دست داد."
    ),
    "revision_rejected": (
        "بازنویسی کنار گذاشته شد چون از متن اصلی بهتر نبود."
    ),
}

_SEVERITY: Final[dict[QualityNoteKind, QualityNoteSeverity]] = {
    "claim_omitted": "notable",
    "citation_dropped": "informational",
    "turn_not_revised": "notable",
    "revision_rejected": "informational",
}


def listener_impact_for(kind: QualityNoteKind) -> str:
    return _LISTENER_IMPACT[kind]


def severity_for(kind: QualityNoteKind) -> QualityNoteSeverity:
    return _SEVERITY[kind]


def make_quality_note(
    *,
    stage: str,
    kind: QualityNoteKind,
    subject: str,
) -> QualityNote:
    return QualityNote(
        stage=stage,
        kind=kind,
        subject=subject,
        listener_impact=listener_impact_for(kind),
        severity=severity_for(kind),
    )


def all_quality_note_kinds() -> tuple[QualityNoteKind, ...]:
    return tuple(_LISTENER_IMPACT.keys())


def notable_count(notes: list[QualityNote]) -> int:
    return sum(1 for note in notes if note.severity == "notable")


def exceeds_degradation_ceiling(
    notes: list[QualityNote],
    *,
    segment_count: int,
) -> bool:
    """Provisional ceiling: >25% of segments as notable notes, or ≥3 notable.

    When ``segment_count`` is 0 (unknown), only the absolute ≥3 rule applies so
    callers without a plan cannot trip the proportional ceiling by accident.
    """

    count = notable_count(notes)
    if count >= 3:
        return True
    if segment_count <= 0:
        return False
    return count / segment_count > 0.25
