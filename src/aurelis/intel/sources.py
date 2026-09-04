"""Market data sources.

M1 ships exactly one: a deterministic, offline **fixture** source. That is a
deliberate choice, and the honesty of it matters more than the convenience.

The alternative — wiring a live exchange feed now — would put the network in
CI, make every test's result depend on what the market did that morning, and
give the company data whose provenance nobody had checked. The real crypto
lake arrives with the martex adapter at M4, already validated, and the other
desks' feeds arrive with those desks at M12.

Until then, every observation the company makes records ``source="fixture"``,
and that string travels with it into the record, the station and any citation.
Nothing reads as live data that is not live data.

The generator is a seeded random walk. It is **not** a market simulation and no
research conclusion may be drawn from it: it exists so the agent runtime has
something with a shape to look at. Scenarios with a *known planted answer*,
which agents can legitimately be scored against, are a different thing
entirely and arrive at M10 (ADR-0005).
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from aurelis.core.canonical import sha256_of

__all__ = ["Bar", "FixtureSource", "MarketDataSource", "snapshot_for"]

_SCALE = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Bar:
    """One closed OHLCV bar. ``timestamp`` is the bar's OPEN time, in UTC.

    Prices are ``Decimal``. A bar that went through a binary float could not be
    hashed reproducibly, and the hash is the whole provenance mechanism.
    """

    timestamp: dt.datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def as_dict(self) -> dict[str, Any]:
        return {
            "t": self.timestamp.isoformat(),
            "o": str(self.open),
            "h": str(self.high),
            "l": str(self.low),
            "c": str(self.close),
            "v": str(self.volume),
        }


class MarketDataSource(Protocol):
    """What every desk's data source must provide."""

    name: str

    def bars(self, symbol: str, *, limit: int) -> list[Bar]: ...

    def symbols(self) -> tuple[str, ...]: ...

    def listed_as_of(self, moment: dt.datetime) -> tuple[str, ...]: ...

    def surviving(self) -> tuple[str, ...]: ...

    def anchor(self) -> dt.datetime: ...


