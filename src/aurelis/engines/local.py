"""The built-in engine: deterministic, offline, and free.

What CI runs on, and what the company uses until a desk's real engine is
wired. Everything here is exact decimal arithmetic over fixture bars, so the
same specification and seed produce a byte-identical artifact on any machine.

**The bar loop has one-bar latency, and that is the whole point.** A signal is
computed from bars up to and including *t*, and the resulting position is
entered at the open of *t+1*. A strategy therefore cannot act on information
from the bar it trades into. Written this way, look-ahead is structurally
impossible rather than something a reviewer has to notice — which is the same
discipline martex-quant's event-driven engine uses, and the reason its
vectorised screening layer is explicitly for pre-filtering only.

**Costs are never zero.** They come from the spec's cost model, they are
charged on every position change, and a spec that tried to omit them would
still get the default. A backtest without costs is not evidence.

This is not a market simulator and the fixture data is not a market. It exists
so the research lifecycle has something real to measure. Scenarios with a
*known planted answer* — which agents can legitimately be scored against —
are a different thing and arrive at M10.
"""

from __future__ import annotations

import statistics
from decimal import Decimal, getcontext
from typing import Any

from aurelis import __version__
from aurelis.core.canonical import sha256_of
from aurelis.engines.protocol import (
    EngineCapabilities,
    Metric,
    MetricSet,
    RunArtifact,
    UnsupportedMetric,
)
from aurelis.engines.spec import ExperimentSpec

__all__ = ["SIGNALS", "LocalEngine"]

getcontext().prec = 28

_BPS = Decimal("10000")
_ZERO = Decimal("0")
_QUANT = Decimal("0.00000001")

SIGNALS: frozenset[str] = frozenset(
    {"momentum", "mean_reversion", "always_long", "never_trade"}
)
"""The registered operations. A closed set, hand-written and unit-tested.

``never_trade`` and ``always_long`` are not filler: they are the baselines
every result must beat. A rule that cannot beat holding the asset has not
found anything, and a rule that cannot beat doing nothing has found less.
"""

METRICS: frozenset[str] = frozenset(
    {
        "total_return",
        "sharpe",
        "max_drawdown",
        "n_trades",
        "turnover",
        "cost_drag",
        "exposure",
        "mean_return",
    }
)


