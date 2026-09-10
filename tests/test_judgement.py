"""M25 — an agent picks its own market, states a view, and is scored on it.

The acceptance criteria, each with a test named after it:

* the agent chooses the market; nothing is assigned,
* a view is sealed before the outcome exists, and a horizon that has already
  passed is refused,
* a sealed view cannot be edited, rescored or deleted — enforced by the
  database, not by convention,
* a view is scored once, mechanically, against a recording, when its horizon
  expires; until a recording covers it, it is pending,
* calibration is read off the record, stated against observed, by band,
* a thesis citing a figure the agent was not shown seals nothing; an
  unreadable reply seals nothing; declining is legitimate and recorded,
* views on fixtures are kept apart from the mandate,
* the loop seats judges until every recorded market has a view, then stops
  and says why,
* the forward record is legible on the station.

**Nothing here touches the network.** Recordings come from a recorded vendor
payload or a desk fixture, and every model call is answered by a script.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aurelis.autonomy.loop import run_autonomy
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.intel.fixturefeed import FixtureFeed
from aurelis.intel.live import CoinbaseCandles
from aurelis.judgement.calibration import (
    COIN_TOSS,
    agent_calibration,
    calibration_over,
    company_calibration,
)
from aurelis.judgement.resolution import resolve_due
from aurelis.judgement.seat import (
    JudgementRefused,
    parse_view,
    resolvable,
    seat_agent,
    verify_seal,
)
from aurelis.judgement.standin import scripted_judge
from aurelis.judgement.tables import Thesis
from aurelis.mandate.assessment import assess
from aurelis.mandate.standard import STANDARD
from aurelis.org.desks import Desk
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.platform.llm.types import LlmRequest
from aurelis.runtime import Runtime

_HOUR = 3600
_START = 1_780_000_000


# ------------------------------------------------------------------ fixtures


class _Recorded:
    """A recorded vendor response: [time, low, high, open, close, volume]."""

    def __init__(self, closes: list[Decimal], *, start: int = _START) -> None:
        rows = [
            [start + i * _HOUR, float(c) - 1, float(c) + 1, float(c), float(c), 5.0]
            for i, c in enumerate(closes)
        ]
        self._payload = json.dumps(list(reversed(rows))).encode()

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        return io.BytesIO(self._payload)


def _closes(count: int, *, base: int = 100, step: int = 1) -> list[Decimal]:
    return [Decimal(base + i * step) for i in range(count)]


def _clock_after(count: int) -> FrozenClock:
    """A clock a few minutes after the last recorded bar opened."""
    return FrozenClock(dt.datetime.fromtimestamp(_START + (count - 1) * _HOUR + 600, tz=dt.UTC))


@pytest.fixture
def clock() -> FrozenClock:
    return _clock_after(200)


@pytest.fixture
def company(settings: Settings, clock: FrozenClock) -> Any:
    """Staffed, with two recorded markets and a scripted judge in every seat."""
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=standins()))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(_closes(200)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=200,
        )
        built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(_closes(200, base=3000, step=-2)), pause=0),
            desk="crypto",
            symbol="ETH-USD",
            bars=200,
        )
    try:
        yield built
    finally:
        built.close()


def _theses(company: Runtime) -> list[Thesis]:
    with company.database.session() as session:
        return list(session.execute(sa.select(Thesis).order_by(Thesis.ref)).scalars())


# ------------------------------------------------ the agent chooses the market


def test_the_agent_chooses_the_market_and_nothing_is_assigned(
    settings: Settings, clock: FrozenClock
) -> None:
    """Two agents, the same two markets on offer, different choices — because
    the choice is the agent's, not a desk assignment."""

    def picky(request: LlmRequest) -> str:
        prompt = request.messages[-1].content
        if "Which market do you want" in prompt:
            wants = "eth-usd" if request.actor == "AG-0004" else "btc-usd"
            return f"ANSWER: {wants}\nBECAUSE: it is the market I want to state a view on."
        return scripted_judge(request)

    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=picky))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        for symbol, closes in (
            ("BTC-USD", _closes(200)),
            ("ETH-USD", _closes(200, base=3000, step=-2)),
        ):
            built.snapshots.ingest(
                session,
                CoinbaseCandles(opener=_Recorded(closes), pause=0),
                desk="crypto",
                symbol=symbol,
                bars=200,
            )
        offered = {r.snapshot.symbol for r in resolvable(session)}
    assert offered == {"BTC-USD", "ETH-USD"}

    first = seat_agent(built, agent_handle="INTEL")
    second = seat_agent(built, agent_handle="QUANT")
    built.close()
    assert first is not None and second is not None
    assert {first.instrument, second.instrument} == {"BTC-USD", "ETH-USD"}
    assert first.agent_ref != second.agent_ref


