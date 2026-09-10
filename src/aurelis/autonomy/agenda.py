"""What the company may do to itself next, and when it must stop doing it.

`aurelis tick` already runs the working day — briefings fire, standups happen,
agents take their turns. What it cannot do is decide what the day is *for*.
This module is that decision, and almost all of its content is refusals.

**The mandate is the work queue.** The company already publishes a standard it
must meet before asking to trade real money, and :func:`aurelis.mandate.assess`
already says which conditions it misses. So the loop does not carry a plan: it
asks itself what it is missing and takes the first action that could move one.
A hard-coded sequence would be a plan somebody wrote, running unattended, and
the first time the company's state diverged from that plan it would keep
executing it anyway.

**Repeating a search is not progress.** This is the rule the whole module
exists for. If a campaign ran and `survived_selection` is still unmet, running
a second campaign does not improve the odds — it widens the search, which
*raises* the bar the best result has to clear, and it does so faster than it
finds anything. An autonomous loop that kept searching until something passed
would not be a research company. It would be a machine for manufacturing false
discoveries, running unattended, with the company's own preregistration
machinery producing the paperwork.

So every action declares when it is **exhausted**, and an exhausted action is
never retried. When nothing is left, the loop says so and stops. A condition
that no available action can move is reported as *stuck*, with the reason —
which is a result about the company, not a failure of the loop.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.authoring.tables import AuthoringAttempt, Campaign
from aurelis.meetings.tables import MeetingObjection
from aurelis.portfolio.tables import Allocation
from aurelis.research.replication import ReplicationOutcome
from aurelis.research.tables import Registration, Replication
from aurelis.strategy.tables import PromotionGate

__all__ = [
    "AGENDA",
    "JUDGING_DEPARTMENTS",
    "Action",
    "ActionRefused",
    "Choice",
    "choose",
    "stuck_reasons",
]


class ActionRefused(RuntimeError):
    """The action ran and the seat refused what came back.

    Distinct from a failure. A failed action is exhausted for the run because
    retrying it would do the same thing again; a refused judgement is one
    agent's unusable reply, recorded against that agent, and the next agent
    may well answer. The first live wake of the service found the difference:
    one agent cited a rounded figure, the seat refused it, and the loop marked
    the whole judge action failed and stopped seating the other five.
    """



@dataclass(frozen=True, slots=True)
class Action:
    """One thing the company can do to itself, and the rule that ends it."""

    key: str
    condition: str
    """The mandate condition this could move. One action, one condition: an
    action that claimed several would keep looking useful after the one it
    actually served was met."""

    intent: str
    """What it does, in a sentence, for the record and the operator."""

    exhausted: Callable[[Session], str]
    """Returns a reason when the action must not run again, or ``""``.

    A reason rather than a boolean, because "we already did this and it did not
    work" is the most important sentence an autonomous loop can produce and
    throwing it away would leave the operator reading a silent stop.
    """

    estimated_calls: int
    """Roughly what it costs in model calls. Used to stop before a budget is
    exceeded rather than after."""


def _count(session: Session, entity: Any, *where: Any) -> int:
    """Count rows of a mapped class.

    Takes the class rather than a table name on purpose. The first version of
    this module counted ``campaigns``; the table is ``authoring_campaigns``,
    nothing checked the string, and the loop crashed on its second cycle. A
    mapped class is a name Python resolves at import, so the same mistake is
    now an ImportError in the test suite rather than an OperationalError in an
    unattended run.
    """
    query = sa.select(sa.func.count()).select_from(entity)
    for clause in where:
        query = query.where(clause)
    return int(session.execute(query).scalar_one())


# ------------------------------------------------------------ the exhaustion rules


JUDGING_DEPARTMENTS: tuple[str, ...] = (
    "market_intelligence",
    "quantitative_research",
    "strategy_laboratory",
)
"""Whose agents take the judgement seat unattended.

