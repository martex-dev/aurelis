"""A fixture source per desk, on that desk's clock.

**None of this is market data and no research conclusion about any real market
may be drawn from it.** Every bar records ``source="fixture:<desk>"`` and every
snapshot records ``is_live: False``, exactly as the crypto fixture has since
M1. What M12 adds is that each desk's fixtures have the *shape* of that desk —
its calendar, its instrument names, its typical volatility, and its
casualties — so that the machinery underneath a desk is exercised by something
with the right joints.

The two things that are genuinely real here:

**Sessions.** An equities source produces no bar for a Saturday, and none for
the small hours. A backtest that traded an S&P name on a Sunday would be
obviously wrong on any real feed and silently fine on a naive fixture, so the
fixture refuses to produce the bar.

**Casualties.** Every desk has names that stopped trading, because survivorship
is not a crypto problem. A delisted equity, an expired contract, a currency
that got repegged, and — on the memecoin desk — most of the universe. The
memecoin source is the extreme case on purpose: two thirds of its names die,
which is closer to that market than any tidier number would be.

Live feeds arrive per desk when there is one to wire, and until then
:func:`live_feed_status` says plainly that there is not.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field
from decimal import Decimal

from aurelis.desks.calendars import TradingCalendar, calendar_for
from aurelis.intel.sources import Bar
from aurelis.org.desks import DESKS, Desk

__all__ = [
    "DESK_FIXTURES",
    "DeskFixture",
    "DeskUniverse",
    "fixture_for",
    "live_feed_status",
]

_SCALE = Decimal("0.01")
_ANCHOR = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


@dataclass(frozen=True, slots=True)
class DeskUniverse:
    """What trades on a desk, and what used to."""

    survivors: tuple[str, ...]
    casualties: dict[str, int]
    """Symbol to the bar index it stopped trading at. Every desk has some."""

    base: dict[str, Decimal]
    volatility: Decimal
    tick: Decimal = Decimal("0.01")
    """The desk's price resolution.

    Not decoration. A cent tick is right for equities and destroys two of the
    seven desks: a 0.6% move on an FX rate of 1.00 rounds away entirely, and a
    memecoin priced at four thousandths of a cent quantizes to zero. Both
    produced perfectly flat series that the research lifecycle happily ran to a
    verdict on, which is why :func:`_moves` is now a readiness check.
    """

    death_mark: Decimal = Decimal("-0.60")
    pre_death_drift: Decimal = Decimal("0.004")

    @property
    def population(self) -> tuple[str, ...]:
        return (*self.survivors, *sorted(self.casualties))


@dataclass(frozen=True, slots=True)
class DeskFixture:
    """A deterministic source for one desk, honouring its calendar and tick."""

    desk: Desk
    universe: DeskUniverse
    calendar: TradingCalendar
    interval: str = "1h"
    _cache: dict[str, list[Bar]] = field(default_factory=dict, repr=False)

    @property
    def tick(self) -> Decimal:
        return self.universe.tick

    def moves(self, symbol: str | None = None, *, limit: int = 60) -> bool:
        """Whether this desk's prices actually change.

        A desk whose bars are constant cannot produce evidence, and it does not
        announce itself: the engine runs, the metrics compute, the verdict rule
        returns UNDERPOWERED, and nothing anywhere says the input was flat.
        """
        chosen = symbol or self.symbols()[0]
        closes = {bar.close for bar in self.bars(chosen, limit=limit)}
        return len(closes) > 1

    @property
    def name(self) -> str:
        return f"fixture:{self.desk.value}"

    def symbols(self) -> tuple[str, ...]:
        return self.universe.survivors

    def all_symbols(self) -> tuple[str, ...]:
        return self.universe.population

    def surviving(self) -> tuple[str, ...]:
        """What is still trading. Choosing from this list IS the bias."""
        return self.universe.survivors

    def listed_as_of(self, moment: dt.datetime) -> tuple[str, ...]:
        index = max(0, int((moment - _ANCHOR).total_seconds() // 3600))
        return tuple(
            symbol
            for symbol in self.all_symbols()
            if self.universe.casualties.get(symbol, 10**9) > index
        ) or self.universe.survivors

    def anchor(self) -> dt.datetime:
        return _ANCHOR

    def delisted_at(self, symbol: str) -> int | None:
        return self.universe.casualties.get(symbol)

    def bars(self, symbol: str, *, limit: int = 120) -> list[Bar]:
        if symbol not in self.all_symbols():
            raise KeyError(
                f"{symbol!r} does not trade on the {self.desk.value} desk; its "
                f"universe is {self.all_symbols()}"
            )
        if limit < 1:
            raise ValueError("limit must be positive")
        built = self._cache.get(symbol)
        if built is None or len(built) < limit:
            built = self._build(symbol, max(limit, 240))
            self._cache[symbol] = built
        return built[:limit]

    # ------------------------------------------------------------ generation

    def _build(self, symbol: str, count: int) -> list[Bar]:
        universe = self.universe
        dies_at = universe.casualties.get(symbol)
        price = universe.base[symbol]
        bars: list[Bar] = []
        stamp = _ANCHOR
        index = 0

        while len(bars) < count:
            # The calendar decides. An equities fixture simply produces no bar
            # for a Saturday, so a strategy cannot trade into one -- which on a
            # naive fixture it silently could.
            if not self.calendar.is_session(stamp):
                stamp += dt.timedelta(hours=1)
                continue

            step = self._step(symbol, index)
            if dies_at is not None:
                if index == dies_at:
                    step = universe.death_mark
                elif index > dies_at:
                    step = Decimal(0)
                else:
                    step += universe.pre_death_drift

            tick = universe.tick
            open_price = price
            close_price = (price * (Decimal(1) + step)).quantize(tick)
            if close_price <= Decimal(0):
                close_price = tick
            bars.append(
                Bar(
                    timestamp=stamp,
                    open=open_price.quantize(tick),
                    high=(max(open_price, close_price) * Decimal("1.003")).quantize(tick),
                    low=(min(open_price, close_price) * Decimal("0.997")).quantize(tick),
                    close=close_price,
                    volume=(Decimal(1000) + Decimal(index % 29) * Decimal(11)).quantize(_SCALE),
                )
            )
            price = close_price
            index += 1
            stamp += dt.timedelta(hours=1)
        return bars

    def _step(self, symbol: str, index: int) -> Decimal:
        digest = hashlib.sha256(
            f"{self.desk.value}:{symbol}:{index}".encode()
        ).digest()
        raw = int.from_bytes(digest[:4], "big")
        unit = Decimal(raw) / Decimal(0xFFFFFFFF) - Decimal("0.5")
        return (unit * self.universe.volatility).quantize(Decimal("0.00000001"))


def _universe(
    survivors: tuple[str, ...],
    casualties: dict[str, int],
    base: Decimal,
    volatility: str,
    tick: str = "0.01",
) -> DeskUniverse:
    prices = {
        symbol: base * (Decimal(1) + Decimal(i) / Decimal(4))
        for i, symbol in enumerate((*survivors, *sorted(casualties)))
    }
    return DeskUniverse(
        survivors=survivors,
        casualties=casualties,
        base=prices,
        volatility=Decimal(volatility),
        tick=Decimal(tick),
    )


#: One universe per desk. Instrument names are shaped like the desk's real
#: ones so that a reader can tell at a glance which desk an artifact came from.
_UNIVERSES: dict[Desk, DeskUniverse] = {
    Desk.EQUITIES: _universe(
        ("ACME", "BRIDGE", "CORTEX", "DELTA"),
        {"ZENITH": 84, "PALLAS": 132},
        Decimal(60),
        "0.018",
    ),
    Desk.OPTIONS: _universe(
        ("ACME 250C", "ACME 300C", "BRIDGE 120P"),
        {"ZENITH 90C": 96},
        Decimal(4),
        "0.06",
    ),
    Desk.FUTURES: _universe(
        ("ES", "NQ", "ZN", "ZB"),
        {"ES-EXPIRED": 120},
        Decimal(4500),
        "0.012",
    ),
    Desk.COMMODITIES: _universe(
        ("CL", "NG", "GC", "ZC"),
        {"NG-EXPIRED": 108},
        Decimal(70),
        "0.022",
    ),
    Desk.FX: _universe(
        ("EURUSD", "USDJPY", "GBPUSD", "AUDUSD"),
        {"EURCHF-PEG": 72},
        Decimal(1),
        "0.006",
        # A pipette. At a cent tick every FX bar in this fixture was identical
        # to the last, and the research lifecycle ran to a verdict on a flat
        # line without anything noticing.
        tick="0.00001",
    ),
    Desk.MEMECOIN: _universe(
        ("PEPO", "WOJK"),
        # Four dead out of six. Survivorship is not a bias on this desk, it is
        # the default state of the data, and a tidier ratio would misrepresent
        # what the universe looks like.
        {"MOONX": 40, "SAFEZ": 56, "INUFI": 72, "RUGGD": 88},
        Decimal("0.004"),
        "0.09",
        # Ten decimal places. A token priced at four thousandths of a cent
        # quantized to zero at a cent tick, so every close was 0.01 and the
        # whole desk measured exactly nothing.
        tick="0.0000000001",
    ),
}


DESK_FIXTURES: dict[Desk, DeskFixture] = {
    desk: DeskFixture(desk=desk, universe=universe, calendar=calendar_for(desk.value))
    for desk, universe in _UNIVERSES.items()
}
"""Fixture sources for the six desks M12 opens.

CRYPTO is absent on purpose: it has had :class:`FixtureSource` since M1 and a
validated martex data lake behind it, and replacing that with a second fixture
would be a regression dressed as consistency.
"""


def fixture_for(desk: Desk | str) -> DeskFixture:
    key = Desk(desk) if isinstance(desk, str) else desk
    try:
        return DESK_FIXTURES[key]
    except KeyError:
        raise KeyError(
            f"no fixture universe for the {key.value} desk"
            + (
                "; crypto reads the martex lake through the M1 fixture source"
                if key is Desk.CRYPTO
                else ""
            )
        ) from None


def live_feed_status() -> dict[str, str]:
    """Which desks have a live data feed. None of them do, and it says so."""
    return {
        desk.value: (
            "fixture only — deterministic, offline, and not a market. The "
            f"{spec.data_sources[0]} feed is named in the desk registry and is "
            "not wired."
        )
        for desk, spec in DESKS.items()
    }