def test_a_second_view_on_the_same_market_is_not_offered_while_the_first_is_open(
    company: Runtime,
) -> None:
    """The same bet placed twice would count twice in the calibration."""
    first = seat_agent(company, agent_handle="INTEL")
    second = seat_agent(company, agent_handle="INTEL")
    assert first is not None and second is not None
    assert first.instrument != second.instrument
    with pytest.raises(JudgementRefused, match="already hold"):
        seat_agent(company, agent_handle="INTEL")


# ------------------------------------------------ sealed before the outcome exists


def test_a_view_is_sealed_before_the_outcome_exists(company: Runtime) -> None:
    sealed = seat_agent(company, agent_handle="INTEL")
    assert sealed is not None
    assert sealed.resolves_at > sealed.sealed_at
    assert sealed.reference_at < sealed.sealed_at, "the reference is what the agent was shown"
    rows = _theses(company)
    assert len(rows) == 1
    assert verify_seal(rows[0])
    assert rows[0].outcome is None and rows[0].brier is None and rows[0].scored_at is None
    assert len(rows[0].material_digest) == 64, "what the agent saw is an artifact"


def test_a_view_whose_horizon_has_already_passed_is_refused(
    settings: Settings,
) -> None:
    """The one way a forward prediction quietly becomes a backward one: a
    stale recording. The stand-in asks for 24h; the clock is two days on."""
    stale = FrozenClock(dt.datetime.fromtimestamp(_START + 200 * _HOUR + 48 * _HOUR, tz=dt.UTC))
    built = Runtime.build(settings, clock=stale, provider=MockProvider(responder=scripted_judge))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(_closes(200)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=200,
        )
    with pytest.raises(JudgementRefused, match="already passed"):
        seat_agent(built, agent_handle="INTEL")
    assert _theses(built) == [], "nothing was sealed"
    with built.database.session() as session:
        refused = session.execute(
            sa.text("SELECT count(*) FROM events WHERE kind = 'judgement.thesis_refused'")
        ).scalar_one()
    built.close()
    assert refused == 1, "the refusal is on the record"


# ------------------------------------------------ the seal is enforced by the database


def test_a_sealed_thesis_cannot_be_edited_rescored_or_deleted(company: Runtime) -> None:
    sealed = seat_agent(company, agent_handle="INTEL")
    assert sealed is not None

    with (
        company.database.session() as session,
        pytest.raises(IntegrityError, match="cannot be changed"),
    ):
        session.execute(
            sa.text("UPDATE theses SET confidence = '0.99000000' WHERE ref = :ref"),
            {"ref": sealed.ref},
        )
    with (
        company.database.session() as session,
        pytest.raises(IntegrityError, match="never deleted"),
    ):
        session.execute(sa.text("DELETE FROM theses WHERE ref = :ref"), {"ref": sealed.ref})

    # Score it, then try to score it again.
    company.clock.advance(hours=25)
    with company.database.session() as session:
        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(_closes(230)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=230,
        )
        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(_closes(230, base=3000, step=-2)), pause=0),
            desk="crypto",
            symbol="ETH-USD",
            bars=230,
        )
        scored = [
            r for r in resolve_due(session, ledger=company.ledger, clock=company.clock) if r.scored
        ]
    assert scored, "the horizon passed and a recording covers it"
    with (
        company.database.session() as session,
        pytest.raises(IntegrityError, match="already been scored"),
    ):
        session.execute(
            sa.text("UPDATE theses SET outcome = 0, brier = '1.0' WHERE ref = :ref"),
            {"ref": sealed.ref},
        )
    assert verify_seal(_theses(company)[0]), "scoring did not touch the sealed fields"


# ------------------------------------------------ scored once, mechanically


