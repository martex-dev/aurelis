"""M47 — the company works while there is work, and asks about what is rare.

The first two wakes back on 25 September spent twenty and fifteen of four
hundred model calls and stopped: one decline on one market kept an agent out
of the seat for all sixty-seven, and the miner offered the same eight
high-volume pairs of price noise every hour.

The acceptance criteria, each with a test named after it:

* a judge that passed on one market is still offered the others, and the
  market it passed on returns once it has a new recording,
* a judge that declined to pick any market waits for the next recording,
* a refusal after a market was picked names the market,
* the miner counts every pair in one pass and matches the pair-by-pair count,
* the rarest triggers come first and each brings its strongest partners,
* a single social post is a reading and a burst of them is an event,
* a pattern is put to the same agent again only once it has materially more
  occurrences than when the agent answered,
* a wake spends at most its share of the day's model calls.

**Nothing here touches the network.**
"""

from __future__ import annotations

import datetime as dt
import io
import json
from typing import Any

import pytest

from aurelis.autonomy.agenda import REASK_GROWTH, _last_word_on_pattern, _seatable
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.enums import EventKind
from aurelis.intel.live import CoinbaseCandles
from aurelis.judgement.seat import (
    ALL_MARKETS,
    JudgementRefused,
    declined_on_standing,
    seat_agent,
)
from aurelis.judgement.standin import scripted_judge
from aurelis.mechanism.mining import is_reading, mine_diverse, mine_pairs
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.platform.llm.types import LlmRequest
from aurelis.runtime import Runtime
from aurelis.service.loop import Service, cycle_once
from aurelis.world.store import World

_HOUR = 3600
_START = 1_780_000_000


def _bars(count: int, *, base: float = 100.0, step: float = 1.0) -> bytes:
    rows = [
        [
            _START + i * _HOUR,
            base + i * step - 1,
            base + i * step + 1,
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


class _PassesOnBtc:
    """Declines any view on BTC; otherwise answers like the stand-in."""

    def __init__(self) -> None:
        self.markets: list[str] = []

    def __call__(self, request: LlmRequest) -> str:
        prompt = request.messages[-1].content
        if "Which market do you want" in prompt:
            wants = "btc-usd" if "btc-usd" in prompt else "eth-usd"
            self.markets.append(wants)
            return f"ANSWER: {wants}\nBECAUSE: it is the one I want to look at first."
        if "State your view on BTC-USD" in prompt:
            return "DIRECTION: nothing\n"
        if "State your view on" in prompt:
            return scripted_judge(request)
        return standins()(request)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(dt.datetime.fromtimestamp(_START + 199 * _HOUR + 600, tz=dt.UTC))


def _company(settings: Settings, clock: FrozenClock, responder: Any) -> Runtime:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=responder))
    built.initialise()
    built.staff()
    return built


def _record(company: Runtime, symbol: str, *, base: float = 100.0) -> None:
    with company.database.session() as session:
        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Payload(_bars(200, base=base)), pause=0),
            desk="crypto",
            symbol=symbol,
            bars=200,
        )


# ------------------------------------------------------------ the judge seat


def test_a_judge_that_passed_on_one_market_is_still_offered_the_others(
    settings: Settings, clock: FrozenClock
) -> None:
    responder = _PassesOnBtc()
    company = _company(settings, clock, responder)
    try:
        _record(company, "BTC-USD")
        _record(company, "ETH-USD", base=3000.0)
        assert seat_agent(company, agent_handle="INTEL") is None, "passed on BTC"
        with company.database.session() as session:
            agent = company.roster.by_handle(session, "INTEL").ref
            assert declined_on_standing(session, agent) == frozenset({"BTC-USD"})
            assert agent in {a.ref for a in _seatable(session)[0]}, "ETH is still open to it"
        sealed = seat_agent(company, agent_handle="INTEL")
        assert sealed is not None and sealed.instrument == "ETH-USD"
        assert responder.markets == ["btc-usd", "eth-usd"], "BTC was not offered again"
        _record(company, "BTC-USD")  # a new recording: BTC is new material
        with company.database.session() as session:
            assert declined_on_standing(session, agent) == frozenset()
    finally:
        company.close()


