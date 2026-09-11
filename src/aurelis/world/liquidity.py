"""The venue's own liquidity ranking, so a grant can name a universe.

Three instruments were the whole of the company's world through M33, and a
mechanism stated on one of them fires only when that one breaks its range.
``MEC-0001`` needs twenty out-of-sample predictions and one chart supplies a
range break every day or so. A mechanism is a claim about a kind of event, not
about a chart, and the test of it is every instrument on which the event fires.

Coinbase publishes, without credentials, one document with every product's
last day: open, high, low, last, and volume in base units. Ranked by units, a
memecoin with a trillion of them outranks bitcoin; the ranking here is by
dollars, volume times last. Pegged instruments — a stablecoin against the
dollar, a token wrapping gold — move so little that a range break on them is
noise, and they are excluded by their *measured* range rather than by a list of
names somebody has to maintain: an instrument whose whole day was narrower than
``min_range_pct`` is not a market a mechanism can be tested on.

The selection happens once, when a person records the grant. The rule and the
ranking it was drawn from go on the record, and the service still cannot widen
what it was granted.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from aurelis.intel.live import USER_AGENT, FeedUnavailable

__all__ = ["CoinbaseStats", "Liquidity", "Universe", "UniverseRule", "rank_universe"]

_Q = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class CoinbaseStats:
    """``GET /products/stats``: every product's last day, in one call."""

    name: str = "coinbase"
    endpoint: str = "https://api.exchange.coinbase.com/products/stats"
    timeout: int = 25
    opener: Any = None

    def stats(self) -> dict[str, Any]:
        request = urllib.request.Request(self.endpoint, headers={"User-Agent": USER_AGENT})
        opener = self.opener or urllib.request.urlopen
        try:
            with opener(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            raise FeedUnavailable(f"{self.name} refused the stats ({error.code})") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise FeedUnavailable(f"{self.name} stats could not be reached: {error}") from error
        if not isinstance(payload, dict):
            raise FeedUnavailable(f"{self.name} returned {type(payload).__name__}, not stats")
        return payload


@dataclass(frozen=True, slots=True)
class Liquidity:
    """One instrument's last day, as the ranking sees it."""

    symbol: str
    last: Decimal
    volume_24h: Decimal
    """In base units. Not comparable across instruments; ``notional_24h`` is."""

    notional_24h: Decimal
    range_24h_pct: Decimal
    """``(high - low) / last``, in percent. What a pegged instrument fails."""

    def describe(self) -> str:
        return (
            f"{self.symbol}: {self.notional_24h:,.0f} notional over 24h, "
            f"range {self.range_24h_pct}%"
        )


@dataclass(frozen=True, slots=True)
class UniverseRule:
    """How a universe is drawn. Printed on the grant, so a reader knows."""

    quote: str = "USD"
    top: int = 30
    min_range_pct: Decimal = Decimal("0.2")

    def describe(self) -> str:
        return (
            f"top {self.top} {self.quote}-quoted instruments by 24h notional, "
            f"excluding any whose 24h range was under {self.min_range_pct}%"
        )


@dataclass(frozen=True, slots=True)
class Universe:
    """What one ranking chose, and what it set aside."""

    rule: UniverseRule
    ranked: tuple[Liquidity, ...]
    """Every instrument the rule considered, most liquid first."""

    chosen: tuple[str, ...]
    excluded_pegged: tuple[str, ...]
    """Instruments in the top of the ranking whose range failed the rule."""

    def as_record(self) -> dict[str, Any]:
        return {
            "rule": self.rule.describe(),
            "quote": self.rule.quote,
            "top": self.rule.top,
            "min_range_pct": str(self.rule.min_range_pct),
            "chosen": list(self.chosen),
            "excluded_pegged": list(self.excluded_pegged),
            "ranked": [
                {
                    "symbol": row.symbol,
                    "last": str(row.last),
                    "volume_24h": str(row.volume_24h),
                    "notional_24h": str(row.notional_24h),
                    "range_24h_pct": str(row.range_24h_pct),
                }
                for row in self.ranked
            ],
        }


def _decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _liquidity(symbol: str, day: Any) -> Liquidity | None:
    if not isinstance(day, dict):
        return None
    last = _decimal(day.get("last"))
    volume = _decimal(day.get("volume"))
    high = _decimal(day.get("high"))
    low = _decimal(day.get("low"))
    if last is None or volume is None or high is None or low is None:
        return None
    if last <= 0 or volume <= 0 or high < low:
        return None
    return Liquidity(
        symbol=symbol,
        last=last,
        volume_24h=volume,
        notional_24h=(volume * last).quantize(_Q),
        range_24h_pct=((high - low) / last * 100).quantize(Decimal("0.0001")),
    )


def rank_universe(stats: dict[str, Any], rule: UniverseRule) -> Universe:
    """Rank every ``quote``-quoted product by dollar notional and choose the top.

    Pegged instruments are set aside as the ranking is walked, so the chosen
    list is the top ``rule.top`` *tradable* instruments and the record names
    which liquid ones were passed over and why.
    """
    suffix = f"-{rule.quote.upper()}"
    ranked: list[Liquidity] = []
    for symbol, row in stats.items():
        if not str(symbol).upper().endswith(suffix) or not isinstance(row, dict):
            continue
        liquidity = _liquidity(str(symbol), row.get("stats_24hour"))
        if liquidity is not None:
            ranked.append(liquidity)
    ranked.sort(key=lambda row: (-row.notional_24h, row.symbol))

    chosen: list[str] = []
    pegged: list[str] = []
    for row in ranked:
        if len(chosen) >= rule.top:
            break
        if row.range_24h_pct < rule.min_range_pct:
            pegged.append(row.symbol)
            continue
        chosen.append(row.symbol)
    return Universe(
        rule=rule, ranked=tuple(ranked), chosen=tuple(chosen), excluded_pegged=tuple(pegged)
    )