def test_a_view_is_scored_once_against_a_recording_when_its_horizon_expires(
    company: Runtime,
) -> None:
    """BTC-USD rises one a bar; the stand-in says up at 24h. Resolution reads
    the close of the bar that opened at the horizon and settles it."""
    sealed = seat_agent(company, agent_handle="INTEL")
    assert sealed is not None and sealed.instrument == "BTC-USD"
    assert sealed.direction == "up"

    with company.database.session() as session:
        assert resolve_due(session, ledger=company.ledger, clock=company.clock) == [], (
            "nothing is due while the horizon lies ahead"
        )

    company.clock.advance(hours=25)
    with company.database.session() as session:
        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(_closes(230)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=230,
        )
        results = resolve_due(session, ledger=company.ledger, clock=company.clock)

    hit = next(r for r in results if r.ref == sealed.ref)
    assert hit.scored and hit.outcome is True and hit.hit is True
    expected = ((sealed.confidence - 1) ** 2).quantize(Decimal("0.0001"))
    assert hit.brier == expected

    row = next(t for t in _theses(company) if t.ref == sealed.ref)
    assert Decimal(row.resolution_close or 0) == Decimal(sealed.reference_close) + 24
    assert row.resolution_at == sealed.resolves_at
    assert row.scored_against is not None and row.scored_against.startswith("SNP-")

    with company.database.session() as session:
        again = resolve_due(session, ledger=company.ledger, clock=company.clock)
        events = session.execute(
            sa.text("SELECT count(*) FROM events WHERE kind = 'judgement.thesis_scored'")
        ).scalar_one()
    assert all(r.ref != sealed.ref for r in again), "scored once"
    assert events == 1


def test_a_due_view_is_pending_until_a_recording_covers_it(company: Runtime) -> None:
    sealed = seat_agent(company, agent_handle="INTEL")
    assert sealed is not None
    company.clock.advance(hours=48)
    with company.database.session() as session:
        results = resolve_due(session, ledger=company.ledger, clock=company.clock)
    pending = next(r for r in results if r.ref == sealed.ref)
    assert not pending.scored
    assert "no recording" in pending.detail
    assert _theses(company)[0].outcome is None


def test_a_tie_is_not_above(company: Runtime) -> None:
    """Strictly above: a close equal to the reference settles ``up`` as wrong."""
    sealed = seat_agent(company, agent_handle="INTEL")
    assert sealed is not None and sealed.direction == "up"
    company.clock.advance(hours=25)
    flat = [Decimal(sealed.reference_close)] * 230
    with company.database.session() as session:
        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(flat), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=230,
        )
        results = resolve_due(session, ledger=company.ledger, clock=company.clock)
    settled = next(r for r in results if r.ref == sealed.ref)
    assert settled.scored and settled.outcome is False and settled.hit is False


# ------------------------------------------------ calibration


def _thesis(confidence: str, direction: str, outcome: bool, *, live: bool = True) -> Thesis:
    conf = Decimal(confidence)
    return Thesis(
        agent_ref="AG-0001",
        instrument="BTC-USD",
        is_live=live,
        direction=direction,
        confidence=conf,
        probability_up=conf if direction == "up" else 1 - conf,
        outcome=outcome,
        brier=((conf if direction == "up" else 1 - conf) - (1 if outcome else 0)) ** 2,
        scored_at=dt.datetime(2026, 9, 4, tzinfo=dt.UTC),
        horizon_hours=24,
    )


def test_calibration_reads_stated_against_observed_by_band() -> None:
    """Ten views at 0.7, seven right: calibrated. Ten at 0.9, five right:
    over-confident, and the band says by how much."""
    rows = [_thesis("0.7", "up", i < 7) for i in range(10)]
    rows += [_thesis("0.9", "up", i < 5) for i in range(10)]
    record = calibration_over("test", rows)

    assert record.scored == 20 and record.hits == 12
    assert record.hit_rate == Decimal("0.6")
    seventy = next(b for b in record.bands if b.low == Decimal("0.7"))
    ninety = next(b for b in record.bands if b.low == Decimal("0.9"))
    assert seventy.stated == Decimal("0.7") and seventy.observed == Decimal("0.7")
    assert seventy.gap == Decimal("0")
    assert ninety.observed == Decimal("0.5") and ninety.gap == Decimal("0.4")
    assert record.mean_brier is not None
    assert record.base_rate_brier is not None and record.up_frequency == Decimal("0.6")


