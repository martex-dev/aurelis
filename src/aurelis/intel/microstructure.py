"""Order book depth and taker flow, recorded as events.

The first evidence the company holds that is not a close. Coinbase publishes,
without credentials, the top of the order book (``/book?level=2``, fifty
levels a side) and the most recent trades with the side that took liquidity.
Read every wake for every granted instrument, they become two kinds of event
on the instrument entity, hashed and immutable like everything else:

``book.snapshot``
    Depth within one percent of the mid on each side, the imbalance between
    them, the spread in basis points.

``flow.trades``
    Over the most recent trades: taker buy volume, taker sell volume, the
    imbalance, and the volume-weighted price.

And two derived kinds when either is lopsided — ``book.bid_heavy`` /
``book.ask_heavy`` and ``flow.buy_pressure`` / ``flow.sell_pressure`` — so a
mechanism can fire on them and a mined conjunction can join them to a move.

**The trade's ``side`` field is the maker's side, not the taker's.** A trade
marked ``buy`` had a resting buy order that a seller hit; the aggressor sold.
Read naively it inverts every flow signal while looking exactly like a flow
signal, which is the same class of trap as the candle column order in
:mod:`aurelis.intel.live`. Taker side is the opposite of what the row says,
and a test asserts it.

Every raw payload is stored as an artifact and its digest travels in the
event, so a reader can go and look at the fifty levels that produced one
imbalance figure.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from aurelis.core.clock import Clock
from aurelis.intel.live import USER_AGENT, FeedUnavailable
from aurelis.world.store import World

__all__ = [
    "BOOK_HEAVY",
    "FLOW_HEAVY",
    "CoinbaseBook",
    "CoinbaseTrades",
    "Microstructure",
    "record_microstructure",
]

BOOK_HEAVY = Decimal("0.65")
"""Bid share of near-mid depth above this is ``book.bid_heavy``; below
``1 - BOOK_HEAVY`` is ``book.ask_heavy``."""

FLOW_HEAVY = Decimal("0.65")
"""Taker-buy share of recent volume above this is ``flow.buy_pressure``;
below ``1 - FLOW_HEAVY`` is ``flow.sell_pressure``."""

_NEAR = Decimal("0.01")
_Q = Decimal("0.0001")


def _get(url: str, opener: Any, timeout: int, name: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    fetch = opener or urllib.request.urlopen
    try:
        with fetch(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise FeedUnavailable(f"{name} refused the request ({error.code})") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise FeedUnavailable(f"{name} could not be reached: {error}") from error


@dataclass(frozen=True, slots=True)
class CoinbaseBook:
    """``GET /products/{id}/book?level=2``: fifty aggregated levels a side."""

    name: str = "coinbase"
    endpoint: str = "https://api.exchange.coinbase.com"
    timeout: int = 25
    opener: Any = None

    def book(self, symbol: str) -> dict[str, Any]:
        payload = _get(
            f"{self.endpoint}/products/{symbol}/book?level=2", self.opener, self.timeout, self.name
        )
        if not isinstance(payload, dict) or "bids" not in payload or "asks" not in payload:
            raise FeedUnavailable(f"{self.name} returned a book without bids and asks")
        return payload


@dataclass(frozen=True, slots=True)
class CoinbaseTrades:
    """``GET /products/{id}/trades``: the most recent trades, newest first."""

    name: str = "coinbase"
    endpoint: str = "https://api.exchange.coinbase.com"
    timeout: int = 25
    limit: int = 500
    opener: Any = None

    def trades(self, symbol: str) -> list[dict[str, Any]]:
        payload = _get(
            f"{self.endpoint}/products/{symbol}/trades?limit={self.limit}",
            self.opener,
            self.timeout,
            self.name,
        )
        if not isinstance(payload, list):
            raise FeedUnavailable(f"{self.name} returned {type(payload).__name__}, not trades")
        return [row for row in payload if isinstance(row, dict) and "side" in row]


@dataclass(frozen=True, slots=True)
class Microstructure:
    """One reading of one instrument."""

    symbol: str
    mid: Decimal
    spread_bps: Decimal
    bid_depth: Decimal
    ask_depth: Decimal
    book_imbalance: Decimal
    """Bid share of near-mid depth, in [0, 1]."""

    taker_buy: Decimal
    taker_sell: Decimal
    flow_imbalance: Decimal
    """Taker-buy share of recent volume, in [0, 1]."""

    vwap: Decimal
    trades: int


def summarise_book(payload: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Mid, spread in bps, bid depth and ask depth within one percent, bid share."""
    bids = [
        (Decimal(str(p)), Decimal(str(s))) for p, s, *_ in payload["bids"] if Decimal(str(s)) > 0
    ]
    asks = [
        (Decimal(str(p)), Decimal(str(s))) for p, s, *_ in payload["asks"] if Decimal(str(s)) > 0
    ]
    if not bids or not asks:
        raise FeedUnavailable("an empty side of the book cannot be summarised")
    best_bid = max(p for p, _ in bids)
    best_ask = min(p for p, _ in asks)
    mid = (best_bid + best_ask) / 2
    spread = ((best_ask - best_bid) / mid * 10_000).quantize(_Q)
    bid_depth = sum((s * p for p, s in bids if p >= mid * (1 - _NEAR)), Decimal(0))
    ask_depth = sum((s * p for p, s in asks if p <= mid * (1 + _NEAR)), Decimal(0))
    total = bid_depth + ask_depth
    share = (bid_depth / total).quantize(_Q) if total > 0 else Decimal("0.5")
    return (
        mid,
        spread,
        bid_depth.quantize(Decimal("0.01")),
        ask_depth.quantize(Decimal("0.01")),
        share,
    )


