"""Descriptive measures over a bar series.

Deterministic arithmetic, in exact decimal, returned as strings. Three reasons
it is software rather than something an agent works out:

* it is reproducible, and a model's arithmetic is not;
* it is free, and a model call is not;
* the result carries a provenance chain, and a number a model produced carries
  nothing at all.

Everything here is descriptive. Nothing decides, ranks or concludes. A
"momentum" measure is the observed change over a window and says nothing about
whether that predicts anything — a distinction the research lifecycle at M4
depends on and which is easiest to keep by never blurring it here.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

__all__ = ["describe_bars"]

_PCT = Decimal("0.0001")
_PRICE = Decimal("0.01")


def _decimal(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"bar field {field!r} is not a number: {value!r}") from None


def describe_bars(bars: list[dict[str, Any]]) -> dict[str, str]:
    """Summarise a bar series.

    Returns strings so the caller cannot accidentally reintroduce a float, and
    so the values hash identically wherever they are recorded.
    """
    if not bars:
        raise ValueError("cannot describe an empty series")

    closes = [_decimal(b["c"], "c") for b in bars]
    highs = [_decimal(b["h"], "h") for b in bars]
    lows = [_decimal(b["l"], "l") for b in bars]
    volumes = [_decimal(b["v"], "v") for b in bars]

    first, last = closes[0], closes[-1]
    change = (last / first - Decimal(1)) if first else Decimal(0)

    returns = [
        (closes[i] / closes[i - 1] - Decimal(1)) for i in range(1, len(closes)) if closes[i - 1]
    ]
    mean_return = sum(returns, Decimal(0)) / Decimal(len(returns)) if returns else Decimal(0)

    if len(returns) > 1:
        variance = sum(((r - mean_return) ** 2 for r in returns), Decimal(0)) / Decimal(
            len(returns) - 1
        )
        # Decimal has no sqrt on the type itself; the context provides it and
        # keeps the result exact to the working precision.
        volatility = variance.sqrt()
    else:
        volatility = Decimal(0)

    up_bars = sum(1 for r in returns if r > 0)

    return {
        "bars": str(len(bars)),
        "first_close": str(first.quantize(_PRICE)),
        "last_close": str(last.quantize(_PRICE)),
        "high": str(max(highs).quantize(_PRICE)),
        "low": str(min(lows).quantize(_PRICE)),
        "change": str(change.quantize(_PCT)),
        "mean_return": str(mean_return.quantize(Decimal("0.000001"))),
        "return_volatility": str(volatility.quantize(Decimal("0.000001"))),
        "up_bar_fraction": str(
            (Decimal(up_bars) / Decimal(len(returns))).quantize(_PCT) if returns else Decimal(0)
        ),
        "mean_volume": str(
            (sum(volumes, Decimal(0)) / Decimal(len(volumes))).quantize(_PRICE)
        ),
    }
