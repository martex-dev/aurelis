"""M64 — the agents work together: they ask each other for help, and huddle.

The acceptance criteria, each with a test named after it:

* an agent stating a view may ask one colleague one question first; the
  question and the answer are real messages, and the answer reaches the agent
  before it decides,
* an answer is an opinion: a figure that appears only in it cannot be cited,
* an agent that does not ask states its view exactly as before,
* two agents holding opposite open views on one market are huddled: each
  makes its case, answers the other and revises, and a moderator who holds
  neither view writes the company's position and a brain note,
* a huddle changes no sealed view, and none is held twice on one market in a
  day or beyond the call budget,
* whether talking helps is measured: before against after, once the views
  resolve.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.collab.consult import parse_ask
from aurelis.collab.huddle import CALLS, disagreements, hold_huddles, huddle_record
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.intel.live import CoinbaseCandles
from aurelis.judgement.resolution import resolve_due
from aurelis.judgement.seat import seat_agent
from aurelis.judgement.standin import scripted_judge
from aurelis.judgement.tables import Thesis
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.platform.llm.types import LlmRequest
from aurelis.runtime import Runtime

_HOUR = 3600
_START = 1_780_000_000


class _Recorded:
    def __init__(self, count: int) -> None:
        rows = [
            [_START + i * _HOUR, 99.0 + i, 101.0 + i, 100.0 + i, 100.0 + i, 5.0]
            for i in range(count)
        ]
        self._payload = json.dumps(list(reversed(rows))).encode()

    def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
        return io.BytesIO(self._payload)


def _view(direction: str) -> str:
    return (
        "HORIZON: 24h\n"
        f"DIRECTION: {direction}\n"
        "CONFIDENCE: 0.6\n"
        f"THESIS: The recent run says {direction} to me.\n"
        "WRONG_IF: the run reverses."
    )


class _Room:
    """Every seat scripted; INTEL says up, QUANT says down, INTEL may ask first."""

    def __init__(self, *, intel_asks: bool = False) -> None:
        self.intel_asks = intel_asks
        self.prompts: list[str] = []
        self.inner = standins()

    def __call__(self, request: LlmRequest) -> str:
        prompt = request.messages[-1].content
        self.prompts.append(prompt)
        if "State your view on" in prompt:
            handle = self.handle_of.get(request.actor, "")
            if handle == "INTEL" and self.intel_asks and "You asked" not in prompt:
                return "ASK: QUANT: Is there any news on BTC that I should weigh?"
            if handle == "INTEL":
                return _view("up")
            if handle == "QUANT":
                return _view("down")
        if "Which market do you want" in prompt or "Attack this view" in prompt:
            return scripted_judge(request)
        if "Respond to the attack" in prompt:
            return scripted_judge(request)
        return self.inner(request)

    handle_of: dict[str, str] = {}


def _company(settings: Settings, room: _Room) -> Runtime:
    clock = FrozenClock(dt.datetime.fromtimestamp(_START + 199 * _HOUR + 600, tz=dt.UTC))
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=room))
    built.initialise()
    built.staff()
    with built.database.session() as session:
        built.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(200), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=200,
        )
        room.handle_of = {
            str(built.roster.by_handle(session, h).ref): h for h in ("INTEL", "QUANT")
        }
    return built


def _count(company: Runtime, sql: str) -> int:
    with company.database.session() as session:
        return int(session.execute(sa.text(sql)).scalar_one())


# ------------------------------------------------------------ asking for help


def test_a_reply_is_read_as_a_request_for_help_only_when_it_is_one() -> None:
    handles = {"QUANT", "INTEL"}
    assert parse_ask("ASK: quant: any news on BTC?", handles) == ("QUANT", "any news on BTC?")
    assert parse_ask("ASK: GHOST: anyone?", handles) is None
    assert parse_ask("DIRECTION: up\nASK: QUANT: and?", handles) is None, "an answer, not a request"


def test_an_agent_asks_a_colleague_before_it_states_its_view(settings: Settings) -> None:
    room = _Room(intel_asks=True)
    company = _company(settings, room)
    try:
        sealed = seat_agent(company, agent_handle="INTEL")
        assert sealed is not None and sealed.direction == "up"
        second = [p for p in room.prompts if "You asked QUANT" in p]
        assert second, "the agent was asked again, with the answer"
        assert "my record is no better than a coin toss" in second[0], "QUANT's own answer"
        assert "do not cite a figure that appears only here" in second[0]
        assert any("A colleague asks you:" in p for p in room.prompts), "QUANT was seated"
        with company.database.session() as session:
            kinds = list(session.execute(sa.text("SELECT kind FROM messages")).scalars())
        assert sorted(kinds) == ["answer", "question"], "real messages, both ways"
        assert _count(company, "SELECT count(*) FROM events WHERE kind = 'agent.consulted'") == 1
    finally:
        company.close()


def test_an_agent_that_does_not_ask_states_its_view_as_before(settings: Settings) -> None:
    room = _Room()
    company = _company(settings, room)
    try:
        sealed = seat_agent(company, agent_handle="INTEL")
        assert sealed is not None
        assert any("You may ask ONE colleague ONE question" in p for p in room.prompts)
        assert _count(company, "SELECT count(*) FROM events WHERE kind = 'agent.consulted'") == 0
        assert _count(company, "SELECT count(*) FROM messages") == 0
    finally:
        company.close()


# ------------------------------------------------------------ huddles


@pytest.fixture
def split(settings: Settings) -> Any:
    """INTEL has sealed up and QUANT has sealed down, on BTC-USD."""
    company = _company(settings, _Room())
    seat_agent(company, agent_handle="INTEL")
    seat_agent(company, agent_handle="QUANT")
    try:
        yield company
    finally:
        company.close()


def test_two_agents_who_disagree_are_huddled_and_the_company_takes_a_position(
    split: Runtime,
) -> None:
    with split.database.session() as session:
        found = disagreements(session, split.clock.now())
        seals_before = dict(session.execute(sa.select(Thesis.ref, Thesis.seal)).all())
    assert [d.instrument for d in found] == ["BTC-USD"]
    held = hold_huddles(split, at=split.clock.now(), calls_left=50)
    assert len(held) == 1
    with split.database.session() as session:
        meeting = session.execute(
            sa.text("SELECT type, status, productive, state_changes, chair FROM meetings")
        ).one()
        turns = list(
            session.execute(sa.text("SELECT phase, speaker FROM meeting_turns ORDER BY seq")).all()
        )
        decision = session.execute(
            sa.text("SELECT outcome, supporting FROM decisions WHERE meeting_ref = :r"),
            {"r": held[0]},
        ).one()
        seals_after = dict(session.execute(sa.select(Thesis.ref, Thesis.seal)).all())
        notes = list(
            session.execute(
                sa.text("SELECT text FROM brain_notes WHERE source_ref = :s"),
                {"s": f"huddle {held[0]}"},
            ).scalars()
        )
        critic = split.roster.by_handle(session, "CRITIC").ref
    assert meeting[0] == "huddle" and meeting[1] == "closed" and meeting[2]
    assert meeting[4] == critic, "a moderator who holds neither view"
    assert [phase for phase, _ in turns] == [
        "opening",
        "opening",
        "exchange",
        "exchange",
        "synthesis",
    ]
    assert decision[0] == "none"
    supporting = json.loads(decision[1]) if isinstance(decision[1], str) else decision[1]
    assert {e["after_up"] for e in supporting} == {"0.55"}
    assert {Decimal(e["before_up"]) for e in supporting} == {Decimal("0.6"), Decimal("0.4")}
    assert notes, "the position became a note every agent reads"
    assert seals_after == seals_before, "a huddle changes no sealed view"


def test_no_second_huddle_on_one_market_in_a_day_or_beyond_the_budget(split: Runtime) -> None:
    assert hold_huddles(split, at=split.clock.now(), calls_left=CALLS - 1) == []
    assert len(hold_huddles(split, at=split.clock.now(), calls_left=50)) == 1
    assert hold_huddles(split, at=split.clock.now(), calls_left=50) == []


def test_whether_talking_helps_is_measured_before_against_after(split: Runtime) -> None:
    hold_huddles(split, at=split.clock.now(), calls_left=50)
    with split.database.session() as session:
        early = huddle_record(session)
    assert early.held == 1 and early.resolved == 0
    assert "too few" in early.verdict()

    split.clock.advance(hours=25)
    with split.database.session() as session:
        split.snapshots.ingest(
            session,
            CoinbaseCandles(opener=_Recorded(230), pause=0),
            desk="crypto",
            symbol="BTC-USD",
            bars=230,
        )
        resolve_due(session, ledger=split.ledger, clock=split.clock)
        record = huddle_record(session)
    # BTC went up. INTEL said up at 0.6 and QUANT down (0.4 up); both said 0.55 after.
    assert record.resolved == 2
    assert record.brier_before == Decimal("0.2600")  # (0.16 + 0.36) / 2
    assert record.brier_after == Decimal("0.2025")


def test_the_control_room_shows_who_worked_with_whom(split: Runtime) -> None:
    from aurelis.station.app import station_app

    held = hold_huddles(split, at=split.clock.now(), calls_left=50)
    room = station_app(split).handle("/office/room/control", {}).body.decode()
    assert "data-tab='together'" in room and held[0] in room
    assert "does talking help?" in room
