"""The built-in engine: deterministic, offline, and free.

What CI runs on, and what the company uses until a desk's real engine is
wired. Everything here is exact decimal arithmetic over fixture bars, so the
same specification and seed produce a byte-identical artifact on any machine.

**The bar loop has one-bar latency, and that is the whole point.** A signal is
computed from bars up to and including *t*, and the resulting book is entered
at the open of *t+1*. A strategy therefore cannot act on information from the
bar it trades into. Written this way, look-ahead is structurally impossible
rather than something a reviewer has to notice — the same discipline
martex-quant's event-driven engine uses, and the reason its vectorised
screening layer is explicitly for pre-filtering only.

**The universe is resolved, not assumed.** ``point_in_time`` decides whether a
run may trade names that later died. That single flag is the difference
between a defensible backtest and one that has quietly been told the answer,
and it is measurable here rather than merely arguable.

**Costs are never zero.** They come from the spec's cost model, they are
charged on every change in the book, and a spec that tried to omit them would
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

__all__ = ["METRICS", "SIGNALS", "LocalEngine", "describe_run"]

getcontext().prec = 28

_BPS = Decimal("10000")
_ZERO = Decimal("0")
_QUANT = Decimal("0.00000001")

SIGNALS: frozenset[str] = frozenset(
    {"momentum", "mean_reversion", "rotation", "always_long", "never_trade"}
)
"""The registered operations. A closed set, hand-written and unit-tested.

``never_trade`` and ``always_long`` are not filler: they are the baselines
every result must beat. A rule that cannot beat holding the asset has not
found anything, and one that cannot beat doing nothing has found less.

