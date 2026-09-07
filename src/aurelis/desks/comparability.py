"""Making research comparable across desks, and refusing when it is not.

This is M12's acceptance criterion — "its research is comparable across desks
in the ledger" — and until now the company could not do it. The engine reported
``sharpe`` with ``unit="per_bar"``, which was honest and useless: a per-bar
Sharpe of 0.05 on hourly crypto bars is about ``0.05 * sqrt(8760)`` annualised,
and the same number on daily equity bars is about ``0.05 * sqrt(252)``. Ranking
them side by side would rank them by sampling frequency, and the archive would
conclude that the fastest-sampled desk had the best research.

Three rules.

**Rate metrics are converted; level metrics are not.** A Sharpe ratio is a rate
per unit time and scales with the square root of the sampling frequency. Total
return over a window is a level — it does not care how finely the window was
sampled, and multiplying it by anything would be nonsense. Drawdown is a level
too. The table below says which is which, and a metric that is not in it is
**refused**, not passed through: passing an unknown metric through unchanged is
how a rate quietly gets compared unconverted.

**A conversion carries its factor.** The converted figure records the calendar,
the interval and the multiplier, so a reader can undo it. A number that has
been silently rescaled is worse than one that was never comparable.

**Two things measured on different windows are not comparable at all.** Not
after conversion, not with a caveat. Annualisation fixes the *frequency*
mismatch; it does nothing about a strategy measured over a bull quarter and one
measured over five years, and reporting those as comparable would be the more
dangerous error because it looks rigorous.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from aurelis.desks.calendars import TradingCalendar, calendar_for
from aurelis.engines.protocol import Metric

__all__ = [
    "METRIC_SCALING",
    "Comparable",
    "Incomparable",
    "Scaling",
    "annualise",
    "compare",
]


class Scaling(StrEnum):
    """How a metric behaves when the sampling frequency changes."""

    RATE = "rate"
    """Per unit time. Scales with ``sqrt(periods per year)`` — a Sharpe ratio.
    Comparable across desks only after conversion."""

    DRIFT = "drift"
    """Per unit time, linearly. A mean return per bar. Scales with the number
    of periods, not its square root."""

    LEVEL = "level"
    """Independent of sampling frequency. Total return over a window, maximum
    drawdown, exposure. Already comparable; converting one would be nonsense."""

    COUNT = "count"
    """A tally of events. Comparable only as a rate per unit time, and this
    module deliberately does not invent that rate — a trade count on an hourly
    desk and one on a daily desk are different questions, not the same question
    at different scales."""


METRIC_SCALING: dict[str, Scaling] = {
    "sharpe": Scaling.RATE,
    "deflated_sharpe": Scaling.RATE,
    "mean_return": Scaling.DRIFT,
    "total_return": Scaling.LEVEL,
    "max_drawdown": Scaling.LEVEL,
    "exposure": Scaling.LEVEL,
    "cost_drag": Scaling.LEVEL,
    "n_trades": Scaling.COUNT,
    "turnover": Scaling.COUNT,
}
"""How each metric the engine produces behaves under a change of frequency.

