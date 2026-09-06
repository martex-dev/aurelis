"""Worlds with something planted in them.

A world is a deterministic price history built from a recipe. It implements
:class:`~aurelis.intel.sources.MarketDataSource`, so the ordinary engine runs
against it without knowing it is synthetic — which is the property the whole
scoring layer rests on. A scenario that ran through special-cased code would
measure a parallel machine rather than the company's own.

**Every world takes a seed, and the seed is the point.** A recipe is a
*generating process*; a seed draws one history from it. An experiment gets one
draw, exactly as a researcher gets one past. The truth measurement gets many,
which is the scale no experiment is allowed and the reason a planted effect can
be told apart from a lucky one (ADR-0005).

What can be planted:

``premium``
    Genuine serial correlation: a fraction of the trailing move is repeated on
    the next bar. This is a real effect — a momentum rule captures it, and it
    survives replication.

``regime``
    The premium confined to one stretch of the window. The whole period looks
    like an edge; the earlier half does not.

``priming``
    An outsized run inside the first lookback window, so a rule that trades
    straight out of its half-informed bars earns from them.

``dispersion``
    Cross-sectional spread that puts the premium in the single best-ranked
    name only, so widening the book dilutes it. Capacity, planted.

``deaths``
    Names that drift up and then delist at a mark-down. Survivorship, planted —
    and only a defect when the *presented* universe drops them.

Nothing here asserts that a plant worked. Whether a world actually contains
what its recipe asked for is settled in :mod:`aurelis.engines.synthetic.truth`,
by measurement.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any

from aurelis.intel.sources import Bar

__all__ = ["Death", "SyntheticWorld", "WorldRecipe"]

_SCALE = Decimal("0.01")
_ZERO = Decimal("0")
_ONE = Decimal("1")

_ANCHOR = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

_TRAILING_CAP = Decimal("0.15")
"""How much trailing move the premium may feed on, per bar."""

_STEP_CAP = Decimal("0.60")
"""The largest single-bar move any world may produce. A delisting mark is at
the edge of it; nothing else should come close."""


@dataclass(frozen=True, slots=True)
class Death:
    """A name that stops trading, and what a holder gets back.

    ``drift`` is positive on purpose. The names that died usually looked like
    the best names right up until they did not, which is why a ranking rule is
    drawn to them and why dropping them flatters a backtest. A world whose
    casualties merely drifted down would make survivorship undetectable.
    """

    symbol: str
    at_bar: int
    drift: Decimal = Decimal("0.006")
    mark: Decimal = Decimal("-0.60")


@dataclass(frozen=True, slots=True)
class WorldRecipe:
    """What to build, before any seed is applied.

    A recipe is not a claim. It is an instruction to a generator, and the
    generator is free to produce a history in which the instruction did not
    take — a small premium can be swamped by noise in any single draw. That is
    why truth is measured rather than read off this object.
    """

    survivors: tuple[str, ...] = ("AAA", "BBB", "CCC", "DDD")
    bars: int = 96
    volatility: Decimal = Decimal("0.02")
    """Half-width of the per-bar random step, before any plant."""

    premium: Decimal = _ZERO
    """Fraction of the trailing move repeated on the next bar. The effect."""

    premium_lookback: int = 6
    regime_from: int | None = None
    """Bar index the premium starts at. ``None`` means the whole window."""

    regime_to: int | None = None
    priming: Decimal = _ZERO
    """Extra drift applied inside the first ``priming_bars`` bars."""

    priming_bars: int = 0
    dispersion: Decimal = _ZERO
    """How much of the premium is concentrated in the leading name.

    At 0 every name gets all of it, and a wider book is free. At 1 only the
    leader does, so widening dilutes. **Above 1 the share goes negative**: the
    marginal names carry an anti-momentum tilt, and rotating into them is
    actively costly. That is the honest shape of a capacity limit -- the names
    past the top of the ranking are not merely neutral, they are the ones the
    edge was never in -- and at exactly 1 the dilution was not strong enough to
    make CAPACITY_IGNORED measurable at all."""

    deaths: tuple[Death, ...] = field(default_factory=tuple)
    base: Decimal = Decimal("100")

    def with_deaths(self, *deaths: Death) -> WorldRecipe:
        return replace(self, deaths=(*self.deaths, *deaths))

    @property
    def casualties(self) -> tuple[str, ...]:
        return tuple(death.symbol for death in self.deaths)

    @property
    def population(self) -> tuple[str, ...]:
        """Everything that ever listed, survivors and casualties alike."""
        return (*self.survivors, *self.casualties)

    def as_payload(self) -> dict[str, Any]:
        """Canonical form. Part of a scenario's identity, so float-free."""
        return {
            "survivors": list(self.survivors),
            "bars": self.bars,
            "volatility": str(self.volatility),
            "premium": str(self.premium),
            "premium_lookback": self.premium_lookback,
            "regime_from": self.regime_from,
            "regime_to": self.regime_to,
            "priming": str(self.priming),
            "priming_bars": self.priming_bars,
            "dispersion": str(self.dispersion),
            "base": str(self.base),
            "deaths": [
                {
                    "symbol": d.symbol,
                    "at_bar": d.at_bar,
                    "drift": str(d.drift),
                    "mark": str(d.mark),
                }
                for d in self.deaths
            ],
        }


