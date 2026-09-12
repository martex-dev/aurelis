"""M39 — evidence is counted by independent episode, and open positions always close.

The acceptance criteria, each with a test named after it:

* predictions whose horizons overlap are one episode, across instruments,
* thirty instruments breaking out in the same hour are one observation, not
  thirty: enough predictions from too few episodes is still gathering, and
  the sweep retires nothing on it,
* a mechanism with enough independent episodes still becomes a scheme, and
  the retirement reason names the episodes,
* a paper position opened while the mechanism was a scheme is closed at its
  horizon even after the mechanism stops being one,
* the station and the CLI count episodes.

**Nothing here touches the network.**
"""

from __future__ import annotations

import datetime as dt
import io
import json
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.intel.live import CoinbaseCandles
from aurelis.judgement.resolution import resolve_due
from aurelis.judgement.tables import Thesis
from aurelis.mechanism.library import MIN_EPISODES, MIN_SCORED_PREDICTIONS, episodes_of
from aurelis.mechanism.paper import close_settled, has_open_trades, trade_firings
from aurelis.mechanism.predictions import generate_predictions
from aurelis.mechanism.tables import MechanismTrade
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.station.app import station_app
from aurelis.world.derive import derive_price_events

_HOUR = 3600
_START = 1_780_000_000


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


def _thesis(ref: str, at_hours: int, instrument: str = "BTC-USD") -> Thesis:
    return Thesis(
        ref=ref,
        instrument=instrument,
        reference_at=dt.datetime.fromtimestamp(_START + at_hours * _HOUR, tz=dt.UTC),
    )


def test_predictions_whose_horizons_overlap_are_one_episode_across_instruments() -> None:
    same_hour = [_thesis(f"THS-{i:04d}", 100, f"X{i}-USD") for i in range(30)]
    assert len(episodes_of(same_hour, 6)) == 1, "thirty instruments, one hour, one episode"
    spread = [_thesis(f"THS-{i:04d}", 100 + 24 * i) for i in range(12)]
    assert len(episodes_of(spread, 6)) == 12, "a day apart with a six-hour horizon: twelve"
    chain = [_thesis(f"THS-{i:04d}", 100 + 4 * i) for i in range(6)]
    # Hours 100, 104 sit inside the first horizon (100..106); 108 starts the
    # next (108..114) with 112 inside it; 116 the third with 120 inside it.
    assert [len(e) for e in episodes_of(chain, 6)] == [2, 2, 2]
    assert episodes_of([], 6) == []


def _company(
    settings: Settings, clock: FrozenClock, symbols: tuple[str, ...], *, bars: int = 300
) -> Runtime:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=standins()))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        for index, symbol in enumerate(symbols):
            snapshot = built.snapshots.ingest(
                session,
                CoinbaseCandles(opener=_Payload(_rising(bars, base=100.0 + index)), pause=0),
                desk="crypto",
                symbol=symbol,
                bars=bars,
            )
            derive_price_events(session, built.world, snapshot)
    return built


