"""Is the company thinking? One answer, at the top of the facility (M60).

Twice the company stopped thinking for days while the station looked busy:
the mailman kept coming (fetches, recordings, scores) and the rooms kept
their furniture, but no agent had reached a model. The page showed "0 model
call(s)" in small print, which is a fact, not an alarm.

This module reduces the record to one of four states, worst first:

* **asleep**: the service's open ``service.asleep`` alert. Agents tried and
  could not reach a model. Says why and what to do, in the alert's own words.
* **stopped**: no wake has started for longer than two intervals. The
  service is not running, or is stuck inside a wake.
* **thinking**: a model answered in the last two hours.
* **quiet**: none of the above (an unstaffed or brand-new workspace, or a
  budget spent for the day).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

__all__ = ["STOPPED_AFTER", "Health", "company_health"]

STOPPED_AFTER = dt.timedelta(hours=2, minutes=30)
"""No wake started for this long, on an hourly service, is a stopped one."""

_RECENT = dt.timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class Health:
    state: str
    """``asleep``, ``stopped``, ``thinking`` or ``quiet``."""
    headline: str
    detail: str
    todo: str

    @property
    def alarming(self) -> bool:
        return self.state in {"asleep", "stopped"}


def _aware(moment: dt.datetime) -> dt.datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


def _hours(delta: dt.timedelta) -> str:
    hours = delta.total_seconds() / 3600
    if hours < 48:
        return f"{hours:.0f} hour(s)"
    return f"{hours / 24:.0f} day(s)"


def company_health(session: Session, now: dt.datetime) -> Health:
    from aurelis.alerts.tables import Alert
    from aurelis.platform.db.tables import Event
    from aurelis.service.loop import ASLEEP_SOURCE

    now = _aware(now)
    asleep = session.execute(
        sa.select(Alert).where(Alert.source == ASLEEP_SOURCE, Alert.resolved_at.is_(None))
    ).scalar_one_or_none()
    last_call = session.execute(
        sa.select(sa.func.max(Event.created_at)).where(Event.kind == "model.called")
    ).scalar_one_or_none()
    silent = (
        f"The last time an agent thought was {_hours(now - _aware(last_call))} ago."
        if last_call is not None
        else "No agent has thought yet."
    )
    if asleep is not None:
        message = asleep.message.split(" The provider said:")[0]
        return Health(
            "asleep",
            "Your company is asleep: no agent can think.",
            f"{message} {silent} (alert {asleep.ref}, since "
            f"{_aware(asleep.raised_at):%Y-%m-%d %H:%M} UTC)",
            asleep.recommended_action,
        )

    last_wake = session.execute(
        sa.select(sa.func.max(Event.created_at)).where(
            Event.kind.in_(("service.woke", "service.started"))
        )
    ).scalar_one_or_none()
    if last_wake is not None and now - _aware(last_wake) > STOPPED_AFTER:
        return Health(
            "stopped",
            "Your company has stopped: the service has not woken.",
            f"The last wake started {_hours(now - _aware(last_wake))} ago. {silent}",
            "If the scheduled task 'Aurelis' is running, its supervisor restarts the "
            "service within a minute; if this stays, run scripts\\run-aurelis.ps1, "
            "or restart the PC to let the task start it.",
        )

    if last_call is not None and now - _aware(last_call) <= _RECENT:
        recent = int(
            session.execute(
                sa.select(sa.func.count()).where(
                    Event.kind == "model.called", Event.created_at >= now - dt.timedelta(hours=1)
                )
            ).scalar_one()
        )
        return Health(
            "thinking",
            "Your company is thinking.",
            f"{recent} model call(s) in the last hour.",
            "",
        )
    return Health("quiet", "Your company is quiet.", silent, "")