class SyntheticWorld:
    """One draw of a recipe. A :class:`MarketDataSource` over planted history.

    Deterministic in ``(recipe, seed, symbol, index)`` and nothing else: no
    global RNG, no clock, no machine-dependent float. Two processes on two
    operating systems build the same bars, which is what lets a scenario score
    be compared across a matrix build.
    """

    __slots__ = ("recipe", "seed", "_cache")

    def __init__(self, recipe: WorldRecipe, seed: int) -> None:
        self.recipe = recipe
        self.seed = seed
        self._cache: dict[str, list[Bar]] = {}

    @property
    def name(self) -> str:
        return f"synthetic:{self.seed}"

    # ------------------------------------------------------------ the source

    def symbols(self) -> tuple[str, ...]:
        return self.recipe.survivors

    def all_symbols(self) -> tuple[str, ...]:
        return self.recipe.population

    def surviving(self) -> tuple[str, ...]:
        """What is still trading. Choosing from this list *is* the bias."""
        return self.recipe.survivors

    def listed_as_of(self, moment: dt.datetime) -> tuple[str, ...]:
        index = max(0, int((moment - _ANCHOR).total_seconds() // 3600))
        dead = {d.symbol: d.at_bar for d in self.recipe.deaths}
        listed = tuple(
            symbol
            for symbol in self.all_symbols()
            if dead.get(symbol, 10**9) > index
        )
        return listed or self.recipe.survivors

    def anchor(self) -> dt.datetime:
        return _ANCHOR

    def bars(self, symbol: str, *, limit: int = 96) -> list[Bar]:
        if symbol not in self.all_symbols():
            raise KeyError(
                f"{symbol!r} is not in this world; it holds {self.all_symbols()}"
            )
        if limit < 1:
            raise ValueError("limit must be positive")
        built = self._cache.get(symbol)
        if built is None or len(built) < limit:
            built = self._build(symbol, max(limit, self.recipe.bars))
            self._cache[symbol] = built
        return built[:limit]

    # ------------------------------------------------------------ generation

    def _build(self, symbol: str, count: int) -> list[Bar]:
        recipe = self.recipe
        death = next((d for d in recipe.deaths if d.symbol == symbol), None)
        rank = self._rank(symbol)

        price = recipe.base
        closes: list[Decimal] = []
        bars: list[Bar] = []
        for index in range(count):
            step = self._noise(symbol, index)

            if recipe.premium and self._in_regime(index):
                look = recipe.premium_lookback
                if index >= look and closes[index - look]:
                    trailing = closes[index - 1] / closes[index - look] - _ONE
                    # Clamped, because the premium is positive feedback: a
                    # fraction of the trailing move is repeated, and the
                    # repeated move feeds the next trailing move. Unbounded,
                    # a strong premium compounds a price to overflow within a
                    # hundred bars. The clamp is what makes the effect a
                    # persistent tilt rather than a runaway.
                    trailing = max(-_TRAILING_CAP, min(_TRAILING_CAP, trailing))
                    share = self._premium_share(rank)
                    step += trailing * recipe.premium * share

            if recipe.priming and index < recipe.priming_bars:
                step += recipe.priming

            if death is not None:
                if index == death.at_bar:
                    step = death.mark
                elif index > death.at_bar:
                    step = _ZERO  # no market left to move in
                else:
                    step += death.drift

            step = max(-_STEP_CAP, min(_STEP_CAP, step))
            open_price = price
            close_price = (price * (_ONE + step)).quantize(_SCALE)
            if close_price <= _ZERO:
                close_price = _SCALE
            bars.append(
                Bar(
                    timestamp=_ANCHOR + dt.timedelta(hours=index),
                    open=open_price.quantize(_SCALE),
                    high=(max(open_price, close_price) * Decimal("1.003")).quantize(_SCALE),
                    low=(min(open_price, close_price) * Decimal("0.997")).quantize(_SCALE),
                    close=close_price,
                    volume=(Decimal(1000) + Decimal(index % 41) * Decimal(7)).quantize(_SCALE),
                )
            )
            closes.append(close_price)
            price = close_price
        return bars

    def _in_regime(self, index: int) -> bool:
        start = self.recipe.regime_from
        end = self.recipe.regime_to
        if start is not None and index < start:
            return False
        return not (end is not None and index >= end)

    def _premium_share(self, rank: int) -> Decimal:
        """How much of the premium this name gets.

        With ``dispersion`` at zero every name gets all of it, and holding
        three names is as good as holding one. At one, only the leading name
        does — which is what makes a wider book measurably worse and gives
        CAPACITY_IGNORED something real to find.
        """
        dispersion = self.recipe.dispersion
        if not dispersion or rank == 0:
            return _ONE
        return _ONE - dispersion

    def _rank(self, symbol: str) -> int:
        """The name's position in the recipe. Rank 0 carries the edge."""
        population = self.all_symbols()
        return population.index(symbol)

    def _noise(self, symbol: str, index: int) -> Decimal:
        digest = hashlib.sha256(
            f"{self.seed}:{symbol}:{index}".encode()
        ).digest()
        raw = int.from_bytes(digest[:4], "big")
        unit = Decimal(raw) / Decimal(0xFFFFFFFF) - Decimal("0.5")
        return (unit * self.recipe.volatility).quantize(Decimal("0.00000001"))
