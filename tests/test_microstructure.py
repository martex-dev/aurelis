"""M32 — order book depth and taker flow enter the event stream.

The acceptance criteria, each with a test named after it:

* a book is summarised to mid, spread, near-mid depth per side and bid share,
  from the vendor's shape,
* the trade row's side is the maker's, so taker flow is the inverse -- and a
  test pins it,
* a reading records two events and, when lopsided, the heavy kinds; the raw
  payloads are an artifact whose digest the events carry; recording the same
  instant twice records nothing new,
* the service records microstructure for every granted live instrument each
  wake, and an outage is an incident,
* the judges see the newest reading in their material,
* a mechanism can fire on a flow event.

**Nothing here touches the network.** Payloads are recorded.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.intel.live import CoinbaseCandles, FeedUnavailable
from aurelis.intel.microstructure import (
    BOOK_HEAVY,
    CoinbaseBook,
    CoinbaseTrades,
    record_microstructure,
    summarise_book,
    summarise_trades,
)
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.world.store import World
from aurelis.world.tables import WorldEvent

_HOUR = 3600
_START = 1_780_000_000


class _Json:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        if isinstance(self.payload, Exception):
            raise self.payload
        return io.BytesIO(json.dumps(self.payload).encode())


def _book(bid_heavy: bool = True) -> dict[str, Any]:
    # Vendor shape: [price, size, num_orders], bids descending, asks ascending.
    big, small = ("4.0", "1.0") if bid_heavy else ("1.0", "4.0")
    return {
        "sequence": 1,
        "bids": [["100.00", big, 3], ["99.50", big, 2], ["90.00", "50.0", 1]],
        "asks": [["100.10", small, 3], ["100.60", small, 2], ["111.00", "50.0", 1]],
        "time": "2026-06-01T00:00:00Z",
    }


def _trades(buyers: bool = True) -> list[dict[str, Any]]:
    # A `sell` row is a resting sell a buyer lifted: the taker bought.
    maker = "sell" if buyers else "buy"
    other = "buy" if buyers else "sell"
    return [
        {"time": "t", "trade_id": 1, "price": "100.05", "size": "3.0", "side": maker},
        {"time": "t", "trade_id": 2, "price": "100.05", "size": "3.0", "side": maker},
        {"time": "t", "trade_id": 3, "price": "100.00", "size": "1.0", "side": other},
    ]


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(dt.datetime.fromtimestamp(_START + 200 * _HOUR + 600, tz=dt.UTC))


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Any:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=standins()))
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


# ------------------------------------------------------------ summarising


def test_a_book_is_summarised_from_the_vendors_shape() -> None:
    mid, spread, bid_depth, ask_depth, share = summarise_book(_book(bid_heavy=True))
    assert mid == Decimal("100.05")
    assert spread == Decimal("9.9950")
    # Only levels within one percent of the mid count; the 90 and 111 levels do not.
    assert bid_depth == Decimal("798.00")  # 4*100 + 4*99.5
    assert ask_depth == Decimal("200.70")  # 1*100.1 + 1*100.6
    assert share > BOOK_HEAVY


def test_the_trade_side_is_the_makers_so_taker_flow_is_the_inverse() -> None:
    """Three units on `sell` rows and one on a `buy` row means takers bought
    six and sold one. Read naively it is the other way round, which would
    invert every flow signal while looking exactly like one."""
    buy, sell, share, vwap, count = summarise_trades(_trades(buyers=True))
    assert buy == Decimal("6.0000") and sell == Decimal("1.0000")
    assert share > Decimal("0.85")
    assert count == 3 and vwap > 0


# ------------------------------------------------------------ recording


def test_a_reading_records_events_with_the_raw_payload_as_an_artifact(
    company: Runtime, clock: FrozenClock
) -> None:
    with company.database.session() as session:
        reading, new = record_microstructure(
            session,
            company.world,
            company.artifacts,
            symbol="BTC-USD",
            book_feed=CoinbaseBook(opener=_Json(_book(True))),
            trades_feed=CoinbaseTrades(opener=_Json(_trades(True))),
            clock=clock,
        )
        again_reading, again = record_microstructure(
            session,
            company.world,
            company.artifacts,
            symbol="BTC-USD",
            book_feed=CoinbaseBook(opener=_Json(_book(True))),
            trades_feed=CoinbaseTrades(opener=_Json(_trades(True))),
            clock=clock,
        )
        events = World.events_for(session, entity_kind="instrument", entity_key="BTC-USD")
        artifacts = session.execute(
            sa.text("SELECT count(*) FROM artifacts WHERE kind = 'microstructure.raw'")
        ).scalar_one()
    kinds = sorted(e.kind for e in events)
    assert new == 4 and again == 0, "the same instant twice records nothing new"
    assert kinds == ["book.bid_heavy", "book.snapshot", "flow.buy_pressure", "flow.trades"]
    assert reading.book_imbalance == again_reading.book_imbalance
    assert artifacts == 1, "identical raw payloads are one artifact"
    snapshot = next(e for e in events if e.kind == "book.snapshot")
    assert len(snapshot.payload["raw"]) == 16
    assert snapshot.payload["bid_share"] == str(reading.book_imbalance)


def test_a_balanced_reading_records_no_heavy_event(company: Runtime, clock: FrozenClock) -> None:
    balanced = _book(True)
    balanced["asks"] = [["100.10", "4.0", 3], ["100.60", "4.0", 2]]
    even = [
        {"time": "t", "trade_id": 1, "price": "100", "size": "1", "side": "buy"},
        {"time": "t", "trade_id": 2, "price": "100", "size": "1", "side": "sell"},
    ]
    with company.database.session() as session:
        _, new = record_microstructure(
            session,
            company.world,
            company.artifacts,
            symbol="ETH-USD",
            book_feed=CoinbaseBook(opener=_Json(balanced)),
            trades_feed=CoinbaseTrades(opener=_Json(even)),
            clock=clock,
        )
        kinds = {
            e.kind
            for e in World.events_for(session, entity_kind="instrument", entity_key="ETH-USD")
        }
    assert new == 2 and kinds == {"book.snapshot", "flow.trades"}


def test_an_empty_side_or_a_refusal_is_a_feed_error(company: Runtime, clock: FrozenClock) -> None:
    with company.database.session() as session:
        with pytest.raises(FeedUnavailable, match="empty side"):
            record_microstructure(
                session,
                company.world,
                company.artifacts,
                symbol="X-USD",
                book_feed=CoinbaseBook(opener=_Json({"bids": [], "asks": [["1", "1", 1]]})),
                trades_feed=CoinbaseTrades(opener=_Json([])),
                clock=clock,
            )
        with pytest.raises(FeedUnavailable, match="reached"):
            record_microstructure(
                session,
                company.world,
                company.artifacts,
                symbol="X-USD",
                book_feed=CoinbaseBook(opener=_Json(OSError("down"))),
                trades_feed=CoinbaseTrades(opener=_Json([])),
                clock=clock,
            )


# ------------------------------------------------------------ the service and the seat


def test_the_service_records_microstructure_for_every_granted_live_instrument(
    company: Runtime, clock: FrozenClock
) -> None:
    from aurelis.service.loop import Service, cycle_once

    rows = [
        [
            _START + i * _HOUR,
            99.0 + i * 0.01,
            101.0 + i * 0.01,
            100.0 + i * 0.01,
            100.0 + i * 0.01,
            5.0,
        ]
        for i in range(200)
    ]
    candles = json.dumps(list(reversed(rows))).encode()
    with company.database.session() as session:
        company.grants.grant(
            session,
            source="coinbase",
            desk="crypto",
            instruments=("BTC-USD",),
            granted_by="OPERATOR",
            reason="a test of microstructure in the service",
            bars=200,
        )
    service = Service(
        company,
        feeds=lambda _g: CoinbaseCandles(opener=_Json(json.loads(candles)), pause=0),
        catalogues=lambda _g: __import__(
            "aurelis.world.sources", fromlist=["CoinbaseProducts"]
        ).CoinbaseProducts(
            opener=_Json(
                [
                    {
                        "id": "BTC-USD",
                        "base_currency": "BTC",
                        "quote_currency": "USD",
                        "status": "online",
                    }
                ]
            )
        ),
        microstructure=lambda _g: (
            CoinbaseBook(opener=_Json(_book(True))),
            CoinbaseTrades(opener=_Json(_trades(True))),
        ),
        cycles_per_wake=2,
    )
    wake = cycle_once(company, service=service)
    assert "microstructure" in wake.note
    with company.database.session() as session:
        kinds = {
            e.kind
            for e in World.events_for(session, entity_kind="instrument", entity_key="BTC-USD")
        }
    assert {"book.snapshot", "flow.trades", "flow.buy_pressure"} <= kinds

    down = Service(
        company,
        feeds=lambda _g: CoinbaseCandles(opener=_Json(json.loads(candles)), pause=0),
        catalogues=lambda _g: __import__(
            "aurelis.world.sources", fromlist=["CoinbaseProducts"]
        ).CoinbaseProducts(
            opener=_Json(
                [
                    {
                        "id": "BTC-USD",
                        "base_currency": "BTC",
                        "quote_currency": "USD",
                        "status": "online",
                    }
                ]
            )
        ),
        microstructure=lambda _g: (
            CoinbaseBook(opener=_Json(OSError("refused"))),
            CoinbaseTrades(opener=_Json(_trades(True))),
        ),
        cycles_per_wake=2,
    )
    second = cycle_once(company, service=down)
    assert any("microstructure" in i for i in ()) or len(second.incidents) >= 1


def test_the_judges_see_the_newest_reading(company: Runtime, clock: FrozenClock) -> None:
    from aurelis.judgement.seat import _recent_events

    rows = [[_START + i * _HOUR, 99.0, 101.0, 100.0, 100.0 + i * 0.1, 5.0] for i in range(200)]
    with company.database.session() as session:
        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Json(list(reversed(rows))), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=200,
        )
        record_microstructure(
            session,
            company.world,
            company.artifacts,
            symbol="BTC-USD",
            book_feed=CoinbaseBook(opener=_Json(_book(False))),
            trades_feed=CoinbaseTrades(opener=_Json(_trades(False))),
            clock=clock,
        )
        lines = _recent_events(session, "BTC-USD")
    joined = "\n".join(lines)
    assert "book.snapshot" in joined and "flow.trades" in joined
    assert "book.ask_heavy" in joined and "flow.sell_pressure" in joined


def test_a_mechanism_can_fire_on_a_flow_event(company: Runtime, clock: FrozenClock) -> None:
    """A flow event on an instrument with a recording is an occurrence like any
    other: the mechanism seals a forward prediction against the close at that
    instant."""
    from aurelis.mechanism.predictions import generate_predictions

    rows = [[_START + i * _HOUR, 99.0, 101.0, 100.0, 100.0 + i, 5.0] for i in range(201)]
    # The reading has to fall inside a recording to have a reference close:
    # take it at the last bar's instant.
    clock.set(dt.datetime.fromtimestamp(_START + 200 * _HOUR, tz=dt.UTC))
    with company.database.session() as session:
        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Json(list(reversed(rows))), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=201,
        )
        record_microstructure(
            session,
            company.world,
            company.artifacts,
            symbol="BTC-USD",
            book_feed=CoinbaseBook(opener=_Json(_book(True))),
            trades_feed=CoinbaseTrades(opener=_Json(_trades(True))),
            clock=clock,
        )
        mechanism = company.mechanisms.state(
            session,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            title="pressure then continuation",
            trigger_kind="flow.buy_pressure",
            desk="crypto",
            horizon_hours=6,
            direction="up",
            confidence=Decimal("0.6"),
            why="taker buying that outruns resting depth walks the book up until it is refilled.",
            other_side="resting sellers who are lifted and do not replace their quotes at once.",
            decay="it dies once quoters widen on flow, within weeks.",
            origin="invented",
            found_on_instrument="BTC-USD",
            found_on_event="test",
            model="test",
        )
        run = generate_predictions(session, mechanism, clock=clock)
        thesis = session.execute(
            sa.text("SELECT instrument, direction FROM theses WHERE mechanism_ref = :m"),
            {"m": mechanism.ref},
        ).one()
    assert len(run.sealed) == 1 and thesis == ("BTC-USD", "up")
    assert isinstance(WorldEvent.__tablename__, str)
