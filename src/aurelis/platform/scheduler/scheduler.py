"""The scheduler: the company's working day.

Briefings, standups, monitors, data pulls, the paper-trading cycle — the
rhythm of the firm is scheduled work, not an agent deciding to act. An agent
that woke itself up whenever it felt like it would be unbudgetable and
untestable.

Jobs are rows, so the schedule survives a restart and is inspectable in Mission
Control. Firing a job enqueues a task; the scheduler never runs work itself.
That keeps one path into the queue and one place where budgets are checked.

Fixed intervals only. A cron parser buys expressiveness this system has no use
for yet, and the day's rhythm — every 5 minutes, every hour, once a day — is
entirely expressible as an interval.

**Missed firings do not stack.** A machine asleep for six hours should not
wake to six identical briefing tasks; it should produce one briefing and move
on. :meth:`Scheduler.tick` advances ``next_due_at`` past the present rather
than by exactly one interval, and records how many firings were skipped.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aurelis.core.clock import Clock, SystemClock
from aurelis.core.enums import EventKind
from aurelis.core.ids import uuid7
from aurelis.platform.db.tables import ScheduledJob, Task
from aurelis.platform.ledger.ledger import Ledger
from aurelis.platform.queue.queue import TaskQueue

__all__ = ["Scheduler"]


class Scheduler:
    """Registers recurring jobs and turns due ones into queued tasks."""

    __slots__ = ("_clock", "_ledger", "_queue")

    def __init__(
        self,
        queue: TaskQueue | None = None,
        ledger: Ledger | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._ledger = ledger or Ledger(self._clock)
        self._queue = queue or TaskQueue(self._ledger, clock=self._clock)

    def register(
        self,
        session: Session,
        *,
        name: str,
        task_kind: str,
        interval_seconds: int,
        payload: dict[str, Any] | None = None,
        first_due: dt.datetime | None = None,
        enabled: bool = True,
    ) -> ScheduledJob:
        """Register or update a job by name. Idempotent.

        Re-registering keeps ``next_due_at`` if the interval is unchanged, so
        restarting the process does not reset every schedule and delay the
        whole company by one interval.
        """
        moment = self._clock.now()
        existing = session.execute(
            sa.select(ScheduledJob).where(ScheduledJob.name == name)
        ).scalar_one_or_none()

        if existing is not None:
            interval_changed = existing.interval_seconds != interval_seconds
            existing.task_kind = task_kind
            existing.payload = dict(payload or {})
            existing.interval_seconds = interval_seconds
            existing.enabled = enabled
            if interval_changed:
                existing.next_due_at = first_due or moment
            session.flush()
            return existing

        job = ScheduledJob(
            job_id=uuid7(),
            name=name,
            task_kind=task_kind,
            payload=dict(payload or {}),
            interval_seconds=interval_seconds,
            enabled=enabled,
            next_due_at=first_due or moment,
            created_at=moment,
        )
        session.add(job)
        session.flush()
        self._ledger.append(
            session,
            kind=EventKind.JOB_REGISTERED,
            subject=name,
            payload={"task_kind": task_kind, "interval_seconds": interval_seconds},
            at=moment,
        )
        return job

    def due(self, session: Session, *, at: dt.datetime | None = None) -> list[ScheduledJob]:
        moment = at or self._clock.now()
        return list(
            session.execute(
                sa.select(ScheduledJob)
                .where(ScheduledJob.enabled.is_(True), ScheduledJob.next_due_at <= moment)
                .order_by(ScheduledJob.next_due_at)
            )
            .scalars()
            .all()
        )

    def tick(self, session: Session, *, at: dt.datetime | None = None) -> list[Task]:
        """Fire every due job once and return the tasks queued."""
        moment = at or self._clock.now()
        fired: list[Task] = []

        for job in self.due(session, at=moment):
            skipped = self._advance(job, moment)
            task = self._queue.enqueue(
                session,
                kind=job.task_kind,
                payload={**job.payload, "scheduled_job": job.name},
                subject=job.name,
                at=moment,
            )
            job.last_fired_at = moment
            job.fire_count += 1
            session.flush()
            self._ledger.append(
                session,
                kind=EventKind.JOB_FIRED,
                subject=job.name,
                payload={
                    "task_ref": task.ref,
                    "skipped_firings": skipped,
                    "next_due_at": job.next_due_at.isoformat(),
                },
                at=moment,
            )
            fired.append(task)

        return fired

    @staticmethod
    def _advance(job: ScheduledJob, moment: dt.datetime) -> int:
        """Move ``next_due_at`` past ``moment``; return firings skipped."""
        interval = dt.timedelta(seconds=job.interval_seconds)
        job.next_due_at = job.next_due_at + interval
        skipped = 0
        while job.next_due_at <= moment:
            job.next_due_at += interval
            skipped += 1
        return skipped
