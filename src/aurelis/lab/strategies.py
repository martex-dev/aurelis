"""The classic strategies the lab tests (M65).

These are the known ways traders say they make money, written down
mechanically: trend following, momentum, breakouts, mean reversion and MACD,
plus mechanical versions of two ICT/SMC ideas, the fair value gap and the
liquidity sweep. None of them is the company's own idea. The point is to
learn, on years of data and with honest costs, which of the things people
teach survive. That is the floor the agents' own ideas have to clear.

**Rule for every function.** ``positions[t]`` is the position held from the
close of bar ``t`` to the close of bar ``t + 1``. It may only use bars up to
and including ``t``. A test (``test_lab.py``) checks that changing a future
bar never changes an earlier position.

The ICT/SMC versions are approximations, and the names say so. Those methods
are taught as discretionary reading of charts. What is tested here is the
part of each that can be written as a rule.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ["CATALOGUE", "Spec", "positions_for"]

Bars = Sequence[tuple[int, float, float, float, float, float]]
Rule = Callable[[Bars, dict[str, Any]], list[int]]


def _sma(values: Sequence[float], n: int, t: int) -> float | None:
    if t + 1 < n:
        return None
    return sum(values[t - n + 1 : t + 1]) / n


def _ema_series(values: Sequence[float], n: int) -> list[float]:
    k = 2.0 / (n + 1)
    out: list[float] = []
    for i, v in enumerate(values):
        out.append(v if i == 0 else v * k + out[-1] * (1 - k))
    return out


def sma_cross(bars: Bars, p: dict[str, Any]) -> list[int]:
    closes = [b[4] for b in bars]
    out = []
    for t in range(len(closes)):
        fast, slow = _sma(closes, p["fast"], t), _sma(closes, p["slow"], t)
        out.append(0 if fast is None or slow is None else (1 if fast > slow else -1))
    return out


def momentum(bars: Bars, p: dict[str, Any]) -> list[int]:
    closes = [b[4] for b in bars]
    n = p["lookback"]
    return [0 if t < n else (1 if closes[t] > closes[t - n] else -1) for t in range(len(closes))]


def donchian(bars: Bars, p: dict[str, Any]) -> list[int]:
    """Enter on a close beyond the last ``n`` bars' range; leave on half that range."""
    n, exit_n = p["n"], max(2, p["n"] // 2)
    out: list[int] = []
    state = 0
    for t in range(len(bars)):
        if t >= n:
            hi = max(b[2] for b in bars[t - n : t])
            lo = min(b[3] for b in bars[t - n : t])
            ex_hi = max(b[2] for b in bars[t - exit_n : t])
            ex_lo = min(b[3] for b in bars[t - exit_n : t])
            close = bars[t][4]
            if close > hi:
                state = 1
            elif close < lo:
                state = -1
            elif (state == 1 and close < ex_lo) or (state == -1 and close > ex_hi):
                state = 0
        out.append(state)
    return out


def rsi_reversion(bars: Bars, p: dict[str, Any]) -> list[int]:
    """Buy oversold, sell overbought, flat in between (Wilder's RSI)."""
    closes = [b[4] for b in bars]
    n, low, high = p["period"], p["low"], p["high"]
    out: list[int] = []
    gain = loss = 0.0
    for t in range(len(closes)):
        if t == 0:
            out.append(0)
            continue
        change = closes[t] - closes[t - 1]
        g, lo = max(change, 0.0), max(-change, 0.0)
        if t <= n:
            gain += g / n
            loss += lo / n
            out.append(0)
            continue
        gain = (gain * (n - 1) + g) / n
        loss = (loss * (n - 1) + lo) / n
        rsi = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
        out.append(1 if rsi < low else (-1 if rsi > high else 0))
    return out


def bollinger_reversion(bars: Bars, p: dict[str, Any]) -> list[int]:
    closes = [b[4] for b in bars]
    n, k = p["n"], p["k"]
    out: list[int] = []
    for t in range(len(closes)):
        if t + 1 < n:
            out.append(0)
            continue
        window = closes[t - n + 1 : t + 1]
        mean = sum(window) / n
        sd = (sum((x - mean) ** 2 for x in window) / n) ** 0.5
        c = closes[t]
        out.append(1 if c < mean - k * sd else (-1 if c > mean + k * sd else 0))
    return out


def macd(bars: Bars, p: dict[str, Any]) -> list[int]:
    closes = [b[4] for b in bars]
    fast, slow = _ema_series(closes, p["fast"]), _ema_series(closes, p["slow"])
    line = [f - s for f, s in zip(fast, slow, strict=True)]
    signal = _ema_series(line, p["signal"])
    warm = p["slow"] + p["signal"]
    return [0 if t < warm else (1 if line[t] > signal[t] else -1) for t in range(len(closes))]


def fvg_ict(bars: Bars, p: dict[str, Any]) -> list[int]:
    """ICT-style fair value gap, approximated: a three-bar gap up (today's low
    above the high two bars ago) is bought, a gap down sold, held ``hold`` bars."""
    hold = p["hold"]
    out: list[int] = []
    state, left = 0, 0
    for t in range(len(bars)):
        if t >= 2:
            if bars[t][3] > bars[t - 2][2]:
                state, left = 1, hold
            elif bars[t][2] < bars[t - 2][3]:
                state, left = -1, hold
        if left > 0:
            left -= 1
        else:
            state = 0
        out.append(state)
    return out


def sweep_smc(bars: Bars, p: dict[str, Any]) -> list[int]:
    """SMC-style liquidity sweep, approximated: price takes out the last
    ``n`` bars' high and closes back below it (a sweep of buy-side liquidity),
    so short; the mirror for lows. Held ``hold`` bars."""
    n, hold = p["n"], p["hold"]
    out: list[int] = []
    state, left = 0, 0
    for t in range(len(bars)):
        if t >= n:
            hi = max(b[2] for b in bars[t - n : t])
            lo = min(b[3] for b in bars[t - n : t])
            _, _, high, low, close, _ = bars[t]
            if high > hi and close < hi:
                state, left = -1, hold
            elif low < lo and close > lo:
                state, left = 1, hold
        if left > 0:
            left -= 1
        else:
            state = 0
        out.append(state)
    return out


@dataclass(frozen=True, slots=True)
class Spec:
    family: str
    params: tuple[tuple[str, Any], ...]
    long_only: bool
    note: str = ""

    @property
    def name(self) -> str:
        args = ",".join(f"{k}={v}" for k, v in self.params)
        return f"{self.family}({args}){' long-only' if self.long_only else ''}"


_RULES: dict[str, Rule] = {
    "sma_cross": sma_cross,
    "momentum": momentum,
    "donchian": donchian,
    "rsi_reversion": rsi_reversion,
    "bollinger_reversion": bollinger_reversion,
    "macd": macd,
    "fvg_ict": fvg_ict,
    "sweep_smc": sweep_smc,
}

_GRID: tuple[tuple[str, tuple[dict[str, Any], ...]], ...] = (
    ("sma_cross", ({"fast": 5, "slow": 20}, {"fast": 10, "slow": 50},
                   {"fast": 20, "slow": 100}, {"fast": 50, "slow": 200})),
    ("momentum", ({"lookback": 20}, {"lookback": 60}, {"lookback": 120}, {"lookback": 250})),
    ("donchian", ({"n": 20}, {"n": 55})),
    ("rsi_reversion", ({"period": 2, "low": 10, "high": 90},
                       {"period": 14, "low": 30, "high": 70})),
    ("bollinger_reversion", ({"n": 20, "k": 2.0},)),
    ("macd", ({"fast": 12, "slow": 26, "signal": 9},)),
    ("fvg_ict", ({"hold": 3}, {"hold": 10})),
    ("sweep_smc", ({"n": 20, "hold": 5}, {"n": 10, "hold": 3})),
)  # fmt: skip

CATALOGUE: tuple[Spec, ...] = tuple(
    Spec(family, tuple(sorted(params.items())), long_only)
    for family, grid in _GRID
    for params in grid
    for long_only in (False, True)
)
"""Every strategy the lab tests: 18 settings, each long-short and long-only."""


def positions_for(spec: Spec, bars: Bars) -> list[int]:
    raw = _RULES[spec.family](bars, dict(spec.params))
    return [max(0, p) for p in raw] if spec.long_only else raw
