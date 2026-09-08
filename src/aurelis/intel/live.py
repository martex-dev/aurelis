"""Real market data, fetched once and frozen.

The first of the two conditions the mandate reported as **blocked**: every
number this company holds was computed on a fixture, and no amount of research
could change that.

The thing to get right is not the HTTP call. It is that **a live feed cannot be
researched against directly.** It moves. An experiment run twice against an
endpoint gets two different answers, and the entire preregistration
architecture rests on a data fingerprint that identifies exactly what ran. A
company that pointed its engine at a live URL would have replaced reproducible
research with a moving target and kept all the vocabulary.

So live data enters through an **ingestion**: fetch once, normalise, hash,
store. Research then runs against the stored snapshot, which is immutable and
citable, and two runs of the same experiment get the same bars forever. The
feed is the boundary; everything inside it is frozen.

What is real here and what is not
---------------------------------

The bars are real. They come from Coinbase's public candles endpoint, no
credentials, no account — genuine BTC-USD prices that genuinely traded.

What that does **not** buy is power. A few thousand hourly bars is months, and
:mod:`aurelis.desks.power` says settling an annualised Sharpe of 0.5 on this
desk needs about fifteen years of them. Real data makes the research *about a
market*; it does not make an underpowered claim settleable, and the mandate
will keep saying so.

Nothing in the test suite touches the network. :class:`CandleFeed` is a
protocol and the tests pass a recorded payload, which is the same discipline
every other external dependency in this repository is held to.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from aurelis.core.errors import IntegrityViolation
from aurelis.intel.sources import Bar

__all__ = [
    "COINBASE_GRANULARITIES",
    "CandleFeed",
    "CoinbaseCandles",
    "FeedUnavailable",
    "interval_seconds",
]

USER_AGENT = "aurelis-research/0.1 (+https://github.com/martex-dev/aurelis)"

COINBASE_GRANULARITIES: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "1d": 86400,
}
"""The intervals the vendor supports, by this company's own interval names.

