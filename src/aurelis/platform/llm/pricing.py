"""Model prices, versioned.

Prices change. A cost figure recorded last quarter must keep meaning what it
meant then, so every cost row is written against ``PRICE_TABLE_VERSION`` and
historical totals are never recomputed at today's rates.

Rates are USD per million tokens, as Decimal — money through a binary float is
how accounting drifts.

An unknown model raises rather than defaulting to zero. A silent zero would
make an unpriced model look free, and "free" is exactly the wrong thing for a
budget check to believe.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aurelis.core.enums import ModelTier

__all__ = ["PRICE_TABLE_VERSION", "ModelPrice", "price_for", "tier_for", "usd_for"]

PRICE_TABLE_VERSION = "2026-09-04"

_PER_MILLION = Decimal("1000000")


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    tier: ModelTier


#: Keyed by exact model id. Aliases are deliberately absent: a request must
#: name the version it wants, so a cached response always belongs to a model
#: that still exists.
PRICES: dict[str, ModelPrice] = {
    "claude-opus-5": ModelPrice(Decimal("15"), Decimal("75"), ModelTier.HIGH),
    "claude-sonnet-5": ModelPrice(Decimal("3"), Decimal("15"), ModelTier.MID),
    "claude-haiku-4-5-20251001": ModelPrice(Decimal("1"), Decimal("5"), ModelTier.LOW),
    # The mock provider is free and priced explicitly, so that a run under it
    # produces a real cost row of zero rather than no row at all.
    "mock-1": ModelPrice(Decimal("0"), Decimal("0"), ModelTier.LOW),
}


def price_for(model: str) -> ModelPrice:
    try:
        return PRICES[model]
    except KeyError:
        raise KeyError(
            f"no price recorded for model {model!r}. Add it to PRICES and bump "
            "PRICE_TABLE_VERSION — an unpriced model must not be assumed free."
        ) from None


def tier_for(model: str) -> ModelTier:
    return price_for(model).tier


def usd_for(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    """Cost of one call, at the current table."""
    price = price_for(model)
    return (
        price.input_per_mtok * Decimal(tokens_in) + price.output_per_mtok * Decimal(tokens_out)
    ) / _PER_MILLION
