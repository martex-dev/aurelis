"""How the lab judges a strategy (M65): honestly, out of sample, after costs.

Three things decide whether a classic strategy "works" here, and the order
matters:

1. **Costs.** Every change of position pays the desk's own round-trip cost
   (``desks/costs.py``, which states where each number came from). Every day
   a position is held pays the desk's carry. A strategy that wins before
   costs and loses after them does not work.
2. **Luck.** Test a few thousand strategies and some will look excellent by
   chance. The in-sample Sharpe has to clear the best Sharpe you would expect
   from that many strategies with no edge at all: the expected maximum of N
   null Sharpes, whose spread is set by how many years were tested.
3. **The future it did not see.** Each series is split, the first 70% in
   sample and the last 30% out. A survivor must clear the luck bar in sample,
   then have a positive Sharpe out of sample *and* beat simply holding the
   asset over the same out-of-sample stretch.

Most will fail. That is the expected and honest result. The lab exists so
the company knows which taught methods do not work on which markets, as
well as which do.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

from aurelis.lab.history import Series
from aurelis.lab.strategies import Spec, positions_for

__all__ = ["MIN_BARS", "SPLIT", "Result", "evaluate", "luck_bar"]

SPLIT = 0.7
MIN_BARS = 400
_EULER = 0.5772156649


def periods_per_year(desk: str) -> int:
    return 365 if desk in ("crypto", "memecoin") else 252


def luck_bar(n_trials: int, years: float) -> float:
    """The best annualised Sharpe expected from ``n_trials`` strategies with no edge.

    For a strategy with no edge, the Sharpe estimated over ``years`` years has
    a standard error of about one over the square root of ``years``. The
    expected maximum of N such estimates is that error times the expected
    maximum of N standard normals (Bailey and López de Prado's approximation).
    """
    if n_trials < 2 or years <= 0:
        return 0.0
    z = NormalDist()
    expected_max = (1 - _EULER) * z.inv_cdf(1 - 1 / n_trials) + _EULER * z.inv_cdf(
        1 - 1 / (n_trials * math.e)
    )
    return expected_max / math.sqrt(years)


@dataclass(frozen=True, slots=True)
class Leg:
    sharpe: float
    total: float
    hold: float
    max_drawdown: float
    trades: int


@dataclass(frozen=True, slots=True)
class Result:
    spec: Spec
    symbol: str
    desk: str
    bars: int
    in_sample: Leg
    out_of_sample: Leg
    verdict: str


def _leg(
    returns: list[float], positions: list[int], closes: list[float], lo: int, hi: int,
    per_change: float, carry: float, ppy: int,
) -> Leg:  # fmt: skip
    daily: list[float] = []
    trades = 0
    prev = positions[lo - 1] if lo > 0 else 0
    for t in range(lo, hi):
        pos = positions[t]
        change = abs(pos - prev)
        trades += 1 if change else 0
        daily.append(pos * returns[t] - change * per_change - abs(pos) * carry)
        prev = pos
    if not daily:
        return Leg(0.0, 0.0, 0.0, 0.0, 0)
    mean = sum(daily) / len(daily)
    sd = (sum((x - mean) ** 2 for x in daily) / len(daily)) ** 0.5
    sharpe = (mean / sd) * math.sqrt(ppy) if sd > 0 else 0.0
    equity, peak, worst = 1.0, 1.0, 0.0
    for x in daily:
        equity *= 1 + x
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1)
    hold = closes[hi] / closes[lo] - 1 - 2 * per_change
    return Leg(round(sharpe, 3), round(equity - 1, 4), round(hold, 4), round(worst, 4), trades)


def evaluate(spec: Spec, series: Series, *, n_trials: int) -> Result | None:
    """One strategy on one market. ``None`` if the series is too short to say."""
    from aurelis.desks.costs import costs_for

    bars = series.bars
    if len(bars) < MIN_BARS:
        return None
    closes = [b[4] for b in bars]
    returns = [closes[t + 1] / closes[t] - 1 if closes[t] else 0.0 for t in range(len(closes) - 1)]
    positions = positions_for(spec, bars)
    model = costs_for(series.desk)
    per_change = float(model.round_trip_bps) / 2 / 10_000
    ppy = periods_per_year(series.desk)
    carry = float(model.carry_bps_annual) / 10_000 / ppy
    cut = int(len(returns) * SPLIT)
    first = _leg(returns, positions, closes, 0, cut, per_change, carry, ppy)
    second = _leg(returns, positions, closes, cut, len(returns), per_change, carry, ppy)
    bar = luck_bar(n_trials, cut / ppy)
    if first.sharpe <= bar:
        verdict = "no better than luck"
    elif second.sharpe > 0 and second.total > second.hold:
        verdict = "survived"
    else:
        verdict = "failed out of sample"
    return Result(spec, series.symbol, series.desk, len(bars), first, second, verdict)