def test_a_judge_that_declined_to_pick_any_market_waits_for_the_next_recording(
    settings: Settings, clock: FrozenClock
) -> None:
    def abstains(request: LlmRequest) -> str:
        if "Which market do you want" in request.messages[-1].content:
            return "ANSWER: nothing\nBECAUSE: none of these has moved enough to call."
        return standins()(request)

    company = _company(settings, clock, abstains)
    try:
        _record(company, "BTC-USD")
        assert seat_agent(company, agent_handle="INTEL") is None
        with company.database.session() as session:
            agent = company.roster.by_handle(session, "INTEL").ref
            assert declined_on_standing(session, agent) == frozenset({ALL_MARKETS})
            assert agent not in {a.ref for a in _seatable(session)[0]}
        _record(company, "ETH-USD")
        with company.database.session() as session:
            assert ALL_MARKETS not in declined_on_standing(session, agent)
    finally:
        company.close()


def test_a_refusal_after_a_market_was_picked_names_the_market(
    settings: Settings, clock: FrozenClock
) -> None:
    def invents(request: LlmRequest) -> str:
        prompt = request.messages[-1].content
        if "State your view on" in prompt:
            return (
                "HORIZON: 24h\nDIRECTION: up\nCONFIDENCE: 0.6\n"
                "THESIS: it will rise 37.25 percent because volume is building.\n"
                "WRONG_IF: it falls below the last close.\n"
            )
        return standins()(request)

    company = _company(settings, clock, invents)
    try:
        _record(company, "BTC-USD")
        with pytest.raises(JudgementRefused) as refused:
            seat_agent(company, agent_handle="INTEL")
        assert refused.value.instrument == "BTC-USD"
        with company.database.session() as session:
            agent = company.roster.by_handle(session, "INTEL").ref
            events = [
                e
                for e in company.ledger.for_subject(session, agent)
                if e.kind == EventKind.THESIS_REFUSED.value
            ]
            assert events[-1].payload["instrument"] == "BTC-USD"
            assert declined_on_standing(session, agent) == frozenset({"BTC-USD"})
    finally:
        company.close()


# ------------------------------------------------------------ the miner


def _events(company: Runtime, kind: str, bars: list[int], key: str = "BTC-USD") -> None:
    with company.database.session() as session:
        for bar in bars:
            company.world.record(
                session,
                kind=kind,
                at=dt.datetime.fromtimestamp(_START + bar * _HOUR, tz=dt.UTC),
                entity_kind="instrument",
                entity_key=key,
                payload={"bar": bar, "kind": kind},
                source="test",
            )


def test_the_miner_counts_every_pair_in_one_pass_and_matches_the_pair_by_pair_count(
    settings: Settings, clock: FrozenClock
) -> None:
    company = _company(settings, clock, standins())
    try:
        _events(company, "price.volume_spike", list(range(0, 120, 3)))
        _events(company, "price.range_break", list(range(1, 120, 5)))
        _events(company, "price.volume_spike", list(range(0, 60, 4)), key="ETH-USD")
        with company.database.session() as session:
            mined = {
                (p.first, p.second): (p.count, p.instruments)
                for p in mine_pairs(session, within=dt.timedelta(hours=24), limit=100)
            }
            for first, second in (
                ("price.volume_spike", "price.range_break"),
                ("price.range_break", "price.volume_spike"),
                ("price.volume_spike", "price.volume_spike"),
            ):
                pairs = World.co_occurrences(
                    session,
                    first_kind=first,
                    second_kind=second,
                    within=dt.timedelta(hours=24),
                    limit=100_000,
                )
                pairs = [p for p in pairs if p.second.digest != p.first.digest]
                assert mined[(first, second)] == (len(pairs), len({p.entity_key for p in pairs}))
    finally:
        company.close()


