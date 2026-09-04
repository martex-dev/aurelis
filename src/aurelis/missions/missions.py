"""Opening missions, decomposing them, and closing them honestly.

The service that owns the three-level hierarchy. Three things it does that are
worth stating plainly.

**It enforces the kickoff and retrospective gates.** ``PLANNING → ACTIVE``
without a kickoff is refused; ``REVIEWING → CLOSED`` without a retrospective is
refused. Meeting at the start and the end is a property of the state machine.

**It computes progress rather than accepting it.** ``Progress`` reports
finished, failed and refused separately. Nothing in this module can be asked to
report a single reassuring percentage.

**It splits budgets downward.** A project's allowance comes out of its
mission's, so a runaway project exhausts itself rather than the company.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, BudgetPeriod, BudgetScope, EventKind, TaskStatus
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import RefKind, uuid7
from aurelis.missions.states import (
    KickoffKind,
    MissionState,
    ProjectState,
    may_transition,
)
from aurelis.missions.tables import Kickoff, Mission, Project, Retrospective, WorkItem
from aurelis.platform.artifacts.store import ArtifactStore
from aurelis.platform.budget.ledger import BudgetEnvelope, BudgetLedger, Spend
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.db.tables import Task
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["Missions", "Progress"]


@dataclass(frozen=True, slots=True)
class Progress:
    """How a mission or project is actually going.

    Deliberately not a single number. ``fraction_finished`` counts every
    terminal outcome, and the failures are carried alongside it so a caller
    cannot report progress without also being able to report what went wrong.
    """

    total: int
    succeeded: int
    failed: int
    refused_budget: int
    cancelled: int
    in_flight: int

    @property
    def finished(self) -> int:
        return self.succeeded + self.failed + self.refused_budget + self.cancelled

    @property
    def fraction_finished(self) -> float:
        return self.finished / self.total if self.total else 0.0

    def describe(self) -> str:
        if not self.total:
            return "no work yet"
        parts = [f"{self.succeeded}/{self.total} succeeded"]
        if self.failed:
            parts.append(f"{self.failed} failed")
        if self.refused_budget:
            parts.append(f"{self.refused_budget} refused for budget")
        if self.cancelled:
            parts.append(f"{self.cancelled} cancelled")
        if self.in_flight:
            parts.append(f"{self.in_flight} in flight")
        return ", ".join(parts)


class Missions:
    """Missions, projects, and the work items that connect them to tasks."""

    __slots__ = ("_artifacts", "_budget", "_clock", "_ledger")

    def __init__(
        self,
        artifacts: ArtifactStore,
        budget: BudgetLedger,
        ledger: Ledger | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._budget = budget
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)

    # -------------------------------------------------------------- opening

    def open_mission(
        self,
        session: Session,
        *,
        objective: str,
        scope: str = "",
        rationale: str = "",
        owner_agent: str | None = None,
        departments: tuple[str, ...] = (),
        desks: tuple[str, ...] = (),
        budget_tokens: int = 0,
        budget_usd: Decimal = Decimal("0"),
        priority: int = 100,
        deadline: dt.datetime | None = None,
        at: dt.datetime | None = None,
    ) -> Mission:
        """Open a mission in PLANNING. It cannot work until it has a kickoff."""
        moment = at or self._clock.now()
        ref = allocate_ref(session, RefKind.MISSION)

        mission = Mission(
            mission_id=uuid7(),
            ref=ref,
            objective=objective,
            scope=scope,
            rationale=rationale,
            priority=priority,
            owner_agent=owner_agent,
            departments=list(departments),
            desks=list(desks),
            state=MissionState.PLANNING,
            budget_usd=budget_usd,
            budget_tokens=budget_tokens,
            deadline=deadline,
            opened_at=moment,
        )
        session.add(mission)
        session.flush()

        self._budget.open(
            session,
            scope=BudgetScope.MISSION,
            scope_id=ref,
            usd=budget_usd,
            tokens=budget_tokens,
            period=BudgetPeriod.LIFETIME,
            at=moment,
        )
        self._ledger.append(
            session,
            kind=EventKind.MISSION_OPENED,
            actor=owner_agent or Actor.OPERATOR,
            subject=ref,
            payload={
                "objective": objective[:200],
                "departments": list(departments),
                "desks": list(desks),
                "budget_tokens": budget_tokens,
            },
            at=moment,
        )
        return mission

    def open_project(
        self,
        session: Session,
        *,
        mission_ref: str,
        name: str,
        intent: str = "",
        lead_agent: str | None = None,
        desk: str | None = None,
        budget_tokens: int = 0,
        budget_usd: Decimal = Decimal("0"),
        at: dt.datetime | None = None,
    ) -> Project:
        """Open a project under a mission, taking a slice of its budget."""
        moment = at or self._clock.now()
        mission = self.mission(session, mission_ref)

        if mission.state in (MissionState.CLOSED, MissionState.CANCELLED):
            raise IntegrityViolation(
                f"mission {mission_ref} is {mission.state}; no further projects"
            )

        allocated = self._allocated_to_projects(session, mission_ref)
        if mission.budget_tokens and allocated + budget_tokens > mission.budget_tokens:
            raise IntegrityViolation(
                f"project budget {budget_tokens} would take mission {mission_ref} "
                f"to {allocated + budget_tokens} tokens against its "
                f"{mission.budget_tokens}; a project cannot spend the company's "
                "money on the mission's behalf"
            )

        ref = allocate_ref(session, RefKind.PROJECT)
        project = Project(
            project_id=uuid7(),
            ref=ref,
            mission_ref=mission_ref,
            name=name,
            intent=intent,
            lead_agent=lead_agent,
            desk=desk,
            state=ProjectState.PLANNING,
            budget_usd=budget_usd,
            budget_tokens=budget_tokens,
            opened_at=moment,
        )
        session.add(project)
        session.flush()

        self._budget.open(
            session,
            scope=BudgetScope.PROJECT,
            scope_id=ref,
            usd=budget_usd,
            tokens=budget_tokens,
            period=BudgetPeriod.LIFETIME,
            at=moment,
        )
        self._ledger.append(
            session,
            kind=EventKind.PROJECT_OPENED,
            actor=lead_agent or Actor.OPERATOR,
            subject=ref,
            payload={
                "mission": mission_ref,
                "name": name,
                "lead": lead_agent,
                "desk": desk,
                "budget_tokens": budget_tokens,
            },
            at=moment,
        )
        return project

    # -------------------------------------------------------------- kickoff

    def record_kickoff(
        self,
        session: Session,
        *,
        subject_ref: str,
        plan: str,
        participants: tuple[str, ...] = (),
        kind: KickoffKind = KickoffKind.OPERATOR,
        authorised_by: str = "operator",
        at: dt.datetime | None = None,
    ) -> Kickoff:
        """Record the plan a mission or project starts from.

        This is what satisfies the kickoff gate. At M3 a Kickoff meeting calls
        this with ``kind=MEETING`` and its own participants; the gate is
        unchanged, only who can satisfy it.
        """
        moment = at or self._clock.now()
        if not plan.strip():
            raise IntegrityViolation(
                "a kickoff must carry a plan; an empty one would satisfy the "
                "gate without doing the thing the gate exists for"
            )

        ref = allocate_ref(session, RefKind.MEETING)
        stored = self._artifacts.put_json(
            session,
            {
                "subject": subject_ref,
                "kind": kind.value,
                "plan": plan,
                "participants": list(participants),
                "authorised_by": authorised_by,
            },
            kind="kickoff",
            produced_by=subject_ref,
        )
        session.add(
            Kickoff(
                kickoff_id=uuid7(),
                ref=ref,
                subject_ref=subject_ref,
                kind=kind.value,
                plan=plan,
                participants=list(participants),
                authorised_by=authorised_by,
                artifact_digest=stored.digest,
                created_at=moment,
            )
        )
        session.flush()

        target = self._subject(session, subject_ref)
        target.kickoff_ref = ref
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.KICKOFF_RECORDED,
            actor=authorised_by,
            subject=subject_ref,
            payload={
                "kickoff": ref,
                "kind": kind.value,
                "participants": list(participants),
                "artifact": stored.digest[:12],
            },
            at=moment,
        )
        return session.execute(sa.select(Kickoff).where(Kickoff.ref == ref)).scalar_one()

    def record_retrospective(
        self,
        session: Session,
        *,
        subject_ref: str,
        summary: str,
        lessons: tuple[str, ...] = (),
        kind: KickoffKind = KickoffKind.OPERATOR,
        authorised_by: str = "operator",
        at: dt.datetime | None = None,
    ) -> Retrospective:
        """Record what was learned, with the outcome counts as they were."""
        moment = at or self._clock.now()
        progress = self.progress(session, subject_ref)
        counts = {
            "total": progress.total,
            "succeeded": progress.succeeded,
            "failed": progress.failed,
            "refused_budget": progress.refused_budget,
            "cancelled": progress.cancelled,
        }

        ref = allocate_ref(session, RefKind.MEETING)
        stored = self._artifacts.put_json(
            session,
            {
                "subject": subject_ref,
                "summary": summary,
                "lessons": list(lessons),
                "outcomes": counts,
            },
            kind="retrospective",
            produced_by=subject_ref,
        )
        session.add(
            Retrospective(
                retrospective_id=uuid7(),
                ref=ref,
                subject_ref=subject_ref,
                kind=kind.value,
                summary=summary,
                lessons=list(lessons),
                outcome_counts=counts,
                authorised_by=authorised_by,
                artifact_digest=stored.digest,
                created_at=moment,
            )
        )
        session.flush()

        target = self._subject(session, subject_ref)
        target.retrospective_ref = ref
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.RETROSPECTIVE_RECORDED,
            actor=authorised_by,
            subject=subject_ref,
            payload={"retrospective": ref, "outcomes": counts, "lessons": len(lessons)},
            at=moment,
        )
        return session.execute(
            sa.select(Retrospective).where(Retrospective.ref == ref)
        ).scalar_one()

    # ----------------------------------------------------------- transitions

    def transition(
        self,
        session: Session,
        subject_ref: str,
        target: MissionState | ProjectState,
        *,
        reason: str = "",
        actor: str = "operator",
        at: dt.datetime | None = None,
    ) -> None:
        """Move a mission or project, enforcing the gates."""
        moment = at or self._clock.now()
        subject = self._subject(session, subject_ref)
        is_project = isinstance(subject, Project)
        current = subject.state

        if not may_transition(current, target.value, project=is_project):
            raise IntegrityViolation(
                f"{subject_ref} cannot go {current} -> {target.value}"
            )

        if target in (MissionState.ACTIVE, ProjectState.ACTIVE) and current in (
            MissionState.PLANNING,
            ProjectState.PLANNING,
        ):
            if subject.kickoff_ref is None:
                raise IntegrityViolation(
                    f"{subject_ref} cannot start work without a kickoff. "
                    "Meeting at the start is a property of the state machine, "
                    "not a convention -- record one with `record_kickoff`."
                )
            if isinstance(subject, Mission):
                subject.activated_at = moment

        if target in (MissionState.CLOSED, ProjectState.CLOSED):
            if subject.retrospective_ref is None:
                raise IntegrityViolation(
                    f"{subject_ref} cannot close without a retrospective. "
                    "What was learned is the point of finishing."
                )
            subject.closed_at = moment
            subject.closure_reason = reason

        if target in (MissionState.CANCELLED, ProjectState.CANCELLED):
            if not reason.strip():
                raise IntegrityViolation(
                    f"cancelling {subject_ref} requires a stated reason"
                )
            subject.closed_at = moment
            subject.closure_reason = reason

        subject.state = target.value
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.MISSION_STATE_CHANGED
            if isinstance(subject, Mission)
            else EventKind.PROJECT_STATE_CHANGED,
            actor=actor,
            subject=subject_ref,
            payload={"from": current, "to": target.value, "reason": reason},
            at=moment,
        )

    # ----------------------------------------------------------------- work

    def place(
        self,
        session: Session,
        *,
        task_ref: str,
        project_ref: str,
        step: int = 0,
        at: dt.datetime | None = None,
    ) -> WorkItem:
        """Record that a task belongs to a project."""
        project = self.project(session, project_ref)
        item = WorkItem(
            task_ref=task_ref,
            mission_ref=project.mission_ref,
            project_ref=project_ref,
            step=step,
            created_at=at or self._clock.now(),
        )
        session.add(item)
        session.flush()
        return item

    def envelope_for(self, session: Session, project_ref: str) -> BudgetEnvelope:
        """The budget scopes work in this project counts against."""
        from aurelis.runtime import COMPANY_SCOPE_ID

        project = self.project(session, project_ref)
        return BudgetEnvelope(
            company=COMPANY_SCOPE_ID,
            mission=project.mission_ref,
            project=project_ref,
        )

    # ------------------------------------------------------------- progress

    def progress(self, session: Session, subject_ref: str) -> Progress:
        """Task outcomes for a mission or project. Computed, never asserted."""
        column = (
            WorkItem.project_ref if subject_ref.startswith("PRJ-") else WorkItem.mission_ref
        )
        rows = session.execute(
            sa.select(Task.status, sa.func.count())
            .join(WorkItem, WorkItem.task_ref == Task.ref)
            .where(column == subject_ref)
            .group_by(Task.status)
        ).all()
        counts = {str(status): int(count) for status, count in rows}
        total = sum(counts.values())
        return Progress(
            total=total,
            succeeded=counts.get(TaskStatus.SUCCEEDED, 0),
            failed=counts.get(TaskStatus.FAILED, 0),
            refused_budget=counts.get(TaskStatus.REFUSED_BUDGET, 0),
            cancelled=counts.get(TaskStatus.CANCELLED, 0),
            in_flight=counts.get(TaskStatus.QUEUED, 0) + counts.get(TaskStatus.CLAIMED, 0),
        )

    def spent(self, session: Session, subject_ref: str) -> Spend:
        scope = BudgetScope.PROJECT if subject_ref.startswith("PRJ-") else BudgetScope.MISSION
        return self._budget.spent(session, scope, subject_ref)

    # -------------------------------------------------------------- reading

    def mission(self, session: Session, ref: str) -> Mission:
        row = session.execute(sa.select(Mission).where(Mission.ref == ref)).scalar_one_or_none()
        if row is None:
            raise KeyError(f"no mission {ref!r}")
        return row

    def project(self, session: Session, ref: str) -> Project:
        row = session.execute(sa.select(Project).where(Project.ref == ref)).scalar_one_or_none()
        if row is None:
            raise KeyError(f"no project {ref!r}")
        return row

    def missions(self, session: Session) -> list[Mission]:
        return list(
            session.execute(sa.select(Mission).order_by(Mission.ref)).scalars().all()
        )

    def projects(self, session: Session, mission_ref: str) -> list[Project]:
        return list(
            session.execute(
                sa.select(Project)
                .where(Project.mission_ref == mission_ref)
                .order_by(Project.ref)
            )
            .scalars()
            .all()
        )

    def work_items(self, session: Session, project_ref: str) -> list[WorkItem]:
        return list(
            session.execute(
                sa.select(WorkItem)
                .where(WorkItem.project_ref == project_ref)
                .order_by(WorkItem.step, WorkItem.task_ref)
            )
            .scalars()
            .all()
        )

    # -------------------------------------------------------------- helpers

    def _subject(self, session: Session, ref: str) -> Mission | Project:
        if ref.startswith("PRJ-"):
            return self.project(session, ref)
        return self.mission(session, ref)

    @staticmethod
    def _allocated_to_projects(session: Session, mission_ref: str) -> int:
        total = session.execute(
            sa.select(sa.func.coalesce(sa.func.sum(Project.budget_tokens), 0)).where(
                Project.mission_ref == mission_ref
            )
        ).scalar_one()
        return int(total)