``rotation`` is cross-sectional — it ranks the whole universe each bar and
holds the leaders. It is the signal survivorship bias actually bites, because
a universe chosen with hindsight can never rotate into a name that later died.
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

        from aurelis.engines.universe import resolve_universe
        from aurelis.intel.sources import source_for

        source = source_for(spec.universe.desk)
        universe = resolve_universe(
            spec.universe.desk,
            spec.universe.symbols,
            point_in_time=spec.universe.point_in_time,
            as_of=source.anchor(),
        )
        if not universe.symbols:
            raise UnsupportedMetric(
                f"the {spec.universe.desk} universe resolved to nothing under "
                f"{'point-in-time' if spec.universe.point_in_time else 'hindsight'} "
                "selection; there is no experiment to run"
            )

        series = {
            symbol: source.bars(symbol, limit=spec.data.bars)
            for symbol in universe.symbols
        }
        fingerprint = sha256_of(
            {symbol: [b.as_dict() for b in bars] for symbol, bars in series.items()}
        )

        weights = self._weights(spec, series)
        curve, trades, costs = self._simulate(spec, series, weights)
        metrics = self._measure(spec, curve, weights, trades, costs)

        return RunArtifact(
            spec_digest=spec.digest(),
            data_fingerprint=fingerprint,
            code_version=f"aurelis-local@{__version__}",
            seed=spec.seed,
            metrics=metrics,
            series={"equity": [str(value) for value in curve]},
            diagnostics={
                "universe": list(universe.symbols),
                "universe_basis": "point_in_time" if universe.point_in_time else "hindsight",
                "excluded_by_hindsight": list(universe.excluded),
                "survivorship_exposed": universe.survivorship_exposed,
                "bars": spec.data.bars,
                "source": source.name,
                "is_live": False,
                "round_trip_cost_bps": str(spec.backtest.costs.round_trip_bps),
            },
        )

    # -------------------------------------------------------------- signals

    def _weights(
        self, spec: ExperimentSpec, series: dict[str, list[Any]]
    ) -> list[dict[str, Decimal]]:
        """Target weight per symbol per bar, from bars up to and including t.

        A pure function of past closes. The latency that stops it from being
        look-ahead is applied once, in :meth:`_simulate`, rather than trusted
        to each signal separately.
        """
        symbols = sorted(series)
        length = min(len(series[symbol]) for symbol in symbols)
        closes = {symbol: [bar.close for bar in series[symbol]] for symbol in symbols}
        lookback = max(1, spec.signal.lookback)

        if spec.signal.kind == "rotation":
            top_k = max(1, int(spec.signal.parameters.get("top_k", 1)))
            return self._rotation(closes, symbols, length, lookback, top_k)

        primary = symbols[0]
        weights: list[dict[str, Decimal]] = []
        for index in range(length):
            exposure = self._single(
                spec.signal.kind,
                closes[primary],
                index,
                lookback,
                spec.signal.threshold,
                allow_short=spec.backtest.allow_short,
            )
            weights.append({primary: exposure} if exposure != _ZERO else {})
        return weights

    @staticmethod
    def _single(
        kind: str,
        closes: list[Decimal],
        index: int,
        lookback: int,
        threshold: Decimal,
        *,
        allow_short: bool,
    ) -> Decimal:
        if kind == "never_trade":
            return _ZERO
        if kind == "always_long":
            return Decimal(1)
        if index < lookback:
            return _ZERO
        past = closes[index - lookback]
        change = (closes[index] / past - Decimal(1)) if past else _ZERO
        if kind == "momentum":
            if change > threshold:
                return Decimal(1)
            return Decimal(-1) if allow_short and change < -threshold else _ZERO
        if change < -threshold:
            return Decimal(1)
        return Decimal(-1) if allow_short and change > threshold else _ZERO

    @staticmethod
    def _rotation(
        closes: dict[str, list[Decimal]],
        symbols: list[str],
        length: int,
        lookback: int,
        top_k: int,
    ) -> list[dict[str, Decimal]]:
        """Hold the top ``k`` names by trailing return, equally weighted.

        Cross-sectional, and therefore the signal on which the universe
        definition matters most: a hindsight universe can only rank names that
        survived, so it never picks the one that was about to die.
        """
        weights: list[dict[str, Decimal]] = []
        for index in range(length):
            if index < lookback:
                weights.append({})
                continue
            ranked: list[tuple[Decimal, str]] = []
            for symbol in symbols:
                past = closes[symbol][index - lookback]
                change = (closes[symbol][index] / past - Decimal(1)) if past else _ZERO
                ranked.append((change, symbol))
            # Symbol is the tiebreak so the ordering is total and the run stays
            # byte-reproducible.
            ranked.sort(key=lambda pair: (-pair[0], pair[1]))
            chosen = [symbol for change, symbol in ranked[:top_k] if change > _ZERO]
            if not chosen:
                weights.append({})
                continue
            share = Decimal(1) / Decimal(len(chosen))
            weights.append(dict.fromkeys(chosen, share))
        return weights

    # ------------------------------------------------------------ simulation

    @staticmethod
    def _simulate(
        spec: ExperimentSpec,
        series: dict[str, list[Any]],
        weights: list[dict[str, Decimal]],
    ) -> tuple[list[Decimal], int, Decimal]:
        """Walk the bars with one-bar execution latency.

        Per bar *t*, the book held is the one the signal asked for at *t-1*,
        and each position earns that symbol's open-to-close return for *t*. Any
        change in the book is charged the cost of the difference traded.
        """
        equity = spec.backtest.initial_cash
        curve: list[Decimal] = []
        held: dict[str, Decimal] = {}
        trades = 0
        costs = _ZERO
        cost_rate = (
            spec.backtest.costs.fee_bps
            + spec.backtest.costs.spread_bps
            + spec.backtest.costs.slippage_bps
        ) / _BPS

        for index in range(len(weights)):
            target = weights[index - 1] if index > 0 else {}
            if index < spec.backtest.warmup_bars:
                target = {}

            traded = sum(
                (
                    abs(target.get(symbol, _ZERO) - held.get(symbol, _ZERO))
                    for symbol in set(target) | set(held)
                ),
                _ZERO,
            )
            if traded > _ZERO:
                charge = equity * traded * cost_rate
                equity -= charge
                costs += charge
                trades += 1
                held = dict(target)

            for symbol, weight in held.items():
                bar = series[symbol][index]
                if bar.open:
                    equity += equity * weight * (bar.close / bar.open - Decimal(1))

            curve.append(equity.quantize(_QUANT))

        return curve, trades, costs.quantize(_QUANT)

    # ------------------------------------------------------------- measuring

    def _measure(
        self,
        spec: ExperimentSpec,
        curve: list[Decimal],
        exposures: list[dict[str, Decimal]],
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
            Decimal(sum(1 for book in exposures if book)) / Decimal(len(exposures))
            if exposures
            else _ZERO
        )

        return_low, return_high = self._block_bootstrap(
            returns, "total_return", seed=spec.seed
        )
        drawdown_low, drawdown_high = self._block_bootstrap(
            returns, "max_drawdown", seed=spec.seed
        )

        available: dict[str, Metric] = {
            "total_return": Metric(
                "total_return",
                total_return.quantize(_QUANT),
                low=return_low,
                high=return_high,
                unit="fraction",
                method="local.equity_ratio+block_bootstrap",
            ),
            "mean_return": Metric(
                "mean_return",
                mean.quantize(_QUANT),
                unit="per_bar",
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
                "max_drawdown",
                drawdown,
                low=drawdown_low,
                high=drawdown_high,
                unit="fraction",
                method="local.peak_to_trough+block_bootstrap",
            ),
            "n_trades": Metric(
                "n_trades", Decimal(trades), method="local.book_changes"
            ),
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
                "exposure",
                in_market.quantize(_QUANT),
                unit="fraction",
                method="local.time_in_market",
            ),
        }
        return MetricSet(
            tuple(available[name] for name in spec.metrics if name in available)
        )

    @staticmethod
    def _sharpe_with_interval(
        returns: list[Decimal],
    ) -> tuple[Decimal, Decimal | None, Decimal | None]:
        """Per-bar Sharpe with a normal-approximation confidence interval.

        The interval is the load-bearing part. Without it the verdict rule
        cannot tell "no effect" from "too few observations to say", and those
        two get reported as the same thing — which is how a research corpus
        quietly fills up with confident nothing.

        The approximation is honest about what it is: it assumes independent,
        roughly normal returns, which market returns are not. The method name
        travels with the metric so a reader can weigh it.
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


    # ------------------------------------------------------------- bootstrap

    @staticmethod
    def _block_bootstrap(
        returns: list[Decimal],
        statistic: str,
        *,
        seed: int,
        resamples: int = 200,
        block: int = 8,
    ) -> tuple[Decimal | None, Decimal | None]:
        """A circular block bootstrap interval for a path-dependent statistic.

        Total return and drawdown are functions of the whole path, so the
        normal approximation that works for a Sharpe ratio does not apply to
        them. Resampling *blocks* rather than individual returns keeps the
        local autocorrelation that makes a drawdown a drawdown -- shuffling
        returns one at a time would destroy the runs of losses that are the
        entire thing being measured, and produce an interval far too narrow.

        Without an interval these metrics cannot support a confirmatory claim
        at all: the verdict rule reports UNDERPOWERED, which is correct but
        makes every path-based claim unanswerable. This is what makes them
        answerable.

        Deterministic: the generator is seeded from the specification, so the
        same run reproduces the same interval. Arithmetic is in float because
        this is an uncertainty *estimate* rather than a measurement -- the
        point estimate above stays exact decimal, and the method name travels
        with the metric so a reader can weigh the difference.
        """
        import random as _random

        n = len(returns)
        if n < 3 * block:
            return None, None

        values = [float(r) for r in returns]
        rng = _random.Random(seed * 1_000_003 + n)
        outcomes: list[float] = []

        for _ in range(resamples):
            path: list[float] = []
            while len(path) < n:
                start = rng.randrange(n)
                path.extend(values[(start + i) % n] for i in range(block))
            path = path[:n]

            equity = 1.0
            peak = 1.0
            worst = 0.0
            for step in path:
                equity *= 1.0 + step
                peak = max(peak, equity)
                if peak:
                    worst = max(worst, (peak - equity) / peak)
            outcomes.append(worst if statistic == "max_drawdown" else equity - 1.0)

        outcomes.sort()
        low = outcomes[int(0.025 * resamples)]
        high = outcomes[min(resamples - 1, int(0.975 * resamples))]
        return Decimal(str(round(low, 8))), Decimal(str(round(high, 8)))

    @staticmethod
    def _max_drawdown(curve: list[Decimal]) -> Decimal:
        peak = _ZERO
        worst = _ZERO
        for value in curve:
            peak = max(peak, value)
            if peak:
                worst = max(worst, (peak - value) / peak)
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