def test_the_rarest_triggers_come_first_and_each_brings_its_strongest_partners(
    settings: Settings, clock: FrozenClock
) -> None:
    company = _company(settings, clock, standins())
    try:
        _events(company, "price.volume_spike", list(range(0, 190, 2)))
        _events(company, "price.range_break", list(range(1, 190, 3)))
        _events(company, "attention.boost", [20, 80, 140, 170])
        with company.database.session() as session:
            diverse = mine_diverse(session, within=dt.timedelta(hours=24), per_trigger=2)
            by_count = mine_pairs(session, within=dt.timedelta(hours=24), limit=4)
        assert diverse[0].first == "attention.boost", "the rare event is asked about first"
        assert {p.first for p in diverse} == {
            "attention.boost",
            "price.range_break",
            "price.volume_spike",
        }
        assert sum(1 for p in diverse if p.first == "attention.boost") == 2
        assert all(p.first != "attention.boost" for p in by_count), "count alone buries it"
    finally:
        company.close()


def test_a_single_social_post_is_a_reading_and_a_burst_of_them_is_an_event() -> None:
    assert is_reading("social.post")
    assert not is_reading("social.burst") and not is_reading("attention.boost")


# ------------------------------------------------------------ asking again


def test_a_pattern_is_put_to_the_same_agent_again_only_on_materially_more_evidence(
    settings: Settings, clock: FrozenClock
) -> None:
    company = _company(settings, clock, standins())
    try:
        with company.database.session() as session:
            agent = company.roster.by_handle(session, "QUANT").ref
            company.ledger.append(
                session,
                kind=EventKind.MECHANISM_DECLINED,
                actor=agent,
                subject=agent,
                payload={
                    "trigger": "attention.boost",
                    "then": "price.range_break",
                    "because": "too few to tell a boost from the noise.",
                    "occurrences": 10,
                },
                at=clock.now(),
            )
        _events(company, "price.volume_spike", [5])  # a newer event, as every wake has
        with company.database.session() as session:
            answered = _last_word_on_pattern(
                session, agent, "attention.boost", "price.range_break", 12
            )
            reopened = _last_word_on_pattern(
                session, agent, "attention.boost", "price.range_break", int(10 * REASK_GROWTH)
            )
        assert answered, "twelve is not materially more than ten"
        assert not reopened, "fifteen is: the pattern is asked again"
    finally:
        company.close()


# ------------------------------------------------------------ the wake's share


def test_a_wake_spends_at_most_its_share_of_the_days_model_calls(
    settings: Settings, clock: FrozenClock
) -> None:
    company = _company(settings, clock, standins())
    try:
        _record(company, "BTC-USD")
        _record(company, "ETH-USD", base=3000.0)
        wake = cycle_once(
            company,
            service=Service(company, calls_per_day=1000, calls_per_wake=6, cycles_per_wake=50),
        )
        assert 0 < wake.calls <= 6, wake.note
    finally:
        company.close()


def test_a_mechanisms_predictions_do_not_block_its_author_from_its_own_view(
    settings: Settings, clock: FrozenClock
) -> None:
    from decimal import Decimal

    from aurelis.mechanism.predictions import generate_predictions

    company = _company(settings, clock, standins())
    try:
        _record(company, "BTC-USD")
        _events(company, "price.range_break", [196, 197, 198])
        with company.database.session() as session:
            author = company.roster.by_handle(session, "INTEL").ref
            mechanism = company.mechanisms.state(
                session,
                agent_ref=author,
                title="a new high draws buyers",
                trigger_kind="price.range_break",
                desk="crypto",
                horizon_hours=6,
                direction="up",
                confidence=Decimal("0.6"),
                why="a new high draws in the momentum buyers who were waiting for it.",
                other_side="the shorts who sold the old high and now cover.",
                decay="it fades as the crowd learns to buy the high, within months.",
                origin="invented",
                found_on_instrument="BTC-USD",
                found_on_event="none",
                model="test",
            )
            run = generate_predictions(session, mechanism, clock=company.clock)
            assert run.sealed, "the mechanism holds open predictions on BTC in INTEL's name"
            assert author in {a.ref for a in _seatable(session)[0]}
        sealed = seat_agent(company, agent_handle="INTEL")
        assert sealed is not None and sealed.instrument == "BTC-USD"
    finally:
        company.close()