class LocalEngine:
    """Deterministic offline research engine."""

    name = "local"

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            name=self.name,
            version=__version__,
            available=True,
            detail=(
                "deterministic offline engine over fixture data; free, "
                "reproducible, and not a market simulation"
            ),
            signals=SIGNALS,
            metrics=METRICS,
            desks=frozenset({"crypto"}),
            deterministic=True,
        )

    # ------------------------------------------------------------------ run

    def run(self, spec: ExperimentSpec) -> RunArtifact:
        supported, reason = self.capabilities().supports(spec)
        if not supported:
            raise UnsupportedMetric(reason)

        from aurelis.intel.sources import source_for

        source = source_for(spec.universe.desk)
        symbol = spec.universe.symbols[0]
        bars = source.bars(symbol, limit=spec.data.bars)
        fingerprint = sha256_of([b.as_dict() for b in bars])

        closes = [b.close for b in bars]
        opens = [b.open for b in bars]

        exposures = self._exposures(spec, closes)
        curve, trades, costs = self._simulate(spec, opens, closes, exposures)
        metrics = self._measure(spec, curve, exposures, trades, costs)

        return RunArtifact(
            spec_digest=spec.digest(),
            data_fingerprint=fingerprint,
            code_version=f"aurelis-local@{__version__}",
            seed=spec.seed,
            metrics=metrics,
            series={
                "equity": [str(value) for value in curve],
                "exposure": [str(value) for value in exposures],
            },
            diagnostics={
                "symbol": symbol,
                "bars": len(bars),
                "source": source.name,
                "is_live": False,
                "warmup_bars": spec.backtest.warmup_bars,
                "round_trip_cost_bps": str(spec.backtest.costs.round_trip_bps),
            },
        )

    # -------------------------------------------------------------- signals

    @staticmethod
    def _exposures(spec: ExperimentSpec, closes: list[Decimal]) -> list[Decimal]:
        """Target exposure per bar, in [-1, 1], from bars up to and including t.

        Deliberately a pure function of past closes. The latency that stops it
        from being look-ahead is applied in :meth:`_simulate`, in one place,
        rather than trusted to each signal.
        """
        kind = spec.signal.kind
        lookback = max(1, spec.signal.lookback)
        threshold = spec.signal.threshold
        allow_short = spec.backtest.allow_short

        exposures: list[Decimal] = []
        for index, close in enumerate(closes):
            if kind == "never_trade":
                exposures.append(_ZERO)
                continue
            if kind == "always_long":
                exposures.append(Decimal(1))
                continue
            if index < lookback:
                exposures.append(_ZERO)
                continue

            past = closes[index - lookback]
            change = (close / past - Decimal(1)) if past else _ZERO

            if kind == "momentum":
                signal = Decimal(1) if change > threshold else _ZERO
                if allow_short and change < -threshold:
                    signal = Decimal(-1)
            else:  # mean_reversion
                signal = Decimal(1) if change < -threshold else _ZERO
                if allow_short and change > threshold:
                    signal = Decimal(-1)
            exposures.append(signal)
        return exposures

    # ------------------------------------------------------------ simulation

    @staticmethod
    def _simulate(
        spec: ExperimentSpec,
        opens: list[Decimal],
        closes: list[Decimal],
        exposures: list[Decimal],
    ) -> tuple[list[Decimal], int, Decimal]:
        """Walk the bars, one at a time, with one-bar execution latency.

        Per bar *t*: the position entered is the one the signal asked for at
        *t-1*, and it earns the return from *t*'s open to *t*'s close. A
        position change is charged the full round-trip cost.
        """
        equity = spec.backtest.initial_cash
        curve: list[Decimal] = []
        held = _ZERO
        trades = 0
        costs = _ZERO
        cost_rate = (
            spec.backtest.costs.fee_bps
            + spec.backtest.costs.spread_bps
            + spec.backtest.costs.slippage_bps
        ) / _BPS

        for index in range(len(closes)):
            # The signal from the PREVIOUS bar is what can be acted on now.
            target = exposures[index - 1] if index > 0 else _ZERO
            if index < spec.backtest.warmup_bars:
                target = _ZERO

            if target != held:
                charge = equity * abs(target - held) * cost_rate
                equity -= charge
                costs += charge
                trades += 1
                held = target

            if held != _ZERO and opens[index]:
                intrabar = closes[index] / opens[index] - Decimal(1)
                equity += equity * held * intrabar

            curve.append(equity.quantize(_QUANT))

        return curve, trades, costs.quantize(_QUANT)

    # ------------------------------------------------------------- measuring

    def _measure(
        self,
        spec: ExperimentSpec,
        curve: list[Decimal],
        exposures: list[Decimal],
        trades: int,
        costs: Decimal,
    ) -> MetricSet:
        start = spec.backtest.initial_cash
        end = curve[-1] if curve else start
        returns = [
            (curve[i] / curve[i - 1] - Decimal(1))
            for i in range(1, len(curve))
            if curve[i - 1]
        ]

        total_return = (end / start - Decimal(1)) if start else _ZERO
        mean = sum(returns, _ZERO) / Decimal(len(returns)) if returns else _ZERO

        sharpe, sharpe_low, sharpe_high = self._sharpe_with_interval(returns)
        drawdown = self._max_drawdown(curve)
        in_market = (
            Decimal(sum(1 for e in exposures if e != _ZERO)) / Decimal(len(exposures))
            if exposures
            else _ZERO
        )

        available: dict[str, Metric] = {
            "total_return": Metric(
                "total_return", total_return.quantize(_QUANT), unit="fraction",
                method="local.equity_ratio",
            ),
            "mean_return": Metric(
                "mean_return", mean.quantize(_QUANT), unit="per_bar",
                method="local.arithmetic_mean",
            ),
            "sharpe": Metric(
                "sharpe",
                sharpe,
                low=sharpe_low,
                high=sharpe_high,
                unit="per_bar",
                method="local.sharpe_normal_ci",
            ),
            "max_drawdown": Metric(
                "max_drawdown", drawdown, unit="fraction", method="local.peak_to_trough"
            ),
            "n_trades": Metric("n_trades", Decimal(trades), method="local.position_changes"),
            "turnover": Metric(
                "turnover",
                (Decimal(trades) / Decimal(len(curve))).quantize(_QUANT)
                if curve
                else _ZERO,
                unit="per_bar",
                method="local.trades_per_bar",
            ),
            "cost_drag": Metric(
                "cost_drag",
                (costs / start).quantize(_QUANT) if start else _ZERO,
                unit="fraction",
                method="local.total_costs_over_initial",
            ),
            "exposure": Metric(
                "exposure", in_market.quantize(_QUANT), unit="fraction",
                method="local.time_in_market",
            ),
        }
        return MetricSet(tuple(available[name] for name in spec.metrics if name in available))

    @staticmethod
    def _sharpe_with_interval(
        returns: list[Decimal],
    ) -> tuple[Decimal, Decimal | None, Decimal | None]:
        """Per-bar Sharpe with a normal-approximation confidence interval.

        The interval is the load-bearing part. Without it the verdict rule
        cannot tell "no effect" from "too few observations to say", and those
        two get reported as the same thing — which is how a research corpus
        quietly fills up with confident nothing.

        The approximation is honest for what it is: it assumes independent,
        roughly normal returns, which market returns are not. The method name
        travels with the metric so a reader can weigh it, and M5's bootstrap
        replaces it.
        """
        if len(returns) < 3:
            return _ZERO, None, None
        floats = [float(r) for r in returns]
        mean = statistics.fmean(floats)
        deviation = statistics.stdev(floats)
        if deviation == 0:
            return _ZERO, None, None

        n = len(floats)
        sharpe = mean / deviation
        # Lo (2002): se(SR) ~= sqrt((1 + SR^2/2) / n) for iid returns.
        standard_error = ((1 + sharpe * sharpe / 2) / n) ** 0.5
        margin = 1.96 * standard_error
        return (
            Decimal(str(round(sharpe, 8))),
            Decimal(str(round(sharpe - margin, 8))),
            Decimal(str(round(sharpe + margin, 8))),
        )

    @staticmethod
    def _max_drawdown(curve: list[Decimal]) -> Decimal:
        peak = _ZERO
        worst = _ZERO
        for value in curve:
            peak = max(peak, value)
            if peak:
                drop = (peak - value) / peak
                worst = max(worst, drop)
        return worst.quantize(_QUANT)


def describe_run(artifact: RunArtifact) -> dict[str, Any]:
    """Compact summary for a view or an evidence pack."""
    return {
        "spec": artifact.spec_digest[:12],
        "data": artifact.data_fingerprint[:12],
        "code": artifact.code_version,
        "seed": artifact.seed,
        **{m.name: str(m.value) for m in artifact.metrics.metrics},
    }
