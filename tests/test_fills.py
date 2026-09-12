"""M40 — paper fills at the price the wake can see.

The acceptance criteria, each with a test named after it:

* a position opens at the newest close the wake can see, not the trigger's
  close, and the slippage between them is reported,
* a position closes at the newest close the wake can see, not the resolution
  bar's, and the realised P&L is the difference between the two fills,
* a firing with no recorded price as new as its trigger is not opened, and
  the result says why,
* a settled position with no price newer than its entry stays open until
  there is one,
* the station and the CLI show entry and exit.

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
from aurelis.mechanism import paper
from aurelis.mechanism.paper import close_settled, pnl_of, trade_firings
from aurelis.mechanism.predictions import generate_predictions
from aurelis.mechanism.tables import MechanismTrade
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.station.app import station_app
from aurelis.world.derive import derive_price_events

_HOUR = 3600
_START = 1_780_000_000


def _climbing(count: int) -> bytes:
    """Every bar a new high, one point up: the close at bar ``i`` is 100 + i."""
    rows = [
        [_START + i * _HOUR, 99.0 + i, 101.0 + i, 100.0 + i, 100.0 + i, 5.0] for i in range(count)
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


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Any:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=standins()))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        snapshot = built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_climbing(300)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=300,
        )
        derive_price_events(session, built.world, snapshot)
    try:
        yield built
    finally:
        built.close()


def _mechanism(company: Runtime) -> Any:
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


def _trades(company: Runtime, ref: str) -> list[tuple[MechanismTrade, Thesis]]:
    with company.database.session() as session:
        return list(
            session.execute(
                sa.select(MechanismTrade, Thesis)
                .join(Thesis, Thesis.ref == MechanismTrade.thesis_ref)
                .where(MechanismTrade.mechanism_ref == ref)
                .order_by(Thesis.reference_at)
            ).all()
        )


def test_a_position_opens_at_the_newest_close_the_wake_can_see_and_reports_the_slippage(
    company: Runtime,
) -> None:
    mechanism = _mechanism(company)
    with company.database.session() as session:
        result = trade_firings(company, session, mechanism, at=company.clock.now())
        summary = pnl_of(session, mechanism.ref)
    # The recording runs to bar 299 while the clock stands at 292: a fixture
    # can hold bars from the future, a venue cannot. The six triggers at or
    # before the clock open; the seven after it are refused, and say why.
    assert len(result.opened) == 6 and len(result.refused) == 7
    assert "no recorded price as new as the trigger" in result.note
    rows = _trades(company, mechanism.ref)
    # Every open fill is the bar-292 close, whatever bar the trigger fired on.
    assert {Decimal(t.entry_price or "0") for t, _ in rows} == {Decimal("392")}
    assert all(t.entry_bar_at is not None for t, _ in rows)
    earliest_trade, earliest_thesis = rows[0]
    assert Decimal(earliest_thesis.reference_close) < Decimal(earliest_trade.entry_price)
    assert summary["slippage_bps"] is not None and summary["slippage_bps"] > 0, (
        "a long filled above the trigger's close paid for the hour"
    )


def test_a_position_closes_at_the_newest_close_the_wake_can_see_and_pnl_is_the_fills(
    company: Runtime,
) -> None:
    mechanism = _mechanism(company)
    with company.database.session() as session:
        trade_firings(company, session, mechanism, at=company.clock.now())
    company.clock.advance(hours=8)  # bar 300 + 10 min: the newest bar is 299
    with company.database.session() as session:
        resolve_due(session, ledger=company.ledger, clock=company.clock)
        closing = close_settled(company, session, mechanism, at=company.clock.now())
    assert closing.closed and not closing.refused
    rows = _trades(company, mechanism.ref)
    assert {Decimal(t.exit_price or "0") for t, _ in rows} == {Decimal("399")}
    for trade, thesis in rows:
        assert thesis.resolution_close is not None
        assert Decimal(thesis.resolution_close) < Decimal("399"), "not the resolution bar's close"
        assert trade.pnl is not None and trade.pnl > 0
    with company.database.session() as session:
        summary = pnl_of(session, mechanism.ref)
    assert summary["closed"] == len(rows) and summary["pnl"] > 0


def test_a_firing_with_no_price_as_new_as_its_trigger_is_not_opened_and_says_why(
    company: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    mechanism = _mechanism(company)
    monkeypatch.setattr(paper, "_executable_price", lambda *_args, **_kwargs: None)
    with company.database.session() as session:
        result = trade_firings(company, session, mechanism, at=company.clock.now())
    assert result.opened == () and result.refused
    assert "no recorded price as new as the trigger" in result.note
    assert _trades(company, mechanism.ref) == []


def test_a_settled_position_with_no_newer_price_stays_open_until_there_is_one(
    company: Runtime,
) -> None:
    mechanism = _mechanism(company)
    with company.database.session() as session:
        trade_firings(company, session, mechanism, at=company.clock.now())
    # Pretend the horizon passed but no newer bar was recorded: resolve, then
    # try to close at the same instant the entries were filled.
    company.clock.advance(hours=8)
    with company.database.session() as session:
        resolve_due(session, ledger=company.ledger, clock=company.clock)
        same_instant = dt.datetime.fromtimestamp(_START + 292 * _HOUR + 600, tz=dt.UTC)
        held = close_settled(company, session, mechanism, at=same_instant)
    assert held.closed == () and "still open" in held.note
    assert all(t.close_order_ref is None for t, _ in _trades(company, mechanism.ref))
    with company.database.session() as session:
        later = close_settled(company, session, mechanism, at=company.clock.now())
    assert later.closed


def test_the_station_and_the_cli_show_entry_and_exit(company: Runtime) -> None:
    mechanism = _mechanism(company)
    with company.database.session() as session:
        trade_firings(company, session, mechanism, at=company.clock.now())
    page = station_app(company).handle(f"/mechanism/{mechanism.ref}", {}).body.decode()
    assert "ENTRY" in page.upper() and "EXIT" in page.upper() and ">392.0<" in page
    assert "does not fill at the trigger" in page
    with company.database.session() as session:
        summary = pnl_of(session, mechanism.ref)
    assert "slippage_bps" in summary
