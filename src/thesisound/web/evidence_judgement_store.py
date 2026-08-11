"""Append-only evidence judgement queue under workspaces/_feedback/."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

JudgementVerdict = Literal["correct", "incorrect", "cleared"]
JudgementReason = Literal[
    "excerpt_does_not_support",
    "wrong_locator",
    "claim_mismatch",
    "other",
]

_MAX_NOTE = 500


class EvidenceJudgementRecord(BaseModel):
    project_id: UUID
    turn_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    source_id: UUID | None = None
    block_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    chapter: str | None = None
    section: str | None = None
    verdict: JudgementVerdict
    reason: JudgementReason | None = None
    note: str | None = None
    user_id: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    excerpt: str | None = None
    claim_text: str | None = None
    source_title: str | None = None
    locator_label: str | None = None
    extraction_identity: dict[str, Any] | None = None
    reconciler_identity: dict[str, Any] | None = None

    @field_validator("note")
    @classmethod
    def cap_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            return None
        if len(trimmed) > _MAX_NOTE:
            raise ValueError(f"note must be at most {_MAX_NOTE} characters")
        return trimmed

    @model_validator(mode="after")
    def require_reason_when_incorrect(self) -> EvidenceJudgementRecord:
        if self.verdict == "incorrect" and self.reason is None:
            raise ValueError("incorrect judgements require a reason")
        if self.verdict != "incorrect":
            object.__setattr__(self, "reason", None)
        return self


def judgement_key(record: EvidenceJudgementRecord) -> tuple[int, str, str, str]:
    return (
        record.user_id,
        str(record.project_id),
        record.turn_id,
        record.evidence_id,
    )


class EvidenceJudgementStore:
    """Append-only JSONL; last record wins per (user, project, turn, evidence)."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()
        self.path = self.workspace_root / "_feedback" / "evidence-judgements.jsonl"

    def append(self, record: EvidenceJudgementRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def read_all(self) -> list[EvidenceJudgementRecord]:
        if not self.path.is_file():
            return []
        rows: list[EvidenceJudgementRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows.append(EvidenceJudgementRecord.model_validate_json(line))
        return rows

    def latest_by_key(self) -> dict[tuple[int, str, str, str], EvidenceJudgementRecord]:
        latest: dict[tuple[int, str, str, str], EvidenceJudgementRecord] = {}
        for record in self.read_all():
            latest[judgement_key(record)] = record
        return latest
