from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from thesisound.modeling import ModelConfigurationError
from thesisound.services.model_pricing import CostCalculator


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_pricing_file_prices_nothing(tmp_path: Path) -> None:
    calculator = CostCalculator(tmp_path / "does-not-exist.toml")

    result = calculator.price(
        provider="gemini",
        model="gemini-3.1-flash",
        operation="structured_text",
        started_at=datetime(2026, 6, 1, tzinfo=UTC),
        input_tokens=1_000,
        output_tokens=500,
        cached_tokens=0,
    )

    assert result is None
    assert calculator.version == "unset"


def test_unknown_model_returns_none_not_zero(tmp_path: Path) -> None:
    """The whole feature's promise: an unpriced model must render as
    unknown, never as a silently misleading 0."""

    path = _write(
        tmp_path / "pricing.toml",
        """
        version = "2026-01"
        [[prices]]
        provider = "gemini"
        model = "gemini-3.1-flash"
        operation = "structured_text"
        effective_from = 2026-01-01
        input_per_million_micros = 75_000
        output_per_million_micros = 300_000
        """,
    )
    calculator = CostCalculator(path)

    result = calculator.price(
        provider="gemini",
        model="some-other-model",
        operation="structured_text",
        started_at=datetime(2026, 6, 1, tzinfo=UTC),
        input_tokens=1_000,
        output_tokens=500,
        cached_tokens=0,
    )

    assert result is None


def test_prices_by_token_counts_at_the_configured_rate(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "pricing.toml",
        """
        version = "2026-01"
        [[prices]]
        provider = "gemini"
        model = "gemini-3.1-flash"
        operation = "structured_text"
        effective_from = 2026-01-01
        input_per_million_micros = 75_000
        output_per_million_micros = 300_000
        cached_per_million_micros = 18_750
        """,
    )
    calculator = CostCalculator(path)

    result = calculator.price(
        provider="gemini",
        model="gemini-3.1-flash",
        operation="structured_text",
        started_at=datetime(2026, 6, 1, tzinfo=UTC),
        input_tokens=1_000_000,
        output_tokens=500_000,
        cached_tokens=200_000,
    )

    assert result is not None
    assert result.cost_micros == 75_000 + 150_000 + 3_750
    assert result.pricing_version == "2026-01"


def test_flat_per_call_rate_ignores_token_counts(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "pricing.toml",
        """
        version = "2026-01"
        [[prices]]
        provider = "gemini"
        model = "gemini-3.1-flash-tts-preview"
        operation = "tts"
        effective_from = 2026-01-01
        per_call_micros = 4_000
        """,
    )
    calculator = CostCalculator(path)

    result = calculator.price(
        provider="gemini",
        model="gemini-3.1-flash-tts-preview",
        operation="tts",
        started_at=datetime(2026, 6, 1, tzinfo=UTC),
        input_tokens=None,
        output_tokens=None,
        cached_tokens=None,
    )

    assert result is not None
    assert result.cost_micros == 4_000


def test_the_newest_row_at_or_before_the_call_wins(tmp_path: Path) -> None:
    """A price change must only affect calls made after it takes effect --
    the effective-dated row selection this whole design exists for."""

    path = _write(
        tmp_path / "pricing.toml",
        """
        version = "2026-06"
        [[prices]]
        provider = "gemini"
        model = "gemini-3.1-flash"
        operation = "structured_text"
        effective_from = 2026-01-01
        input_per_million_micros = 75_000

        [[prices]]
        provider = "gemini"
        model = "gemini-3.1-flash"
        operation = "structured_text"
        effective_from = 2026-06-01
        input_per_million_micros = 50_000
        """,
    )
    calculator = CostCalculator(path)

    before_the_change = calculator.price(
        provider="gemini",
        model="gemini-3.1-flash",
        operation="structured_text",
        started_at=datetime(2026, 3, 1, tzinfo=UTC),
        input_tokens=1_000_000,
        output_tokens=0,
        cached_tokens=0,
    )
    after_the_change = calculator.price(
        provider="gemini",
        model="gemini-3.1-flash",
        operation="structured_text",
        started_at=datetime(2026, 7, 1, tzinfo=UTC),
        input_tokens=1_000_000,
        output_tokens=0,
        cached_tokens=0,
    )
    before_any_row = calculator.price(
        provider="gemini",
        model="gemini-3.1-flash",
        operation="structured_text",
        started_at=datetime(2025, 1, 1, tzinfo=UTC),
        input_tokens=1_000_000,
        output_tokens=0,
        cached_tokens=0,
    )

    assert before_the_change is not None and before_the_change.cost_micros == 75_000
    assert after_the_change is not None and after_the_change.cost_micros == 50_000
    assert before_any_row is None


def test_invalid_toml_raises_a_clear_configuration_error(tmp_path: Path) -> None:
    path = _write(tmp_path / "pricing.toml", "this is not [ valid toml")

    with pytest.raises(ModelConfigurationError):
        CostCalculator(path)


def test_checked_in_pricing_file_ships_with_no_active_prices() -> None:
    """The default config must never invent plausible-looking dollar figures
    for a real model -- every call prices as unknown until an operator adds
    their own real rates."""

    calculator = CostCalculator(Path("config/model-pricing.toml"))

    result = calculator.price(
        provider="gemini",
        model="gemini-3.1-flash",
        operation="structured_text",
        started_at=datetime.now(UTC),
        input_tokens=1_000,
        output_tokens=500,
        cached_tokens=0,
    )

    assert result is None