class FixtureSource:
    """Deterministic offline bars.

    Same symbol and same limit always produce the same bars, on every machine,
    with no network and no credentials. That is what lets the whole company be
    exercised in CI for free.
    """

    name = "fixture"

    #: What is still trading. The hindsight list, and what a careless universe
    #: definition produces.
    SYMBOLS: tuple[str, ...] = ("BTC/USDT", "ETH/USDT", "SOL/USDT")

    #: Names that were listed at the start and later died.
    #:
    #: These exist so survivorship bias is **measurable rather than
    #: discussable**. A universe that quietly drops them cannot lose money on a
    #: delisting, and the difference between running with and without them is
    #: exactly what a SURVIVORSHIP objection predicts. Their price paths decay
    #: hard and then stop, which is what delisting looks like from the outside.
    DELISTED: tuple[str, ...] = ("LUNC/USDT", "FTT/USDT", "HOTAIR/USDT")

    _ANCHOR = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    _BASE = {
        "BTC/USDT": Decimal("42000"),
        "ETH/USDT": Decimal("2300"),
        "SOL/USDT": Decimal("98"),
        "LUNC/USDT": Decimal("64"),
        "FTT/USDT": Decimal("25"),
        "HOTAIR/USDT": Decimal("12"),
    }

    #: The bar index at which each dead name stops trading. After this its
    #: price is flat at whatever was left, which is the honest representation:
    #: the position could not be exited into a market that no longer existed.
    _DELISTS_AT = {"LUNC/USDT": 96, "FTT/USDT": 132, "HOTAIR/USDT": 168}

    #: Per-bar drift applied to the dying names before they delist.
    #:
    #: **Positive**, and that is the whole point. Survivorship bias is
    #: dangerous precisely because the names that died usually looked like the
    #: best names right up until they did not -- LUNA and FTT both outperformed
    #: for months before going to nothing. A momentum or rotation rule is
    #: therefore *attracted* to them, and a universe that quietly drops them
    #: reports the attraction without ever paying for it.
    #:
    #: If the dying names merely drifted down, no ranking rule would ever hold
    #: one and survivorship would be undetectable here -- which is exactly what
    #: the first version of this fixture got wrong.
    _PRE_DELISTING_DRIFT = Decimal("0.006")

    #: The one-bar loss at delisting. A holder recovers a fraction and cannot
    #: have traded out beforehand -- this is the event survivorship bias
    #: removes from the record entirely.
    _DELISTING_MARK = Decimal("-0.60")

    def symbols(self) -> tuple[str, ...]:
        return self.SYMBOLS

    def all_symbols(self) -> tuple[str, ...]:
        """Everything that ever listed, survivors and casualties alike."""
        return (*self.SYMBOLS, *self.DELISTED)

    def surviving(self) -> tuple[str, ...]:
        """What is still trading. Choosing from this list IS the bias."""
        return self.SYMBOLS

    def listed_as_of(self, moment: dt.datetime) -> tuple[str, ...]:
        """What a person could actually have chosen on ``moment``.

        Everything that had listed by then, including the names that later
        died -- which is the whole point of asking the question this way.
        """
        index = max(0, int((moment - self._ANCHOR).total_seconds() // 3600))
        return tuple(
            symbol
            for symbol in self.all_symbols()
            if self._DELISTS_AT.get(symbol, 10**9) > index
        ) or self.SYMBOLS

    def anchor(self) -> dt.datetime:
        """The start of the fixture history."""
        return self._ANCHOR

    def delisted_at(self, symbol: str) -> int | None:
        """The bar this name stopped trading, or ``None`` if it survived."""
        return self._DELISTS_AT.get(symbol)

    def bars(self, symbol: str, *, limit: int = 120) -> list[Bar]:
        if symbol not in self._BASE:
            raise KeyError(
                f"{symbol!r} is not in the fixture universe {self.SYMBOLS}. "
                "Live universes arrive with the desks at M4/M12."
            )
        if limit < 1:
            raise ValueError("limit must be positive")

        price = self._BASE[symbol]
        delists_at = self._DELISTS_AT.get(symbol)
        bars: list[Bar] = []
        for index in range(limit):
            # A hash-derived step: deterministic, reproducible across machines
            # and Python versions, and not seeded from any global RNG state.
            step = self._step(symbol, index)
            if delists_at is not None:
                if index == delists_at:
                    # The delisting mark. A holder does not walk away flat:
                    # they get back a fraction, once, and cannot trade out at
                    # any price in between. This single bar is the cost that a
                    # survivors-only universe never pays.
                    step = self._DELISTING_MARK
                elif index > delists_at:
                    step = Decimal(0)  # no market left to move in
                else:
                    step += self._PRE_DELISTING_DRIFT
            open_price = price
            close_price = (price * (Decimal(1) + step)).quantize(_SCALE)
            high = max(open_price, close_price) * Decimal("1.004")
            low = min(open_price, close_price) * Decimal("0.996")
            bars.append(
                Bar(
                    timestamp=self._ANCHOR + dt.timedelta(hours=index),
                    open=open_price.quantize(_SCALE),
                    high=high.quantize(_SCALE),
                    low=low.quantize(_SCALE),
                    close=close_price,
                    volume=(Decimal(1000) + Decimal(index % 37) * Decimal(13)).quantize(_SCALE),
                )
            )
            price = close_price
        return bars

    @staticmethod
    def _step(symbol: str, index: int) -> Decimal:
        digest = hashlib.sha256(f"{symbol}:{index}".encode()).digest()
        # Map the first two bytes onto roughly [-1%, +1%].
        raw = int.from_bytes(digest[:2], "big")
        return (Decimal(raw) / Decimal(65535) - Decimal("0.5")) / Decimal(50)


#: The source each desk currently reads from. One entry, honestly.
DESK_SOURCES: dict[str, MarketDataSource] = {"crypto": FixtureSource()}


def source_for(desk: str) -> MarketDataSource:
    try:
        return DESK_SOURCES[desk]
    except KeyError:
        raise KeyError(
            f"desk {desk!r} has no data source. Only the CRYPTO desk is active; "
            "the others open at M12 with their feeds."
        ) from None


def snapshot_for(desk: str, symbol: str | None = None, *, limit: int = 48) -> dict[str, Any]:
    """A desk snapshot for a view, carrying its own provenance.

    ``data_digest`` is the hash of the bars themselves, so anything an agent
    says about this snapshot can be checked against exactly what it was shown.
    """
    source = source_for(desk)
    chosen = symbol or source.symbols()[0]
    bars = source.bars(chosen, limit=limit)
    payload = [b.as_dict() for b in bars]
    return {
        "desk": desk,
        "symbol": chosen,
        "source": source.name,
        "is_live": False,
        "caveat": (
            "Fixture data: deterministic, offline, and not a market simulation. "
            "No research conclusion may be drawn from it."
        ),
        "bars": payload,
        "bar_count": str(len(payload)),
        "data_digest": sha256_of(payload),
        "as_of": bars[-1].timestamp.isoformat(),
    }
