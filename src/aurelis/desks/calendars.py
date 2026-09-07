"""Trading calendars, and the number that makes research comparable.

A desk is not just a set of instruments. It is a **clock**. Crypto trades every
hour of every day; the New York Stock Exchange trades six and a half hours on
about 252 days a year; CME futures trade nearly around the clock but still
close; FX runs five days a week and stops for the weekend.

That difference is why a per-bar Sharpe ratio cannot be compared across desks,
and until M12 the company could not compare its own research: the engine
reported ``sharpe`` with ``unit="per_bar"``, which was honest and useless. A
per-bar Sharpe of 0.05 on hourly crypto bars and one of 0.05 on daily equity
bars are different quantities wearing the same name — the first is roughly
``0.05 * sqrt(8760)``, the second roughly ``0.05 * sqrt(252)``, and a research
archive that ranked them side by side would rank them by *sampling frequency*.

So a calendar carries ``periods_per_year`` for each interval it supports, and
that number is the conversion. It is declared per calendar rather than derived
from a formula, because the derivation is where the error lives: 24/7 really is
8760 hourly bars a year, but XNYS is 6.5 hours a session and 252 sessions, so
1638 hourly bars — not 8760, and not 6132.

``periods_per_year`` is deliberately **not** available for every interval on
every calendar. Asking for weekly bars on a calendar that has not declared them
is a ``KeyError`` rather than a guess, for the same reason an engine refuses a
metric it cannot compute: a plausible wrong number is worse than a refusal.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

__all__ = ["CALENDARS", "TradingCalendar", "calendar_for", "calendar_named"]


@dataclass(frozen=True, slots=True)
class TradingCalendar:
    """When a market is open, and how many bars of each size that is."""

    name: str
    description: str
    sessions_per_year: int
    hours_per_session: Decimal
    weekend_open: bool
    periods: dict[str, int]
    """Interval to bars per year. The conversion factor for annualisation."""

    holidays: int = 0
    """Sessions lost to declared holidays, already deducted from
    ``sessions_per_year``. Recorded so the deduction is visible."""

    def periods_per_year(self, interval: str) -> int:
        """Bars of ``interval`` in a year on this calendar."""
        try:
            return self.periods[interval]
        except KeyError:
            raise KeyError(
                f"{self.name} has not declared how many {interval!r} bars it "
                f"has in a year; it declares {sorted(self.periods)}. A guessed "
                "conversion factor would silently rescale every Sharpe ratio "
                "computed on this desk."
            ) from None

    def annualisation(self, interval: str) -> Decimal:
        """``sqrt(periods per year)`` — what a per-bar Sharpe is multiplied by."""
        return Decimal(self.periods_per_year(interval)).sqrt()

    def is_session(self, moment: dt.datetime) -> bool:
        """Whether the market is open at ``moment``.

        Coarse on purpose: weekday and hour-of-day, no holiday table. A desk
        whose backtests depend on an exact holiday calendar needs a real one,
        and this says so rather than pretending. What it does catch is the
        error that matters at this stage — an equity strategy trading on a
        Sunday.
        """
        if not self.weekend_open and moment.weekday() >= 5:
            return False
        if self.hours_per_session >= 24:
            return True
        open_hour = 14 if self.name == "XNYS" else 0
        span = int(self.hours_per_session)
        return open_hour <= moment.hour < open_hour + span

    def as_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sessions_per_year": self.sessions_per_year,
            "hours_per_session": str(self.hours_per_session),
            "weekend_open": self.weekend_open,
            "periods": dict(sorted(self.periods.items())),
        }

    def describe(self) -> str:
        return (
            f"{self.name}: {self.sessions_per_year} sessions x "
            f"{self.hours_per_session}h"
            + (" including weekends" if self.weekend_open else ", weekdays only")
        )


CALENDARS: dict[str, TradingCalendar] = {
    calendar.name: calendar
    for calendar in (
        TradingCalendar(
            name="24/7",
            description="Continuous. Crypto and memecoins.",
            sessions_per_year=365,
            hours_per_session=Decimal(24),
            weekend_open=True,
            # 365 * 24 = 8760. The one calendar where the naive answer is right.
            periods={"1h": 8760, "4h": 2190, "1d": 365, "1w": 52},
        ),
        TradingCalendar(
            name="XNYS",
            description="New York Stock Exchange. Equities and listed options.",
            sessions_per_year=252,
            hours_per_session=Decimal("6.5"),
            weekend_open=False,
            holidays=10,
            # 252 * 6.5 = 1638 hourly bars, not 8760 and not 6132. Getting this
            # wrong rescales every annualised Sharpe on the desk by 2.3x.
            periods={"1h": 1638, "1d": 252, "1w": 52},
        ),
        TradingCalendar(
            name="CME",
            description="Chicago Mercantile Exchange. Futures and commodities.",
            sessions_per_year=252,
            hours_per_session=Decimal(23),
            weekend_open=False,
            holidays=10,
            # Nearly around the clock, and still not 24/7: the daily halt and
            # the weekend together cost about a third of the year.
            periods={"1h": 5796, "4h": 1449, "1d": 252},
        ),
        TradingCalendar(
            name="24/5",
            description="Continuous on weekdays. Spot FX.",
            sessions_per_year=260,
            hours_per_session=Decimal(24),
            weekend_open=False,
            periods={"1h": 6240, "4h": 1560, "1d": 260},
        ),
    )
}
"""The four calendars the seven desks run on.

Sharing a calendar is what makes two desks' research directly comparable:
equities and options are both XNYS, futures and commodities are both CME. Two
desks on different calendars are comparable only after conversion, and
:mod:`aurelis.desks.comparability` is where that conversion is applied and
recorded.
"""


def calendar_named(name: str) -> TradingCalendar:
    try:
        return CALENDARS[name]
    except KeyError:
        raise KeyError(
            f"no calendar {name!r}; the registry holds {sorted(CALENDARS)}"
        ) from None


def calendar_for(desk: str) -> TradingCalendar:
    """The calendar the desk registry says this desk runs on."""
    from aurelis.org.desks import DESKS, Desk

    try:
        spec = DESKS[Desk(desk)]
    except (KeyError, ValueError):
        raise KeyError(f"no desk {desk!r}") from None
    return calendar_named(spec.calendar)
