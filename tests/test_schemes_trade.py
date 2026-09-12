"""M31 — the company hunts for mechanisms on its own, and a scheme trades on paper.

The acceptance criteria, each with a test named after it:

* the event stream is mined for ranked conjunctions, deterministically,
* the base rate a mechanism must beat is the instrument's unconditional
  up-frequency, so a mechanism that is right every time can be a scheme,
* a mechanism becomes a candidate scheme only out of sample, on enough
  predictions, beating a coin toss and that base rate,
* a candidate scheme trades its firings on paper through Risk, opens at the
  reference close and closes at the resolution close, and its realised P&L
  after fees is on the record; a mechanism that is not a scheme trades nothing,
* the autonomy loop brings mined conjunctions to judging agents, one
  (agent, pair) per cycle, and stops when every pair has been answered on the
  standing events,
* the mandate has a twelfth condition, ``scheme``, read from the record,
* the richer derived events fire on a recording and are figure-citable.

**Nothing here touches the network.** Recordings are recorded payloads.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.autonomy.loop import run_autonomy
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.intel.live import CoinbaseCandles
from aurelis.judgement.resolution import resolve_due
from aurelis.mandate.assessment import assess
from aurelis.mandate.standard import STANDARD
from aurelis.mechanism.discovery import propose_mechanism
from aurelis.mechanism.library import MIN_SCORED_PREDICTIONS
from aurelis.mechanism.mining import mine_pairs
from aurelis.mechanism.paper import pnl_of, trade_firings
from aurelis.mechanism.predictions import generate_predictions
from aurelis.mechanism.tables import Mechanism, MechanismTrade
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.runtime import Runtime
from aurelis.trading.tables import Order
from aurelis.world.derive import derive_price_events
from aurelis.world.tables import WorldEvent

_HOUR = 3600
_START = 1_780_000_000


def _edge(count: int, *, every: int = 30, lift: float = 9.0) -> bytes:
    """A market with a real, mechanical edge and a drift near one half.

    Every ``every`` bars a volume spike prints. The six bars after it step up
    by ``lift`` in total, the six after that give it all back, and the rest
    zigzag by one -- so a mechanism "spike then up over 6h" is right every
    time, while over a 6-bar window starting anywhere the close is above its
    start about half the time. A forecaster who knew only the drift scores a
    coin toss; the mechanism does not.

    The lift is nine points on a thousand: large enough that a paper round
    trip filled at the wake *after* the spike (M40), paying ten basis points
    a side and the spread, still shows the edge after fees. At three points
    it did not -- the old hindsight fill at the spike's own close had been
    carrying the test.
    """
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
            # A deterministic pseudo-random step, small against the lift, so a
            # six-bar window starting anywhere is above its start about half
            # the time and the post-spike lift still makes a new high.
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
    """Generate at the frozen clock, then advance past every horizon and settle."""
    with company.database.session() as session:
        generate_predictions(session, mechanism, clock=company.clock)
    company.clock.set(dt.datetime.fromtimestamp(_START + upto_bar * _HOUR, tz=dt.UTC))
    with company.database.session() as session:
        resolve_due(session, ledger=company.ledger, clock=company.clock)


# ------------------------------------------------------------ mining


def test_the_event_stream_is_mined_for_ranked_conjunctions(company: Runtime) -> None:
    with company.database.session() as session:
        pairs = mine_pairs(session, within=dt.timedelta(hours=24), min_count=3)
        kinds = {k for (k,) in session.execute(sa.select(WorldEvent.kind).distinct())}
    assert pairs, "the edge market has conjunctions"
    assert pairs == sorted(pairs, key=lambda p: (-p.count, p.first, p.second))
    assert all(p.count >= 3 for p in pairs)
    assert "price.volume_spike" in kinds and "price.range_break" in kinds
    assert not any(p.first == "listing.seen" for p in pairs)


# ------------------------------------------------------------ the base rate


def test_the_base_rate_is_unconditional_so_a_right_mechanism_can_be_a_scheme(
    company: Runtime,
) -> None:
    """On a market whose drift is a coin toss, a mechanism that is right on
    every firing must beat the base rate. Under the old definition -- the
    up-frequency among its own predictions -- it could not have."""
    # State it early so every spike ahead of the clock is a forward prediction.
    company.clock.set(dt.datetime.fromtimestamp(_START + 30 * _HOUR, tz=dt.UTC))
    mechanism = _state(company)
    _score_all(company, mechanism, upto_bar=910)
    with company.database.session() as session:
        status = company.mechanisms.status(session, mechanism.ref)
    assert status.scored >= MIN_SCORED_PREDICTIONS, status.describe()
    assert status.calibration.hit_rate == Decimal("1")
    assert status.base_rate_brier is not None
    assert Decimal("0.10") < status.base_rate_brier <= Decimal("0.36"), (
        "a drift near a half scores near a coin toss"
    )
    assert status.beats_base_rate and status.is_scheme
    assert status.verdict == "candidate scheme"


def test_a_mechanism_is_not_a_scheme_until_it_has_enough_out_of_sample_predictions(
    company: Runtime,
) -> None:
    company.clock.set(dt.datetime.fromtimestamp(_START + 860 * _HOUR, tz=dt.UTC))
    mechanism = _state(company)
    _score_all(company, mechanism, upto_bar=910)
    with company.database.session() as session:
        status = company.mechanisms.status(session, mechanism.ref)
        schemes = company.mechanisms.schemes(session)
    assert 0 < status.scored < MIN_SCORED_PREDICTIONS
    assert not status.is_scheme and status.verdict.startswith("gathering")
    assert schemes == []


# ------------------------------------------------------------ paper trading


def test_a_candidate_scheme_trades_its_firings_on_paper_through_risk(
    company: Runtime,
) -> None:
    company.clock.set(dt.datetime.fromtimestamp(_START + 30 * _HOUR, tz=dt.UTC))
    mechanism = _state(company)
    _score_all(company, mechanism, upto_bar=910)

    # Nothing has traded yet; the record earned the right, now use it. Opening
    # every already-scored firing would be hindsight, so seed one fresh firing
    # ahead of the clock: state a new occurrence via a later recording.
    with company.database.session() as session:
        assert company.mechanisms.status(session, mechanism.ref).is_scheme
        snapshot = company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_edge(940)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=940,
        )
        derive_price_events(session, company.world, snapshot, tail=940)
        # The clock stands where the wake would: just after the fresh firing
        # at bar 930, so the fill is at a price the wake can see (M40).
        company.clock.set(dt.datetime.fromtimestamp(_START + 931 * _HOUR + 600, tz=dt.UTC))
        generate_predictions(session, mechanism, clock=company.clock)
        first = trade_firings(runtime=company, session=session, mechanism=mechanism)
        trades = list(session.execute(sa.select(MechanismTrade)).scalars())
        orders = list(session.execute(sa.select(Order)).scalars())
    assert first.opened, first.describe()
    assert len(trades) == len(first.opened)
    assert all(t.close_order_ref is None for t in trades)
    assert all(o.version_ref == mechanism.version_ref for o in orders)
    assert mechanism.version_ref is not None or trades[0].open_order_ref

    # Advance to the wake after the horizon, settle, and the positions close
    # at the newest close that wake can see (M40); each round trip carries its
    # realised P&L after fees.
    company.clock.set(dt.datetime.fromtimestamp(_START + 937 * _HOUR + 600, tz=dt.UTC))
    with company.database.session() as session:
        resolve_due(session, ledger=company.ledger, clock=company.clock)
        second = trade_firings(runtime=company, session=session, mechanism=mechanism)
        summary = pnl_of(session, mechanism.ref)
        risk_rows = session.execute(sa.text("SELECT count(*) FROM risk_assessments")).scalar_one()
    assert second.closed, second.describe()
    assert summary["closed"] == len(second.closed)
    assert summary["won"] == summary["closed"], "right every time, and it shows after fees"
    assert summary["pnl"] > 0
    assert risk_rows >= 2, "every intent went through Risk"


def test_a_mechanism_that_is_not_a_scheme_trades_nothing(company: Runtime) -> None:
    company.clock.set(dt.datetime.fromtimestamp(_START + 860 * _HOUR, tz=dt.UTC))
    mechanism = _state(company)
    _score_all(company, mechanism, upto_bar=910)
    with company.database.session() as session:
        assert not company.mechanisms.status(session, mechanism.ref).is_scheme
        assert company.mechanisms.schemes(session) == []
        trades = session.execute(
            sa.select(sa.func.count()).select_from(MechanismTrade)
        ).scalar_one()
    assert trades == 0


# ------------------------------------------------------------ the loop


def test_the_loop_brings_mined_conjunctions_to_agents_and_stops_when_all_are_answered(
    settings: Settings, clock: FrozenClock
) -> None:
    def declines(request: Any) -> str:
        if "State a mechanism for this pattern" in request.messages[-1].content:
            return "MECHANISM: nothing"
        return standins()(request)

    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=declines))
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
        judges = session.execute(
            sa.text(
                "SELECT count(*) FROM agents WHERE state IN ('active','working') AND department "
                "IN ('market_intelligence','quantitative_research','strategy_laboratory')"
            )
        ).scalar_one()
        pairs = len(mine_pairs(session, within=dt.timedelta(hours=24), min_count=3, limit=8))
    outcome = run_autonomy(built, cycles=judges * pairs + 40, calls=1000)
    discovered = [c for c in outcome.cycles if c.action == "discover"]
    assert len(discovered) == judges * pairs, [c.describe() for c in outcome.cycles[:5]]
    assert all("declined" in c.detail for c in discovered)
    assert "answered" in outcome.stuck["scheme"] or "every mined" in outcome.stuck["scheme"]
    with built.database.session() as session:
        declined = session.execute(
            sa.text("SELECT count(*) FROM events WHERE kind = 'mechanism.declined'")
        ).scalar_one()
    assert declined == judges * pairs
    again = run_autonomy(built, cycles=6, calls=100)
    assert "discover" not in {c.action for c in again.acted}, "same events, same answers"
    built.close()


# ------------------------------------------------------------ the mandate


def test_the_mandate_reads_the_scheme_condition_from_the_record(company: Runtime) -> None:
    assert len(STANDARD) == 13 and any(c.key == "scheme" for c in STANDARD)
    before = next(f for f in assess(company).findings if f.criterion.key == "scheme")
    assert not before.met and "no mechanism" in before.reading
    company.clock.set(dt.datetime.fromtimestamp(_START + 30 * _HOUR, tz=dt.UTC))
    mechanism = _state(company)
    _score_all(company, mechanism, upto_bar=910)
    after = next(f for f in assess(company).findings if f.criterion.key == "scheme")
    assert after.met, after.reading
    assert "1 candidate scheme" in after.reading


# ------------------------------------------------------------ derived events


def test_the_richer_derived_events_fire_and_are_citable(company: Runtime) -> None:
    with company.database.session() as session:
        kinds = {k for (k,) in session.execute(sa.select(WorldEvent.kind).distinct())}
        flip = (
            session.execute(
                sa.select(WorldEvent).where(WorldEvent.kind == "price.momentum_flip").limit(1)
            )
            .scalars()
            .first()
        )
    assert "price.momentum_flip" in kinds
    assert flip is not None and flip.payload["to"] in ("up", "down")
    assert "return_24" in flip.payload


# ------------------------------------------------------------ the miner's evidence (M33)


def test_the_miner_shows_the_in_sample_effect_of_a_trigger(company: Runtime) -> None:
    """On the edge market the six hours after a spike rise every time, and any
    six hours rise about half the time. Both columns come from the same
    recording, and the material says the figures are in sample."""
    from aurelis.mechanism.mining import effect_of

    with company.database.session() as session:
        effect = effect_of(session, trigger="price.volume_spike", horizon_hours=6)
    assert effect is not None and effect.n >= 20
    assert effect.up_rate_after == Decimal("1")
    assert Decimal("0.35") < effect.unconditional_up_rate < Decimal("0.8")
    assert effect.mean_return_after > effect.unconditional_mean_return
    assert effect.lift > Decimal("0.2")


def test_the_agent_is_shown_the_evidence_and_may_cite_it(
    settings: Settings, clock: FrozenClock
) -> None:
    """A mechanism that cites the in-sample figures it was shown passes the
    figure check; one that cites a figure it was not shown is refused. The
    evidence is kept as an artifact the mechanism names."""
    from aurelis.mechanism.discovery import MechanismRefused

    seen: list[str] = []

    def citing(request: Any) -> str:
        prompt = request.messages[-1].content
        if "State a mechanism for this pattern" in prompt:
            seen.append(prompt)
            import re

            match = re.search(
                r"6h after the trigger: n (\d+), mean (-?[\d.]+)%, up ([\d.]+)", prompt
            )
            assert match, prompt
            n, mean, up = match.groups()
            return (
                "MECHANISM: spike then lift\nDIRECTION: up\nHORIZON: 6\nCONFIDENCE: 0.7\n"
                f"WHY: across {n} spikes the next six hours averaged {mean}% and rose {up} of "
                "the time, because a burst of forced buying is filled before it is done.\n"
                "OTHER_SIDE: passive quoters who lean against the burst and are run over.\n"
                "DECAY: it fades once quoters widen around spikes, within months.\n"
            )
        return standins()(request)

    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=citing))
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
        mechanism = propose_mechanism(
            built.provider,
            session,
            built.mechanisms,
            agent_ref=built.roster.by_handle(session, "QUANT").ref,
            trigger_kind="price.volume_spike",
            second_kind="price.range_break",
            desk="crypto",
            window_hours=24,
            ledger=built.ledger,
            artifacts=built.artifacts,
        )
        assert mechanism is not None
        assert mechanism.evidence_digest and len(mechanism.evidence_digest) == 64
        kind = session.execute(
            sa.text("SELECT kind FROM artifacts WHERE digest = :d"),
            {"d": mechanism.evidence_digest},
        ).scalar_one()
    assert kind == "mechanism.evidence"
    assert "In Sample Evidence" in seen[0] and "6h after any bar" in seen[0]
    assert "not evidence the pattern predicts anything" in seen[0]

    def inventing(request: Any) -> str:
        if "State a mechanism for this pattern" in request.messages[-1].content:
            return (
                "MECHANISM: made up\nDIRECTION: up\nHORIZON: 6\nCONFIDENCE: 0.7\n"
                "WHY: it rose 93.7% of the time last year which the table does not show.\n"
                "OTHER_SIDE: slow traders.\nDECAY: fades over months.\n"
            )
        return standins()(request)

    other = Runtime.build(settings, clock=clock, provider=MockProvider(responder=inventing))
    with other.database.session() as session, pytest.raises(MechanismRefused, match="not shown"):
        propose_mechanism(
            other.provider,
            session,
            other.mechanisms,
            agent_ref=built.roster.by_handle(session, "STRAT").ref,
            trigger_kind="price.volume_spike",
            second_kind="price.range_break",
            desk="crypto",
            window_hours=24,
            # A different agent in the prompt, or the response cache hands this
            # call the first agent's answer -- the M25 finding, again.
            identity="You are STRAT, the strategy architect.",
        )
    other.close()
    built.close()
