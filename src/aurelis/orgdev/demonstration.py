"""The M11 demonstration: the company changes its own shape and measures it.

Two changes, run one after the other, because one is not enough to show that
the verdict discriminates.

.. code-block:: text

    scan the roster           AG-0004 stands in for 9 Intelligence charters
    BREADTH fires             nothing about any one of them is attributable
    ORG-0001  split 2 off     predict attributable_charters up by 1
              Board approves
              measure         0 -> 0.  NO_CHANGE. The prediction failed.
    ORG-0002  split 6 more    the same prediction, made again
              Board approves
              measure         0 -> 1.  IMPROVED.

The first change is the one worth reading. It was a **sensible** change — news
and sentiment genuinely belong together, the handover was clean, coverage was
conserved — and the thing it was sold on did not happen. Seven charters is as
unattributable as nine. The record says ``no_change``, because the prediction
was hashed before the Board saw it and there is no way to re-aim it afterwards
(ADR-0012).

A company that measured its own reorganisations loosely would have written that
one down as a success: something was split, the org chart looks more sensible,
everyone agreed at the time. What it actually bought was one attributable agent
out of a needed seven, and only the second change closed the gap.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.agents.tables import Agent, AgentState
from aurelis.core.errors import IntegrityViolation
from aurelis.meetings.types import MeetingType
from aurelis.orgdev.detection import TriggerHit, scan
from aurelis.orgdev.development import MeasuredEffect, Prediction
from aurelis.orgdev.metrics import agent_metrics
from aurelis.orgdev.states import EffectVerdict, OrgChangeKind, TriggerKind
from aurelis.runtime import Runtime

__all__ = ["OrgDevOutcome", "OrgStep", "run_one_change", "run_org_development"]

#: The first split. Two charters that belong together -- a news desk and a
#: sentiment desk read the same sources -- so it is a defensible change rather
#: than an arbitrary one, which is what makes its failure informative.
FIRST_SPLIT = ("intel.news_analyst", "intel.sentiment_analyst")

#: The second. Everything except ``intel.head``, so the generalist is left
#: holding exactly one charter and its outputs become attributable at last.
SECOND_SPLIT = (
    "intel.fundamental_analyst",
    "intel.technical_analyst",
    "intel.macro_analyst",
    "intel.regime_analyst",
    "intel.alternative_data_analyst",
    "intel.source_reliability",
)


@dataclass(frozen=True, slots=True)
class OrgStep:
    """One proposed, decided, applied and measured change."""

    change_ref: str
    meeting_ref: str
    subject: str
    new_agent: str
    trigger: TriggerKind
    trigger_value: str
    predicted: str
    locked_digest: str
    breadth_before: int
    breadth_after: int
    moved: tuple[str, ...]
    handover: str
    new_agent_verdict: str
    effect: MeasuredEffect
    coverage_intact: bool

    @property
    def prediction_held(self) -> bool:
        return self.effect.verdict is EffectVerdict.IMPROVED

    def describe(self) -> str:
        return (
            f"{self.change_ref}: {self.subject} {self.breadth_before} -> "
            f"{self.breadth_after} charters, {self.new_agent} takes "
            f"{len(self.moved)}; predicted {self.predicted}; "
            f"{self.effect.verdict.value}"
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "change": self.change_ref,
            "meeting": self.meeting_ref,
            "subject": self.subject,
            "new_agent": self.new_agent,
            "trigger": self.trigger.value,
            "predicted": self.predicted,
            "locked_digest": self.locked_digest,
            "moved": list(self.moved),
            "effect": self.effect.verdict.value,
            "effect_detail": self.effect.detail,
            "coverage_intact": self.coverage_intact,
        }


@dataclass(frozen=True, slots=True)
class OrgDevOutcome:
    """Both changes, and what the pair of them established."""

    steps: tuple[OrgStep, ...]

    @property
    def first(self) -> OrgStep:
        return self.steps[0]

    @property
    def last(self) -> OrgStep:
        return self.steps[-1]

    @property
    def coverage_intact(self) -> bool:
        return all(step.coverage_intact for step in self.steps)

    @property
    def verdicts(self) -> tuple[EffectVerdict, ...]:
        return tuple(step.effect.verdict for step in self.steps)

    @property
    def discriminates(self) -> bool:
        """The point of running two: the verdict is not a rubber stamp."""
        return len(set(self.verdicts)) > 1

    def describe(self) -> str:
        return " | ".join(step.describe() for step in self.steps)

    def as_payload(self) -> dict[str, Any]:
        return {
            "steps": [step.as_payload() for step in self.steps],
            "verdicts": [v.value for v in self.verdicts],
            "coverage_intact": self.coverage_intact,
        }


def run_org_development(
    runtime: Runtime, *, at: dt.datetime | None = None
) -> OrgDevOutcome:
    """Two structural changes, each proposed, decided, applied and measured."""
    moment = at or runtime.clock.now()
    first = run_one_change(
        runtime,
        charters=FIRST_SPLIT,
        handle="NEWS",
        at=moment,
        note=(
            "News and sentiment read the same sources, so they belong on one "
            "desk. Splitting them off makes that pair measurable."
        ),
    )
    second = run_one_change(
        runtime,
        charters=SECOND_SPLIT,
        handle="ANALYSIS",
        at=moment,
        note=(
            "The first split left seven charters behind, which is as "
            "unattributable as nine. This one leaves the head charter alone."
        ),
    )
    return OrgDevOutcome(steps=(first, second))


def run_one_change(
    runtime: Runtime,
    *,
    charters: tuple[str, ...],
    handle: str,
    note: str,
    at: dt.datetime | None = None,
) -> OrgStep:
    """Propose, decide, apply and measure one structural change."""
    moment = at or runtime.clock.now()

    with runtime.database.session() as session:
        hit = _breadth_hit(session, charters)
        subject = hit.subject
        breadth_before = int(hit.reading.value or 0)

        # The prediction. Deliberately the *subject's* attributability, which
        # is the metric the trigger fired on -- not the new agent's, which
        # would be a different and much easier claim.
        prediction = Prediction(
            metric="attributable_charters",
            direction="up",
            magnitude=Decimal(1),
            plan=(
                "Read attributable_charters for the split agent before the "
                "transfer and again after it. It is 1 only when the agent "
                "holds exactly one charter, so a split that leaves it holding "
                "several will not satisfy this."
            ),
            after_days=0,
            subject=subject,
        )

        proposer = _proposer(session, subject)
        change = runtime.orgdev.propose(
            session,
            hit=hit,
            proposed_by=proposer,
            prediction=prediction,
            justification=(
                f"{hit.handle} stands in for {breadth_before} Intelligence "
                "charters. No output it produces can be attributed to any one "
                f"of them, so neither load nor quality can be measured per "
                f"area. {note}"
            ),
            charters=charters,
            new_handle=handle,
            kind=OrgChangeKind.FISSION,
            at=moment,
        )
        change_ref = change.ref
        digest = runtime.orgdev.lock(session, change_ref, at=moment)

    # The room. Convened after the lock, so nothing it says can reach the
    # prediction it will later be judged against.
    with runtime.database.session() as session:
        participants = _board(session, exclude=subject)
        meeting = runtime.chair.convene(
            session,
            meeting_type=MeetingType.BOARD,
            subject=f"Fission: split {len(charters)} charter(s) off {subject}",
            chair=participants[0],
            participants=participants,
            subject_ref=change_ref,
            trigger=hit.trigger.kind.value,
            evidence={
                "trigger": hit.evidence,
                "predicts": prediction.as_payload(),
                "locked_digest": digest,
                "charters": list(charters),
            },
            at=moment,
        )
        meeting_ref = meeting.ref
        runtime.chair.run(
            session,
            meeting_ref,
            forecast_question=(
                "Will splitting these charters make the subject agent's "
                "outputs attributable per area?"
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
        handover = applied.report.describe() if applied.report else "nothing moved"

    # The new agent is a hire like any other: it runs the scenario suite for
    # its specialty before it works (ADR-0005).
    with runtime.database.session() as session:
        outcome = runtime.onboarding.run(session, new_agent, at=moment)
        if outcome.may_work:
            runtime.roster.set_state(session, new_agent, AgentState.ACTIVE, at=moment)
        verdict = outcome.verdict.value

    with runtime.database.session() as session:
        effect = runtime.orgdev.measure(session, change_ref, at=moment)
        breadth_after = int(agent_metrics(session, subject).value("breadth") or 0)
        moved = tuple(charters)
        intact = _coverage_intact(session)

    return OrgStep(
        change_ref=change_ref,
        meeting_ref=meeting_ref,
        subject=subject,
        new_agent=new_agent,
        trigger=hit.trigger.kind,
        trigger_value=str(hit.reading.value),
        predicted=prediction.describe(),
        locked_digest=digest,
        breadth_before=breadth_before,
        breadth_after=breadth_after,
        moved=moved,
        handover=handover,
        new_agent_verdict=verdict,
        effect=effect,
        coverage_intact=intact,
    )


def _breadth_hit(session: Session, charters: tuple[str, ...]) -> TriggerHit:
    """The widest generalist that holds the charters we intend to split.

    Found by scanning, not named: the demonstration must go through the same
    detection the company would, or it would be a script pretending to be a
    measurement.
    """
    hits = [hit for hit in scan(session) if hit.trigger.kind is TriggerKind.BREADTH]
    for hit in sorted(hits, key=lambda h: -(h.reading.value or 0)):
        held = set(
            session.execute(
                sa.text("SELECT charter_id FROM agent_coverage WHERE agent_ref = :a"),
                {"a": hit.subject},
            ).scalars()
        )
        if set(charters) <= held:
            return hit
    raise IntegrityViolation(
        f"no agent triggering on breadth holds all of {sorted(charters)}; the "
        "company has already been split further than this expects"
    )


def _proposer(session: Session, subject: str) -> str:
    """The Org Development Lead, who may not be the change's subject."""
    ref = session.execute(
        sa.text(
            "SELECT agent_ref FROM agent_coverage WHERE charter_id = "
            "'exec.org_development'"
        )
    ).scalar_one_or_none()
    if ref is None or ref == subject:
        raise IntegrityViolation(
            "the Org Development charter is unheld, or held by the very agent "
            "this change is about. An agent may not propose a change to its "
            "own record (ADR-0003)."
        )
    return str(ref)


