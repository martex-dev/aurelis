"""M49 — the judge sees what the mechanisms see.

After M48 fixed the figure guard, five of seven live judges declined at the
market stage for the same reason: the mechanisms that beat the drift key off
book, flow and range breaks, and the market stage showed only price changes.

* each market's line carries its fresh readings, the signals that fired on
  it in the last day, and the open calls a mechanism has sealed on it,
* a reading that is stale, and anything the company learned after the
  moment, is not on the board,
* the market stage shows the board, and the view stage shows the picked
  market's board in full,
* a clock time is not a figure.

**Nothing here touches the network.**
"""

from __future__ import annotations

import datetime as dt
import io
import json
from decimal import Decimal
from typing import Any

import pytest

from aurelis.agents.interpret import unsourced_numerals
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.intel.live import CoinbaseCandles
from aurelis.judgement.board import market_board
from aurelis.judgement.seat import seat_agent
from aurelis.mechanism.predictions import generate_predictions
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.platform.llm.types import LlmRequest
from aurelis.runtime import Runtime
from aurelis.world.derive import derive_price_events

_HOUR = 3600
_START = 1_780_000_000
_BARS = 300


def _rising(count: int, *, breaks_every: int = 10, base: float = 100.0) -> bytes:
    rows = []
    high = base
    for i in range(count):
        if i % breaks_every == 0:
            high += 5.0
        rows.append([_START + i * _HOUR, high - 1, high + 1, high, high, 5.0])
    return json.dumps(list(reversed(rows))).encode()


class _Payload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        return io.BytesIO(self._data)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(dt.datetime.fromtimestamp(_START + (_BARS - 1) * _HOUR + 600, tz=dt.UTC))


def _company(settings: Settings, clock: FrozenClock, responder: Any) -> Runtime:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=responder))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        for index, symbol in enumerate(("BTC-USD", "ETH-USD")):
            snapshot = built.snapshots.ingest(
                session,
                CoinbaseCandles(opener=_Payload(_rising(_BARS, base=100.0 + index)), pause=0),
                desk="crypto",
                symbol=symbol,
                bars=_BARS,
            )
            derive_price_events(session, built.world, snapshot)
    return built


def _record(
    company: Runtime,
    kind: str,
    hours_ago: float,
    payload: dict[str, Any],
    *,
    key: str = "BTC-USD",
    learned_in: float = 0,
) -> None:
    now = company.clock.now()
    at = now - dt.timedelta(hours=hours_ago)
    with company.database.session() as session:
        company.world.record(
            session,
            kind=kind,
            at=at,
            entity_kind="instrument",
            entity_key=key,
            payload=payload,
            source="test",
            recorded_at=at + dt.timedelta(hours=learned_in),
        )


def _mechanism_calls(company: Runtime) -> str:
    with company.database.session() as session:
        mechanism = company.mechanisms.state(
            session,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            title="break then continuation",
            trigger_kind="price.range_break",
            desk="crypto",
            horizon_hours=24,
            direction="up",
            confidence=Decimal("0.7"),
            why="stops above the range are run and the forced buying carries the close.",
            other_side="the shorts whose stops sit just above the range.",
            decay="it fades as the stops move, within months.",
            origin="invented",
            found_on_instrument="ZZZ-USD",
            found_on_event="none",
            model="test",
        )
        generate_predictions(session, mechanism, clock=company.clock)
        return mechanism.ref


def test_each_market_shows_its_fresh_readings_recent_signals_and_open_mechanism_calls(
    settings: Settings, clock: FrozenClock
) -> None:
    company = _company(settings, clock, standins())
    try:
        mechanism = _mechanism_calls(company)
        _record(company, "book.snapshot", 0.5, {"bid_share": "0.6705", "mid": "1"})
        _record(company, "flow.trades", 0.5, {"buy_share": "0.8042", "trades": 500})
        _record(company, "book.bid_heavy", 2, {"bid_share": "0.6705"})
        _record(company, "social.burst", 5, {"mentions_6h": 25})
        with company.database.session() as session:
            board = market_board(session, ("BTC-USD", "ETH-USD"), clock.now())
    finally:
        company.close()
    btc = board["BTC-USD"].render()
    assert "book bid share 0.6705" in btc and "taker buy share 0.8042" in btc
    assert "book.bid_heavy (bid_share 0.6705) 2h ago" in btc
    assert "social.burst (mentions_6h 25) 5h ago" in btc
    assert f"{mechanism} says up by" in btc
    assert "price.range_break" in btc, "the derived price events are signals too"
    assert "book.snapshot" not in btc, "a reading is shown as its value, not as a signal"
    assert board["ETH-USD"].render() and "bid share" not in board["ETH-USD"].render()


def test_a_stale_reading_and_anything_learned_after_the_moment_are_not_on_the_board(
    settings: Settings, clock: FrozenClock
) -> None:
    company = _company(settings, clock, standins())
    try:
        _record(company, "book.snapshot", 5, {"bid_share": "0.5555"})
        _record(company, "oi.surge", 3, {"change_pct": "12.5"}, learned_in=4)
        _record(company, "news.burst", 30, {"mentions_6h": 9})
        with company.database.session() as session:
            line = market_board(session, ["BTC-USD"], clock.now())["BTC-USD"].render()
    finally:
        company.close()
    assert "0.5555" not in line, "a book three hours old is not a book"
    assert "oi.surge" not in line, "the company had not learned it yet"
    assert "news.burst" not in line, "older than a day"


def test_the_market_stage_shows_the_board_and_the_view_stage_shows_it_in_full(
    settings: Settings, clock: FrozenClock
) -> None:
    seen: list[LlmRequest] = []

    def recorder(request: LlmRequest) -> str:
        seen.append(request)
        return standins()(request)

    company = _company(settings, clock, recorder)
    try:
        _record(company, "book.snapshot", 0.5, {"bid_share": "0.6705"})
        _record(company, "flow.buy_pressure", 1, {"buy_share": "0.8042"})
        _record(company, "book.snapshot", 0.5, {"bid_share": "0.4100"}, key="ETH-USD")
        seat_agent(company, agent_handle="INTEL")
    finally:
        company.close()
    market = next(r for r in seen if "Which market" in r.messages[-1].content)
    shown = market.messages[-1].content
    assert "book bid share 0.6705" in shown and "book bid share 0.4100" in shown
    assert "flow.buy_pressure (buy_share 0.8042) 1h ago" in shown
    views = [
        r for r in seen if "open mechanism calls" in r.messages[-1].content and r is not market
    ]
    assert views, "the view stage carries the picked market's board"


def test_a_clock_time_is_not_a_figure() -> None:
    assert unsourced_numerals("it resolves by 09:30Z, after the 14:00 close", set()) == []
    assert unsourced_numerals("it fell 0.262 by 09:30Z", set()) == ["0.262"]


def test_a_zero_padded_integer_is_a_name_and_not_a_quantity() -> None:
    said = "MEC-0004/0007 both fired, as did (0006); the pool fell 150 and 0.5%"
    assert unsourced_numerals(said, set()) == ["150", "0.5%"]