Not a menu of ideas: which market, which horizon and which direction stay with
the agent. This is only the org question of who is asked, and it is the
departments whose charters are about forming views. Risk and Trading are not
asked, on purpose: the agent that sizes a position should not be the one whose
view it rests on.
"""


def _judges(session: Session) -> list[Any]:
    from aurelis.agents.tables import Agent, AgentState

    return list(
        session.execute(
            sa.select(Agent)
            .where(
                Agent.department.in_(JUDGING_DEPARTMENTS),
                Agent.state.in_([AgentState.ACTIVE.value, AgentState.WORKING.value]),
            )
            .order_by(Agent.ref)
        ).scalars()
    )


def _answered_on_this_material(session: Session, agent_ref: str) -> bool:
    """Whether the agent's last word on the seat was a refusal or a decline
    made against the recordings that still stand.

    The seat shows the same material until a new recording exists, and the
    response cache hands the same reply back to the same prompt -- so seating
    an agent again before anything has changed is asking the same question and
    refusing the same answer. An agent whose last judgement event is newer than
    the newest recording, and was not a seal, waits for the next fetch.
    """
    from aurelis.core.enums import EventKind
    from aurelis.platform.db.tables import Event

    last_word = session.execute(
        sa.select(Event.kind, Event.seq)
        .where(
            Event.actor == agent_ref,
            Event.kind.in_(
                [
                    EventKind.THESIS_SEALED.value,
                    EventKind.THESIS_DECLINED.value,
                    EventKind.THESIS_REFUSED.value,
                ]
            ),
        )
        .order_by(Event.seq.desc())
        .limit(1)
    ).first()
    if last_word is None or last_word[0] == EventKind.THESIS_SEALED.value:
        return False
    newest_recording = session.execute(
        sa.select(sa.func.max(Event.seq)).where(
            Event.kind == EventKind.MARKET_SNAPSHOT_INGESTED.value
        )
    ).scalar()
    return newest_recording is None or int(last_word[1]) > int(newest_recording)


def _seatable(session: Session) -> tuple[list[Any], int, int]:
    """Agents with an instrument they hold no open view on, and the counts.

    An agent whose last reply on the current recordings was refused or
    declined is not offered the seat again until a newer recording exists.
    """
    from aurelis.intel.snapshots import MarketSnapshot
    from aurelis.judgement.tables import Thesis

    instruments = set(session.execute(sa.select(MarketSnapshot.symbol).distinct()).scalars())
    open_views = _count(session, Thesis, Thesis.scored_at.is_(None))
    seatable: list[Any] = []
    for agent in _judges(session):
        held = set(
            session.execute(
                sa.select(Thesis.instrument).where(
                    Thesis.agent_ref == agent.ref, Thesis.scored_at.is_(None)
                )
            ).scalars()
        )
        if instruments - held and not _answered_on_this_material(session, agent.ref):
            seatable.append(agent)
    return seatable, len(instruments), open_views


def _nothing_to_judge(session: Session) -> str:
    """The seat runs until every judge holds a view on every recorded market.

    Then it stops, and the reason is the honest one: a forward record cannot be
    hurried. The open views need their horizons to pass and a recording that
    covers them, and the loop fetches nothing.
    """
    seatable, instruments, open_views = _seatable(session)
    if not instruments:
        return (
            "no market has been recorded, so there is nothing to state a view "
            "against. Fetching is a decision for a person"
        )
    if not _judges(session):
        return "no active agent sits in a department that forms views"
    if seatable:
        return ""
    return (
        f"every judging agent holds an open view on every recorded market, or "
        f"was refused or declined on the recordings that stand ({open_views} "
        "sealed and waiting). A second view on the same instrument before the "
        "first resolves is the same bet twice, and the same material gets the "
        "same answer. What is missing is time and a fresh recording, and the "
        "loop fetches nothing"
    )


def _authored_already(session: Session) -> str:
    n = _count(session, AuthoringAttempt, AuthoringAttempt.refused_at.is_(None))
    if not n:
        return ""
    return (
        f"{n} design(s) have been authored. Authoring another does not make an "
        "existing one better; it adds a trial to the family and raises the bar "
        "every one of them has to clear"
    )


def _campaign_already(session: Session) -> str:
    """The rule this module exists for.

    One campaign, ever, per company state. A campaign is already a declared
    search with a budget frozen before the first design; running a second one
    because the first found nothing is the multiple-testing trap with extra
    steps, and it is exactly what an unattended loop would do if nothing
    stopped it.
    """
    n = _count(session, Campaign)
    if not n:
        return ""
    return (
        f"{n} campaign(s) have run. A second search does not improve the odds "
        "of the first: it widens the declared space, which raises the surplus "
        "the best design must clear, faster than searching finds anything. "
        "Searching harder is not the answer to a search that found nothing"
    )


def _replicated_everything(session: Session) -> str:
    locked = _count(session, Registration, Registration.locked_at.is_not(None))
    done = int(
        session.execute(
            sa.select(
                sa.func.count(sa.distinct(Replication.parent_registration_ref))
            )
        ).scalar_one()
    )
    if not locked:
        return "nothing has been locked, so there is no result to replicate"
    if done >= locked:
        return (
            f"all {locked} locked registration(s) have been replicated. A "
            "second variation of the same claim is a third bet on one draw of "
            "history, not more evidence"
        )

    # Learned from its own record, and the reason this rule is not simply
    # "have we replicated everything?". The first autonomous run replicated
    # five different registrations across five cycles and every one came back
    # NOTHING_TO_REPLICATE, because every original had been underpowered. That
    # is not repetition by the letter -- each registration was new -- and it is
    # repetition in every way that matters.
    tried = _count(session, Replication)
    empty = _count(
        session,
        Replication,
        Replication.outcome == ReplicationOutcome.NOTHING_TO_REPLICATE.value,
    )
    if tried and tried == empty:
        return (
            f"{tried} replication(s) have run and every one found nothing to "
            "replicate: the original never settled, so a variation of it "
            "agrees about nothing. Replicating another unsettled claim writes "
            "the same row again. What is missing is a result, not a re-test"
        )
    return ""


def _reviewed_already(session: Session) -> str:
    n = _count(session, MeetingObjection)
    if not n:
        return ""
    return (
        f"{n} objection(s) have been raised and settled. Convening another "
        "review of work nobody has changed since would produce the same "
        "objections against the same evidence"
    )


def _deploy_refused(session: Session) -> str:
    live = _count(session, Allocation, Allocation.withdrawn_at.is_(None))
    if live:
        return "a version is already allocated; the book does not need another"
    gates = _count(session, PromotionGate)
    if gates:
        return ""
    return (
        "no version has ever cleared its gates, and deployment refuses on the "
        "evidence rather than on anything a retry could change. What is "
        "missing is a research result, not another attempt to deploy"
    )


def _nothing_deployed(session: Session) -> str:
    if not _count(session, Allocation, Allocation.withdrawn_at.is_(None)):
        return (
            "nothing is deployed, and a paper walk of an empty book would "
            "measure the company trading nothing"
        )
    return ""


AGENDA: tuple[Action, ...] = (
    Action(
        key="judge",
        condition="calibrated",
        intent=(
            "settle any view whose horizon a recording already covers, then "
            "seat one agent to choose a market and state a view, have a critic "
            "attack it, and seal what survives"
        ),
        exhausted=_nothing_to_judge,
        estimated_calls=4,
    ),
    Action(
        key="author",
        condition="authored",
        intent="put an agent in the author's seat and measure what it designs",
        exhausted=_authored_already,
        estimated_calls=6,
    ),
    Action(
        key="campaign",
        condition="survived_selection",
        intent=(
            "search the design space inside a budget declared before the first "
            "design, then subtract what a search that wide returns from noise"
        ),
        exhausted=_campaign_already,
        estimated_calls=14,
    ),
    Action(
        key="review",
        condition="reviewed",
        intent="hold a research review and let the critic attack the evidence",
        exhausted=_reviewed_already,
        estimated_calls=4,
    ),
    Action(
        key="replicate",
        condition="replicated",
        intent="re-test a locked result under one declared variation",
        exhausted=_replicated_everything,
        estimated_calls=0,
    ),
    Action(
        key="deploy",
        condition="risk_cleared",
        intent="read the gates from the record and ask for a promotion",
        exhausted=_deploy_refused,
        estimated_calls=0,
    ),
    Action(
        key="paper",
        condition="paper_gap_measured",
        intent="walk the held-out window and compare it against the backtest",
        exhausted=_nothing_deployed,
        estimated_calls=0,
    ),
)
"""Every action, in the order the company should try them.

