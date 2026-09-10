"""A desk fixture, served as a feed, so a recording can exist offline.

The judgement seat and the resolver read recordings and nothing else. In CI
and in tests there is no market to record, so this adapter lets a fixture be
ingested through exactly the path a vendor is — same hashing, same immutable
bars, same citation — with ``is_live`` false on the row. Nothing downstream
can mistake it for a market: the seat tells the agent it is a fixture, the
calibration report keeps the rows apart, and the mandate does not count them.

**The bars are re-timestamped to end at the clock.** A fixture is anchored at
the start of 2026 so that its research use is reproducible; a recording that
ended months ago would make every horizon from it already expired and the
seat would refuse, correctly, to seal anything against it. The prices are the
fixture's and deterministic; only the clock they are laid against is the
present one, and the recording says which fixture and which moment.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from aurelis.core.clock import Clock, SystemClock
from aurelis.desks.sources import fixture_for
from aurelis.intel.live import interval_seconds
from aurelis.intel.sources import Bar, FixtureSource
from aurelis.org.desks import Desk

__all__ = ["FixtureFeed"]


@dataclass(frozen=True, slots=True)
class FixtureFeed:
    """A fixture behind the :class:`~aurelis.intel.live.CandleFeed` protocol."""

    desk: Desk
    clock: Clock = SystemClock()
    interval: str = "1h"

    @property
    def name(self) -> str:
        return f"fixture:{self.desk.value}"

    @property
    def endpoint(self) -> str:
        return "offline"

    def source(self) -> Any:
        if self.desk is Desk.CRYPTO:
            return FixtureSource()
        return fixture_for(self.desk)

    def symbols(self) -> tuple[str, ...]:
        symbols: tuple[str, ...] = self.source().symbols()
        return symbols

    def candles(self, symbol: str, *, interval: str, bars: int) -> list[Bar]:
        if interval != self.interval:
            raise ValueError(f"the {self.desk.value} fixture serves {self.interval} bars only")
        step = interval_seconds(interval)
        generated = self.source().bars(symbol, limit=bars)[-bars:]
        # Lay the bars against the present so that horizons from the last bar
        # lie ahead of the clock. The last bar opens at the most recent whole
        # interval strictly before now, so the reference is at least one bar
        # old -- as a real recording made a moment ago would be.
        now = self.clock.now()
        last_open = dt.datetime.fromtimestamp(
            (int(now.timestamp()) // step) * step - step, tz=dt.UTC
        )
        count = len(generated)
        return [
            Bar(
                timestamp=last_open - dt.timedelta(seconds=step * (count - 1 - index)),
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            )
            for index, bar in enumerate(generated)
        ]
