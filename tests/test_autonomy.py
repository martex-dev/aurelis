"""M24: the company decides its own next action, and knows when to stop.

The acceptance criteria from the roadmap, each with a test named after it:

* the mandate is the work queue — what it does is decided by what it is missing,
* a search is never repeated, which is the whole reason this layer exists,
* it stops when nothing is left and says which conditions it gave up on,
* it cannot fetch data and cannot trade,
* a failed action is recorded and does not spin the loop.

The dangerous failure here is not a crash. It is a loop that keeps searching
until something passes, unattended, with the company's own preregistration
machinery producing paperwork for it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
import sqlalchemy as sa

from aurelis.authoring.standin import scripted_author
from aurelis.authoring.tables import AuthoringAttempt, Campaign
from aurelis.autonomy.agenda import AGENDA, choose
from aurelis.autonomy.loop import run_autonomy
from aurelis.autonomy.tables import AutonomyCycle
from aurelis.platform.llm.providers import MockProvider
from aurelis.runtime import Runtime


@pytest.fixture
def company(settings, clock) -> Runtime:  # type: ignore[no-untyped-def]
    """A staffed company whose provider can answer an authoring question.

    The plain mock echoes its input, which cannot answer a closed question, so
    a loop run against it refuses at the first slot. That is a real state and
    it has its own test below; it is not the state to measure the agenda in.
    """
    built = Runtime.build(
        settings, clock=clock, provider=MockProvider(responder=scripted_author)
    )
    built.initialise()
    built.staff()
    try:
        yield built
    finally:
        built.close()


def _run(company: Runtime, **kwargs: Any) -> Any:
    return run_autonomy(company, **kwargs)


# ------------------------------------------------- the mandate is the queue


def test_what_it_does_is_decided_by_what_it_is_missing(company: Runtime) -> None:
    """M24 acceptance (a). No plan is carried in here.

    Every action names one mandate condition, and the loop only ever picks an
    action whose condition the company's own standard currently reports as
    unmet. A hard-coded sequence would keep executing after the company's state
    diverged from it.
    """
    outcome = _run(company, cycles=3)
    assert outcome.acted, "it did something"

    # Everything it chose was aimed at a condition the standard reported unmet
    # when the choice was made -- which is recorded on the row, so this is
    # checked against what the company saw rather than against hindsight.
    with company.database.session() as session:
        rows = list(
            session.execute(
                sa.select(AutonomyCycle)
                .where(AutonomyCycle.run_ref == outcome.run_ref)
                .order_by(AutonomyCycle.n)
            ).scalars()
        )
    by_key = {action.key: action for action in AGENDA}
    for row in rows:
        if row.action is None:
            continue
        assert by_key[row.action].condition in set(row.unmet), (
            f"{row.action} was chosen for a condition already met"
        )

    # The first thing a fresh company is missing is a design of its own.
    assert outcome.cycles[0].action == "author"


def test_every_action_names_exactly_one_condition() -> None:
    """An action that claimed several would keep looking useful after the one
    it actually served was met."""
    conditions = [action.condition for action in AGENDA]
    assert len(conditions) == len(set(conditions))


# ----------------------------------------- a search is never repeated


def test_a_second_campaign_is_never_run(company: Runtime) -> None:
    """M24 acceptance (b), and the reason this layer exists.

    A campaign is a declared search with a budget frozen before the first
    design. Running a second one because the first found nothing widens the
    declared space, which *raises* the surplus the best design must clear —
    faster than searching finds anything. An unattended loop that did this
    would be a machine for manufacturing false discoveries.
    """
    _run(company, cycles=12)
    with company.database.session() as session:
        assert session.execute(
            sa.select(sa.func.count()).select_from(Campaign)
        ).scalar_one() == 1

    # And again, from the state the first run left behind.
    second = _run(company, cycles=12)
    with company.database.session() as session:
        assert session.execute(
            sa.select(sa.func.count()).select_from(Campaign)
        ).scalar_one() == 1
    assert "campaign" not in {c.action for c in second.acted}


def test_it_will_not_replicate_when_every_replication_found_nothing(
    company: Runtime,
) -> None:
    """Repetition by the letter is not the test; repetition in effect is.

    The first autonomous run replicated five different registrations over five
    cycles and every one came back ``nothing_to_replicate``, because every
    original had been underpowered. Each registration was new. Nothing was
    learned five times.
    """
    outcome = _run(company, cycles=12)
    replications = [c for c in outcome.acted if c.action == "replicate"]
    assert len(replications) <= 1, (
        "a second replication of an unsettled claim writes the same row again"
    )


def test_authoring_twice_is_refused_with_its_reason(company: Runtime) -> None:
    """A second design does not improve the first. It adds a trial to the
    family and raises the bar every design has to clear."""
    _run(company, cycles=12)
    with company.database.session() as session:
        before = session.execute(
            sa.select(sa.func.count()).select_from(AuthoringAttempt)
        ).scalar_one()
    _run(company, cycles=12)
    with company.database.session() as session:
        after = session.execute(
            sa.select(sa.func.count()).select_from(AuthoringAttempt)
        ).scalar_one()
    assert after == before


# -------------------------------------------------- stopping, and saying why


def test_it_stops_when_nothing_is_left_and_names_what_it_gave_up_on(
    company: Runtime,
) -> None:
    """M24 acceptance (c).

    A loop that stopped without saying which conditions it had abandoned, and
    why, would be indistinguishable from one that crashed.
    """
    outcome = _run(company, cycles=20)
    assert outcome.cycles[-1].action is None, "it stopped rather than ran out of cycles"
    assert "exhausted" in outcome.stopped_because
    unmet = set(outcome.stuck)
    assert unmet, "a fresh company has not met the standard"
    for condition, why in outcome.stuck.items():
        assert len(why) > 30, f"{condition} was abandoned without a reason"


def test_the_decision_to_do_nothing_is_recorded(company: Runtime) -> None:
    """The most common outcome at the end of a run, and a row either way."""
    outcome = _run(company, cycles=20)
    with company.database.session() as session:
        rows = list(
            session.execute(
                sa.select(AutonomyCycle).where(AutonomyCycle.run_ref == outcome.run_ref)
            ).scalars()
        )
    assert len(rows) == len(outcome.cycles)
    stopped = [r for r in rows if r.action is None]
    assert len(stopped) == 1
    assert stopped[0].outcome == "stopped"


def test_an_action_that_moved_nothing_is_not_recorded_as_success(
    company: Runtime,
) -> None:
    """A loop that logged 'acted' without logging 'moved nothing' would make a
    company that achieves nothing look busy."""
    outcome = _run(company, cycles=20)
    ran = [c for c in outcome.acted if c.outcome == "acted"]
    assert ran, "something ran"
    assert any(not c.moved for c in ran), "the ordinary case is recorded as itself"


# ------------------------------------------------------------ the bounds


def test_the_cycle_bound_stops_it(company: Runtime) -> None:
    outcome = _run(company, cycles=2)
    assert len(outcome.cycles) <= 2


def test_the_call_budget_stops_it_before_it_is_crossed(company: Runtime) -> None:
    """Estimated from the agenda before an action starts, so a run cannot
    discover it is over budget by going over budget."""
    outcome = _run(company, cycles=20, calls=1)
    assert outcome.calls <= 6, "it did not start work it could not afford"
    assert outcome.cycles[-1].action is None


def test_a_budget_of_zero_does_nothing_and_says_so(company: Runtime) -> None:
    outcome = _run(company, cycles=5, calls=0)
    assert not outcome.acted
    assert "budget" in outcome.stopped_because or "exhausted" in outcome.stopped_because


# ------------------------------------------------- what it is not allowed to do


def test_there_is_no_action_that_reaches_the_network() -> None:
    """M24 acceptance (d), first half.

    Fetching is the one thing in this company that reaches outside it, and an
    unattended loop is the last place it should happen without a person.
    """
    assert "live_data" not in {action.condition for action in AGENDA}
    keys = {action.key for action in AGENDA}
    assert not keys & {"fetch", "data", "ingest"}


def test_there_is_no_action_that_could_trade(company: Runtime) -> None:
    """M24 acceptance (d), second half.

    Not disabled — absent. The paper action exists and refuses on an empty
    book; there is no live broker adapter anywhere for it to reach.
    """
    from aurelis.trading.states import BrokerKind

    assert "live" not in {kind.value for kind in BrokerKind}
    outcome = _run(company, cycles=20)
    assert "paper" not in {c.action for c in outcome.acted}, (
        "nothing was deployed, so there was nothing to walk"
    )


def test_the_loop_cannot_lower_a_bar_it_failed_to_clear(company: Runtime) -> None:
    """The standard is hashed, and nothing in the autonomy package writes to
    it. A loop that could edit its own criteria would be able to declare
    success."""
    from aurelis.mandate.standard import digest

    before = digest()
    _run(company, cycles=20)
    assert digest() == before


# ------------------------------------------------------------ failure


def test_a_failed_action_is_recorded_and_does_not_spin(
    company: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed action is a fact about the company, not a crash of the loop —
    and the exhaustion rule still applies to it, so it cannot be retried
    forever."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("the engine fell over")

    monkeypatch.setattr("aurelis.authoring.attempt.run_authoring", _explode)
    outcome = _run(company, cycles=6)
    failures = [c for c in outcome.cycles if c.outcome == "failed"]
    assert failures, "the failure was recorded"
    assert "the engine fell over" in failures[0].detail
    assert len(failures) == 1, (
        "an action that failed is exhausted for the run. The first version "
        "re-ran a refused authoring every cycle, because a refusal writes "
        "nothing and the exhaustion rule reads what was written"
    )


def test_a_provider_that_cannot_answer_stops_the_run_rather_than_spinning(
    runtime: Runtime,
) -> None:
    """The plain mock echoes its input, so it cannot answer a closed question
    and authoring refuses at the first slot. That is a real operating state —
    a workspace pointed at a provider that is down, or not signed in — and the
    loop must report it once and stop, not discover it every cycle."""
    runtime.staff()
    outcome = run_autonomy(runtime, cycles=6)
    failures = [c for c in outcome.cycles if c.outcome == "failed"]
    assert len(failures) == 1, "the refusal was learned once"
    assert outcome.cycles[-1].action is None
    assert "failed earlier in this run" in outcome.cycles[-1].reason


def test_every_agenda_rule_runs_against_a_real_database(company: Runtime) -> None:
    """The first version counted a table called ``campaigns``; the table is
    ``authoring_campaigns``, nothing checked the string, and the loop crashed
    on its second cycle. The rules take mapped classes now — this is the test
    that would have caught it either way."""
    with company.database.session() as session:
        for action in AGENDA:
            action.exhausted(session)  # must not raise
        assert choose(session, frozenset({"authored"}), budget_left=100).acts


def test_the_run_is_on_the_chain(company: Runtime) -> None:
    from aurelis.core.enums import EventKind

    outcome = _run(company, cycles=4)
    with company.database.session() as session:
        kinds = {event.kind for event in company.ledger.tail(session, 500)}
        report = company.ledger.verify(session)
    assert EventKind.AUTONOMY_RUN_FINISHED in kinds
    assert report.ok
    assert outcome.run_ref.startswith("RUN-A")


def test_a_run_started_now_does_not_reuse_an_earlier_runs_number(
    company: Runtime,
) -> None:
    first = _run(company, cycles=1)
    second = _run(company, cycles=1)
    assert first.run_ref != second.run_ref


def test_cycles_are_numbered_within_a_run(company: Runtime) -> None:
    outcome = _run(company, cycles=20, at=dt.datetime(2026, 9, 10, tzinfo=dt.UTC))
    assert [c.n for c in outcome.cycles] == list(range(1, len(outcome.cycles) + 1))
