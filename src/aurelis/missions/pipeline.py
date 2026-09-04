"""Planning a project into a chain of dependent tasks.

The piece that turns "we want a briefing reviewed" into three tasks that
sequence themselves. Each step declares which agent does it and what it waits
for; the queue does the rest, because a task with unmet dependencies is simply
invisible to ``claim``.

That is deliberate. The alternative — an orchestrator that polls for
completions and dispatches the next step — is a component that has to be
running, can fall over, and becomes the single thing that knows how work
flows. Here the dependency *is* the plan, it lives in the database, and a
company that was switched off overnight resumes exactly where it stopped.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from aurelis.core.enums import TaskStatus
from aurelis.core.errors import IntegrityViolation
from aurelis.missions.missions import Missions
from aurelis.platform.budget.ledger import Spend
from aurelis.platform.db.tables import Task
from aurelis.platform.queue.queue import TaskQueue

__all__ = ["Step", "plan_project"]


@dataclass(frozen=True, slots=True)
class Step:
    """One task in a project's plan."""

    kind: str
    assignee: str
    payload: dict[str, Any] = field(default_factory=dict)
    tokens: int = 5_000
    usd: Decimal = Decimal("0")
    after: tuple[str, ...] = ()
    """Names of earlier steps this waits for. Names, not task refs — the plan
    is written before any of the tasks exist."""

    name: str = ""

    @property
    def label(self) -> str:
        return self.name or self.kind


def plan_project(
    session: Session,
    missions: Missions,
    queue: TaskQueue,
    *,
    project_ref: str,
    steps: tuple[Step, ...],
    at: dt.datetime | None = None,
) -> list[Task]:
    """Turn a plan into queued, dependency-linked tasks.

    Every task counts against the project's budget envelope, so a project that
    over-plans is refused at dispatch rather than discovering halfway through
    that it cannot afford to finish.

    A step refused for budget still gets its dependents queued — and they are
    then cancelled by :meth:`TaskQueue.cancel_stranded`, which records *why*
    rather than leaving them waiting on something that will never happen.
    """
    envelope = missions.envelope_for(session, project_ref)
    by_name: dict[str, str] = {}
    created: list[Task] = []

    for index, step in enumerate(steps):
        if step.label in by_name:
            raise IntegrityViolation(
                f"two steps in {project_ref} are both called {step.label!r}; "
                "dependencies are named, so names must be unique within a plan"
            )
        unknown = [name for name in step.after if name not in by_name]
        if unknown:
            raise IntegrityViolation(
                f"step {step.label!r} waits for {unknown}, which is not an "
                "earlier step in this plan. Plans are ordered: a step can only "
                "depend on something already declared."
            )

        task = queue.enqueue(
            session,
            kind=step.kind,
            assignee=step.assignee,
            subject=project_ref,
            payload=dict(step.payload),
            allowance=Spend(step.usd, step.tokens),
            envelope=envelope,
            depends_on=tuple(by_name[name] for name in step.after),
            at=at,
        )
        missions.place(session, task_ref=task.ref, project_ref=project_ref, step=index, at=at)
        by_name[step.label] = task.ref
        created.append(task)

    return created


def chain_is_complete(tasks: list[Task]) -> bool:
    """True when every task in a plan reached a terminal state."""
    terminal = {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.REFUSED_BUDGET,
    }
    return all(task.status in terminal for task in tasks)
