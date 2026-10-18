"""Long price history for every desk, from free sources with no key (M65).

The live service records hourly bars for the crypto universe it is granted,
which is weeks of history for most coins. Testing a classic strategy honestly
needs years, and on every market the company may one day trade. So the lab
fetches daily bars:

- **crypto**: Coinbase's public candles, the same vendor the service records.
- **equities, ETFs, indices, forex, futures and commodities**: Yahoo
  Finance's public chart endpoint, read-only and keyless.

Stooq was tried and now sits behind a browser check; the lab does not try to
get past a check meant to keep programs out.

Each series fetched is stored as an artifact with its digest, so a lab run
names exactly the bars it tested on, and a rerun on the same digests must
produce the same results.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aurelis.intel.live import FeedUnavailable

__all__ = [
    "UNIVERSE",
    "Bar",
    "Series",
    "coinbase_daily",
    "fetch",
    "yahoo_daily",
]

Bar = tuple[int, float, float, float, float, float]
"""(unix seconds, open, high, low, close, volume)."""

_UA = "Mozilla/5.0 (compatible; AurelisLab/1.0; read-only research)"

#: What the lab tests on, by desk: (symbol as the vendor knows it, source).
#: Crypto is read from the live grants at run time; these are the rest.
UNIVERSE: dict[str, tuple[tuple[str, str], ...]] = {
    "equities": tuple(
        (s, "yahoo")
        for s in (
            "SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT", "NVDA", "AMZN", "META",
            "GOOGL", "TSLA", "JPM", "XOM", "^GSPC", "^NDX",
        )
    ),
    "fx": tuple(
        (s, "yahoo")
        for s in (
            "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCHF=X", "USDCAD=X",
            "NZDUSD=X",
        )
    ),
    "commodities": tuple(
        (s, "yahoo") for s in ("GC=F", "SI=F", "CL=F", "NG=F", "HG=F", "ZC=F")
    ),
    "futures": tuple((s, "yahoo") for s in ("ES=F", "NQ=F", "YM=F", "ZN=F")),
}  # fmt: skip


@dataclass(frozen=True, slots=True)
class Series:
    symbol: str
    desk: str
    source: str
    bars: tuple[Bar, ...]

    @property
    def closes(self) -> list[float]:
        return [b[4] for b in self.bars]

    def payload(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "desk": self.desk,
            "source": self.source,
            "interval": "1d",
            # As strings: the artifact store hashes exactly, and a binary float
            # does not serialise the same way on every machine.
            "bars": [[str(b[0]), *(repr(x) for x in b[1:])] for b in self.bars],
        }


Opener = Callable[[urllib.request.Request, int], Any]


def _get(url: str, opener: Opener | None = None) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        reader = (
            opener(request, 30)
            if opener is not None
            else urllib.request.urlopen(request, timeout=30)  # noqa: S310
        )
        with reader as response:
            return json.loads(response.read())
    except Exception as error:  # noqa: BLE001 - one series failing is reported, not fatal
        raise FeedUnavailable(f"{url.split('?')[0]} could not be read: {error}") from error


def yahoo_daily(symbol: str, *, years: int = 10, opener: Opener | None = None) -> list[Bar]:
    """Daily bars from Yahoo's public chart endpoint, oldest first."""
    from urllib.parse import quote

    data = _get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}"
        f"?range={years}y&interval=1d",
        opener,
    )
    result = (data.get("chart") or {}).get("result") or []
    if not result:
        raise FeedUnavailable(f"yahoo returned no data for {symbol}")
    stamps = result[0].get("timestamp") or []
    quote_ = ((result[0].get("indicators") or {}).get("quote") or [{}])[0]
    out: list[Bar] = []
    for i, ts in enumerate(stamps):
        o, h, low, c = (quote_.get(k, [None])[i] for k in ("open", "high", "low", "close"))
        v = (quote_.get("volume") or [0] * len(stamps))[i] or 0
        if None in (o, h, low, c):
            continue
        out.append((int(ts), float(o), float(h), float(low), float(c), float(v)))
    return out


def coinbase_daily(
    product: str, *, days: int = 1800, opener: Opener | None = None, pause: float = 0.35
) -> list[Bar]:
    """Daily bars from Coinbase's public candles, oldest first, paged 300 at a time."""
    end = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start_all = end - dt.timedelta(days=days)
    rows: dict[int, Bar] = {}
    cursor = end
    while cursor > start_all:
        start = max(start_all, cursor - dt.timedelta(days=299))
        url = (
            f"https://api.exchange.coinbase.com/products/{product}/candles?granularity=86400"
            f"&start={start.isoformat()}&end={cursor.isoformat()}"
        )
        page = _get(url, opener)
        if not page:
            break
        for t, low, high, o, c, v in page:
            rows[int(t)] = (int(t), float(o), float(high), float(low), float(c), float(v))
        cursor = start
        if pause:
            time.sleep(pause)
    return [rows[t] for t in sorted(rows)]


def fetch(
    desk: str, symbol: str, source: str, *, opener: Opener | None = None, pause: float = 0.35
) -> Series:
    if source == "coinbase":
        bars = coinbase_daily(symbol, opener=opener, pause=pause)
    elif source == "yahoo":
        bars = yahoo_daily(symbol, opener=opener)
        if pause:
            time.sleep(pause)
    else:
        raise FeedUnavailable(f"no lab source called {source!r}")
    return Series(symbol=symbol, desk=desk, source=source, bars=tuple(bars))