def test_a_record_that_only_knows_the_drift_does_not_beat_the_base_rate() -> None:
    """Always 'up at 0.7' on a market that went up 70% of the time is exactly
    the base rate: informative against a coin, uninformative against the
    market."""
    rows = [_thesis("0.7", "up", i < 7) for i in range(10)]
    record = calibration_over("drift", rows)
    assert record.informative, "beats always saying 50%"
    assert record.mean_brier == record.base_rate_brier
    assert not record.beats_base_rate


def test_an_empty_record_is_reported_as_nothing_scored_not_as_a_score() -> None:
    record = calibration_over("fresh", [])
    assert record.mean_brier is None and record.hit_rate is None
    assert not record.informative
    assert "none scored" in record.describe()


def test_calibration_is_cut_by_agent_market_and_horizon(company: Runtime) -> None:
    seat_agent(company, agent_handle="INTEL")
    seat_agent(company, agent_handle="QUANT")
    with company.database.session() as session:
        report = company_calibration(session)
        mine = agent_calibration(session, _theses(company)[0].agent_ref)
    assert report["overall"][0].sealed == 2
    assert {r.label for r in report["by_agent"]} == {t.agent_ref for t in _theses(company)}
    assert {r.label for r in report["by_horizon"]} == {"24h"}
    assert mine.sealed == 1 and mine.scored == 0 and mine.pending == 1
    assert Decimal("0.25") == COIN_TOSS


# ------------------------------------------------ the refusals


def test_a_thesis_citing_a_figure_it_was_not_shown_seals_nothing(
    settings: Settings, clock: FrozenClock
) -> None:
    def inventor(request: LlmRequest) -> str:
        prompt = request.messages[-1].content
        if "State your view on" in prompt:
            return (
                "HORIZON: 24h\nDIRECTION: up\nCONFIDENCE: 0.8\n"
                "THESIS: funding is at 0.0432 and open interest rose 17.5% overnight.\n"
                "WRONG_IF: funding flips.\n"
            )
        return scripted_judge(request)

    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=inventor))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(_closes(200)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=200,
        )
    with pytest.raises(JudgementRefused, match="not shown"):
        seat_agent(built, agent_handle="INTEL")
    assert _theses(built) == []
    built.close()


def test_an_unreadable_reply_seals_nothing(settings: Settings, clock: FrozenClock) -> None:
    def rambler(request: LlmRequest) -> str:
        prompt = request.messages[-1].content
        if "State your view on" in prompt:
            return "I think it probably goes up, maybe 70% sure, over a day or so."
        return scripted_judge(request)

    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=rambler))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(_closes(200)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=200,
        )
    with pytest.raises(JudgementRefused, match="direction"):
        seat_agent(built, agent_handle="INTEL")
    assert _theses(built) == []
    built.close()


def test_declining_is_legitimate_and_recorded(settings: Settings, clock: FrozenClock) -> None:
    def abstainer(request: LlmRequest) -> str:
        if "Which market do you want" in request.messages[-1].content:
            return "ANSWER: nothing\nBECAUSE: I have no view on either."
        return scripted_judge(request)

    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=abstainer))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(_closes(200)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=200,
        )
    assert seat_agent(built, agent_handle="INTEL") is None
    assert _theses(built) == []
    with built.database.session() as session:
        declined = session.execute(
            sa.text("SELECT count(*) FROM events WHERE kind = 'judgement.thesis_declined'")
        ).scalar_one()
    built.close()
    assert declined == 1


def test_the_seat_refuses_when_nothing_can_be_resolved(
    settings: Settings, clock: FrozenClock
) -> None:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=scripted_judge))
    built.initialise()
    built.staff()
    with pytest.raises(JudgementRefused, match="nothing can be resolved"):
        seat_agent(built, agent_handle="INTEL")
    built.close()


