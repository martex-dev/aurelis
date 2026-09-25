"""M48 — the company evolves how its agents think, on the forward record.

The acceptance criteria, each with a test named after it:

* a method's fitness is the Brier of the views sealed under it, against a
  coin toss, with a standard error, and is unproven under twenty views,
* a failing method is replaced by one the best-calibrated colleague writes,
  and the new method records the fitness it has to beat,
* with no colleague better than chance, the failing agent revises its own,
* an unreadable reply adopts nothing and says so,
* a method only counts the views sealed since it was adopted,
* an agent's method is part of its identity at every seat,
* the wake runs evolution at most once a day and says so,
* a method is append-only,
* a ref is a name and not a figure, and a figure an agent was shown in its
  system prompt -- the brain, its notes, its method -- is sourced. Before
  this, six of seven live judges were refused at the market stage for citing
  ``MEC-0001`` and the brain's own numbers.

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

from aurelis.agents.decide import Choice, Question, decide_as
from aurelis.agents.interpret import UnsourcedFigures, allowed_figures, unsourced_numerals
from aurelis.core.clock import FrozenClock
from aurelis.core.config import Settings
from aurelis.core.enums import EventKind
from aurelis.evolution import methods
from aurelis.evolution.methods import (
    MIN_VIEWS,
    Fitness,
    adopt_method,
    current_method,
    evolve,
    fitness_of,
)
from aurelis.evolution.tables import AgentMethod
from aurelis.intel.live import CoinbaseCandles
from aurelis.judgement.seat import seat_agent
from aurelis.platform.llm.providers import MockProvider
from aurelis.platform.llm.seating import standins
from aurelis.platform.llm.types import LlmRequest
from aurelis.runtime import Runtime
from aurelis.service.loop import Service, cycle_once

_HOUR = 3600
_START = 1_780_000_000
_METHOD = (
    "METHOD: Only state a view when the day's move came on rising volume, keep the "
    "confidence near the middle, and say nothing on anything that has not moved.\n"
    "BECAUSE: the worst calls were confident guesses on quiet markets.\n"
)


class _Writer:
    def __init__(self, reply: str = _METHOD) -> None:
        self.reply = reply
        self.asked: list[LlmRequest] = []

    def __call__(self, request: LlmRequest) -> str:
        if "Write the method" in request.messages[-1].content:
            self.asked.append(request)
            return self.reply
        return standins()(request)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(dt.datetime.fromtimestamp(_START + 199 * _HOUR + 600, tz=dt.UTC))


def _company(settings: Settings, clock: FrozenClock, responder: Any) -> Runtime:
    built = Runtime.build(settings, clock=clock, provider=MockProvider(responder=responder))
    built.initialise()
    built.staff()
    return built


def _briers(values: dict[str, list[str]]) -> Any:
    def fake(session: Any, agent_ref: str, since: Any) -> list[Decimal]:  # noqa: ARG001
        return [Decimal(v) for v in values.get(agent_ref, [])]

    return fake


def _refs(company: Runtime, *handles: str) -> list[str]:
    with company.database.session() as session:
        return [company.roster.by_handle(session, h).ref for h in handles]


# ------------------------------------------------------------ fitness


def test_a_methods_fitness_is_its_forward_brier_against_a_coin_toss_with_an_error() -> None:
    def fit(values: list[str]) -> Fitness:
        n = len(values)
        mean = sum(Decimal(v) for v in values) / n
        return Fitness("AG-X", None, n, mean, Decimal("0.02"))

    assert fit(["0.40"] * MIN_VIEWS).verdict == "failing"
    assert fit(["0.15"] * MIN_VIEWS).verdict == "thriving"
    assert fit(["0.26"] * MIN_VIEWS).verdict == "chance", "within one error of a coin toss"
    assert fit(["0.40"] * (MIN_VIEWS - 1)).verdict == "unproven"
    assert "coin toss" in fit(["0.40"] * MIN_VIEWS).describe()


# ------------------------------------------------------------ replacement


def test_a_failing_method_is_replaced_by_one_the_best_calibrated_colleague_writes(
    settings: Settings, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = _Writer()
    company = _company(settings, clock, writer)
    try:
        failing, strong, weaker = _refs(company, "INTEL", "QUANT", "STRAT")
        monkeypatch.setattr(
            methods,
            "_scored_briers",
            _briers(
                {
                    failing: ["0.45", "0.35"] * 12,
                    strong: ["0.10", "0.16"] * 12,
                    weaker: ["0.18", "0.24"] * 12,
                }
            ),
        )
        run = evolve(company, at=clock.now())
        with company.database.session() as session:
            adopted = current_method(session, failing)
            untouched = current_method(session, strong)
            events = session.execute(
                sa.text("SELECT count(*) FROM events WHERE kind = :k"),
                {"k": EventKind.METHOD_ADOPTED.value},
            ).scalar_one()
    finally:
        company.close()
    assert len(run.adopted) == 1 and run.calls == 1 and events == 1
    assert adopted is not None and adopted.version == 1 and adopted.authored_by == strong
    assert adopted.baseline_views == 24 and adopted.baseline_brier == "0.4000"
    assert "rising volume" in adopted.text and untouched is None
    assert writer.asked[0].actor == strong, "the colleague who beats the coin toss wrote it"
    shown = writer.asked[0].messages[-1].content
    assert "Colleague Who Beats The Coin Toss" in shown or "colleague" in shown.lower()
    assert "failing" in run.describe() and failing in run.describe()


def test_with_no_colleague_better_than_chance_the_failing_agent_revises_its_own(
    settings: Settings, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = _Writer()
    company = _company(settings, clock, writer)
    try:
        (failing,) = _refs(company, "INTEL")
        monkeypatch.setattr(methods, "_scored_briers", _briers({failing: ["0.45"] * 30}))
        run = evolve(company, at=clock.now())
        with company.database.session() as session:
            adopted = current_method(session, failing)
    finally:
        company.close()
    assert run.adopted and adopted is not None and adopted.authored_by == failing
    assert "from your own worst calls" in writer.asked[0].messages[-1].content


def test_an_unreadable_reply_adopts_nothing_and_says_so(
    settings: Settings, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = _company(settings, clock, _Writer("I would rather not."))
    try:
        (failing,) = _refs(company, "INTEL")
        monkeypatch.setattr(methods, "_scored_briers", _briers({failing: ["0.45"] * 30}))
        run = evolve(company, at=clock.now())
        with company.database.session() as session:
            assert current_method(session, failing) is None
    finally:
        company.close()
    assert run.adopted == () and run.refused == (failing,) and "unreadable" in run.describe()


def test_a_method_counts_only_the_views_sealed_since_it_was_adopted(
    settings: Settings, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = _company(settings, clock, standins())
    seen: list[Any] = []

    def spy(session: Any, agent_ref: str, since: Any) -> list[Decimal]:  # noqa: ARG001
        seen.append(since)
        return []

    try:
        (agent,) = _refs(company, "INTEL")
        with company.database.session() as session:
            assert fitness_of(session, agent).verdict == "unproven"
            method = adopt_method(
                session,
                agent_ref=agent,
                text="Say nothing unless the market moved on volume; keep confidence modest.",
                reason="a test of the window",
                authored_by=agent,
                baseline=None,
                at=clock.now(),
            )
            monkeypatch.setattr(methods, "_scored_briers", spy)
            fitness_of(session, agent)
        assert seen == [method.adopted_at]
    finally:
        company.close()


# ------------------------------------------------------------ at the seat


def test_an_agents_method_is_part_of_its_identity_at_every_seat(
    settings: Settings, clock: FrozenClock
) -> None:
    seen: list[LlmRequest] = []

    def recorder(request: LlmRequest) -> str:
        seen.append(request)
        return standins()(request)

    company = _company(settings, clock, recorder)
    try:
        rows = [
            [_START + i * _HOUR, 99.0 + i, 101.0 + i, 100.0 + i, 100.0 + i, 5.0] for i in range(200)
        ]

        class _Bars:
            def __call__(self, request: object, timeout: int = 0) -> object:  # noqa: ARG002
                return io.BytesIO(json.dumps(list(reversed(rows))).encode())

        with company.database.session() as session:
            company.snapshots.ingest(
                session,
                CoinbaseCandles(opener=_Bars(), pause=0),
                desk="crypto",
                symbol="BTC-USD",
                bars=200,
            )
            (agent,) = [company.roster.by_handle(session, "INTEL").ref]
            adopt_method(
                session,
                agent_ref=agent,
                text="Prefer the longest horizon and never exceed a confidence of seventy percent.",
                reason="a test",
                authored_by=agent,
                baseline=None,
                at=clock.now(),
            )
        seat_agent(company, agent_handle="INTEL")
    finally:
        company.close()
    assert seen and all("Your method (version 1" in r.system for r in seen if r.actor == agent)
    assert any("never exceed a confidence" in r.system for r in seen)


# ------------------------------------------------------------ the wake


def test_the_wake_runs_evolution_at_most_once_a_day_and_says_so(
    settings: Settings, clock: FrozenClock
) -> None:
    company = _company(settings, clock, standins())
    try:
        first = cycle_once(company, service=Service(company, calls_per_day=50, cycles_per_wake=1))
        clock.advance(hours=2)
        second = cycle_once(company, service=Service(company, calls_per_day=50, cycles_per_wake=1))
        clock.advance(hours=23)
        third = cycle_once(company, service=Service(company, calls_per_day=50, cycles_per_wake=1))
    finally:
        company.close()
    assert "evolution:" in first.note and "methods measured" in first.note
    assert "evolution:" not in second.note, "once a day"
    assert "evolution:" in third.note


def test_the_station_shows_an_agents_method_its_fitness_and_every_version(
    settings: Settings, clock: FrozenClock
) -> None:
    from aurelis.station.app import station_app

    company = _company(settings, clock, standins())
    try:
        (agent,) = _refs(company, "INTEL")
        with company.database.session() as session:
            for text in (
                "Say nothing unless the market moved on volume; keep confidence modest.",
                "Prefer the longest horizon and never exceed a confidence of seventy percent.",
            ):
                adopt_method(
                    session,
                    agent_ref=agent,
                    text=text,
                    reason="a test of the page",
                    authored_by=agent,
                    baseline=None,
                    at=clock.now(),
                )
        page = station_app(company).handle(f"/agent/{agent}", {}).body.decode()
    finally:
        company.close()
    assert "<h2>Method</h2>" in page and "version 2" in page
    assert "never exceed a confidence" in page and "UNPROVEN" in page
    assert page.count("a test of the page") == 2, "every version is kept on the page"


def test_a_ref_is_a_name_and_not_a_figure() -> None:
    shown = allowed_figures({"record": "MEC-0001 scored 0.176 against 0.264"})
    said = "MEC-0001 and AG-0006 agree on H1; the Brier was 0.176, not 0.262, and it fell -3%."
    assert unsourced_numerals(said, shown) == ["0.262", "-3%"]


def test_a_figure_in_the_system_prompt_was_shown_and_is_sourced(
    settings: Settings, clock: FrozenClock
) -> None:
    def answer(request: LlmRequest) -> str:  # noqa: ARG001
        return "ANSWER: a\nBECAUSE: MEC-0001 scores 0.176 in the shared brain.\n"

    company = _company(settings, clock, answer)
    try:
        with company.database.session() as session:
            decision = decide_as(
                company.provider,
                session,
                agent_ref="AG-0001",
                question=Question("Which?", (Choice("a", "the first"), Choice("b", "the other"))),
                material={"markets": "a, b"},
                system="Shared brain: MEC-0001 is a candidate scheme, Brier 0.176.",
            )
            assert decision.chosen == frozenset({"a"})
            with pytest.raises(UnsourcedFigures):
                decide_as(
                    company.provider,
                    session,
                    agent_ref="AG-0001",
                    question=Question("Which?", (Choice("a", "the first"),)),
                    material={"markets": "a"},
                    system="Shared brain: nothing measured yet.",
                )
    finally:
        company.close()


def test_a_method_is_append_only(settings: Settings, clock: FrozenClock) -> None:
    company = _company(settings, clock, standins())
    try:
        (agent,) = _refs(company, "INTEL")
        with company.database.session() as session:
            adopt_method(
                session,
                agent_ref=agent,
                text="Say nothing unless the market moved on volume; keep confidence modest.",
                reason="a test",
                authored_by=agent,
                baseline=None,
                at=clock.now(),
            )
        engine = company.database.engine
        with pytest.raises(sa.exc.IntegrityError, match="append-only"), engine.begin() as c:
            c.execute(sa.update(AgentMethod).values(text="something else entirely, and longer"))
        with pytest.raises(sa.exc.IntegrityError, match="append-only"), engine.begin() as c:
            c.execute(sa.delete(AgentMethod))
    finally:
        company.close()
