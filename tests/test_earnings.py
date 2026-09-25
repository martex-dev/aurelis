"""M54 — a scheme's paper trading is judged after costs, by episode.

The acceptance criteria, each with a test named after it:

* a scheme earns only when it made money in total and its winning episodes
  beat a coin at the bar for the family of schemes measured,
* a scheme loses when it lost in total and its losing episodes beat a coin at
  0.05, not divided, because a stop protects the book,
* below ten episodes a record is gathering, whatever it made,
* one episode that tripled cannot carry a record: episodes are counted, not
  summed,
* the drawdown is the deepest fall of the running P&L below its high,
* thirty round trips opened in one hour are one episode,
* the wake stops a losing scheme opening positions, once, with Risk as the
  actor and the numbers on the record, and says so,
* the mandate has a fourteenth condition, ``earning``, read from the record,
* the station and the brain show each scheme's record after costs.

**Nothing here touches the network.**
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from tests.test_schemes_trade import (
    _START,
    CoinbaseCandles,
    _edge,
    _Payload,
    _score_all,
    _state,
    derive_price_events,
)
from tests.test_schemes_trade import clock as clock  # noqa: F401 - a fixture
from tests.test_schemes_trade import company as company  # noqa: F401 - a fixture

from aurelis.core.enums import EventKind
from aurelis.mandate.standard import STANDARD
from aurelis.mechanism import earnings
from aurelis.mechanism.earnings import family_bar, judge
from aurelis.mechanism.library import episodes_of
from aurelis.mechanism.predictions import generate_predictions
from aurelis.mechanism.tables import MechanismTrade
from aurelis.runtime import Runtime
from aurelis.service.loop import Service, cycle_once

_HOUR = 3600


def _d(*values: str) -> list[Decimal]:
    return [Decimal(v) for v in values]


# ------------------------------------------------------------ the rules


def test_a_scheme_earns_only_beyond_the_bar_for_the_family() -> None:
    wins = _d(*(["120"] * 11), "-40")
    alone = judge("MEC-0001", wins, wins, bar=family_bar(1))
    among_many = judge("MEC-0001", wins, wins, bar=family_bar(20))
    assert alone.p_earn == Decimal("0.0032") and alone.bar == Decimal("0.05")
    assert alone.verdict == "earning after costs" and alone.earning
    assert among_many.bar == Decimal("0.0025")
    assert among_many.verdict == "not distinguishable from luck", "the best of twenty books"


def test_a_scheme_loses_at_an_undivided_bar_because_a_stop_protects_the_book() -> None:
    losses = _d(*(["-30"] * 9), "10", "12")
    record = judge("MEC-0002", losses, losses, bar=family_bar(20))
    assert record.pnl == Decimal("-248.00") and record.lost == 9 and record.won == 2
    assert record.p_lose == Decimal("0.0327") and record.p_lose > record.bar
    assert record.verdict == "losing after costs" and record.losing


def test_below_ten_episodes_a_record_is_gathering_whatever_it_made() -> None:
    record = judge("MEC-0003", _d(*(["500"] * 9)), _d(*(["500"] * 9)), bar=family_bar(1))
    assert record.verdict == "gathering (9/10 paper episodes)"
    assert not record.earning and not record.losing


def test_one_episode_that_tripled_cannot_carry_a_record() -> None:
    lucky = _d("9000", *(["-20"] * 10))
    record = judge("MEC-0004", lucky, lucky, bar=family_bar(1))
    assert record.pnl > 0 and record.won == 1 and record.lost == 10
    assert record.verdict == "not distinguishable from luck"


def test_the_drawdown_is_the_deepest_fall_below_the_running_high() -> None:
    record = judge(
        "MEC-0005", _d("100", "-60", "-70", "50"), _d("100", "-60", "-70", "50"), bar=Decimal(1)
    )
    assert record.drawdown == Decimal("130.00") and record.worst_episode == Decimal("-70.00")


def test_thirty_round_trips_opened_in_one_hour_are_one_episode() -> None:
    class _T:
        def __init__(self, n: int, at: dt.datetime) -> None:
            self.ref = f"THS-{n:04d}"
            self.reference_at = at

    start = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)
    same_hour = [_T(n, start + dt.timedelta(minutes=n)) for n in range(30)]
    later = [_T(99, start + dt.timedelta(days=1))]
    assert len(episodes_of(same_hour + later, 6)) == 2  # type: ignore[arg-type]


# ------------------------------------------------------------ the wake


def _losing(ref: str) -> Any:
    losses = _d(*(["-30"] * 10), "5")
    return {ref: judge(ref, losses, losses, bar=family_bar(1))}


def test_the_wake_stops_a_losing_scheme_opening_positions_once_and_says_so(
    company: Runtime,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    company.clock.set(dt.datetime.fromtimestamp(_START + 30 * _HOUR, tz=dt.UTC))
    mechanism = _state(company)
    _score_all(company, mechanism, upto_bar=910)
    with company.database.session() as session:
        snapshot = company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_edge(940)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=940,
        )
        derive_price_events(session, company.world, snapshot, tail=940)
        company.clock.set(dt.datetime.fromtimestamp(_START + 931 * _HOUR + 600, tz=dt.UTC))
        generate_predictions(session, mechanism, clock=company.clock)
        assert company.mechanisms.status(session, mechanism.ref).is_scheme
    monkeypatch.setattr(earnings, "earnings_board", lambda session: _losing(mechanism.ref))
    first = cycle_once(company, service=Service(company, calls_per_day=0, cycles_per_wake=1))
    company.clock.advance(hours=1)
    second = cycle_once(company, service=Service(company, calls_per_day=0, cycles_per_wake=1))
    with company.database.session() as session:
        trades = session.execute(sa.select(sa.func.count()).select_from(MechanismTrade)).scalar()
        events = session.execute(
            sa.text("SELECT actor, payload FROM events WHERE kind = :k"),
            {"k": EventKind.MECHANISM_SUSPENDED.value},
        ).all()
        risk = company.roster.by_handle(session, "RISK").ref
    assert trades == 0, "a scheme losing after costs opens nothing"
    assert f"suspended from paper for losing after costs: {mechanism.ref}" in first.note
    assert "suspended from paper" not in second.note, "recorded once"
    assert len(events) == 1 and events[0].actor == risk


def test_without_a_losing_record_the_same_wake_trades(
    company: Runtime,  # noqa: F811
) -> None:
    company.clock.set(dt.datetime.fromtimestamp(_START + 30 * _HOUR, tz=dt.UTC))
    mechanism = _state(company)
    _score_all(company, mechanism, upto_bar=910)
    with company.database.session() as session:
        snapshot = company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_edge(940)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=940,
        )
        derive_price_events(session, company.world, snapshot, tail=940)
        company.clock.set(dt.datetime.fromtimestamp(_START + 931 * _HOUR + 600, tz=dt.UTC))
        generate_predictions(session, mechanism, clock=company.clock)
    wake = cycle_once(company, service=Service(company, calls_per_day=0, cycles_per_wake=1))
    with company.database.session() as session:
        trades = session.execute(sa.select(sa.func.count()).select_from(MechanismTrade)).scalar()
    assert trades and "suspended" not in wake.note


# ------------------------------------------------------------ the record


def test_the_mandate_has_an_earning_condition_read_from_the_record(
    company: Runtime,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aurelis.mandate.assessment import assess

    assert len(STANDARD) == 14
    keys = [c.key for c in STANDARD]
    assert keys.index("earning") == keys.index("scheme") + 1
    before = {f.criterion.key: f for f in assess(company).findings}
    assert not before["earning"].met and "no scheme has traded" in before["earning"].reading

    wins = _d(*(["120"] * 11), "-40")
    monkeypatch.setattr(
        earnings,
        "earnings_board",
        lambda session: {"MEC-0001": judge("MEC-0001", wins, wins, bar=family_bar(1))},
    )
    after = {f.criterion.key: f for f in assess(company).findings}
    assert after["earning"].met and "1 earning after costs" in after["earning"].reading


def test_the_station_and_the_brain_show_each_schemes_record_after_costs(
    company: Runtime,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aurelis.brain.briefing import briefing
    from aurelis.station.app import station_app

    company.clock.set(dt.datetime.fromtimestamp(_START + 30 * _HOUR, tz=dt.UTC))
    mechanism = _state(company)
    losing = _losing(mechanism.ref)
    monkeypatch.setattr(earnings, "earnings_board", lambda session: losing)
    page = station_app(company).handle("/mechanisms", {}).body.decode()
    assert "AFTER COSTS" in page and "LOSING AFTER COSTS" in page
    with company.database.session() as session:
        company.ledger.append(
            session,
            kind=EventKind.MECHANISM_SUSPENDED,
            actor="AG-RISK",
            subject=mechanism.ref,
            payload={"pnl": "-295", "episodes": 11, "won": 1, "lost": 10},
            at=company.clock.now(),
        )
        brain = briefing(session)
    page = station_app(company).handle("/mechanisms", {}).body.decode()
    assert "SUSPENDED: LOSING AFTER COSTS" in page
    assert "After costs, by episode" not in brain.record, "only schemes that traded"
