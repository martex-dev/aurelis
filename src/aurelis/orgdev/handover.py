"""Fission and fusion: coverage moves, and everything attached to it moves too.

The one design decision that makes this safe is that **coverage is never
deleted and recreated**. A split is a single ``UPDATE`` moving rows from one
agent to another, so at no instant is a charter held by nobody, and at no
instant is it held by two people. Delete-then-insert would break the first;
insert-then-delete would break the second. Moving breaks neither, and it leaves
the database free to refuse every deletion that would orphan a charter — which
it does, including the cascade from retiring an agent
(:mod:`aurelis.orgdev.invariants`).

Handover is the rest of the work, and it is the part ADR-0003 warned would be
real:

**Tasks.** Open tasks assigned to the splitting agent, whose subject falls in
the moved area, are reassigned. A task in flight — already claimed — is *not*
moved: taking work out of somebody's hands mid-execution loses whatever they
were part-way through, and the queue has no way to hand that over. Those stay,
and the handover report says how many.

**Channels.** The new agent is enrolled in the department and desk channels its
coverage implies. It is not enrolled in the old agent's channels wholesale: a
generalist's memberships are the union of nine roles, and copying them would
give a specialist eight rooms it has no business in.

**Memory scope.** Read views and write scopes are *resolved from coverage*, not
stored, so they transfer atomically with the charters and nothing has to
remember to move them. That is what ADR-0003 bought.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.agents.tables import Agent, AgentCoverage, AgentState
from aurelis.comms.channels import Comms
from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind, TaskStatus
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import RefKind, uuid7
from aurelis.org.charters import CHARTERS, Seniority
from aurelis.org.departments import Department
from aurelis.org.desks import Desk
from aurelis.org.registry import resolve_authority
from aurelis.orgdev.tables import CoverageTransfer
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.db.tables import Task
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["Handover", "HandoverReport"]


@dataclass(frozen=True, slots=True)
class HandoverReport:
    """What actually moved, and what deliberately did not."""

    charters: tuple[str, ...]
    from_agent: str
    to_agent: str
    tasks_reassigned: tuple[str, ...]
    tasks_left_in_flight: tuple[str, ...]
    channels_joined: tuple[str, ...]

    def as_payload(self) -> dict[str, Any]:
        return {
            "charters": list(self.charters),
            "from": self.from_agent,
            "to": self.to_agent,
            "tasks_reassigned": list(self.tasks_reassigned),
            "tasks_left_in_flight": list(self.tasks_left_in_flight),
            "channels_joined": list(self.channels_joined),
        }

    def describe(self) -> str:
        left = (
            f", {len(self.tasks_left_in_flight)} left in flight"
            if self.tasks_left_in_flight
            else ""
        )
        return (
            f"{len(self.charters)} charter(s) {self.from_agent} -> "
            f"{self.to_agent}; {len(self.tasks_reassigned)} task(s) "
            f"reassigned{left}"
        )


class Handover:
    """Splits and merges agents, moving everything the coverage carries."""

    __slots__ = ("_comms", "_ledger", "_clock")

    def __init__(
        self,
        comms: Comms | None = None,
        ledger: Ledger | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._comms = comms
        self._ledger = ledger or Ledger(self._clock)

    # -------------------------------------------------------------- fission

    def split(
        self,
        session: Session,
        *,
        from_ref: str,
        handle: str,
        charters: tuple[str, ...],
        seniority: Seniority | None = None,
        desk: Desk | None = None,
        change_ref: str | None = None,
        note: str = "",
        at: dt.datetime | None = None,
    ) -> tuple[str, HandoverReport]:
        """Split ``charters`` off ``from_ref`` onto a new agent.

        Returns the new agent's reference and what moved. Refuses to leave the
        original with nothing: an agent stripped of all its coverage is a
        fusion, and calling it a split would hide a retirement inside a growth
        event.
        """
        moment = at or self._clock.now()
        source = self._agent(session, from_ref)
        held = self._coverage(session, from_ref)

        if not charters:
            raise IntegrityViolation("a fission must move at least one charter")
        missing = sorted(set(charters) - set(held))
        if missing:
            raise IntegrityViolation(
                f"{from_ref} does not hold {missing}; a fission may only split "
                "coverage its subject actually has"
            )
        remaining = sorted(set(held) - set(charters))
        if not remaining:
            raise IntegrityViolation(
                f"splitting {sorted(charters)} would leave {from_ref} holding "
                "nothing. Moving an agent's entire coverage is a fusion, and "
                "recording it as a split would hide a retirement inside a "
                "growth event."
            )

        clash = session.execute(
            sa.select(Agent.ref).where(Agent.handle == handle)
        ).scalar_one_or_none()
        if clash is not None:
            raise IntegrityViolation(
                f"handle {handle!r} is already used by {clash}"
            )

        department = self._department_of(charters)
        authority = resolve_authority(charters, seniority or Seniority.SENIOR)

        ref = allocate_ref(session, RefKind.AGENT)
        session.add(
            Agent(
                agent_id=uuid7(),
                ref=ref,
                handle=handle,
                department=department.value,
                desk=(desk or _desk_of(source)),
                team=source.team,
                seniority=(seniority or Seniority.SENIOR).value,
                tier=authority.tier.value,
                # HIRED, not ACTIVE. The new agent runs the training suite
                # before it works, exactly like any other hire (ADR-0005).
                state=AgentState.HIRED,
                hired_at=moment,
                hired_by=change_ref or "org_change",
                note=note or f"split from {from_ref}",
            )
        )
        session.flush()

        report = self._move(
            session,
            charters=tuple(charters),
            from_ref=from_ref,
            to_ref=ref,
            change_ref=change_ref,
            reason="fission",
            department=department,
            desk=desk or _desk_of(source),
            at=moment,
        )

        self._ledger.append(
            session,
            kind=EventKind.ORG_FISSION,
            actor=Actor.SYSTEM,
            subject=from_ref,
            payload={
                "new_agent": ref,
                "handle": handle,
                "change_ref": change_ref,
                "moved": list(charters),
                "retained": remaining,
                "handover": report.as_payload(),
            },
            at=moment,
        )
        return ref, report

    # --------------------------------------------------------------- fusion

    def merge(
        self,
        session: Session,
        *,
        from_ref: str,
        into_ref: str,
        change_ref: str | None = None,
        at: dt.datetime | None = None,
    ) -> HandoverReport:
        """Move all of ``from_ref``'s coverage into ``into_ref`` and retire it.

        The retirement is only possible *after* the coverage has moved: a
        trigger refuses to retire an agent that still holds a charter, and the
        cascade from deleting its coverage rows would be refused too. The order
        here is not a convention — it is the only order the database permits.
        """
        moment = at or self._clock.now()
        self._agent(session, from_ref)
        self._agent(session, into_ref)
        if from_ref == into_ref:
            raise IntegrityViolation("an agent cannot be merged into itself")

        charters = self._coverage(session, from_ref)
        if not charters:
            raise IntegrityViolation(
                f"{from_ref} holds no charters; there is nothing to merge"
            )

        target = self._agent(session, into_ref)
        report = self._move(
            session,
            charters=charters,
            from_ref=from_ref,
            to_ref=into_ref,
            change_ref=change_ref,
            reason="fusion",
            department=Department(target.department),
            desk=target.desk,
            at=moment,
        )

        retired = self._agent(session, from_ref)
        retired.state = AgentState.RETIRED
        retired.retired_at = moment
        session.flush()

        combined = self._coverage(session, into_ref)
        target.tier = resolve_authority(
            combined, Seniority(target.seniority)
        ).tier.value
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.ORG_FUSION,
            actor=Actor.SYSTEM,
            subject=from_ref,
            payload={
                "merged_into": into_ref,
                "change_ref": change_ref,
                "moved": list(charters),
                "handover": report.as_payload(),
                "retained_record": (
                    "everything this agent produced stays in the record "
                    "permanently"
                ),
            },
            at=moment,
        )
        return report

    # -------------------------------------------------------------- moving

    def _move(
        self,
        session: Session,
        *,
        charters: tuple[str, ...],
        from_ref: str,
        to_ref: str,
        change_ref: str | None,
        reason: str,
        department: Department,
        desk: str | None,
        at: dt.datetime,
    ) -> HandoverReport:
        # One UPDATE. Not a delete and an insert: a charter is never held by
        # nobody, and never held by two people.
        session.execute(
            sa.update(AgentCoverage)
            .where(
                AgentCoverage.agent_ref == from_ref,
                AgentCoverage.charter_id.in_(charters),
            )
            .values(agent_ref=to_ref, granted_at=at, granted_by=change_ref or "org")
        )
        for charter_id in charters:
            session.add(
                CoverageTransfer(
                    transfer_id=uuid7(),
                    charter_id=charter_id,
                    from_agent=from_ref,
                    to_agent=to_ref,
                    change_ref=change_ref,
                    reason=reason,
                    transferred_at=at,
                )
            )
        session.flush()

        reassigned, in_flight = self._reassign_tasks(
            session, charters=charters, from_ref=from_ref, to_ref=to_ref
        )
        joined = self._enrol(session, to_ref, department=department, desk=desk, at=at)

        return HandoverReport(
            charters=charters,
            from_agent=from_ref,
            to_agent=to_ref,
            tasks_reassigned=reassigned,
            tasks_left_in_flight=in_flight,
            channels_joined=joined,
        )

    @staticmethod
    def _reassign_tasks(
        session: Session,
        *,
        charters: tuple[str, ...],
        from_ref: str,
        to_ref: str,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Move queued work in the transferred area; leave claimed work alone.

        A claimed task is already part-way through somebody's execution. The
        queue can reassign a row but it cannot hand over what the worker was
        holding in mind, so those are left where they are and *reported*.
        """
        areas = {charter_id.split(".", 1)[0] for charter_id in charters}
        rows = list(
            session.execute(
                sa.select(Task).where(
                    Task.assignee == from_ref,
                    Task.status.in_((TaskStatus.QUEUED, TaskStatus.CLAIMED)),
                )
            ).scalars()
        )
        reassigned: list[str] = []
        in_flight: list[str] = []
        for task in rows:
            relevant = task.kind.split(".", 1)[0] in areas
            if not relevant:
                continue
            if task.status == TaskStatus.CLAIMED:
                in_flight.append(task.ref)
                continue
            task.assignee = to_ref
            reassigned.append(task.ref)
        session.flush()
        return tuple(reassigned), tuple(in_flight)

    def _enrol(
        self,
        session: Session,
        agent_ref: str,
        *,
        department: Department,
        desk: str | None,
        at: dt.datetime,
    ) -> tuple[str, ...]:
        if self._comms is None:
            return ()
        implied = self._comms.enrol(
            session, agent_ref, department=department.value, desk=desk, at=at
        )
        # Only the channels its own coverage implies. A generalist's
        # memberships are the union of nine roles, and copying them wholesale
        # would put a specialist in eight rooms it has no business in.
        return tuple(sorted(implied))

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _agent(session: Session, ref: str) -> Agent:
        row = session.execute(
            sa.select(Agent).where(Agent.ref == ref)
        ).scalar_one_or_none()
        if row is None:
            raise KeyError(f"no agent {ref!r}")
        return row

    @staticmethod
    def _coverage(session: Session, ref: str) -> tuple[str, ...]:
        return tuple(
            session.execute(
                sa.select(AgentCoverage.charter_id)
                .where(AgentCoverage.agent_ref == ref)
                .order_by(AgentCoverage.charter_id)
            ).scalars()
        )

    @staticmethod
    def _department_of(charters: tuple[str, ...]) -> Department:
        departments = {CHARTERS[c].department for c in charters}
        if len(departments) != 1:
            raise IntegrityViolation(
                "a fission may not split coverage across departments: "
                f"{sorted(d.value for d in departments)}. An agent belongs to "
                "one department, and a split that spanned two would create "
                "somebody with no clear reporting line."
            )
        return departments.pop()


def _desk_of(agent: Agent) -> str | None:
    return agent.desk
