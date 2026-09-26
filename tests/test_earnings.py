"""M55 — a scheme's paper trading is judged after costs, by episode.

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
import io
import json
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.enums import EventKind
from aurelis.intel.live import CoinbaseCandles
from aurelis.judgement.resolution import resolve_due
from aurelis.mandate.standard import STANDARD
from aurelis.mechanism import earnings
from aurelis.mechanism.discovery import propose_mechanism
from aurelis.mechanism.earnings import family_bar, judge
from aurelis.mechanism.library import episodes_of
from aurelis.mechanism.predictions import generate_predictions
from aurelis.mechanism.tables import Mechanism, MechanismTrade
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.service.loop import Service, cycle_once
from aurelis.world.derive import derive_price_events

_HOUR = 3600
_START = 1_780_000_000


def _edge(count: int, *, every: int = 30, lift: float = 9.0) -> bytes:
    """A market with a mechanical edge after each volume spike and a drift
    near one half, as in the M31 tests: a spike-then-up mechanism is right on
    every firing and becomes a candidate scheme."""
    rows = []
    level = 1000.0
    for i in range(count):
        r = i % every
        spike = r == 0 and i >= 24
        if i >= 24 and 1 <= r <= 6:
            level += lift / 6
        elif i >= 24 and 7 <= r <= 12:
            level -= lift / 6
        else:
            level += 0.2 if ((i * 2654435761) >> 7) & 1 else -0.2
        level += 0.005
        volume = 60.0 if spike else 5.0
        rows.append([_START + i * _HOUR, level - 0.5, level + 0.5, level, level, volume])
    return json.dumps(list(reversed(rows))).encode()


class _Payload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        return io.BytesIO(self._data)


def _up_mechanism(request: Any) -> str:
    if "State a mechanism for this pattern" in request.messages[-1].content:
        return (
            "MECHANISM: spike then lift\nDIRECTION: up\nHORIZON: 6\nCONFIDENCE: 0.8\n"
            "WHY: a volume spike marks forced buying by participants who must fill inside "
            "a window, and price is pushed up until that flow is done.\n"
            "OTHER_SIDE: passive quoters who lean against the flow and are run over.\n"
            "DECAY: it dies once quoters widen around the spike, within a few months.\n"
        )
    return standins()(request)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(dt.datetime.fromtimestamp(_START + 200 * _HOUR + 600, tz=dt.UTC))


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Any:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=_up_mechanism))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        snapshot = built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_edge(900)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=900,
        )
        derive_price_events(session, built.world, snapshot, tail=900)
    try:
        yield built
    finally:
        built.close()


def _state(company: Runtime) -> Mechanism:
    with company.database.session() as session:
        mechanism = propose_mechanism(
            company.provider,
            session,
            company.mechanisms,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            trigger_kind="price.volume_spike",
            second_kind="price.range_break",
            desk="crypto",
            window_hours=24,
            ledger=company.ledger,
        )
        assert mechanism is not None
        return mechanism


def _score_all(company: Runtime, mechanism: Mechanism, *, upto_bar: int) -> None:
    with company.database.session() as session:
        generate_predictions(session, mechanism, clock=company.clock)
    company.clock.set(dt.datetime.fromtimestamp(_START + upto_bar * _HOUR, tz=dt.UTC))
    with company.database.session() as session:
        resolve_due(session, ledger=company.ledger, clock=company.clock)


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
    company: Runtime,
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
    company: Runtime,
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
    company: Runtime,
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
    company: Runtime,
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


# ------------------------------------------------------------ capital follows the record (M57)


def _scheme_with_a_fresh_firing(company: Runtime) -> Mechanism:
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
    return mechanism


def _attached(session: Any, mechanism: Mechanism) -> Mechanism:
    """The mechanism loaded in this session, as the wake loads it, so the
    version it is composed into is written back."""
    return session.execute(sa.select(Mechanism).where(Mechanism.ref == mechanism.ref)).scalar_one()


def _earning(ref: str) -> Any:
    wins = _d(*(["120"] * 11), "-40")
    return {ref: judge(ref, wins, wins, bar=family_bar(1))}


def test_the_ladder_sizes_a_record_and_says_why() -> None:
    from aurelis.mechanism.sizing import BASE_WEIGHT, EARNING_WEIGHT, target_weight

    luck = judge("MEC-0001", _d(*(["10", "-10"] * 6)), _d("0"), bar=family_bar(1))
    assert target_weight(None) == (BASE_WEIGHT, "no round trip closed yet: the base share")
    assert target_weight(_earning("MEC-0001")["MEC-0001"])[0] == EARNING_WEIGHT
    assert target_weight(_losing("MEC-0001")["MEC-0001"])[0] == 0
    weight, why = target_weight(luck)
    assert weight == BASE_WEIGHT and why.startswith("not distinguishable from luck")


def test_a_scheme_earning_after_costs_is_given_twice_the_share(
    company: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aurelis.mechanism.paper import trade_firings
    from aurelis.portfolio.tables import Allocation

    mechanism = _scheme_with_a_fresh_firing(company)
    monkeypatch.setattr(earnings, "earnings_board", lambda session: _earning(mechanism.ref))
    with company.database.session() as session:
        mechanism = _attached(session, mechanism)
        result = trade_firings(company, session, mechanism, at=company.clock.now())
        allocation = session.execute(
            sa.select(Allocation).where(Allocation.version_ref == mechanism.version_ref)
        ).scalar_one()
    assert result.opened
    assert Decimal(str(allocation.weight)) == Decimal("0.10")
    assert "earning after costs" in allocation.rationale


def test_the_portfolio_manager_resizes_a_scheme_when_its_record_moves(
    company: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aurelis.autonomy.duties import run_duties
    from aurelis.mechanism.paper import trade_firings
    from aurelis.portfolio.tables import Allocation

    mechanism = _scheme_with_a_fresh_firing(company)
    with company.database.session() as session:
        mechanism = _attached(session, mechanism)
        trade_firings(company, session, mechanism, at=company.clock.now())
        version = mechanism.version_ref
    monkeypatch.setattr(earnings, "earnings_board", lambda session: _earning(mechanism.ref))
    (duty,) = run_duties(company, at=company.clock.now(), only=("allocation",))
    (again,) = run_duties(company, at=company.clock.now(), only=("allocation",), force=True)
    with company.database.session() as session:
        rows = list(
            session.execute(
                sa.select(Allocation)
                .where(Allocation.version_ref == version)
                .order_by(Allocation.decided_at, Allocation.ref)
            ).scalars()
        )
        pm = company.roster.by_handle(session, "PM").ref
        withdrawn = (
            session.execute(
                sa.text("SELECT actor FROM events WHERE kind = :k"),
                {"k": EventKind.ALLOCATION_WITHDRAWN.value},
            )
            .scalars()
            .all()
        )
    old, new = rows
    assert Decimal(str(old.weight)) == Decimal("0.05") and old.withdrawn_at is not None
    assert "re-sized from 0.05" in old.withdrawn_reason.replace("0.0500", "0.05")
    assert Decimal(str(new.weight)) == Decimal("0.10") and new.withdrawn_at is None
    assert new.decided_by == pm and withdrawn == [pm]
    assert "1 re-sized" in duty.done and duty.findings[0].startswith(mechanism.ref)
    assert "0 re-sized" in again.done, "a share that matches its record is left alone"


def test_schemes_together_never_hold_more_than_half_the_book(
    company: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aurelis.mechanism import sizing
    from aurelis.trading.deployment import open_paper_book

    with company.database.session() as session:
        pm = company.roster.by_handle(session, "PM").ref
        book = open_paper_book(
            company,
            session,
            desk="crypto",
            equity=Decimal("100000"),
            opened_by=pm,
            at=company.clock.now(),
        )
        monkeypatch.setattr(sizing, "scheme_versions", lambda session: {"SV-A", "SV-B"})
        company.book.allocate(
            session,
            portfolio_ref=book,
            version_ref="SV-A",
            weight=Decimal("0.45"),
            rationale="a test holding",
            decided_by=pm,
            at=company.clock.now(),
        )
        room = sizing.room_for(company, session, book, "SV-B")
    assert room == Decimal("0.05")