def _chair_of(session: Session) -> str:
    ref = session.execute(
        sa.text(
            "SELECT agent_ref FROM agent_coverage WHERE charter_id = "
            "'exec.chief_of_staff'"
        )
    ).scalar_one()
    return str(ref)


def _board(session: Session, *, exclude: str) -> tuple[str, ...]:
    """Who sits on the Board. The Chair first; the subject is not in the room."""
    wanted = (
        "exec.chief_of_staff",
        "exec.company_manager",
        "exec.org_development",
        "audit.chief",
        "gov.director",
    )
    seats: list[str] = []
    for charter_id in wanted:
        ref = session.execute(
            sa.text("SELECT agent_ref FROM agent_coverage WHERE charter_id = :c"),
            {"c": charter_id},
        ).scalar_one_or_none()
        if ref and ref != exclude and ref not in seats:
            seats.append(str(ref))
    if not seats:
        raise IntegrityViolation("nobody can sit on the Board")
    return tuple(seats)


def _coverage_intact(session: Session) -> bool:
    """Every charter in the registry is held by exactly one working agent.

    The invariant ADR-0003 promises, checked after the split rather than
    assumed from the fact that the split used an UPDATE.
    """
    from aurelis.org.charters import CHARTERS

    rows = session.execute(
        sa.text(
            "SELECT c.charter_id, COUNT(*) FROM agent_coverage c "
            "JOIN agents a ON a.ref = c.agent_ref "
            "WHERE a.state <> 'retired' GROUP BY c.charter_id"
        )
    ).all()
    holders = {str(charter_id): int(count) for charter_id, count in rows}
    return set(holders) == set(CHARTERS) and all(
        count == 1 for count in holders.values()
    )


def working_agents(session: Session) -> int:
    return int(
        session.execute(
            sa.select(sa.func.count())
            .select_from(Agent)
            .where(Agent.state != AgentState.RETIRED)
        ).scalar_one()
    )
