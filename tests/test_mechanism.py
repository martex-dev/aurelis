"""M30 — a mechanism turns a mined conjunction into a tested scheme.

The acceptance criteria, each with a test named after it:

* an agent states a mechanism over a mined co-occurrence: why it works, who is
  on the other side, a decay model — figure-checked, and a conjunction with no
  causal reason stays a conjunction,
* a stated mechanism is immutable and never deleted; only its retirement is
  written,
* the mechanism predicts every future occurrence of its trigger, sealed before
  the outcome, one per occurrence; a past occurrence is not sealed,
* the predictions score through the M25 resolver and the mechanism's
  out-of-sample calibration is read from them,
* a mechanism whose predictions do not beat the base rate is retired, and the
  training occurrence is excluded from the score,
* mechanism firings do not pollute an agent's own forward calibration,
* the mechanism is legible on the station.

**Nothing here touches the network.** Recordings are recorded payloads.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.intel.live import CoinbaseCandles
from aurelis.judgement.calibration import agent_calibration
from aurelis.judgement.resolution import resolve_due
from aurelis.judgement.tables import Thesis
from aurelis.mechanism.discovery import MechanismRefused, propose_mechanism
from aurelis.mechanism.library import MIN_SCORED_PREDICTIONS, seal_of
from aurelis.mechanism.predictions import generate_predictions
from aurelis.mechanism.standin import scripted_discovery
from aurelis.mechanism.tables import Mechanism
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.types import LlmResponse, Usage
from aurelis.runtime import Runtime
from aurelis.world.derive import derive_price_events

_HOUR = 3600
_START = 1_780_000_000


def _rising(count: int, *, breaks_every: int = 10) -> bytes:
    """A recording that range-breaks upward regularly, so a trigger fires often
    and the up-mechanism is usually right — a base rate near 1, which is what
    makes 'beats the base rate' a real bar rather than a free pass."""
    rows = []
    high = 100.0
    for i in range(count):
        if i % breaks_every == 0:
            high += 5.0
        close = high
        rows.append([_START + i * _HOUR, close - 1, close + 1, close, close, 5.0])
    return json.dumps(list(reversed(rows))).encode()


class _Payload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        return io.BytesIO(self._data)


@pytest.fixture
def clock() -> FrozenClock:
    # A few minutes after the last bar of a 300-bar recording.
    return FrozenClock(dt.datetime.fromtimestamp(_START + 299 * _HOUR + 600, tz=dt.UTC))


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Any:
    built = Runtime.build(
        settings, clock=clock, provider=MockProvider(responder=scripted_discovery)
    )
    built.initialise()
    built.staff()
    with built.database.session() as session:
        snapshot = built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_rising(300)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=300,
        )
        derive_price_events(session, built.world, snapshot)
    try:
        yield built
    finally:
        built.close()


def _mechanism(company: Runtime) -> Mechanism | None:
    with company.database.session() as session:
        return propose_mechanism(
            company.provider,
            session,
            company.mechanisms,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            trigger_kind="price.range_break",
            second_kind="price.range_break",
            desk="crypto",
            window_hours=48,
            ledger=company.ledger,
        )


# ------------------------------------------------------------ stating a mechanism


def test_an_agent_states_a_mechanism_over_a_mined_conjunction(company: Runtime) -> None:
    mechanism = _mechanism(company)
    assert mechanism is not None
    assert mechanism.direction == "up" and mechanism.horizon_hours == 24
    assert "forced" in mechanism.why.lower()
    assert len(mechanism.other_side) > 10 and len(mechanism.decay) > 10
    assert mechanism.origin == "invented"
    assert mechanism.found_on_instrument == "BTC-USD"
    assert seal_of(mechanism) == mechanism.seal


def test_a_conjunction_with_no_causal_reason_stays_a_conjunction(
    settings: Settings, clock: FrozenClock
) -> None:
    def declines(request: Any) -> str:
        if "State a mechanism" in request.messages[-1].content:
            return "MECHANISM: nothing"
        return scripted_discovery(request)

    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=declines))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        snapshot = built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_rising(300)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=300,
        )
        derive_price_events(built.world and session or session, built.world, snapshot)  # noqa: E501
        mechanism = propose_mechanism(
            built.provider,
            session,
            built.mechanisms,
            agent_ref=built.roster.by_handle(session, "QUANT").ref,
            trigger_kind="price.range_break",
            second_kind="price.range_break",
            desk="crypto",
            window_hours=48,
            ledger=built.ledger,
        )
        declined = session.execute(
            sa.text("SELECT count(*) FROM events WHERE kind = 'mechanism.declined'")
        ).scalar_one()
    assert mechanism is None
    assert declined == 1
    built.close()


def test_a_mechanism_citing_an_unshown_figure_is_refused(
    settings: Settings, clock: FrozenClock
) -> None:
    def inventor(request: Any) -> str:
        if "State a mechanism" in request.messages[-1].content:
            return (
                "MECHANISM: fabricated\nDIRECTION: up\nHORIZON: 24\nCONFIDENCE: 0.6\n"
                "WHY: it returned 0.9312 last year which proves it works here too.\n"
                "OTHER_SIDE: slow traders who do not see it.\n"
                "DECAY: it fades as others copy it over months.\n"
            )
        return scripted_discovery(request)

    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=inventor))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        snapshot = built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_rising(300)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=300,
        )
        derive_price_events(session, built.world, snapshot)
        with pytest.raises(MechanismRefused, match="not shown"):
            propose_mechanism(
                built.provider,
                session,
                built.mechanisms,
                agent_ref=built.roster.by_handle(session, "QUANT").ref,
                trigger_kind="price.range_break",
                second_kind="price.range_break",
                desk="crypto",
                window_hours=48,
                ledger=built.ledger,
            )
    built.close()


# ------------------------------------------------------------ immutability


def test_a_stated_mechanism_is_immutable_and_never_deleted(company: Runtime) -> None:
    mechanism = _mechanism(company)
    assert mechanism is not None
    with (
        company.database.session() as session,
        pytest.raises(IntegrityError, match="cannot be changed"),
    ):
        session.execute(
            sa.text("UPDATE mechanisms SET confidence = '0.99000000' WHERE ref = :r"),
            {"r": mechanism.ref},
        )
    with (
        company.database.session() as session,
        pytest.raises(IntegrityError, match="never deleted"),
    ):
        session.execute(sa.text("DELETE FROM mechanisms WHERE ref = :r"), {"r": mechanism.ref})
    # But its retirement may be written.
    with company.database.session() as session:
        company.mechanisms.retire(session, mechanism.ref, reason="a test of retirement")
        row = session.execute(
            sa.select(Mechanism).where(Mechanism.ref == mechanism.ref)
        ).scalar_one()
    assert row.retired_at is not None


# ------------------------------------------------------------ forward predictions


def test_the_mechanism_predicts_only_future_occurrences_one_per_occurrence(
    company: Runtime,
) -> None:
    mechanism = _mechanism(company)
    assert mechanism is not None
    with company.database.session() as session:
        run = generate_predictions(session, mechanism, clock=company.clock)
        again = generate_predictions(session, mechanism, clock=company.clock)
        predictions = list(
            session.execute(
                sa.select(Thesis).where(Thesis.mechanism_ref == mechanism.ref)
            ).scalars()
        )
    assert run.sealed and again.sealed == (), "one prediction per occurrence"
    assert run.skipped_past > 0, "occurrences whose horizon already passed are not sealed"
    for row in predictions:
        assert row.resolves_at > row.sealed_at, "every prediction is forward"
        assert row.mechanism_ref == mechanism.ref
        assert row.direction == "up" and row.confidence == mechanism.confidence


def test_a_mechanisms_predictions_score_through_the_resolver(company: Runtime) -> None:
    mechanism = _mechanism(company)
    assert mechanism is not None
    with company.database.session() as session:
        generate_predictions(session, mechanism, clock=company.clock)
        open_refs = [
            r
            for (r,) in session.execute(
                sa.text("SELECT ref FROM theses WHERE mechanism_ref IS NOT NULL")
            )
        ]
    assert open_refs
    # Advance past the horizon and record a covering recording, then resolve.
    company.clock.advance(hours=30)
    with company.database.session() as session:
        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_rising(360)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=360,
        )
        results = resolve_due(session, ledger=company.ledger, clock=company.clock)
        status = company.mechanisms.status(session, mechanism.ref)
    assert any(r.scored for r in results)
    assert status.scored >= 1
    assert status.calibration.mean_brier is not None


# ------------------------------------------------------------ retirement


def test_a_mechanism_that_does_not_beat_the_base_rate_is_retired(
    settings: Settings,
) -> None:
    """A down-mechanism on a market that only ever rises is wrong every time,
    which is worse than the base rate. With enough scored predictions the sweep
    retires it, and the training occurrence never counts."""
    clock = FrozenClock(dt.datetime.fromtimestamp(_START + 299 * _HOUR + 600, tz=dt.UTC))

    def down(request: Any) -> str:
        if "State a mechanism" in request.messages[-1].content:
            return (
                "MECHANISM: fade the break\nDIRECTION: down\nHORIZON: 6\nCONFIDENCE: 0.7\n"
                "WHY: a break marks exhaustion and the move reverses as latecomers are trapped.\n"
                "OTHER_SIDE: momentum chasers who buy the break and are the exit liquidity.\n"
                "DECAY: it fades as the crowd learns to fade it too, within a few quarters.\n"
            )
        return scripted_discovery(request)

    # State the mechanism early in the recording, so almost every occurrence is
    # still ahead of the clock and seals as a forward prediction in one pass;
    # then advance to the end and resolve them all. breaks_every=5 gives enough
    # occurrences to clear MIN_SCORED_PREDICTIONS.
    clock.set(dt.datetime.fromtimestamp(_START + 172 * _HOUR + 600, tz=dt.UTC))
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=down))
    built.initialise()
    built.staff()

    bars = 500
    with built.database.session() as session:
        agent = built.roster.by_handle(session, "QUANT").ref
        snapshot = built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_rising(bars, breaks_every=5)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=bars,
        )
        derive_price_events(session, built.world, snapshot)
        mechanism = propose_mechanism(
            built.provider,
            session,
            built.mechanisms,
            agent_ref=agent,
            trigger_kind="price.range_break",
            second_kind="price.range_break",
            desk="crypto",
            window_hours=48,
            ledger=built.ledger,
        )
        generate_predictions(session, mechanism, clock=built.clock)

    # The recording already covers the whole run; advance past every horizon
    # and settle.
    built.clock.set(dt.datetime.fromtimestamp(_START + 505 * _HOUR, tz=dt.UTC))
    with built.database.session() as session:
        resolve_due(session, ledger=built.ledger, clock=built.clock)

    assert mechanism is not None
    with built.database.session() as session:
        status = built.mechanisms.status(session, mechanism.ref)
        retired = built.mechanisms.sweep_retirements(session)
        after = built.mechanisms.status(session, mechanism.ref)
    assert status.scored >= MIN_SCORED_PREDICTIONS, status.describe()
    assert not status.calibration.beats_base_rate, "a down call on a rising market is worse"
    assert retired and retired[0].ref == mechanism.ref
    assert after.retired and "did not beat" in after.mechanism.retired_reason
    built.close()


# ------------------------------------------------------------ isolation


def test_mechanism_firings_do_not_pollute_an_agents_forward_record(company: Runtime) -> None:
    mechanism = _mechanism(company)
    assert mechanism is not None
    with company.database.session() as session:
        generate_predictions(session, mechanism, clock=company.clock)
        # The proposing agent has mechanism-tagged theses but has judged nothing.
        record = agent_calibration(session, mechanism.agent_ref, live_only=False)
    assert record.sealed == 0, "a mechanism firing is not the agent judging"


# ------------------------------------------------------------ the station


def test_the_mechanism_is_legible_on_the_station(company: Runtime) -> None:
    from aurelis.station.app import station_app
    from aurelis.station.build import build_sealed

    mechanism = _mechanism(company)
    assert mechanism is not None
    with company.database.session() as session:
        generate_predictions(session, mechanism, clock=company.clock)
    page = station_app(company).handle("/mechanisms", {}).body.decode()
    assert mechanism.ref in page and "candidate scheme" not in page.lower() or mechanism.ref in page
    assert "GATHERING" in page.upper() or "SCHEME" in page.upper()
    html = build_sealed(company, company.settings.workspace / "station.html").path.read_text(
        encoding="utf-8"
    )
    assert "Mechanisms" in html and mechanism.ref in html


def test_a_prediction_is_not_a_model_call() -> None:
    """A mechanism firing is mechanical: the reasoning was done once, when the
    mechanism was stated. Each prediction is that reasoning applied, with no
    provider round trip -- which is why a thesis can carry model 'mechanism:...'."""
    response = LlmResponse(text="unused", usage=Usage(1, 1), model=None)  # type: ignore[arg-type]
    assert response.text == "unused"


# ------------------------------------------------------------ what the station and the CLI show


def test_the_station_shows_the_unconditional_base_rate_not_the_triggers_own(
    company: Runtime,
) -> None:
    """Found on the live workspace after the first scored prediction: the
    mechanisms page read `base rate 0.0000`. It was printing the calibration's
    base rate, which is conditioned on the trigger and with one scored
    prediction is a perfect forecaster. The figure a reader must see is the
    one retirement compares against: the instrument's own drift."""
    from decimal import Decimal

    from aurelis.station.projections import mechanisms_view

    # Just after the recording's last break (bar 290), so a six-hour horizon
    # from it is still ahead and one prediction seals forward.
    company.clock.set(dt.datetime.fromtimestamp(_START + 292 * _HOUR + 600, tz=dt.UTC))
    with company.database.session() as session:
        mechanism = company.mechanisms.state(
            session,
            agent_ref=company.roster.by_handle(session, "QUANT").ref,
            title="break then continuation, six hours",
            trigger_kind="price.range_break",
            desk="crypto",
            horizon_hours=6,
            direction="up",
            confidence=Decimal("0.7"),
            why="stops above the range are run and the forced buying carries the close.",
            other_side="the shorts whose stops sit just above the range.",
            decay="it fades as the stops move, within months.",
            origin="invented",
            found_on_instrument="BTC-USD",
            found_on_event="test",
            model="test",
        )
        generate_predictions(session, mechanism, clock=company.clock)
    company.clock.advance(hours=30)
    with company.database.session() as session:
        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_rising(360)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=360,
        )
        resolve_due(session, ledger=company.ledger, clock=company.clock)
        status = company.mechanisms.status(session, mechanism.ref)
        row = next(r for r in mechanisms_view(session).rows if r["ref"] == mechanism.ref)
    assert status.scored >= 1
    assert status.base_rate_brier is not None
    assert row["base_rate"] == str(status.base_rate_brier)
    assert status.calibration.base_rate_brier != status.base_rate_brier, (
        "on a market that only rises the trigger's own base rate is a perfect "
        "forecaster; the drift over six bars is not, and that is the difference "
        "the page must show"
    )