def summarise_trades(rows: list[dict[str, Any]]) -> tuple[Decimal, Decimal, Decimal, Decimal, int]:
    """Taker buy volume, taker sell volume, taker-buy share, VWAP, count.

    The row's ``side`` is the maker's. A ``sell`` row is a resting sell that a
    buyer lifted: taker bought. This is the inversion the module docstring
    warns about, and it lives in exactly one place.
    """
    buy = Decimal(0)
    sell = Decimal(0)
    notional = Decimal(0)
    volume = Decimal(0)
    for row in rows:
        size = Decimal(str(row.get("size", "0")))
        price = Decimal(str(row.get("price", "0")))
        if size <= 0 or price <= 0:
            continue
        taker_bought = str(row["side"]).lower() == "sell"
        if taker_bought:
            buy += size
        else:
            sell += size
        notional += size * price
        volume += size
    total = buy + sell
    share = (buy / total).quantize(_Q) if total > 0 else Decimal("0.5")
    vwap = (notional / volume).quantize(Decimal("0.01")) if volume > 0 else Decimal(0)
    return buy.quantize(_Q), sell.quantize(_Q), share, vwap, len(rows)


def read(symbol: str, book_payload: dict[str, Any], trades: list[dict[str, Any]]) -> Microstructure:
    mid, spread, bid_depth, ask_depth, book_share = summarise_book(book_payload)
    buy, sell, flow_share, vwap, count = summarise_trades(trades)
    return Microstructure(
        symbol=symbol,
        mid=mid.quantize(Decimal("0.01")),
        spread_bps=spread,
        bid_depth=bid_depth,
        ask_depth=ask_depth,
        book_imbalance=book_share,
        taker_buy=buy,
        taker_sell=sell,
        flow_imbalance=flow_share,
        vwap=vwap,
        trades=count,
    )


def record_microstructure(
    session: Session,
    world: World,
    artifacts: Any,
    *,
    symbol: str,
    book_feed: CoinbaseBook,
    trades_feed: CoinbaseTrades,
    clock: Clock,
    at: dt.datetime | None = None,
) -> tuple[Microstructure, int]:
    """Fetch once, store the raw payloads as artifacts, record the events.

    Returns the reading and how many events were new. The reading's ``at`` is
    the moment of the fetch: a book has no other time, and a snapshot of it is
    a fact about that instant.
    """
    moment = at or clock.now()
    book_payload = book_feed.book(symbol)
    trades = trades_feed.trades(symbol)
    reading = read(symbol, book_payload, trades)

    raw = artifacts.put_json(
        session,
        {"symbol": symbol, "at": moment.isoformat(), "book": book_payload, "trades": trades},
        kind="microstructure.raw",
        produced_by=book_feed.name,
    )
    source = f"{book_feed.endpoint}/products/{symbol}"
    world.see(session, kind="instrument", key=symbol, source=source, at=moment)
    new = 0

    _, created = world.record(
        session,
        kind="book.snapshot",
        at=moment,
        entity_kind="instrument",
        entity_key=symbol,
        payload={
            "mid": str(reading.mid),
            "spread_bps": str(reading.spread_bps),
            "bid_depth_1pct": str(reading.bid_depth),
            "ask_depth_1pct": str(reading.ask_depth),
            "bid_share": str(reading.book_imbalance),
            "raw": raw.digest[:16],
        },
        source=source,
        recorded_at=moment,
    )
    new += int(created)
    _, created = world.record(
        session,
        kind="flow.trades",
        at=moment,
        entity_kind="instrument",
        entity_key=symbol,
        payload={
            "trades": reading.trades,
            "taker_buy": str(reading.taker_buy),
            "taker_sell": str(reading.taker_sell),
            "buy_share": str(reading.flow_imbalance),
            "vwap": str(reading.vwap),
            "raw": raw.digest[:16],
        },
        source=source,
        recorded_at=moment,
    )
    new += int(created)

    heavy: list[tuple[str, dict[str, Any]]] = []
    if reading.book_imbalance >= BOOK_HEAVY:
        heavy.append(("book.bid_heavy", {"bid_share": str(reading.book_imbalance)}))
    elif reading.book_imbalance <= 1 - BOOK_HEAVY:
        heavy.append(("book.ask_heavy", {"bid_share": str(reading.book_imbalance)}))
    if reading.flow_imbalance >= FLOW_HEAVY:
        heavy.append(("flow.buy_pressure", {"buy_share": str(reading.flow_imbalance)}))
    elif reading.flow_imbalance <= 1 - FLOW_HEAVY:
        heavy.append(("flow.sell_pressure", {"buy_share": str(reading.flow_imbalance)}))
    for kind, payload in heavy:
        _, created = world.record(
            session,
            kind=kind,
            at=moment,
            entity_kind="instrument",
            entity_key=symbol,
            payload={**payload, "mid": str(reading.mid), "raw": raw.digest[:16]},
            source=source,
            recorded_at=moment,
        )
        new += int(created)
    return reading, new
