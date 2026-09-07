"""M13's demonstration: the company staffs six desks, on evidence, and is measured.

.. code-block:: text

    census                    154 slots exist; 78 are held by nobody
    DESK_UNSTAFFED fires      once per open, unstaffed desk
    for each desk:
        propose               a team, predicting unstaffed_slots falls to zero
        lock                  hashed before the Board sees it
        Board                 decides
        apply                 the team is hired and onboarded
        measure               the predicted metric, again
    census                    every slot held, exactly once

Six changes, six Board meetings, thirty new agents. Not eighty: each desk is
staffed the way the launch roster staffed crypto, with one generalist per
department that has desk-specific charters. Hiring a specialist per charter
would have produced the roadmap's headline number and would have been the
assumption `CLAUDE.md` §16 exists to forbid.

**The scale claim is proved separately, and honestly.** ADR-0003 promised the
runtime never changes as the company grows. That is a claim about the software,
not about how many people the company chose to employ, and it is tested as one:
:func:`prove_scale` hires into every one of the 154 slots as a dedicated
specialist and checks that coverage stays intact, permissions still resolve and
the write-scope guards still refuse. The company runs at 49; the machinery is
shown to run at 154.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from aurelis.agents.tables import Agent, AgentState
from aurelis.meetings.types import MeetingType
from aurelis.org.desks import Desk
from aurelis.org.slots import census
from aurelis.orgdev.development import MeasuredEffect, Prediction
from aurelis.orgdev.staffing import hire_for, staffing_plan, unstaffed_desks
from aurelis.orgdev.states import OrgChangeKind
from aurelis.runtime import Runtime

__all__ = ["DeskHiring", "ScalingOutcome", "run_scaling"]


@dataclass(frozen=True, slots=True)
class DeskHiring:
    """One desk, staffed through the org-change lifecycle."""

    desk: str
    change_ref: str
    meeting_ref: str
    hired: tuple[str, ...]
    slots_before: int
    slots_after: int
    effect: MeasuredEffect
    onboarding: dict[str, str]

    def describe(self) -> str:
        return (
            f"{self.desk:<12} {self.change_ref}  {len(self.hired)} hired, "
            f"{self.slots_before} -> {self.slots_after} unstaffed  "
            f"{self.effect.verdict.value}"
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "desk": self.desk,
            "change": self.change_ref,
            "meeting": self.meeting_ref,
            "hired": list(self.hired),
            "slots_before": self.slots_before,
            "slots_after": self.slots_after,
            "effect": self.effect.verdict.value,
            "onboarding": dict(self.onboarding),
        }


@dataclass(frozen=True, slots=True)
class ScalingOutcome:
    """What staffing the desks established."""

    hirings: tuple[DeskHiring, ...]
    agents_before: int
    agents_after: int
    slots_total: int
    unstaffed_before: int
    unstaffed_after: int
    coverage_intact: bool

    @property
    def hired(self) -> int:
        return sum(len(h.hired) for h in self.hirings)

    @property
    def verdicts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for hiring in self.hirings:
            key = hiring.effect.verdict.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def describe(self) -> str:
        return (
            f"{self.agents_before} -> {self.agents_after} agents over "
            f"{len(self.hirings)} desk(s); {self.unstaffed_before} -> "
            f"{self.unstaffed_after} unstaffed slots of {self.slots_total}; "
            f"verdicts {self.verdicts}"
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "hirings": [h.as_payload() for h in self.hirings],
            "agents_before": self.agents_before,
            "agents_after": self.agents_after,
            "slots_total": self.slots_total,
            "unstaffed_before": self.unstaffed_before,
            "unstaffed_after": self.unstaffed_after,
            "coverage_intact": self.coverage_intact,
        }


def run_scaling(runtime: Runtime, *, at: dt.datetime | None = None) -> ScalingOutcome:
    """Staff every open, unstaffed desk through the org-change lifecycle."""
    moment = at or runtime.clock.now()

    with runtime.database.session() as session:
        before = _headcount(session)
        taken = census(session)
        slots_total = len(taken.required)
        unstaffed_before = len(taken.unstaffed)
        hits = unstaffed_desks(session)

    hirings: list[DeskHiring] = []
    for hit in hits:
        hirings.append(_staff_one_desk(runtime, hit, at=moment))

    with runtime.database.session() as session:
        after = _headcount(session)
        final = census(session)

    return ScalingOutcome(
        hirings=tuple(hirings),
        agents_before=before,
        agents_after=after,
        slots_total=slots_total,
        unstaffed_before=unstaffed_before,
        unstaffed_after=len(final.unstaffed),
        coverage_intact=final.intact,
    )


def _staff_one_desk(runtime: Runtime, hit: Any, *, at: dt.datetime) -> DeskHiring:
    desk = Desk(hit.subject)
    slots_before = int(hit.reading.value or 0)

    with runtime.database.session() as session:
        plan = staffing_plan(session, desk)
        proposer = _org_development(session)
        prediction = Prediction(
            metric="unstaffed_slots",
            direction="down",
            magnitude=Decimal(slots_before),
            plan=(
                "Count the slots on this desk that nobody holds, before the "
                "hires and again after. The desk is fully staffed only if it "
                "reaches zero, so a partial team does not satisfy this."
            ),
            after_days=0,
            subject=desk.value,
        )
        change = runtime.orgdev.propose(
            session,
            hit=hit,
            proposed_by=proposer,
            prediction=prediction,
            justification=(
                f"The {desk.value} desk is open and {slots_before} of its jobs "
                "are held by nobody. It is staffed the way the launch roster "
                f"staffed crypto: {len(plan)} generalist(s), one per "
                "department with desk-specific charters here. Not one "
                "specialist per charter -- a desk on fixture data generates no "
                "load, and hiring for load that does not exist is the "
                "assumption this company measures rather than makes."
            ),
            new_handle=plan[0].handle if plan else None,
            kind=OrgChangeKind.HIRE,
            at=at,
        )
        change_ref = change.ref
        runtime.orgdev.lock(session, change_ref, at=at)

    with runtime.database.session() as session:
        participants = _board(session)
        meeting = runtime.chair.convene(
            session,
            meeting_type=MeetingType.BOARD,
            subject=f"Staff the {desk.value} desk: {len(plan)} generalists",
            chair=participants[0],
            participants=participants,
            subject_ref=change_ref,
            trigger=hit.trigger.kind.value,
            evidence={
                "trigger": hit.evidence,
                "plan": [entry.as_payload() for entry in plan],
                "predicts": prediction.as_payload(),
            },
            at=at,
        )
        meeting_ref = meeting.ref
        runtime.chair.run(
            session,
            meeting_ref,
            forecast_question=(
                f"Will {len(plan)} generalists cover every open slot on the "
                f"{desk.value} desk?"
            ),
            at=at,
        )
        runtime.orgdev.decide(
            session,
            change_ref,
            approved=True,
            decided_by=_chief_of_staff(session),
            meeting_ref=meeting_ref,
            at=at,
        )

    # apply() FIRST, then hire. The baseline is read at the top of apply(),
    # immediately before the change -- so hiring beforehand would read the
    # baseline from the already-staffed desk and the change would measure
    # itself as having done nothing. The org-change machinery moves coverage
    # for a fission; a hire creates it, so the creation happens here.
    hired: list[str] = []
    with runtime.database.session() as session:
        runtime.orgdev.apply(session, change_ref, at=at)
    with runtime.database.session() as session:
        for entry in plan:
            hired.append(hire_for(runtime, session, entry, hired_by=change_ref, at=at))

    onboarding: dict[str, str] = {}
    for ref in hired:
        with runtime.database.session() as session:
            outcome = runtime.onboarding.run(session, ref, at=at)
            onboarding[ref] = outcome.verdict.value
            if outcome.may_work:
                runtime.roster.set_state(session, ref, AgentState.ACTIVE, at=at)
            else:
                runtime.roster.set_state(session, ref, AgentState.RETRAINING, at=at)

    with runtime.database.session() as session:
        effect = runtime.orgdev.measure(session, change_ref, at=at)
        remaining = [s for s in census(session).unstaffed if s.desk == desk.value]

    return DeskHiring(
        desk=desk.value,
        change_ref=change_ref,
        meeting_ref=meeting_ref,
        hired=tuple(hired),
        slots_before=slots_before,
        slots_after=len(remaining),
        effect=effect,
        onboarding=onboarding,
    )


def _headcount(session: Any) -> int:
    return int(
        session.execute(
            sa.select(sa.func.count())
            .select_from(Agent)
            .where(Agent.state != AgentState.RETIRED)
        ).scalar_one()
    )


def _org_development(session: Any) -> str:
    ref = session.execute(
        sa.text(
            "SELECT agent_ref FROM agent_coverage WHERE charter_id = "
            "'exec.org_development'"
        )
    ).scalar_one()
    return str(ref)


def _chief_of_staff(session: Any) -> str:
    ref = session.execute(
        sa.text(
            "SELECT agent_ref FROM agent_coverage WHERE charter_id = "
            "'exec.chief_of_staff'"
        )
    ).scalar_one()
    return str(ref)


def _board(session: Any) -> tuple[str, ...]:
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
        if ref and ref not in seats:
            seats.append(str(ref))
    return tuple(seats)
