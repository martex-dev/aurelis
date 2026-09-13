"""M42 — a reading is not a trigger, and the book closes flat.

The acceptance criteria, each with a test named after it:

* a reading the service records every wake is not offered as a trigger or as
  a follow-on by the miner,
* a mechanism stated on a reading is retired by the sweep without waiting for
  predictions, and the reason says so,
* the in-sample baseline spans only the bars since the trigger was first
  recorded, so a kind recorded for two days is not compared against a season,
* a close order is sized by the quantity the opening fill bought, and the
  book is flat in that instrument afterwards,
* a residual an earlier close left on the book is flattened by the wake,
  through the chain, and the flattening is on the ledger.

**Nothing here touches the network.**
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
from aurelis.intel.live import CoinbaseCandles
from aurelis.judgement.resolution import resolve_due
from aurelis.judgement.tables import Thesis
from aurelis.mechanism.mining import READINGS, effect_of, is_reading, mine_pairs
from aurelis.mechanism.paper import (
    books_with_trades,
    close_settled,
    flatten_book,
    trade_firings,
)
from aurelis.mechanism.predictions import generate_predictions
from aurelis.mechanism.tables import MechanismTrade
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.trading.states import BrokerKind, OrderSide
from aurelis.trading.tables import Position
from aurelis.world.derive import derive_price_events

_HOUR = 3600
_START = 1_780_000_000


def _climbing(count: int) -> bytes:
    """Every bar a new high, one point up: the close at bar ``i`` is 100 + i."""
    rows = [
        [_START + i * _HOUR, 99.0 + i, 101.0 + i, 100.0 + i, 100.0 + i, 5.0] for i in range(count)
    ]
    return json.dumps(list(reversed(rows))).encode()


def _valley(count: int) -> bytes:
    """Falls one point a bar for the first half, then climbs one a bar."""
    rows = []
    half = count // 2
    for i in range(count):
        level = 1000.0 - i if i < half else 1000.0 - half + (i - half)
        rows.append([_START + i * _HOUR, level - 0.5, level + 0.5, level, level, 5.0])
    return json.dumps(list(reversed(rows))).encode()


class _Payload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        return io.BytesIO(self._data)


def _at(bar: int, *, minutes: int = 0) -> dt.datetime:
    return dt.datetime.fromtimestamp(_START + bar * _HOUR + minutes * 60, tz=dt.UTC)


def _company(settings: Settings, clock: FrozenClock, payload: bytes, *, bars: int) -> Runtime:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=standins()))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        snapshot = built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(payload), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=bars,
        )
        derive_price_events(session, built.world, snapshot, tail=bars)
    return built


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(_at(292, minutes=10))


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Any:
    built = _company(settings, clock, _climbing(300), bars=300)
    try:
        yield built
    finally:
        built.close()


def _record_readings(company: Runtime, *, kinds: tuple[str, ...], bars: range) -> None:
    """A reading of every named kind on every bar in the range, as the wake takes them."""
    with company.database.session() as session:
        for bar in bars:
            for kind in kinds:
                company.world.record(
                    session,
                    kind=kind,
                    at=_at(bar),
                    entity_kind="instrument",
                    entity_key="BTC-USD",
                    payload={"bar": bar},
                    source="test",
                )


def _mechanism(company: Runtime, *, trigger: str, then: str | None = None) -> Any:
    with company.database.session() as session:
        return company.mechanisms.state(
            session,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            title=f"{trigger} then up",
            trigger_kind=trigger,
            then_kind=then,
            within_hours=24 if then else None,
            desk="crypto",
            horizon_hours=6,
            direction="up",
            confidence=Decimal("0.7"),
            why="a new high draws in the momentum buyers who were waiting for it.",
            other_side="the shorts who sold the old high and now cover.",
            decay="it fades as the crowd learns to buy the high, within months.",
            origin="invented",
            found_on_instrument="BTC-USD",
            found_on_event="none",
            model="test",
        )


def _positions(company: Runtime, book: str) -> dict[str, Decimal]:
    with company.database.session() as session:
        rows = session.execute(sa.select(Position).where(Position.portfolio_ref == book)).scalars()
        return {p.symbol: Decimal(str(p.quantity)) for p in rows}


# ------------------------------------------------------------ mining


def test_a_reading_recorded_every_wake_is_not_offered_as_a_trigger_or_a_follow(
    company: Runtime,
) -> None:
    assert {"book.snapshot", "flow.trades", "leverage.open_interest"} <= READINGS
    assert is_reading("flow.trades") and not is_reading("price.range_break")
    assert not is_reading("book.bid_heavy"), "a derived book event is an event"
    _record_readings(company, kinds=("flow.trades", "leverage.open_interest"), bars=range(200, 292))
    with company.database.session() as session:
        pairs = mine_pairs(session, within=dt.timedelta(hours=24), min_count=3, limit=100)
    kinds = {p.first for p in pairs} | {p.second for p in pairs}
    assert kinds, "the climbing market still mines its own price events"
    assert not (kinds & READINGS), f"a reading was offered: {kinds & READINGS}"


def test_a_mechanism_stated_on_a_reading_is_retired_and_the_reason_says_so(
    company: Runtime,
) -> None:
    _record_readings(company, kinds=("flow.trades", "leverage.open_interest"), bars=range(200, 292))
    on_reading = _mechanism(company, trigger="flow.trades", then="leverage.open_interest")
    on_event = _mechanism(company, trigger="price.range_break")
    with company.database.session() as session:
        retired = company.mechanisms.sweep_retirements(session, at=company.clock.now())
        status = company.mechanisms.status(session, on_reading.ref)
        still = company.mechanisms.status(session, on_event.ref)
    assert [m.ref for m in retired] == [on_reading.ref]
    assert status.retired and status.predictions == 0, "retired before a single prediction"
    reason = status.mechanism.retired_reason or ""
    assert "reading" in reason and "flow.trades" in reason and "every bar" in reason
    assert not still.retired, "a mechanism on a price event is judged on its predictions"


def test_the_in_sample_baseline_spans_only_the_bars_since_the_trigger_was_first_recorded(
    settings: Settings,
) -> None:
    # A market that falls for 150 bars and climbs for 150. A kind recorded
    # only in the climb, compared against every bar, looks like an edge.
    company = _company(settings, FrozenClock(_at(299)), _valley(300), bars=300)
    try:
        with company.database.session() as session:
            for bar in range(160, 290, 10):
                company.world.record(
                    session,
                    kind="test.recent_kind",
                    at=_at(bar),
                    entity_kind="instrument",
                    entity_key="BTC-USD",
                    payload={},
                    source="test",
                )
            effect = effect_of(session, trigger="test.recent_kind", horizon_hours=6)
        assert effect is not None and effect.n == 13
        assert effect.up_rate_after == Decimal("1")
        assert effect.since == _at(160)
        # The baseline is the climb the kind was recorded in, not the whole
        # valley: over the same bars, any bar was up over 6h too.
        assert effect.unconditional_up_rate == Decimal("1"), effect.describe()
        assert effect.lift == Decimal("0")
        assert "since" in effect.describe()
    finally:
        company.close()


# ------------------------------------------------------------ the book


def test_a_close_order_is_sized_by_the_quantity_held_and_the_book_is_flat_after_it(
    company: Runtime,
) -> None:
    mechanism = _mechanism(company, trigger="price.range_break")
    with company.database.session() as session:
        generate_predictions(session, mechanism, clock=company.clock)
        opened = trade_firings(company, session, mechanism, at=company.clock.now())
    assert opened.opened
    book = books_with_trades_of(company)
    held_before = _positions(company, book)
    assert any(q > 0 for q in held_before.values())
    company.clock.advance(hours=8)  # the close fills seven points higher than the open
    with company.database.session() as session:
        resolve_due(session, ledger=company.ledger, clock=company.clock)
        closing = close_settled(company, session, mechanism, at=company.clock.now())
    assert closing.closed and not closing.refused
    assert all(q == 0 for q in _positions(company, book).values()), (
        "the same dollars at a higher price is fewer units; the close is sized by units"
    )
    with company.database.session() as session:
        trades = list(
            session.execute(
                sa.select(MechanismTrade, Thesis)
                .join(Thesis, Thesis.ref == MechanismTrade.thesis_ref)
                .where(MechanismTrade.mechanism_ref == mechanism.ref)
            ).all()
        )
    assert trades and all(t.pnl is not None and t.pnl > 0 for t, _ in trades)


def books_with_trades_of(company: Runtime) -> str:
    with company.database.session() as session:
        books = books_with_trades(session)
    assert len(books) == 1
    return books[0]


def test_a_residual_position_left_by_an_earlier_close_is_flattened_and_recorded(
    company: Runtime,
) -> None:
    from aurelis.mechanism.paper import _actors
    from aurelis.service.loop import Service, cycle_once

    mechanism = _mechanism(company, trigger="price.range_break")
    with company.database.session() as session:
        generate_predictions(session, mechanism, clock=company.clock)
        opened = trade_firings(company, session, mechanism, at=company.clock.now())
    assert opened.opened
    book = books_with_trades_of(company)
    # Close every trade the way the code before M42 did: the same dollar
    # exposure, at a price seven points higher, which buys back fewer units.
    company.clock.advance(hours=8)
    with company.database.session() as session:
        resolve_due(session, ledger=company.ledger, clock=company.clock)
        actors = _actors(company, session)
        broker = company.brokers[BrokerKind.PAPER]
        rows = list(
            session.execute(
                sa.select(MechanismTrade, Thesis)
                .join(Thesis, Thesis.ref == MechanismTrade.thesis_ref)
                .where(MechanismTrade.mechanism_ref == mechanism.ref)
            ).all()
        )
        for trade, thesis in rows:
            broker.marks[thesis.instrument] = Decimal("399")
            outcome = company.cycle.run(
                session,
                portfolio_ref=book,
                broker=broker,
                intents=(
                    (
                        mechanism.version_ref,
                        thesis.instrument,
                        OrderSide.SELL,
                        Decimal("5000"),
                        Decimal("399"),
                    ),
                ),
                proposer=actors["proposer"],
                assessor=actors["assessor"],
                approver=actors["approver"],
                executor=actors["executor"],
                analyst=actors["analyst"],
                at=company.clock.now(),
            )
            trade.close_order_ref = outcome.orders[0]
            trade.closed_at = company.clock.now()
        session.flush()
    residual = _positions(company, book)["BTC-USD"]
    assert residual > 0, "the old close left units on the book"

    # The wake flattens it, through the chain, and says so.
    wake = cycle_once(company, service=Service(company, cycles_per_wake=1))
    assert _positions(company, book)["BTC-USD"] == 0
    assert "flattened 1" in wake.note and "residual" in wake.note
    with company.database.session() as session:
        again = flatten_book(company, session, book, at=company.clock.now())
        flattenings = [
            e for e in company.ledger.for_subject(session, book) if e.kind == "mechanism.traded"
        ]
    assert again.closed == () and again.note == "", "a flat book writes nothing"
    assert flattenings and flattenings[-1].payload["flattened"] == ["BTC-USD"]
