"""What each market structurally is, derived from the desk registry.

Aurelis inherited a corpus tested on crypto alone and covers seven markets. The
gap between those two facts is where a whole class of false discovery lives: a
funding-rate signal is not a market regularity, it is a *perpetual-swap*
regularity, and applying it to equities produces a number that means nothing
while looking exactly like a result.

So components declare what they *assume* — continuous trading, a funding rate,
short availability — and this module answers whether a desk provides it. A
component whose assumptions a desk cannot meet is ``INAPPLICABLE`` there, which
is a different and much more useful statement than a bad backtest.

Capabilities are **derived from** :data:`~aurelis.org.desks.DESKS` rather than
listed again here. A second table of market facts would be a second source of
truth about the same seven markets, and the two would disagree the first time
somebody edited one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aurelis.org.desks import DESKS, Desk, DeskSpec

__all__ = [
    "Assumption",
    "MarketProfile",
    "profile",
    "unknown_assumptions",
    "unmet_assumptions",
]


class Assumption(StrEnum):
    """A structural fact a component may depend on.

    Deliberately about market *mechanics*, not about whether an edge exists.
    "Momentum works here" is a hypothesis; "this market trades continuously"
    is a property of the venue, and only the second belongs in a check.
    """

    CONTINUOUS_TRADING = "continuous_trading"
    """No session boundaries. Overnight gaps do not exist, so a rule that
    holds through the close means something different."""

    SESSION_CALENDAR = "session_calendar"
    """The opposite: there are opens, closes and holidays to reason about."""

    PERPETUAL_FUNDING = "perpetual_funding"
    """A periodic funding payment between longs and shorts. Crypto perps and
    almost nothing else."""

    TERM_STRUCTURE = "term_structure"
    """Dated contracts with a curve — futures, options, some commodities."""

    IMPLIED_VOLATILITY = "implied_volatility"
    SHORT_SELLING = "short_selling"
    FUNDAMENTALS = "fundamentals"
    """Issuer accounts. Equities have them; a currency pair does not."""

    PHYSICAL_DELIVERY = "physical_delivery"


@dataclass(frozen=True, slots=True)
class MarketProfile:
    """What one desk structurally provides."""

    desk: Desk
    name: str
    calendar: str
    instruments: tuple[str, ...]
    provides: frozenset[Assumption]

    def meets(self, assumption: Assumption) -> bool:
        return assumption in self.provides

    def describe(self) -> str:
        return (
            f"{self.name} ({self.calendar}): "
            + ", ".join(sorted(item.value for item in self.provides))
        )


def profile(desk: Desk) -> MarketProfile:
    """Derive one desk's structural capabilities from its registry entry."""
    spec = DESKS[desk]
    return MarketProfile(
        desk=desk,
        name=spec.name,
        calendar=spec.calendar,
        instruments=spec.instruments,
        provides=frozenset(_derive(spec)),
    )


def unmet_assumptions(
    desk: Desk, assumptions: tuple[str, ...]
) -> tuple[Assumption, ...]:
    """Which of a component's assumptions this desk does not provide.

    Unknown assumption names are ignored rather than rejected: the vocabulary
    will grow as desks open, and a component naming something this version does
    not model should not be silently treated as satisfied *or* blocked. It is
    reported by :func:`unknown_assumptions` instead.
    """
    market = profile(desk)
    unmet: list[Assumption] = []
    for name in assumptions:
        try:
            assumption = Assumption(name)
        except ValueError:
            continue
        if not market.meets(assumption):
            unmet.append(assumption)
    return tuple(unmet)


def unknown_assumptions(assumptions: tuple[str, ...]) -> tuple[str, ...]:
    """Assumption names this version of the vocabulary does not model.

    Surfaced rather than swallowed. A component depending on something the
    checker cannot evaluate is a gap in the checker, and pretending otherwise
    would make the check look more complete than it is.
    """
    known = {item.value for item in Assumption}
    return tuple(name for name in assumptions if name not in known)


def _derive(spec: DeskSpec) -> set[Assumption]:
    """Read structural facts off a desk's registry entry.

    Mechanical on purpose. Every rule below is a statement about the venue that
    a reader can check against the registry, not a judgement about the market.
    """
    provides: set[Assumption] = set()
    instruments = {item.lower() for item in spec.instruments}

    if spec.calendar == "24/7":
        provides.add(Assumption.CONTINUOUS_TRADING)
    else:
        provides.add(Assumption.SESSION_CALENDAR)

    if {"perpetual", "funding"} & instruments:
        provides.add(Assumption.PERPETUAL_FUNDING)
    if {
        "basis",
        "index_future",
        "rate_future",
        "term_structure",
        "vol_surface",
        "carry",
    } & instruments:
        provides.add(Assumption.TERM_STRUCTURE)
    if {"listed_option", "vol_surface"} & instruments:
        provides.add(Assumption.IMPLIED_VOLATILITY)
    if {"single_name", "etf", "index"} & instruments:
        provides.add(Assumption.FUNDAMENTALS)
    if {
        "single_name",
        "etf",
        "index",
        "perpetual",
        "index_future",
        "rate_future",
        "listed_option",
        "major",
        "cross",
    } & instruments:
        provides.add(Assumption.SHORT_SELLING)
    if {"energy", "metals", "agriculture"} & instruments:
        provides.add(Assumption.PHYSICAL_DELIVERY)

    return provides