A closed map rather than arithmetic on the string, because the vendor rejects
anything not on its list and a silently wrong granularity would return bars of
the wrong width under the right label -- which no fingerprint would catch,
since the fingerprint would faithfully hash the wrong data.
"""

_PAGE = 300
"""Candles per request. The vendor caps a page at 300 and returns an error
rather than a truncation above it, so this is a limit rather than a guess."""

_EPOCH_FLOOR = 0
"""How far back the walk may go. Not a stylistic bound: the loop steps `end`
backwards a page at a time, and without a floor a vendor that kept returning
data already collected would walk past the epoch until ``fromtimestamp`` raised
an OSError -- which is how this was found."""


def interval_seconds(interval: str) -> int:
    try:
        return COINBASE_GRANULARITIES[interval]
    except KeyError:
        raise IntegrityViolation(
            f"no vendor granularity for interval {interval!r}; known intervals "
            f"are {sorted(COINBASE_GRANULARITIES)}. Guessing one would return "
            "bars of the wrong width under the right label."
        ) from None


class FeedUnavailable(RuntimeError):
    """The vendor could not be reached, or refused.

    A state, not a crash. The network is the one dependency this company
    genuinely does not control, and an operator should learn that from a
    sentence rather than from a stack trace.
    """


class CandleFeed(Protocol):
    """What an ingestion needs from a vendor.

    The two identity fields are read-only properties rather than variables, so
    a frozen dataclass can satisfy the protocol. A vendor adapter that could be
    mutated after construction would let the endpoint on a snapshot record
    disagree with the endpoint that was actually called.
    """

    @property
    def name(self) -> str: ...

    @property
    def endpoint(self) -> str: ...

    def candles(self, symbol: str, *, interval: str, bars: int) -> list[Bar]: ...


@dataclass(frozen=True, slots=True)
class CoinbaseCandles:
    """Coinbase Exchange public candles. No credentials, no account.

    Chosen because it is public, unauthenticated and broadly reachable. The
    company is not tied to it: :class:`CandleFeed` is the seam, and a second
    vendor is a second class rather than a change here.
    """

    name: str = "coinbase"
    endpoint: str = "https://api.exchange.coinbase.com"
    timeout: int = 25
    opener: Any = None
    """Injectable, so a test can supply a recorded payload. Nothing in the
    suite touches the network."""

    def candles(self, symbol: str, *, interval: str, bars: int) -> list[Bar]:
        """Fetch ``bars`` candles, newest last, paginating backwards.

        The vendor returns **newest first**, and each page is bounded by an
        explicit time window rather than an offset, so pages are requested
        oldest-boundary-first and the whole result is sorted once at the end.
        Paging by position against a feed that is still appending would drop or
        duplicate a bar at every boundary.
        """
        if bars < 1:
            raise IntegrityViolation("a snapshot needs at least one bar")
        step = interval_seconds(interval)
        collected: dict[int, Bar] = {}
        end = int(dt.datetime.now(tz=dt.UTC).timestamp())

        while len(collected) < bars and end > _EPOCH_FLOOR:
            start = max(_EPOCH_FLOOR, end - _PAGE * step)
            page = self._page(symbol, step=step, start=start, end=end)
            before = len(collected)
            for bar in page:
                collected[int(bar.timestamp.timestamp())] = bar
            # Stop when a page adds nothing new, not when it comes back empty.
            # A vendor that has run out of history returns an empty page, but
            # one that returns overlapping data -- or a recorded response that
            # ignores the window -- would loop forever, walking `end` backwards
            # past the epoch until fromtimestamp raised. Progress is the
            # condition; emptiness is only one way to stop making it.
            if len(collected) == before:
                break
            end = start

        ordered = [collected[key] for key in sorted(collected)]
        if not ordered:
            raise FeedUnavailable(
                f"{self.name} returned no candles for {symbol} at {interval}. "
                "Nothing was stored."
            )
        # Newest `bars` of them, oldest first: a snapshot short of what was
        # asked for is honest, and the count travels on the record.
        return ordered[-bars:]

    def _page(
        self, symbol: str, *, step: int, start: int, end: int
    ) -> list[Bar]:
        url = (
            f"{self.endpoint}/products/{symbol}/candles"
            f"?granularity={step}"
            f"&start={dt.datetime.fromtimestamp(start, tz=dt.UTC).isoformat()}"
            f"&end={dt.datetime.fromtimestamp(end, tz=dt.UTC).isoformat()}"
        )
        raw = self._get(url)
        return [_bar_from(row) for row in raw]

    def _get(self, url: str) -> list[list[Any]]:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        opener = self.opener or urllib.request.urlopen
        try:
            with opener(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            raise FeedUnavailable(
                f"{self.name} refused the request ({error.code}). Nothing was "
                "stored."
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise FeedUnavailable(
                f"{self.name} could not be reached: {error}. Nothing was stored."
            ) from error
        if not isinstance(payload, list):
            raise FeedUnavailable(
                f"{self.name} returned {type(payload).__name__}, not a list of "
                "candles. Nothing was stored."
            )
        return payload


def _bar_from(row: list[Any]) -> Bar:
    """One vendor row as a :class:`Bar`.

    **The column order is [time, low, high, open, close, volume].** Low and
    high come before open and close, which is not the order any other system in
    this repository uses and not the order the word OHLCV implies. Reading it
    as OHLC would silently swap the open with the low on every bar -- prices
    that still look like prices, hash reproducibly, and are wrong.
    """
    if len(row) < 6:
        raise FeedUnavailable(f"malformed candle with {len(row)} field(s): {row!r}")
    moment, low, high, opening, close, volume = row[:6]
    return Bar(
        timestamp=dt.datetime.fromtimestamp(int(moment), tz=dt.UTC),
        open=Decimal(str(opening)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=Decimal(str(volume)),
    )
