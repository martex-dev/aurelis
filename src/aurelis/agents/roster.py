"""Hiring, coverage, and resolved authority.

Hiring is an ``INSERT``. That is the point of ADR-0003: the company grows from
seventeen agents to a hundred without the runtime changing, because an agent is
a row and a charter is a registry entry.

Every hire is recorded with who authorised it. At M1 that is the operator; at
M11 it becomes an ``OrgChange`` carrying the trigger evidence, the predicted
effect and the measurement plan, so the company's own structure gets a version
history exactly like a strategy does.

**An agent may not modify its own record.** Not its coverage, not its
permissions, not its metrics. Self-modification would make the growth mechanism
unauditable — an agent that could grant itself a charter could grant itself any
authority in the company.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.agents.tables import Agent, AgentCoverage, AgentState
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import RefKind, uuid7
from aurelis.org.charters import Seniority
from aurelis.org.departments import Department
from aurelis.org.desks import Desk
from aurelis.org.registry import ResolvedAuthority, resolve_authority
from aurelis.org.roster import LAUNCH_ROSTER
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["Roster", "StaffedAgent"]


@dataclass(frozen=True, slots=True)
class StaffedAgent:
    """An agent plus its resolved authority — what the runtime works with."""

    ref: str
    handle: str
    department: Department
    desk: Desk | None
    state: AgentState
    authority: ResolvedAuthority

    @property
    def coverage(self) -> tuple[str, ...]:
        return self.authority.coverage


class Roster:
    """Hires agents and answers what they are allowed to do."""

    __slots__ = ("_clock", "_ledger")

    def __init__(self, ledger: Ledger | None = None, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    # -------------------------------------------------------------- hiring

    def hire(
        self,
        session: Session,
        *,
        handle: str,
        department: Department,
        coverage: tuple[str, ...],
        seniority: Seniority,
        desk: Desk | None = None,
        note: str = "",
        daily_token_budget: int = 0,
        daily_usd_budget: Decimal = Decimal("0"),
        hired_by: str = "operator",
        at: dt.datetime | None = None,
    ) -> StaffedAgent:
        """Add an agent to the company.

        Coverage is resolved *before* the row is written, so a hire naming a
        charter that does not exist fails before anything is recorded.
        """
        moment = at or self._clock.now()
        authority = resolve_authority(coverage, seniority)

        clashing = session.execute(
            sa.select(Agent.ref).where(Agent.handle == handle)
        ).scalar_one_or_none()
        if clashing is not None:
            raise IntegrityViolation(
                f"handle {handle!r} is already used by {clashing}; handles are "
                "what colleagues say out loud and must be unambiguous"
            )

        held = self._held_charters(session)
        overlap = sorted(set(coverage) & set(held))
        if overlap:
            owners = ", ".join(f"{c} (held by {held[c]})" for c in overlap)
            raise IntegrityViolation(
                f"cannot hire {handle}: {owners}. A charter has one owner; "
                "transferring it is a fission, not a second hire."
            )

        ref = allocate_ref(session, RefKind.AGENT)
        session.add(
            Agent(
                agent_id=uuid7(),
                ref=ref,
                handle=handle,
                department=department.value,
                desk=desk.value if desk else None,
                seniority=seniority.value,
                tier=authority.tier.value,
                state=AgentState.HIRED,
                daily_token_budget=daily_token_budget,
                daily_usd_budget=str(daily_usd_budget),
                hired_at=moment,
                hired_by=hired_by,
                note=note,
            )
        )
        session.flush()

        for charter_id in coverage:
            session.add(
                AgentCoverage(
                    agent_ref=ref,
                    charter_id=charter_id,
                    granted_at=moment,
                    granted_by=hired_by,
                )
            )
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.AGENT_HIRED,
            actor=Actor.OPERATOR if hired_by == "operator" else hired_by,
            subject=ref,
            payload={
                "handle": handle,
                "department": department.value,
                "desk": desk.value if desk else None,
                "seniority": seniority.value,
                "tier": authority.tier.value,
                "coverage": list(coverage),
                "stands_in_for": len(coverage),
            },
            at=moment,
        )
        return StaffedAgent(ref, handle, department, desk, AgentState.HIRED, authority)

    def hire_launch_roster(
        self, session: Session, *, at: dt.datetime | None = None
    ) -> list[StaffedAgent]:
        """Staff the company from :data:`aurelis.org.roster.LAUNCH_ROSTER`.

        Idempotent: an already-staffed company is returned unchanged rather
        than duplicated.
        """
        if session.execute(sa.select(sa.func.count()).select_from(Agent)).scalar_one():
            return self.all(session)
        return [
            self.hire(
                session,
                handle=entry.handle,
                department=entry.department,
                coverage=entry.coverage,
                seniority=entry.seniority,
                desk=entry.desk,
                note=entry.note,
                at=at,
            )
            for entry in LAUNCH_ROSTER
        ]

    # ------------------------------------------------------------- lifecycle

    def set_state(
        self,
        session: Session,
        ref: str,
        state: AgentState,
        *,
        at: dt.datetime | None = None,
    ) -> None:
        moment = at or self._clock.now()
        agent = self._row(session, ref)
        previous, agent.state = agent.state, state.value
        if state is AgentState.ACTIVE and agent.onboarded_at is None:
            agent.onboarded_at = moment
        if state is AgentState.SUSPENDED:
            agent.suspended_at = moment
        if state is AgentState.RETIRED:
            agent.retired_at = moment
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.AGENT_STATE_CHANGED,
            actor=Actor.SYSTEM,
            subject=ref,
            payload={"from": previous, "to": state.value},
            at=moment,
        )

    def onboard_all(
        self,
        session: Session,
        *,
        at: dt.datetime | None = None,
        onboarding: Any | None = None,
    ) -> int:
        """Score newly hired agents, then move the ones that may work to ACTIVE.

        This is the M10 gate (ADR-0005). Each pending agent runs the
        training-scenario suite for its specialty; the result becomes its
        starting record; an agent whose record says ``failed`` stays where it
        is. The refusal is not enforced here -- a trigger on ``agents`` refuses
        the transition (:mod:`aurelis.training.triggers`), so a code path that
        skipped this method could not sneak one through.

        ``onboarding`` is optional so the roster keeps working without the
        training layer. Passing ``None`` activates everybody **without a
        record**, and the count returned is of agents moved, not of agents
        certified -- the two were the same thing before M10 and are not any
        more.
        """
        moment = at or self._clock.now()
        pending = (
            session.execute(sa.select(Agent).where(Agent.state == AgentState.HIRED))
            .scalars()
            .all()
        )
        moved = 0
        for agent in pending:
            if onboarding is None:
                self.set_state(session, agent.ref, AgentState.ACTIVE, at=moment)
                moved += 1
                continue
            self.set_state(session, agent.ref, AgentState.ONBOARDING, at=moment)
            outcome = onboarding.run(session, agent.ref, at=moment)
            if outcome.may_work:
                self.set_state(session, agent.ref, AgentState.ACTIVE, at=moment)
                moved += 1
            else:
                self.set_state(session, agent.ref, AgentState.RETRAINING, at=moment)
        return moved

    # -------------------------------------------------------------- reading

    def get(self, session: Session, ref: str) -> StaffedAgent:
        agent = self._row(session, ref)
        return self._staffed(session, agent)

    def by_handle(self, session: Session, handle: str) -> StaffedAgent:
        agent = session.execute(
            sa.select(Agent).where(Agent.handle == handle)
        ).scalar_one_or_none()
        if agent is None:
            raise KeyError(f"no agent with handle {handle!r}")
        return self._staffed(session, agent)

    def all(self, session: Session) -> list[StaffedAgent]:
        rows = session.execute(sa.select(Agent).order_by(Agent.ref)).scalars().all()
        return [self._staffed(session, row) for row in rows]

    def workable(self, session: Session) -> list[StaffedAgent]:
        rows = (
            session.execute(
                sa.select(Agent).where(Agent.state == AgentState.ACTIVE).order_by(Agent.ref)
            )
            .scalars()
            .all()
        )
        return [self._staffed(session, row) for row in rows]

    def coverage_of(self, session: Session, ref: str) -> tuple[str, ...]:
        rows = (
            session.execute(
                sa.select(AgentCoverage.charter_id)
                .where(AgentCoverage.agent_ref == ref)
                .order_by(AgentCoverage.charter_id)
            )
            .scalars()
            .all()
        )
        return tuple(rows)

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _row(session: Session, ref: str) -> Agent:
        agent = session.execute(sa.select(Agent).where(Agent.ref == ref)).scalar_one_or_none()
        if agent is None:
            raise KeyError(f"no agent {ref!r}")
        return agent

    def _staffed(self, session: Session, agent: Agent) -> StaffedAgent:
        coverage = self.coverage_of(session, agent.ref)
        return StaffedAgent(
            ref=agent.ref,
            handle=agent.handle,
            department=Department(agent.department),
            desk=Desk(agent.desk) if agent.desk else None,
            state=AgentState(agent.state),
            authority=resolve_authority(coverage, Seniority(agent.seniority)),
        )

    @staticmethod
    def _held_charters(session: Session) -> dict[str, str]:
        return {
            charter_id: agent_ref
            for charter_id, agent_ref in session.execute(
                sa.select(AgentCoverage.charter_id, AgentCoverage.agent_ref)
            )
        }
