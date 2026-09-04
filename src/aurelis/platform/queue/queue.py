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
from aurelis.platform.db.tables import Task
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
        actor: Actor | str = Actor.SYSTEM,
        at: dt.datetime | None = None,
    ) -> Task:
        """Queue a task, refusing it at dispatch if it cannot be afforded."""
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
            innermost = list(scopes)[-1] if scopes else None
            if innermost is not None:
                task.budget_scope = innermost.value
                task.budget_scope_id = scopes[innermost]

        session.add(task)
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

    # -------------------------------------------------------------- reading

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