Deliberately short, and deliberately missing two things.

There is no action for ``settled``. Whether a claim was confirmed or came back
underpowered is decided by how much data exists against how small an effect was
declared, and no action in a loop can change either — the company would have to
be given more history, which is a decision for whoever runs it.

There is no action for ``live_data``. Fetching is the one thing here that
reaches outside the company, and an unattended loop is the last place that
should happen without somebody saying so.
"""


@dataclass(frozen=True, slots=True)
class Choice:
    """What the loop decided to do next, or why it decided it cannot."""

    action: Action | None
    reason: str

    @property
    def acts(self) -> bool:
        return self.action is not None


def choose(
    session: Session,
    unmet: frozenset[str],
    *,
    budget_left: int,
    failed: frozenset[str] = frozenset(),
) -> Choice:
    """The first action that could move something the company is missing.

    Order matters and is the agenda's, not the mandate's: authoring before
    searching, evidence before deployment. A loop that picked by "which
    condition is listed first" would try to deploy a strategy nobody had
    authored yet.

    ``failed`` is what already went wrong in this run, and excluding it is not
    a nicety. Every other exhaustion rule reads persistent state, and an action
    that *failed* usually wrote none: a refused authoring writes nothing at
    all, on purpose, so ``_authored_already`` still counted zero and the loop
    re-ran it every cycle until it ran out of cycles. Six identical failures,
    recorded six times. An action that failed is exhausted for this run.
    """
    blocked: list[str] = []
    for action in AGENDA:
        if action.condition not in unmet:
            continue
        if action.key in failed:
            blocked.append(
                f"{action.key}: it failed earlier in this run, and nothing has "
                "changed since that would make it succeed now"
            )
            continue
        why = action.exhausted(session)
        if why:
            blocked.append(f"{action.key}: {why}")
            continue
        if action.estimated_calls > budget_left:
            return Choice(
                None,
                f"{action.key} needs about {action.estimated_calls} model "
                f"call(s) and {budget_left} remain in the budget. Stopping "
                "before the limit rather than through it",
            )
        return Choice(action, f"{action.condition} is unmet and {action.key} could move it")

    if blocked:
        return Choice(
            None,
            "every action that could move an unmet condition is exhausted:\n  "
            + "\n  ".join(blocked),
        )
    return Choice(
        None,
        "nothing the company is missing has an action behind it. What remains "
        "is a research result or a decision for whoever runs it",
    )


def stuck_reasons(session: Session, unmet: frozenset[str]) -> dict[str, str]:
    """Per unmet condition, why the company cannot act on it.

    Reported rather than inferred from silence: a loop that stopped without
    saying which conditions it had given up on, and why, would be indis-
    tinguishable from one that crashed.
    """
    out: dict[str, str] = {}
    by_condition = {action.condition: action for action in AGENDA}
    for condition in sorted(unmet):
        action = by_condition.get(condition)
        if action is None:
            out[condition] = (
                "no action can move this. It is decided by evidence the "
                "company has, or by a decision it is not allowed to take "
                "unattended"
            )
            continue
        why = action.exhausted(session)
        out[condition] = why or "actionable"
    return out


def budget_for(actions: tuple[Action, ...]) -> int:
    """What a full pass would cost, for an operator sizing a run."""
    return sum(action.estimated_calls for action in actions)


def action_named(key: str) -> Action:
    for action in AGENDA:
        if action.key == key:
            return action
    raise KeyError(f"no action {key!r}; the agenda is {[a.key for a in AGENDA]}")
