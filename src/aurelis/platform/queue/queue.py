"""The durable task queue.

Tasks live in the database, in the same transaction as the ledger. That is
worth one service's worth of inconvenience: a task moving to ``succeeded`` and
the events describing what it produced must commit together or not at all, and
a separate broker cannot promise that.

**Dispatch is where budgets bite.** :meth:`TaskQueue.enqueue` refuses a task
whose allowance the envelope cannot afford, records the refusal as an event,
and *returns the refused task* rather than raising. Budget exhaustion is a
research outcome, not an error condition.

**Failure is recorded, never retried into success.** A worker that could not
produce a valid artifact has told the company something about the worker or
the task; burying that under retries erases the only signal. Infrastructure
failures are a different matter and get their own kind so they can be
requeued deliberately.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import Actor, EventKind, TaskStatus
from aurelis.core.errors import IntegrityViolation
from aurelis.core.ids import RefKind, uuid7
from aurelis.platform.budget.ledger import BudgetEnvelope, BudgetLedger, Spend
from aurelis.platform.db.refs import allocate_ref
from aurelis.platform.db.tables import Task, TaskDependency
from aurelis.platform.ledger.ledger import Ledger

__all__ = ["TaskQueue"]


class TaskQueue:
    """Database-backed queue of work."""

    __slots__ = ("_budget", "_clock", "_ledger")

    def __init__(
        self,
        ledger: Ledger | None = None,
        budget: BudgetLedger | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)
        self._budget = budget or BudgetLedger(self._ledger, self._clock)

    # ------------------------------------------------------------ dispatch

    def enqueue(
        self,
        session: Session,
        *,
        kind: str,
        payload: dict[str, Any] | None = None,
        assignee: str | None = None,
        subject: str | None = None,
        priority: int = 100,
        allowance: Spend | None = None,
        envelope: BudgetEnvelope | None = None,
        depends_on: tuple[str, ...] = (),
        actor: Actor | str = Actor.SYSTEM,
        at: dt.datetime | None = None,
    ) -> Task:
        """Queue a task, refusing it at dispatch if it cannot be afforded.

        ``depends_on`` names tasks that must succeed first. A task with unmet
        dependencies is simply invisible to :meth:`claim` — nothing polls, and
        no orchestrator is needed to sequence a chain of agents.
        """
        moment = at or self._clock.now()
        ref = allocate_ref(session, RefKind.TASK)
        request = allowance or Spend()

        task = Task(
            task_id=uuid7(),
            ref=ref,
            kind=kind,
            assignee=assignee,
            subject=subject,
            priority=priority,
            payload=dict(payload or {}),
            status=TaskStatus.QUEUED,
            allowance_usd=request.usd,
            allowance_tokens=request.tokens,
            budget_scope=None,
            budget_scope_id=None,
            created_at=moment,
        )

        if envelope is not None and not request.is_zero:
            decision = self._budget.check(session, envelope, request, at=moment)
            if not decision.allowed:
                task.status = TaskStatus.REFUSED_BUDGET
                task.failure_reason = decision.describe()
                task.budget_scope = (
                    decision.bound_by.value if decision.bound_by is not None else None
                )
                task.budget_scope_id = decision.bound_scope_id
                task.finished_at = moment
                session.add(task)
                session.flush()
                self._ledger.append(
                    session,
                    kind=EventKind.TASK_REFUSED_BUDGET,
                    actor=actor,
                    subject=ref,
                    payload={
                        "task_kind": kind,
                        "bound_by": task.budget_scope,
                        "scope_id": decision.bound_scope_id,
                        "currency": decision.currency,
                        "reason": decision.describe(),
                    },
                    at=moment,
                )
                return task

        if envelope is not None:
            scopes = envelope.scope_ids()
            task.budget_envelope = {scope.value: value for scope, value in scopes.items()}
            innermost = list(scopes)[-1] if scopes else None
            if innermost is not None:
                task.budget_scope = innermost.value
                task.budget_scope_id = scopes[innermost]

        session.add(task)
        session.flush()

        for upstream in depends_on:
            if upstream == ref:
                raise IntegrityViolation(f"task {ref} cannot depend on itself")
            session.add(
                TaskDependency(task_ref=ref, depends_on_ref=upstream, created_at=moment)
            )
        session.flush()

        self._ledger.append(
            session,
            kind=EventKind.TASK_ENQUEUED,
            actor=actor,
            subject=ref,
            payload={
                "task_kind": kind,
                "assignee": assignee,
                "priority": priority,
                "allowance_usd": str(request.usd),
                "allowance_tokens": request.tokens,
                "depends_on": list(depends_on),
            },
            at=moment,
        )
        return task

    # -------------------------------------------------------------- claiming

    def claim(
        self,
        session: Session,
        *,
        worker: str,
        kinds: tuple[str, ...] = (),
        assignee: str | None = None,
        at: dt.datetime | None = None,
    ) -> Task | None:
        """Claim the highest-priority queued task, or ``None``.

        A task addressed to a specific agent is only claimable by that agent;
        an unaddressed one is claimable by any worker whose kind filter
        matches. On Postgres the row is locked with ``SKIP LOCKED`` so
        multiple workers never claim the same task; SQLite's single-writer
        model gives the same guarantee without it.
        """
        moment = at or self._clock.now()
        query = (
            sa.select(Task)
            .where(Task.status == TaskStatus.QUEUED)
            .order_by(Task.priority, Task.created_at, Task.ref)
            .limit(1)
        )
        if kinds:
            query = query.where(Task.kind.in_(kinds))
        query = query.where(
            Task.assignee.is_(None) if assignee is None else Task.assignee.in_([assignee, None])
        )

        # Unmet dependencies make a task invisible rather than
        # claimable-and-deferred. A worker that claimed a blocked task would
        # have to hold it or hand it back, and both leave the queue lying about
        # what is ready.
        upstream = sa.orm.aliased(Task)
        query = query.where(
            ~sa.exists(
                sa.select(sa.literal(1))
                .select_from(TaskDependency)
                .join(upstream, upstream.ref == TaskDependency.depends_on_ref)
                .where(
                    TaskDependency.task_ref == Task.ref,
                    upstream.status != TaskStatus.SUCCEEDED,
                )
            )
        )

        if session.bind is not None and session.bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)

        task = session.execute(query).scalar_one_or_none()
        if task is None:
            return None

        task.status = TaskStatus.CLAIMED
        task.claimed_by = worker
        task.claimed_at = moment
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.TASK_CLAIMED,
            actor=worker,
            subject=task.ref,
            payload={"task_kind": task.kind},
            at=moment,
        )
        return task

    # ------------------------------------------------------------ finishing

    def succeed(
        self,
        session: Session,
        task: Task,
        *,
        result_digest: str | None = None,
        at: dt.datetime | None = None,
    ) -> Task:
        """Mark a claimed task done, naming the artifact it produced."""
        self._require_claimed(task)
        moment = at or self._clock.now()
        task.status = TaskStatus.SUCCEEDED
        task.result_digest = result_digest
        task.finished_at = moment
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.TASK_SUCCEEDED,
            actor=task.claimed_by or Actor.SYSTEM,
            subject=task.ref,
            payload={"task_kind": task.kind, "result_digest": result_digest},
            at=moment,
        )
        return task

    def fail(
        self,
        session: Session,
        task: Task,
        *,
        reason: str,
        retryable: bool = False,
        at: dt.datetime | None = None,
    ) -> Task:
        """Record a failure.

        ``retryable`` marks an infrastructure problem — a timeout, a dropped
        connection — and requeues. Anything else is terminal, and stays in the
        record as a fact about the worker or the task.
        """
        self._require_claimed(task)
        moment = at or self._clock.now()
        if retryable:
            task.status = TaskStatus.QUEUED
            task.claimed_by = None
            task.claimed_at = None
        else:
            task.status = TaskStatus.FAILED
            task.finished_at = moment
        task.failure_reason = reason
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.TASK_FAILED,
            actor=task.claimed_by or Actor.SYSTEM,
            subject=task.ref,
            payload={"task_kind": task.kind, "reason": reason, "retryable": retryable},
            at=moment,
        )
        return task

    def cancel(
        self, session: Session, task: Task, *, reason: str, at: dt.datetime | None = None
    ) -> Task:
        moment = at or self._clock.now()
        task.status = TaskStatus.CANCELLED
        task.failure_reason = reason
        task.finished_at = moment
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.TASK_CANCELLED,
            subject=task.ref,
            payload={"task_kind": task.kind, "reason": reason},
            at=moment,
        )
        return task

    @staticmethod
    def _require_claimed(task: Task) -> None:
        if task.status != TaskStatus.CLAIMED:
            raise IntegrityViolation(
                f"task {task.ref} is {task.status}, not claimed — "
                "a task must be claimed before it can finish"
            )

    def cancel_stranded(
        self, session: Session, *, at: dt.datetime | None = None
    ) -> list[Task]:
        """Cancel tasks whose dependency can never succeed.

        A chain that silently stalls forever is indistinguishable from a chain
        nobody started, so a dependent of a failed, cancelled or
        budget-refused task is cancelled with the reason naming the upstream.
        The failure propagates once rather than being rediscovered by whoever
        eventually notices the queue is stuck.
        """
        moment = at or self._clock.now()
        dead = {TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.REFUSED_BUDGET}

        upstream = sa.orm.aliased(Task)
        rows = session.execute(
            sa.select(Task, upstream.ref, upstream.status)
            .join(TaskDependency, TaskDependency.task_ref == Task.ref)
            .join(upstream, upstream.ref == TaskDependency.depends_on_ref)
            .where(Task.status == TaskStatus.QUEUED, upstream.status.in_(dead))
        ).all()

        cancelled: list[Task] = []
        seen: set[str] = set()
        for task, blocker_ref, blocker_status in rows:
            if task.ref in seen:
                continue
            seen.add(task.ref)
            self.cancel(
                session,
                task,
                reason=f"upstream {blocker_ref} is {blocker_status}; this work cannot proceed",
                at=moment,
            )
            cancelled.append(task)
        return cancelled

    # -------------------------------------------------------------- reading

    def blocked_by(self, session: Session, task_ref: str) -> list[str]:
        """Which upstream tasks are still holding this one back."""
        upstream = sa.orm.aliased(Task)
        return list(
            session.execute(
                sa.select(TaskDependency.depends_on_ref)
                .join(upstream, upstream.ref == TaskDependency.depends_on_ref)
                .where(
                    TaskDependency.task_ref == task_ref,
                    upstream.status != TaskStatus.SUCCEEDED,
                )
                .order_by(TaskDependency.depends_on_ref)
            ).scalars()
        )

    def depth(self, session: Session, *, kind: str | None = None) -> int:
        query = sa.select(sa.func.count()).select_from(Task).where(Task.status == TaskStatus.QUEUED)
        if kind is not None:
            query = query.where(Task.kind == kind)
        return int(session.execute(query).scalar_one())

    def counts_by_status(self, session: Session) -> dict[str, int]:
        rows = session.execute(
            sa.select(Task.status, sa.func.count()).group_by(Task.status)
        ).all()
        return {str(status): int(count) for status, count in rows}
