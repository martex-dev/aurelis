"""The company pays for its own shape, and changes it on the evidence.

M17 made every charter's declared model tier reach a real model. That turned a
field which had cost nothing into a bill: **an agent routes at the highest tier
of the charters it holds**, because it must be capable of its most demanding
role, so a generalist holding one expensive charter runs *all* its work on that
model. Twenty-five charters at the launch roster are held by an agent that
routes above the tier they were written for, and the gap between the cheapest
and dearest rate is fifteen to one.

That is a fact about the company's own shape, measured from its own record, and
the machinery to act on it already existed: M11's triggers, preregistered
predictions and measured effects. This module joins the two.

.. code-block:: text

    scan                 TIER_WASTE fires on the worst offender
    propose              split the charters written cheaper than it routes
    lock                 the prediction is hashed before the room sees it
    Board                convened after the lock, so it cannot reach it
    apply                coverage moves, never copied, never dropped
    onboard              the new agent is scored before it may work
    measure              the predicted metric, taken again

What honesty requires here
--------------------------

**The saving is structural, not a dollar figure.** On a subscription every call
reports zero marginal cost, so nothing in this repository can measure money
saved. What it can measure exactly is the *structure*: how many charters run
above their written tier, before and after. The rate table says what that is
worth; the company does not pretend to have observed it.

**One split does not reach zero.** Moving everything below the top tier off an
agent leaves the new agent holding a spread of its own, and it may be
overtiered in turn. The prediction is therefore made about the **subject**,
where fission acts directly, and the company total is reported beside it so a
reader can see how much of the problem one change actually solved.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.agents.tables import Agent, AgentCoverage, AgentState
from aurelis.core.enums import ModelTier
from aurelis.core.errors import IntegrityViolation
from aurelis.meetings.types import MeetingType
from aurelis.org.registry import charter, resolve_authority
from aurelis.orgdev.demonstration import _board, _chair_of, _proposer
from aurelis.orgdev.detection import TriggerHit, scan
from aurelis.orgdev.development import Prediction
from aurelis.orgdev.metrics import COMPANY, agent_metrics, read_metric
from aurelis.orgdev.states import OrgChangeKind, TriggerKind
from aurelis.platform.llm.pricing import price_for
from aurelis.platform.llm.routing import model_for

__all__ = ["RetieringOutcome", "cheaper_charters", "run_retiering"]

_LADDER = (ModelTier.NONE, ModelTier.LOW, ModelTier.MID, ModelTier.HIGH)


def cheaper_charters(session: Session, agent_ref: str) -> tuple[str, ...]:
    """The charters this agent holds that were written for a cheaper model.

    ``NONE`` is excluded. That tier means the work calls no model at all, so
    holding it costs nothing extra however the agent routes -- counting it
    would inflate the case for a split with work that was never going to be
    billed.
    """
    held = [
        str(row)
        for row in session.execute(
            sa.select(AgentCoverage.charter_id)
            .where(AgentCoverage.agent_ref == agent_ref)
            .distinct()
        ).scalars()
    ]
    if not held:
        return ()
    tier = resolve_authority(tuple(held)).tier
    return tuple(
        sorted(
            charter_id
            for charter_id in held
            if charter(charter_id).tier is not ModelTier.NONE
            and _LADDER.index(charter(charter_id).tier) < _LADDER.index(tier)
        )
    )


@dataclass(frozen=True, slots=True)
class RetieringOutcome:
    """What one tier-driven reorganisation established."""

    change_ref: str
    meeting_ref: str
    subject: str
    subject_handle: str
    new_agent: str
    moved: tuple[str, ...]
    routed_before: ModelTier
    routed_after: ModelTier
    subject_before: int
    subject_after: int
    company_before: int
    company_after: int
    verdict: str
    detail: str
    onboarding: str
    rate_gap: str

    @property
    def prediction_held(self) -> bool:
        return self.subject_after < self.subject_before

    @property
    def company_improved(self) -> int:
        """Charters no longer running above their written tier. May be less
        than what moved: the new agent has a spread of its own."""
        return self.company_before - self.company_after

    def describe(self) -> str:
        return (
            f"{self.subject_handle} routed at {self.routed_before.value} for "
            f"{self.subject_before} charter(s) written cheaper; split "
            f"{len(self.moved)} onto {self.new_agent}; subject now "
            f"{self.subject_after}, company {self.company_before} -> "
            f"{self.company_after}. {self.verdict.upper()}"
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "change": self.change_ref,
            "meeting": self.meeting_ref,
            "subject": self.subject,
            "handle": self.subject_handle,
            "new_agent": self.new_agent,
            "moved": list(self.moved),
            "routed_before": self.routed_before.value,
            "routed_after": self.routed_after.value,
            "subject_before": self.subject_before,
            "subject_after": self.subject_after,
            "company_before": self.company_before,
            "company_after": self.company_after,
            "verdict": self.verdict,
            "detail": self.detail,
            "onboarding": self.onboarding,
            "rate_gap": self.rate_gap,
            "caveat": (
                "The saving is structural. Every model call in this repository "
                "reports zero marginal cost under a subscription, so no money "
                "saved has been observed -- what is measured is how many "
                "charters run above the tier they were written for."
            ),
        }


def _worst(session: Session) -> TriggerHit:
    """The agent the company's own detection says is worst, not a named one.

    Scanned rather than chosen, for the reason M11 gave: a demonstration that
    picked its subject would be a script pretending to be a measurement.
    """
    hits = [hit for hit in scan(session) if hit.trigger.kind is TriggerKind.TIER_WASTE]
    if not hits:
        raise IntegrityViolation(
            "no agent holds enough charters below its routed tier to fire the "
            "trigger. Nothing to reorganise, which is a result rather than a "
            "failure."
        )
    return sorted(hits, key=lambda hit: (-(hit.reading.value or 0), hit.subject))[0]


def _company_total(session: Session) -> int:
    total = 0
    for agent in session.execute(
        sa.select(Agent).where(
            Agent.state.notin_((AgentState.RETIRED, AgentState.SUSPENDED))
        )
    ).scalars():
        total += int(agent_metrics(session, agent.ref).value("overtiered_charters") or 0)
    return total


def _rate_gap(low: ModelTier, high: ModelTier) -> str:
    """What the tier difference is worth, per the price table.

    Quoted rather than computed into a saving. The company has not observed a
    saving and will not print one.
    """
    if low is high:
        return "the moved work already routed at its own tier"
    cheap = price_for(model_for("anthropic_api", low))
    dear = price_for(model_for("anthropic_api", high))
    ratio = (dear.input_per_mtok / cheap.input_per_mtok).quantize(Decimal("0.1"))
    return (
        f"{high.value} input costs {dear.input_per_mtok} per Mtok against "
        f"{cheap.input_per_mtok} at {low.value}: {ratio}x. Metered only on the "
        "API path; a subscription reports no marginal cost either way."
    )


def run_retiering(
    runtime: Any, *, new_handle: str | None = None, at: dt.datetime | None = None
) -> RetieringOutcome:
    """Find the worst overtiered agent, split it, and measure what changed."""
    moment = at or runtime.clock.now()

    with runtime.database.session() as session:
        hit = _worst(session)
        subject = hit.subject
        handle = hit.handle
        before = int(hit.reading.value or 0)
        moved = cheaper_charters(session, subject)
        if not moved:  # pragma: no cover - the trigger fired on this count
            raise IntegrityViolation(f"{subject} has nothing written cheaper to move")
        held = [
            str(row)
            for row in session.execute(
                sa.select(AgentCoverage.charter_id)
                .where(AgentCoverage.agent_ref == subject)
                .distinct()
            ).scalars()
        ]
        routed_before = resolve_authority(tuple(held)).tier
        routed_after = resolve_authority(tuple(moved)).tier
        company_before = _company_total(session)

        prediction = Prediction(
            metric="overtiered_charters",
            direction="down",
            # The subject's own count, where fission acts directly. Predicting
            # the company total would be a claim about the new agent's spread
            # as well, which this change does not control.
            magnitude=Decimal(before),
            plan=(
                "Read overtiered_charters for the subject immediately before "
                "the transfer and again after it. Every charter written below "
                "the subject's routed tier is moved, so the count must reach "
                "zero; a split that leaves any behind will not satisfy this."
            ),
            after_days=0,
            subject=subject,
        )
        change = runtime.orgdev.propose(
            session,
            hit=hit,
            proposed_by=_proposer(session, subject),
            prediction=prediction,
            justification=(
                f"{handle} routes at {routed_before.value} because that is the "
                f"highest of the charters it holds, so {before} charter(s) "
                f"written for a cheaper model run on it. Moving them to their "
                f"own agent lets them route at {routed_after.value}. "
                + _rate_gap(routed_after, routed_before)
            ),
            charters=moved,
            new_handle=new_handle or f"{handle}-CHEAP",
            kind=OrgChangeKind.FISSION,
            at=moment,
        )
        change_ref = change.ref
        digest = runtime.orgdev.lock(session, change_ref, at=moment)

    # The room, convened after the lock, so nothing said in it can reach the
    # prediction it will be judged against.
    with runtime.database.session() as session:
        participants = _board(session, exclude=subject)
        meeting = runtime.chair.convene(
            session,
            meeting_type=MeetingType.BOARD,
            subject=f"Retier: move {len(moved)} charter(s) off {handle}",
            chair=participants[0],
            participants=participants,
            subject_ref=change_ref,
            trigger=TriggerKind.TIER_WASTE.value,
            evidence={
                "trigger": hit.evidence,
                "predicts": prediction.as_payload(),
                "locked_digest": digest,
                "charters": list(moved),
                "routes": f"{routed_before.value} -> {routed_after.value}",
            },
            at=moment,
        )
        meeting_ref = meeting.ref
        runtime.chair.run(
            session,
            meeting_ref,
            forecast_question=(
                "Will moving these charters stop them running on a model they "
                "were not written for?"
            ),
            at=moment,
        )

    with runtime.database.session() as session:
        runtime.orgdev.decide(
            session,
            change_ref,
            approved=True,
            decided_by=_chair_of(session),
            meeting_ref=meeting_ref,
            at=moment,
        )

    with runtime.database.session() as session:
        applied = runtime.orgdev.apply(session, change_ref, at=moment)
        new_agent = applied.new_agent or ""

    with runtime.database.session() as session:
        outcome = runtime.onboarding.run(session, new_agent, at=moment)
        if outcome.may_work:
            runtime.roster.set_state(session, new_agent, AgentState.ACTIVE, at=moment)
        onboarding = outcome.verdict.value

    with runtime.database.session() as session:
        effect = runtime.orgdev.measure(session, change_ref, at=moment)
        after = int(read_metric(session, subject, "overtiered_charters").value or 0)
        company_after = _company_total(session)
        assert COMPANY  # the company subject exists; read above is per agent

    return RetieringOutcome(
        change_ref=change_ref,
        meeting_ref=meeting_ref,
        subject=subject,
        subject_handle=handle,
        new_agent=new_agent,
        moved=moved,
        routed_before=routed_before,
        routed_after=routed_after,
        subject_before=before,
        subject_after=after,
        company_before=company_before,
        company_after=company_after,
        verdict=effect.verdict.value,
        detail=effect.detail,
        onboarding=onboarding,
        rate_gap=_rate_gap(routed_after, routed_before),
    )
