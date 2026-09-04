"""The company's working day.

The rhythm of the firm is scheduled work, not an agent deciding it feels like
doing something. An agent that woke itself up would be unbudgetable and
untestable, and the first thing to go wrong at scale would be a loop nobody
could account for.

Standing jobs are registered by name and are idempotent, so restarting the
process does not reset a schedule or delay the whole company by one interval.
Firing a job only ever *enqueues* a task — the scheduler never runs work
itself, which keeps one path into the queue and one place where budgets bite.

Only the jobs M2 can honestly run are here. Meetings arrive at M3, the paper
cycle at M9, and each milestone adds its own rather than this file promising a
working day the company cannot yet have.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from aurelis.agents.roster import Roster
from aurelis.intel.briefing import TASK_KIND as BRIEFING_TASK
from aurelis.platform.scheduler.scheduler import Scheduler

__all__ = ["STANDING_JOBS", "StandingJob", "register_standing_jobs"]

DAY = 24 * 3600


@dataclass(frozen=True, slots=True)
class StandingJob:
    """A recurring piece of the working day."""

    name: str
    task_kind: str
    interval_seconds: int
    purpose: str
    assignee_handle: str | None = None
    """Which agent it is for. ``None`` means any eligible worker — used for
    platform housekeeping that belongs to nobody in particular."""


STANDING_JOBS: tuple[StandingJob, ...] = (
    StandingJob(
        name="desk.crypto.briefing",
        task_kind=BRIEFING_TASK,
        interval_seconds=DAY,
        purpose="The crypto desk's daily briefing.",
        assignee_handle="INTEL",
    ),
)
"""Only the jobs M2 can honestly run.

Queue housekeeping -- cancelling work stranded behind a dependency that can
never succeed -- is deliberately *not* here. It is platform maintenance rather
than something an agent does, so it runs in the tick loop directly. Dressing
it up as agent work would put a task in the queue that no charter is
responsible for.
"""


def register_standing_jobs(
    session: Session,
    scheduler: Scheduler,
    roster: Roster,
    *,
    at: dt.datetime | None = None,
) -> list[str]:
    """Register the working day. Idempotent.

    A job whose agent has not been hired is skipped rather than registered
    against nobody — a scheduled task addressed to an agent that does not
    exist would sit in the queue forever looking like work in progress.
    """
    registered: list[str] = []
    for job in STANDING_JOBS:
        assignee: str | None = None
        if job.assignee_handle is not None:
            try:
                assignee = roster.by_handle(session, job.assignee_handle).ref
            except KeyError:
                continue
        scheduler.register(
            session,
            name=job.name,
            task_kind=job.task_kind,
            interval_seconds=job.interval_seconds,
            assignee=assignee,
            payload={"purpose": job.purpose, "bars": 48},
            first_due=at,
        )
        registered.append(job.name)
    return registered
