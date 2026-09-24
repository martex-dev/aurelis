"""M45 — the service survives what killed it, and a token fill is honest.

On 15 September the range-break scheme opened a paper position on a memecoin
priced at $0.00058782. The price was rounded to eight places on its way into
the database, the order read as over its approval, the refusal poisoned the
wake's session, the wake raised out of the service loop, and the service was
down for nine days with nothing recorded.

The acceptance criteria, each with a test named after it:

* a price is stored exactly to eighteen places, so an order at a memecoin
  price fits the approval it was sized to,
* the order-size rule is replaced on a workspace created under the old one,
* one firing whose order fails is rolled back and the other firings open,
* a position in a token is capped at a share of its pool's liquidity, and a
  pool too shallow for a position worth its fees is refused with the reason,
* a wake that raises is a critical incident and the next wake runs,
* three failed wakes in a row stop the service and say why.

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
from aurelis.mechanism.paper import LIQUIDITY_SHARE, trade_firings
from aurelis.mechanism.predictions import generate_predictions
from aurelis.mechanism.tables import MechanismTrade
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.service.loop import MAX_FAILED_WAKES, Service, serve
from aurelis.trading.states import BrokerKind, OrderSide
from aurelis.trading.tables import Fill, Order
from aurelis.world.derive import derive_price_events

_HOUR = 3600
_START = 1_780_000_000
_TOKEN = "solana:5GefefPX1mDs6ZJB1apYmz6fCTCiNJpHturZ9bvFpump"


def _climbing(count: int, *, base: float = 100.0, step: float = 1.0) -> bytes:
    rows = [
        [
            _START + i * _HOUR,
            base + (i - 1) * step,
            base + (i + 1) * step,
            base + i * step,
            base + i * step,
            5.0,
        ]
        for i in range(count)
    ]
    return json.dumps(list(reversed(rows))).encode()


class _Payload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        return io.BytesIO(self._data)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(dt.datetime.fromtimestamp(_START + 292 * _HOUR + 600, tz=dt.UTC))


def _company(settings: Settings, clock: FrozenClock) -> Runtime:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=standins()))
    built.initialise()
    built.staff()
    return built


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Any:
    built = _company(settings, clock)
    try:
        yield built
    finally:
        built.close()


def _record(company: Runtime, symbol: str, *, desk: str, base: float, step: float) -> None:
    with company.database.session() as session:
        snapshot = company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_climbing(300, base=base, step=step)), pause=0),
            desk=desk,
            symbol=symbol,
            bars=300,
        )
        derive_price_events(session, company.world, snapshot)


def _range_break(company: Runtime) -> Any:
    with company.database.session() as session:
        mechanism = company.mechanisms.state(
            session,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            title="new high then more",
            trigger_kind="price.range_break",
            desk="crypto",
            horizon_hours=6,
            direction="up",
            confidence=Decimal("0.7"),
            why="a new high draws in the momentum buyers who were waiting for it.",
            other_side="the shorts who sold the old high and now cover.",
            decay="it fades as the crowd learns to buy the high, within months.",
            origin="invented",
            found_on_instrument="ZZZ-USD",
            found_on_event="none",
            model="test",
        )
        generate_predictions(session, mechanism, clock=company.clock)
    return mechanism


def _liquidity(company: Runtime, symbol: str, usd: str, *, hours_ago: float = 1) -> None:
    with company.database.session() as session:
        company.world.record(
            session,
            kind="attention.boost",
            at=company.clock.now() - dt.timedelta(hours=hours_ago),
            entity_kind="instrument",
            entity_key=symbol,
            payload={"symbol": "TOK", "liquidity_usd": usd, "total_boosts": "10"},
            source="test",
        )


# ------------------------------------------------------------ exact prices


def test_a_price_is_stored_exactly_so_an_order_at_a_memecoin_price_fits_its_approval(
    company: Runtime,
) -> None:
    from aurelis.mechanism.paper import _actors, ensure_version
    from aurelis.trading.deployment import open_paper_book

    mechanism = _range_break(company)
    price = Decimal("0.000587816203876699")
    with company.database.session() as session:
        actors = _actors(company, session)
        version = ensure_version(company, session, mechanism, at=company.clock.now())
        book = open_paper_book(
            company,
            session,
            desk="memecoin",
            equity=Decimal("100000"),
            opened_by=actors["portfolio"],
            at=company.clock.now(),
        )
        broker = company.brokers[BrokerKind.PAPER]
        broker.marks[_TOKEN] = price
        outcome = company.cycle.run(
            session,
            portfolio_ref=book,
            broker=broker,
            intents=((version, _TOKEN, OrderSide.BUY, Decimal("5000"), price),),
            proposer=actors["proposer"],
            assessor=actors["assessor"],
            approver=actors["approver"],
            executor=actors["executor"],
            analyst=actors["analyst"],
            at=company.clock.now(),
        )
        assert outcome.orders, outcome
        order = session.execute(sa.select(Order).where(Order.ref == outcome.orders[0])).scalar_one()
        fill = session.execute(sa.select(Fill).where(Fill.order_ref == order.ref)).scalar_one()
    assert Decimal(str(order.expected_price)) == price, "eighteen places, not eight"
    assert Decimal(str(fill.price)) > price
    stored = (
        company.database.engine.connect()
        .exec_driver_sql("SELECT expected_price FROM orders WHERE ref = ?", (order.ref,))
        .scalar_one()
    )
    assert stored.startswith("0.000587816203876699")


def test_the_order_size_rule_is_replaced_on_a_workspace_created_under_the_old_one(
    settings: Settings, clock: FrozenClock
) -> None:
    built = _company(settings, clock)
    try:
        with built.database.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER aurelis_order_may_not_exceed_approval")
            connection.exec_driver_sql(
                "CREATE TRIGGER aurelis_order_may_not_exceed_approval BEFORE INSERT ON orders "
                "FOR EACH ROW WHEN 0 BEGIN SELECT 1; END"
            )
        built.initialise()
        with built.database.engine.connect() as connection:
            sql = connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE name = 'aurelis_order_may_not_exceed_approval'"
            ).scalar_one()
        assert "1e-9" in sql and "final_target" in sql
    finally:
        built.close()


# ------------------------------------------------------------ isolation


def test_one_firing_whose_order_fails_is_rolled_back_and_the_others_open(
    company: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(company, "BTC-USD", desk="crypto", base=100.0, step=1.0)
    mechanism = _range_break(company)
    cycle_class = type(company.cycle)
    real_run = cycle_class.run
    calls = {"n": 0}

    def failing_second(self: Any, *args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        outcome = real_run(self, *args, **kwargs)  # a proposal, approval, order, fill
        if calls["n"] == 2:
            raise sa.exc.IntegrityError(
                "INSERT", {}, Exception("Aurelis: a rule refused this order")
            )
        return outcome

    monkeypatch.setattr(cycle_class, "run", failing_second)
    with company.database.session() as session:
        result = trade_firings(company, session, mechanism, at=company.clock.now())
    assert len(result.opened) == 5 and "rolled back" in result.note
    assert "a rule refused this order" in result.note
    with company.database.session() as session:
        trades = session.execute(sa.select(sa.func.count()).select_from(MechanismTrade)).scalar()
        orders = session.execute(sa.select(sa.func.count()).select_from(Order)).scalar()
    assert trades == 5 and orders == 5, "the failed firing's order was rolled back with it"


# ------------------------------------------------------------ liquidity


def test_a_token_position_is_capped_at_a_share_of_its_pool_and_a_shallow_pool_is_refused(
    company: Runtime,
) -> None:
    _record(company, _TOKEN, desk="memecoin", base=0.0005, step=0.000001)
    _liquidity(company, _TOKEN, "50000.00")
    mechanism = _range_break(company)
    with company.database.session() as session:
        result = trade_firings(company, session, mechanism, at=company.clock.now())
        orders = list(session.execute(sa.select(Order).where(Order.symbol == _TOKEN)).scalars())
    assert result.opened and orders
    cap = Decimal("50000") * LIQUIDITY_SHARE
    for order in orders:
        notional = Decimal(str(order.quantity)) * Decimal(str(order.expected_price))
        assert notional <= cap + Decimal("0.01"), f"{notional} over the pool's {cap}"
    # The pool drains: the next firing is refused rather than filled at depth
    # it does not have.
    _liquidity(company, _TOKEN, "3000.00", hours_ago=0)
    later = company.clock.now() + dt.timedelta(hours=1)
    with company.database.session() as session:
        mechanism2 = _range_break(company)
        refused = trade_firings(company, session, mechanism2, at=later)
    assert not refused.opened
    assert "supports only" in refused.note and "not opened" in refused.note


# ------------------------------------------------------------ the service loop


class _Flaky(Service):
    def __init__(self, runtime: Any, *, fail: set[int]) -> None:
        super().__init__(runtime, calls_per_day=0, cycles_per_wake=1)
        self.fail = fail
        self.n = 0

    def wake(self, *, service_ref: str, at: dt.datetime | None = None) -> Any:
        self.n += 1
        if self.n in self.fail:
            raise RuntimeError(f"wake {self.n} fell over")
        return super().wake(service_ref=service_ref, at=at)


def test_a_wake_that_raises_is_a_critical_incident_and_the_next_wake_runs(
    company: Runtime, clock: FrozenClock
) -> None:
    from aurelis.alerts.tables import Alert

    outcome = serve(
        company,
        interval_seconds=_HOUR,
        max_wakes=3,
        service=_Flaky(company, fail={1}),
        sleeper=lambda seconds: clock.advance(seconds=seconds),
    )
    assert len(outcome.wakes) == 2 and outcome.stopped_because == "3 wake(s), as asked"
    with company.database.session() as session:
        alert = session.execute(sa.select(Alert).where(Alert.source == "service.wake")).scalar_one()
    assert alert.severity == "critical" and "wake 1 fell over" in alert.message


def test_three_failed_wakes_in_a_row_stop_the_service_and_say_why(
    company: Runtime, clock: FrozenClock
) -> None:
    outcome = serve(
        company,
        interval_seconds=_HOUR,
        max_wakes=10,
        service=_Flaky(company, fail=set(range(1, 11))),
        sleeper=lambda seconds: clock.advance(seconds=seconds),
    )
    assert outcome.wakes == ()
    assert outcome.stopped_because.startswith(f"{MAX_FAILED_WAKES} wakes in a row failed")
    assert "fell over" in outcome.stopped_because


# ------------------------------------------------------------ an outage's positions


def test_a_round_trip_held_past_its_horizon_by_an_outage_is_not_the_mechanisms_pnl(
    company: Runtime,
) -> None:
    from aurelis.judgement.resolution import resolve_due
    from aurelis.mechanism.paper import close_settled, pnl_of

    _record(company, "BTC-USD", desk="crypto", base=100.0, step=1.0)
    mechanism = _range_break(company)
    with company.database.session() as session:
        opened = trade_firings(company, session, mechanism, at=company.clock.now())
    assert opened.opened
    # The service is down for nine days. When it comes back, the recording
    # covers them and every position closes at once, far past its horizon.
    company.clock.advance(hours=9 * 24)
    with company.database.session() as session:
        snapshot = company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_climbing(520)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=520,
        )
        assert snapshot.bars == 520
        resolve_due(session, ledger=company.ledger, clock=company.clock)
        closing = close_settled(company, session, mechanism, at=company.clock.now())
        summary = pnl_of(session, mechanism.ref)
    assert closing.closed and len(closing.closed) == len(opened.opened)
    assert summary["late"] == len(closing.closed), "every one was held nine days, not six hours"
    assert summary["pnl"] == 0 and summary["won"] == 0, "none of it is the mechanism's"
    assert summary["late_pnl"] > 0, "the rally the outage held them through is still on record"