@pytest.mark.parametrize(
    ("reply", "stage"),
    [
        (
            "HORIZON: 24h\nDIRECTION: up\nCONFIDENCE: 0.5\nTHESIS: "
            + "x" * 30
            + "\nWRONG_IF: "
            + "y" * 20,
            "confidence",
        ),
        (
            "HORIZON: 24h\nDIRECTION: up\nCONFIDENCE: 1.2\nTHESIS: "
            + "x" * 30
            + "\nWRONG_IF: "
            + "y" * 20,
            "confidence",
        ),
        (
            "HORIZON: 2h\nDIRECTION: up\nCONFIDENCE: 0.7\nTHESIS: "
            + "x" * 30
            + "\nWRONG_IF: "
            + "y" * 20,
            "horizon",
        ),
        (
            "HORIZON: 24h\nDIRECTION: up\nCONFIDENCE: 0.7\nTHESIS: short\nWRONG_IF: " + "y" * 20,
            "thesis",
        ),
        (
            "HORIZON: 24h\nDIRECTION: up\nCONFIDENCE: 0.7\nTHESIS: " + "x" * 30 + "\nWRONG_IF: no",
            "wrong_if",
        ),
    ],
)
def test_the_reply_form_is_parsed_not_interpreted(reply: str, stage: str) -> None:
    with pytest.raises(JudgementRefused) as caught:
        parse_view(reply)
    assert caught.value.stage == stage


def test_a_confidence_given_in_percent_is_read_as_a_probability() -> None:
    view = parse_view(
        "HORIZON: 6h\nDIRECTION: down\nCONFIDENCE: 65%\nTHESIS: "
        + "x" * 30
        + "\nWRONG_IF: "
        + "y" * 20
    )
    assert view.confidence == Decimal("0.65")
    assert view.probability_up == Decimal("0.35")
    assert view.hours == 6


# ------------------------------------------------ fixtures are kept apart


def test_views_on_fixtures_do_not_count_toward_the_mandate(settings: Settings) -> None:
    """A fixture is a random walk. Being calibrated on it is being calibrated
    on nothing, and the standard reads market rows only."""
    clock = FrozenClock(dt.datetime(2026, 9, 4, 9, 0, tzinfo=dt.UTC))
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=scripted_judge))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        built.snapshots.ingest(
            session,
            FixtureFeed(Desk.CRYPTO, clock=clock),
            desk="crypto",
            symbol="BTC/USDT",
            bars=300,
            is_live=False,
        )
    sealed = seat_agent(built, agent_handle="INTEL")
    assert sealed is not None and not sealed.is_live

    outcome = assess(built)
    finding = next(f for f in outcome.findings if f.criterion.key == "calibrated")
    assert not finding.met
    assert "0 view(s) sealed on market data" in finding.reading
    assert "1 more on fixtures, not counted" in finding.reading
    with built.database.session() as session:
        assert agent_calibration(session, sealed.agent_ref).sealed == 0
        assert agent_calibration(session, sealed.agent_ref, live_only=False).sealed == 1
    built.close()


def test_the_standard_has_eleven_conditions_and_calibrated_is_second() -> None:
    assert len(STANDARD) == 11
    assert STANDARD[1].key == "calibrated"


def test_the_fixture_feed_lays_its_bars_against_the_clock() -> None:
    clock = FrozenClock(dt.datetime(2026, 9, 4, 9, 30, tzinfo=dt.UTC))
    bars = FixtureFeed(Desk.CRYPTO, clock=clock).candles("BTC/USDT", interval="1h", bars=10)
    assert len(bars) == 10
    assert bars[-1].timestamp == dt.datetime(2026, 9, 4, 8, 0, tzinfo=dt.UTC)
    assert bars[0].timestamp == dt.datetime(2026, 9, 3, 23, 0, tzinfo=dt.UTC)


# ------------------------------------------------ the loop


def test_the_loop_seats_judges_until_every_market_has_a_view_then_says_why(
    company: Runtime,
) -> None:
    """Every judging agent, two recorded markets: one view each per market,
    then a stop whose reason is that a forward record cannot be hurried."""
    with company.database.session() as session:
        judges = session.execute(
            sa.text(
                "SELECT count(*) FROM agents WHERE state IN ('active','working') "
                "AND department IN ('market_intelligence','quantitative_research',"
                "'strategy_laboratory')"
            )
        ).scalar_one()
    expected = judges * 2  # two recorded markets

    outcome = run_autonomy(company, cycles=expected + 4, calls=(expected + 4) * 2)
    judged = [c for c in outcome.acted if c.action == "judge"]
    assert len(judged) == expected, [c.describe() for c in outcome.cycles]
    assert all(c.outcome == "acted" for c in judged)
    assert len(_theses(company)) == expected
    assert outcome.cycles[-1].action is None, "it stopped rather than ran out of cycles"
    assert "waiting" in outcome.stuck["calibrated"]
    assert "fetches nothing" in outcome.stuck["calibrated"]

    again = run_autonomy(company, cycles=8, calls=40)
    assert "judge" not in {c.action for c in again.acted}, "the same bet is not placed twice"