A closed table. A metric absent from it cannot be made comparable, and
:func:`annualise` refuses rather than passing it through — which is the failure
mode that matters, because an unconverted rate looks exactly like a converted
one.
"""


class Incomparable(ValueError):
    """These two measurements cannot be put side by side, and here is why."""


@dataclass(frozen=True, slots=True)
class Comparable:
    """One measurement, converted to a common footing, with the factor shown."""

    metric: str
    desk: str
    raw: Decimal
    value: Decimal
    scaling: Scaling
    factor: Decimal
    calendar: str
    interval: str
    periods_per_year: int
    unit: str

    @property
    def converted(self) -> bool:
        return self.factor != Decimal(1)

    def as_payload(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "desk": self.desk,
            "raw": str(self.raw),
            "value": str(self.value),
            "scaling": self.scaling.value,
            "factor": str(self.factor),
            "calendar": self.calendar,
            "interval": self.interval,
            "periods_per_year": self.periods_per_year,
            "unit": self.unit,
        }

    def describe(self) -> str:
        if not self.converted:
            return (
                f"{self.metric} {self.value} ({self.unit}, unconverted — "
                f"{self.scaling.value})"
            )
        return (
            f"{self.metric} {self.raw} per {self.interval} -> {self.value} "
            f"{self.unit} (x{self.factor.quantize(Decimal('0.001'))}, "
            f"{self.calendar} {self.periods_per_year}/yr)"
        )


def annualise(
    metric: Metric | str,
    value: Decimal | None = None,
    *,
    desk: str,
    interval: str = "1h",
    calendar: TradingCalendar | None = None,
) -> Comparable:
    """Put one measurement on an annual footing for its desk.

    Accepts either a :class:`~aurelis.engines.protocol.Metric` or a name and a
    value, because both callers exist: the station reads metrics off artifacts,
    and the comparison CLI reads names off the ledger.
    """
    if isinstance(metric, Metric):
        name, raw = metric.name, metric.value
    else:
        if value is None:
            raise TypeError("annualise() needs a value when given a metric name")
        name, raw = metric, value

    scaling = METRIC_SCALING.get(name)
    if scaling is None:
        raise Incomparable(
            f"{name!r} has no declared scaling behaviour, so it cannot be made "
            "comparable across desks. Passing it through unchanged would make "
            "an unconverted rate look exactly like a converted one. Metrics "
            f"with declared behaviour: {sorted(METRIC_SCALING)}"
        )

    cal = calendar or calendar_for(desk)
    periods = cal.periods_per_year(interval)

    if scaling is Scaling.RATE:
        factor = cal.annualisation(interval)
        unit = "annualised"
    elif scaling is Scaling.DRIFT:
        factor = Decimal(periods)
        unit = "per_year"
    elif scaling is Scaling.LEVEL:
        factor = Decimal(1)
        unit = "fraction"
    else:
        raise Incomparable(
            f"{name!r} is a count. A trade count on an hourly desk and one on a "
            "daily desk are different questions, not the same question at two "
            "scales, and this module will not invent a rate to join them."
        )

    return Comparable(
        metric=name,
        desk=desk,
        raw=raw,
        value=(raw * factor).quantize(Decimal("0.00000001")),
        scaling=scaling,
        factor=factor,
        calendar=cal.name,
        interval=interval,
        periods_per_year=periods,
        unit=unit,
    )


def compare(left: Comparable, right: Comparable, *, bars: tuple[int, int] | None = None) -> str:
    """Put two converted measurements side by side, or refuse.

    ``bars`` is the number of observations behind each. Given it, this refuses
    a comparison whose windows differ by more than a factor of two — because
    annualisation fixes a frequency mismatch and does nothing at all about a
    strategy measured over one quarter against one measured over five years.
    That comparison is the more dangerous of the two, because the conversion
    makes it look rigorous.
    """
    if left.metric != right.metric:
        raise Incomparable(
            f"{left.metric} and {right.metric} are different measurements"
        )
    if left.scaling is not right.scaling:  # pragma: no cover - same metric name
        raise Incomparable("the same metric cannot have two scaling behaviours")
    if bars is not None:
        low, high = sorted(bars)
        if low <= 0 or high > low * 2:
            raise Incomparable(
                f"{left.desk} was measured over {bars[0]} bars and {right.desk} "
                f"over {bars[1]}. Annualisation makes the frequencies "
                "comparable; it does nothing about the windows, and reporting "
                "these side by side would look rigorous while comparing a "
                "quarter against a decade."
            )
    winner = left if left.value >= right.value else right
    return (
        f"{left.desk} {left.value} vs {right.desk} {right.value} "
        f"({left.unit}) — {winner.desk} higher"
    )