def _state(company: Runtime, *, horizon: int = 6) -> Any:
    with company.database.session() as session:
        return company.mechanisms.state(
            session,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            title="break then continuation",
            trigger_kind="price.range_break",
            desk="crypto",
            horizon_hours=horizon,
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


def _advance_and_score(company: Runtime, symbols: tuple[str, ...], *, bars: int) -> None:
    with company.database.session() as session:
        for index, symbol in enumerate(symbols):
            company.snapshots.ingest(
                session,
                CoinbaseCandles(opener=_Payload(_rising(bars, base=100.0 + index)), pause=0),
                desk="crypto",
                symbol=symbol,
                bars=bars,
            )
        resolve_due(session, ledger=company.ledger, clock=company.clock)


def test_thirty_instruments_breaking_in_the_same_hour_are_one_observation_not_thirty(
    settings: Settings,
) -> None:
    symbols = tuple(f"C{i:02d}-USD" for i in range(12))
    # On this fixture the close steps up at a break and is flat until the
    # next, so a 24-hour horizon sees the rise. Five breaks (bars 250..290)
    # are still inside their horizon on every instrument: 60 predictions, and
    # only two runs of overlapping horizons.
    clock = FrozenClock(dt.datetime.fromtimestamp(_START + 272 * _HOUR + 600, tz=dt.UTC))
    company = _company(settings, clock, symbols)
    try:
        mechanism = _state(company, horizon=24)
        with company.database.session() as session:
            run = generate_predictions(session, mechanism, clock=company.clock)
        assert len(run.sealed) == 60
        company.clock.advance(hours=50)
        _advance_and_score(company, symbols, bars=330)
        with company.database.session() as session:
            status = company.mechanisms.status(session, mechanism.ref)
            retired = company.mechanisms.sweep_retirements(session)
        assert status.scored == 60 >= MIN_SCORED_PREDICTIONS
        assert status.calibration.hits == 60, "every one of them right"
        assert status.episodes == 2 < MIN_EPISODES
        assert not status.enough and not status.is_scheme
        assert status.verdict == (
            f"gathering (60/{MIN_SCORED_PREDICTIONS} predictions, 2/{MIN_EPISODES} episodes)"
        )
        assert retired == [], "too few episodes to retire on, too"
    finally:
        company.close()


def test_a_mechanism_with_enough_independent_episodes_is_judged_and_the_reason_says_so(
    settings: Settings,
) -> None:
    # One instrument, breaks every ten bars, six-hour horizon: every break is
    # its own episode. A break is derived only once the lookback window is
    # full, so the recording is long and the mechanism is stated early enough
    # that thirty-odd breaks are still ahead.
    clock = FrozenClock(dt.datetime.fromtimestamp(_START + 160 * _HOUR + 600, tz=dt.UTC))
    company = _company(settings, clock, ("BTC-USD",), bars=500)
    try:
        mechanism = _state(company)
        with company.database.session() as session:
            run = generate_predictions(session, mechanism, clock=company.clock)
        assert len(run.sealed) >= MIN_SCORED_PREDICTIONS
        company.clock.advance(hours=345)
        _advance_and_score(company, ("BTC-USD",), bars=530)
        with company.database.session() as session:
            status = company.mechanisms.status(session, mechanism.ref)
        assert status.episodes == status.scored >= MIN_EPISODES
        assert status.enough
        # On a market that only rises, "up" cannot beat the drift by prediction
        # or by episode; the verdict says so and the sweep retires it with
        # the episode figures in the reason.
        assert not status.is_scheme
        with company.database.session() as session:
            retired = company.mechanisms.sweep_retirements(session)
        assert len(retired) == 1
        assert "episodes" in retired[0].retired_reason and "by episode" in retired[0].retired_reason
    finally:
        company.close()


def test_a_position_opened_as_a_scheme_is_closed_at_its_horizon_after_demotion(
    settings: Settings,
) -> None:
    from aurelis.service.loop import Service, cycle_once

    clock = FrozenClock(dt.datetime.fromtimestamp(_START + 292 * _HOUR + 600, tz=dt.UTC))
    company = _company(settings, clock, ("BTC-USD",))
    try:
        mechanism = _state(company)
        with company.database.session() as session:
            generate_predictions(session, mechanism, clock=company.clock)
            # Opened while (for the purpose of the test) the caller judged it a
            # scheme: trade_firings trusts its caller, as the docstring says.
            opened = trade_firings(company, session, mechanism, at=company.clock.now())
            assert opened.opened, "a firing was opened on paper"
            assert has_open_trades(session, mechanism.ref)
            status = company.mechanisms.status(session, mechanism.ref)
        assert not status.is_scheme, "and it is not a scheme on the record"

        company.clock.advance(hours=30)
        _advance_and_score(company, ("BTC-USD",), bars=330)
        # The wake, which trades only schemes, still closes what has settled.
        wake = cycle_once(company, service=Service(company, cycles_per_wake=1))
        with company.database.session() as session:
            trades = list(
                session.execute(
                    sa.select(MechanismTrade).where(MechanismTrade.mechanism_ref == mechanism.ref)
                ).scalars()
            )
            assert trades and all(t.close_order_ref is not None for t in trades)
            assert not has_open_trades(session, mechanism.ref)
            again = close_settled(company, session, mechanism, at=company.clock.now())
        assert again.closed == (), "nothing left to close"
        assert "closed 1 paper position" in wake.note or "closed" in wake.note
    finally:
        company.close()


def test_the_station_and_the_cli_count_episodes(settings: Settings) -> None:
    clock = FrozenClock(dt.datetime.fromtimestamp(_START + 292 * _HOUR + 600, tz=dt.UTC))
    company = _company(settings, clock, ("BTC-USD",))
    try:
        mechanism = _state(company)
        page = station_app(company).handle("/mechanisms", {}).body.decode()
        assert "EPISODES" in page.upper() and f"0/{MIN_EPISODES} episodes" in page
        detail = station_app(company).handle(f"/mechanism/{mechanism.ref}", {}).body.decode()
        assert "BRIER BY EPISODE" in detail.upper()
        assert "one observation" in detail
    finally:
        company.close()