def test_one_agents_refusal_does_not_stop_the_others_being_seated(
    settings: Settings, clock: FrozenClock
) -> None:
    """The first live wake of the service: one agent cited a rounded figure,
    the seat refused it, and the loop marked the whole judge action failed and
    stopped seating the other five. A refusal is one agent's reply."""
    from aurelis.agents.tables import Agent

    def one_liar(request: LlmRequest) -> str:
        prompt = request.messages[-1].content
        if "State your view on" in prompt and request.actor == "AG-0004":
            return (
                "HORIZON: 24h\nDIRECTION: up\nCONFIDENCE: 0.8\n"
                "THESIS: it is at roughly 2467 and rising, which is enough.\n"
                "WRONG_IF: it stops rising."
            )
        return standins()(request)

    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=one_liar))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(_closes(200)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=200,
        )
        judges = session.execute(
            sa.select(sa.func.count())
            .select_from(Agent)
            .where(
                Agent.department.in_(
                    ("market_intelligence", "quantitative_research", "strategy_laboratory")
                )
            )
        ).scalar_one()
    outcome = run_autonomy(built, cycles=judges + 3, calls=(judges + 3) * 2)
    outcomes = [c.outcome for c in outcome.cycles if c.action == "judge"]
    assert outcomes.count("refused") == 1, [c.describe() for c in outcome.cycles]
    assert "failed" not in outcomes
    assert len(_theses(built)) == judges - 1, "every other judge was seated"
    assert "refused" in outcome.stuck["calibrated"], "the refusal is part of the stop reason"

    # And the refused agent is not asked again on the same recordings; a new
    # recording makes it seatable again.
    again = run_autonomy(built, cycles=4, calls=8)
    assert "judge" not in {c.action for c in again.acted}
    with built.database.session() as session:
        built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(_closes(200)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=200,
        )
    fresh = run_autonomy(built, cycles=4, calls=8)
    assert [c.outcome for c in fresh.cycles if c.action == "judge"] == ["refused"]
    built.close()


def test_the_loop_settles_what_a_recording_covers_before_seating_anyone(
    company: Runtime,
) -> None:
    sealed = seat_agent(company, agent_handle="INTEL")
    assert sealed is not None
    company.clock.advance(hours=25)
    with company.database.session() as session:
        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(_closes(230)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=230,
        )
    outcome = run_autonomy(company, cycles=1, calls=10)
    first = outcome.cycles[0]
    assert first.action == "judge"
    assert first.detail.startswith("1 view(s) scored from recordings")
    assert next(t for t in _theses(company) if t.ref == sealed.ref).scored_at is not None


# ------------------------------------------------ the station


def test_the_forward_record_is_legible_on_the_station(company: Runtime) -> None:
    from aurelis.station.app import station_app
    from aurelis.station.build import build_sealed

    sealed = seat_agent(company, agent_handle="INTEL")
    assert sealed is not None
    company.clock.advance(hours=25)
    with company.database.session() as session:
        company.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(_closes(230)), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=230,
        )
        resolve_due(session, ledger=company.ledger, clock=company.clock)

    app = station_app(company)
    theses = app.handle("/theses", {}).body.decode()
    assert sealed.ref in theses and "RIGHT" in theses
    one = app.handle(f"/thesis/{sealed.ref}", {}).body.decode()
    assert "VERIFIES" in one and sealed.thesis[:40] in one
    agent = app.handle(f"/agent/{sealed.agent_ref}", {}).body.decode()
    assert "Forward record" in agent
    front = app.handle("/", {}).body.decode()
    assert "VIEWS SCORED" in front

    html = build_sealed(company, company.settings.workspace / "station.html").path.read_text(
        encoding="utf-8"
    )
    assert sealed.ref in html


def test_the_judge_seat_is_answered_by_the_stand_in_only_offline(settings: Settings) -> None:
    from aurelis.platform.llm.seating import seat_provider

    assert seat_provider(settings, scripted_judge) is not None
    live = settings.model_copy(update={"provider": "agent_sdk"})
    assert seat_provider(live, scripted_judge) is None
