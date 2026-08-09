from __future__ import annotations

import tomllib
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from thesisound.modeling import ModelConfigurationError
from thesisound.observability import CallOperation, CostResult


class PriceRow(BaseModel):
    """One priced provider/model/operation, effective from a given date.

    Token rates are micros of currency per one million tokens (matching the
    Google Cloud Billing convention: 1,000,000 micros = one unit of
    currency), so a whole pipeline's cost stays exact integer arithmetic
    with no floating-point drift. ``per_call_micros`` covers operations
    priced per request rather than per token (e.g. a flat TTS/ASR rate).
    """

    provider: str
    model: str
    operation: CallOperation
    effective_from: datetime
    input_per_million_micros: int | None = Field(default=None, ge=0)
    output_per_million_micros: int | None = Field(default=None, ge=0)
    cached_per_million_micros: int | None = Field(default=None, ge=0)
    per_call_micros: int | None = Field(default=None, ge=0)

    @field_validator("effective_from", mode="before")
    @classmethod
    def _normalize_effective_from(cls, value: object) -> object:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day, tzinfo=UTC)
        return value


class PricingDocument(BaseModel):
    version: str = "unset"
    prices: list[PriceRow] = Field(default_factory=list)


class CostCalculator:
    """Prices a completed model call from a checked-in TOML table.

    Loaded once per process (see ``observability.ledger_from_settings``).
    Effective-dated rows let a price change apply going forward without
    altering ``cost_micros`` already persisted on past calls -- ``succeed()``
    writes that once, at call time; ``ObservabilityLedger.reprice()`` is the
    only path that recomputes it, deliberately, against a possibly-updated
    table.

    Ships with no active price rows by design: fabricating plausible-looking
    dollar figures for a bespoke provider (Okian) or guessing at a specific
    account's current negotiated rate would be a *silently wrong* cost,
    which the whole point of this feature is to avoid. ``price()`` returns
    ``None`` for anything not in the table -- callers must render that as
    "unknown", never as zero. Add real rows to ``config/model-pricing.toml``
    (see the commented example there) once you know your actual rates.
    """

    def __init__(self, pricing_file: Path) -> None:
        self.pricing_file = pricing_file
        document = _load_pricing_document(pricing_file)
        self.version = document.version
        self._rows: dict[tuple[str, str, str], list[PriceRow]] = {}
        for row in document.prices:
            key = (row.provider, row.model, row.operation)
            self._rows.setdefault(key, []).append(row)

    def price(
        self,
        *,
        provider: str,
        model: str,
        operation: str,
        started_at: datetime,
        input_tokens: int | None,
        output_tokens: int | None,
        cached_tokens: int | None,
    ) -> CostResult | None:
        candidates = [
            row
            for row in self._rows.get((provider, model, operation), [])
            if row.effective_from <= started_at
        ]
        if not candidates:
            return None
        row = max(candidates, key=lambda item: item.effective_from)
        micros = row.per_call_micros or 0
        micros += _scale(input_tokens, row.input_per_million_micros)
        micros += _scale(output_tokens, row.output_per_million_micros)
        micros += _scale(cached_tokens, row.cached_per_million_micros)
        return CostResult(cost_micros=micros, pricing_version=self.version)


def _scale(tokens: int | None, rate_per_million: int | None) -> int:
    if not tokens or not rate_per_million:
        return 0
    return round(tokens * rate_per_million / 1_000_000)


def _load_pricing_document(path: Path) -> PricingDocument:
    resolved = path.expanduser()
    if not resolved.exists():
        return PricingDocument()
    try:
        payload = tomllib.loads(resolved.read_text(encoding="utf-8"))
        return PricingDocument.model_validate(payload)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        raise ModelConfigurationError(f"Invalid model pricing file at {resolved}: {exc}") from exc
