"""How much data a claim needs, per desk — and why bars are the wrong unit.

The engine estimates a Sharpe ratio's standard error as Lo (2002) does,
``sqrt((1 + SR^2/2) / n)``, and the verdict rule calls a design underpowered
when the resulting interval is wider than twice the minimum effect it set out
to detect. Put those together and the number of observations a claim needs
falls out:

.. code-block:: text

    1.96 * sqrt((1 + SR^2/2) / n)  <=  minimum_effect
    n  >=  (1.96 / minimum_effect)^2 * (1 + SR^2/2)

Which is where the cross-desk lesson lives, and it is not the obvious one.

A claim is worth stating **annualised** — "a Sharpe of 1" means the same thing
to everyone, while "a per-bar Sharpe of 0.05" means an annualised 4.7 on crypto
and 2.0 on equities. Converting an annualised claim down to each desk's per-bar
minimum effect divides it by ``sqrt(periods per year)``, so a high-frequency
desk is chasing a *smaller* per-bar effect and needs *more* bars — and the two
cancel exactly.

**The same annualised claim needs the same number of years on every desk, and a
completely different number of bars.** Settling an annualised Sharpe of 1
takes about 3.8 years everywhere: roughly 33,000 hourly bars on crypto and
6,300 on equities, because a year of crypto has 8760 hours in it and a year of
NYSE has 1638.

The practical consequence is that **a research budget stated in bars is not a
budget.** Giving every desk "1,200 bars" gives crypto seven weeks and equities
nine months, and systematically underpowers whichever desk samples fastest —
while looking scrupulously even-handed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aurelis.desks.calendars import calendar_for

__all__ = ["PowerRequirement", "bars_for_span", "required_observations"]

_Z = Decimal("1.96")


@dataclass(frozen=True, slots=True)
class PowerRequirement:
    """What one desk needs to settle one claim."""

    desk: str
    annualised_claim: Decimal
    per_bar_effect: Decimal
    interval: str
    periods_per_year: int
    bars_required: int
    bars_available: int

    @property
    def years_required(self) -> Decimal:
        return (
            Decimal(self.bars_required) / Decimal(self.periods_per_year)
        ).quantize(Decimal("0.01"))

    @property
    def years_available(self) -> Decimal:
        return (
            Decimal(self.bars_available) / Decimal(self.periods_per_year)
        ).quantize(Decimal("0.01"))

    @property
    def powered(self) -> bool:
        return self.bars_available >= self.bars_required

    def as_payload(self) -> dict[str, Any]:
        return {
            "desk": self.desk,
            "annualised_claim": str(self.annualised_claim),
            "per_bar_effect": str(self.per_bar_effect),
            "interval": self.interval,
            "periods_per_year": self.periods_per_year,
            "bars_required": self.bars_required,
            "bars_available": self.bars_available,
            "years_required": str(self.years_required),
            "years_available": str(self.years_available),
            "powered": self.powered,
        }

    def describe(self) -> str:
        return (
            f"{self.desk}: needs {self.bars_required} {self.interval} bars "
            f"({self.years_required}y), has {self.bars_available} "
            f"({self.years_available}y)"
        )


def required_observations(
    desk: str,
    *,
    annualised_claim: Decimal,
    interval: str = "1h",
    bars_available: int = 0,
) -> PowerRequirement:
    """How many bars this desk needs to settle an annualised Sharpe claim.

    The claim is stated annualised on purpose. Stated per bar, the seven desks
    would be asked seven different questions wearing the same number.
    """
    calendar = calendar_for(desk)
    periods = calendar.periods_per_year(interval)
    per_bar = annualised_claim / calendar.annualisation(interval)
    if per_bar <= 0:
        raise ValueError("an annualised claim must be positive")
    # n >= (z / effect)^2 * (1 + SR^2 / 2), with SR the per-bar figure.
    inflation = Decimal(1) + (per_bar * per_bar) / Decimal(2)
    required = ((_Z / per_bar) ** 2) * inflation
    return PowerRequirement(
        desk=desk,
        annualised_claim=annualised_claim,
        per_bar_effect=per_bar.quantize(Decimal("0.00000001")),
        interval=interval,
        periods_per_year=periods,
        bars_required=int(required.to_integral_value(rounding="ROUND_CEILING")),
        bars_available=bars_available,
    )


def bars_for_span(desk: str, *, years: Decimal, interval: str = "1h") -> int:
    """How many bars of ``interval`` cover ``years`` on this desk's calendar.

    The only honest way to give seven desks the same research budget. A budget
    in bars gives crypto seven weeks and equities nine months for the same
    number.
    """
    calendar = calendar_for(desk)
    periods = calendar.periods_per_year(interval)
    return max(1, int((Decimal(periods) * years).to_integral_value()))
